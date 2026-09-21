#!/usr/bin/env python3
"""release_bump.py — одной командой поднять версию во ВСЕХ поверхностях релиза.

ПОВОД (замер 01.09.2026, выпуск v3.39.1). Версию бампали РУКАМИ в восьми файлах: VERSION,
manifest.package_version, release-claims.version, release-notes.version, README, ROADMAP, раздел
CHANGELOG и release-newsfragment. Рассинхрон ловят валидаторы (validate_release_claims,
validate_ai_first_registry), но уже ПОСТФАКТУМ — класс «объявлено, но не автоматизировано». Здесь
одна формула правит все поверхности сразу; канал берётся из release-claims (не зашит).

Использование:
  release_bump.py <X.Y.Z> --title "заголовок раздела CHANGELOG" [--date YYYY-MM-DD]
                  [--root .] [--body "строка/строки под заголовком"]
  release_bump.py --check [--root .]   # версия одинакова во всех поверхностях?

Дату не берём из системных часов автоматически (в CI/офлайн они разные) — если --date не задан,
берём из последней записи CHANGELOG-заголовка недопустимо, поэтому дату называет вызывающий; в
--check дата не нужна. Возврат: 0 — ок; 1 — ошибка (битый semver, поверхность не найдена, рассинхрон).

РЕЛИЗ ГАСИТ ОЧЕРЕДЬ ЗАЯВЛЕНИЙ (аудит A2, 17.09.2026). towncrier собирает CHANGELOG.md из
newsfragments/, но раньше релиз `build` НЕ звал — фрагменты копились сотнями, «дисциплина заявлений
подтекала там, где декларируется». Теперь бамп СЛИВАЕТ накопленную очередь в раздел CHANGELOG через
`towncrier build` и очищает newsfragments/. Дренаж включается, когда он реально возможен (towncrier
доступен, есть [tool.towncrier] в pyproject и маркер вставки в CHANGELOG) И очередь непуста; иначе —
прежний ручной раздел (не-китовый / офлайн-репозиторий). Что результат достигнут, ДОКАЗЫВАЕТ отдельный
гейт на самом выпуске (`validation/validate_changelog_queue_drained.py --release`): непустая очередь
на релизе краснит джобу и тег не создаётся — обещание «на релизе очередь пуста» стало проверяемым.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

# Маркер towncrier: строка, ПОСЛЕ которой `build` вставляет собранный раздел. Держим её в CHANGELOG
# сразу под `## [Unreleased]`, чтобы каждый релиз ложился под Unreleased и над прошлой версией.
_TOWNCRIER_MARKER = "<!-- towncrier release notes start -->"

# Собственный Product Passport кита (parent): машинные разделы — снимок версии/здоровья/статуса,
# которые обязаны перегенерироваться на релизе, иначе freshness-ратчет
# (tests/contracts/test_kit_product_passport.py) краснит на каждом бампе. Разделы владельца при этом
# сохраняются (см. passport_generator.merge_owner_sections).
_KIT_PASSPORT_REL = ".ai/project/context/product/PRODUCT_PASSPORT.md"


def _channel(root: Path) -> str:
    """Текущий канал из release-claims.yaml (`channel: X`). Нужен для строки версии в README/ROADMAP."""
    txt = (root / "registry" / "release-claims.yaml").read_text(encoding="utf-8")
    m = re.search(r"(?m)^channel:\s*(\S+)\s*$", txt)
    return m.group(1) if m else "qualification"


def current_version(root: Path) -> str:
    return (root / "VERSION").read_text(encoding="utf-8").strip()


# (относительный путь, функция (old,new,channel)->(pattern, repl)) для каждой версионной поверхности.
def _surfaces(old: str, new: str, channel: str):
    o = re.escape(old)
    return [
        ("VERSION", rf"^{o}\s*$", new),
        ("manifest/ai-ops-manifest.yaml", rf"(?m)^(  package_version:\s*){o}\s*$", rf"\g<1>{new}"),
        ("registry/release-claims.yaml", rf"(?m)^(version:\s*){o}\s*$", rf"\g<1>{new}"),
        ("registry/release-notes.yaml", rf"(?m)^(version:\s*){o}\s*$", rf"\g<1>{new}"),
        ("README.md", rf"v{o} {re.escape(channel)}", f"v{new} {channel}"),
        ("ROADMAP.md", rf"v{o} {re.escape(channel)}", f"v{new} {channel}"),
    ]


def _apply(root: Path, rel: str, pattern: str, repl: str) -> None:
    """Заменить РОВНО одно вхождение версии в файле. Ноль вхождений — ошибка (поверхность разошлась)."""
    p = root / rel
    txt = p.read_text(encoding="utf-8")
    new_txt, n = re.subn(pattern, repl, txt, count=1)
    if n != 1:
        raise ValueError(f"{rel}: версия для замены не найдена (ожидалось ровно 1 вхождение, нашлось {n})")
    p.write_text(new_txt, encoding="utf-8")


def _pending_fragments(root: Path) -> list:
    """Накопленные newsfragments (всё, кроме README.md) — очередь заявлений к следующему релизу."""
    d = root / "newsfragments"
    if not d.is_dir():
        return []
    return [p for p in sorted(d.glob("*.md")) if p.name != "README.md"]


def _towncrier_ready(root: Path) -> bool:
    """Возможен ли релизный дренаж очереди через `towncrier build` в ЭТОМ репозитории.

    Три условия, и все обязательны: (1) towncrier импортируется в текущем интерпретаторе — тем же
    `sys.executable` мы его и вызовем; (2) в pyproject объявлен `[tool.towncrier]`; (3) в CHANGELOG
    есть маркер вставки. Иначе (не-китовый / офлайн-репозиторий, тестовая фикстура без конфига) дренаж
    невозможен — пишем раздел вручную, как раньше. Детерминированно: не зависит от того, стоит ли
    towncrier «где-то в системе», а только от того, чем этот процесс реально располагает."""
    if importlib.util.find_spec("towncrier") is None:
        return False
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file() or "[tool.towncrier]" not in pyproject.read_text(encoding="utf-8"):
        return False
    ch = root / "CHANGELOG.md"
    return ch.is_file() and _TOWNCRIER_MARKER in ch.read_text(encoding="utf-8")


def _drain_changelog(root: Path, new: str, date: str, title: str, body: str) -> None:
    """Слить накопленные newsfragments в раздел CHANGELOG и очистить очередь — через `towncrier build`.

    towncrier вставляет раздел `## [<new>] — <date>` под маркером (из title_format) и УДАЛЯЕТ фрагменты.
    Затем шапку доводим до формата кита `## [<new>] — <date> · <title>` и, если задано, вкладываем `body`
    ведущим абзацем — ровно ту шапку ждёт извлечение записок в release.yml и соседние проверки. В конце
    ГЕЙТ: очередь обязана опустеть; иначе — ошибка (релиз не имеет права выйти с недренированной очередью).
    """
    subprocess.run([sys.executable, "-m", "towncrier", "build", "--yes", "--version", new,
                    "--date", date], cwd=str(root), check=True, capture_output=True, text=True)
    ch = root / "CHANGELOG.md"
    txt = ch.read_text(encoding="utf-8")
    header = f"## [{new}] — {date}"
    decorated = header + (f" · {title}" if title else "")
    if body:
        decorated += "\n\n" + body.rstrip()
    txt2, n = re.subn(re.escape(header) + r"(?=\n)", lambda _m: decorated, txt, count=1)
    if n != 1:
        raise ValueError(f"CHANGELOG.md: шапка '{header}' после сборки towncrier не найдена")
    ch.write_text(txt2, encoding="utf-8")
    left = _pending_fragments(root)
    if left:
        raise RuntimeError("очередь newsfragments не опустела после релизной сборки: "
                           + ", ".join(p.name for p in left[:5]))


def _record_changelog(root: Path, new: str, title: str, date: str, body: str, channel: str) -> list:
    """Записать раздел CHANGELOG новой версии. -> список изменённых относительных путей.

    Если дренаж возможен И очередь непуста — сгребаем накопленные заявления в раздел через towncrier
    (очередь очищается). Иначе — прежний ручной раздел под `## [Unreleased]` + release-newsfragment
    (towncrier требует запись на ветке): путь для не-китового/офлайн-репозитория и тестовых фикстур."""
    if _towncrier_ready(root) and _pending_fragments(root):
        _drain_changelog(root, new, date, title, body)
        return ["CHANGELOG.md"]
    # Ручной раздел: репозиторий без towncrier-дренажа. Раздел вставляем под [Unreleased].
    ch = root / "CHANGELOG.md"
    ctxt = ch.read_text(encoding="utf-8")
    section = f"## [{new}] — {date} · {title}\n"
    if body:
        section += "\n" + body.rstrip() + "\n"
    ctxt2, n = re.subn(r"(?m)^## \[Unreleased\]\s*$",
                       f"## [Unreleased]\n\n{section.rstrip()}", ctxt, count=1)
    if n != 1:
        raise ValueError("CHANGELOG.md: не найден раздел '## [Unreleased]' для вставки")
    ch.write_text(ctxt2, encoding="utf-8")
    frag = root / "newsfragments" / f"release-v{new}.chore.md"
    frag.parent.mkdir(parents=True, exist_ok=True)
    frag.write_text(f"Релиз v{new} ({channel}): {title}\n", encoding="utf-8")
    return ["CHANGELOG.md", str(frag.relative_to(root))]


def refresh_kit_passport(root: Path) -> str | None:
    """Перегенерировать машинные разделы собственного паспорта кита под текущую VERSION.

    Вызывается ПОСЛЕ подъёма VERSION: генератор читает уже новую версию. Разделы владельца
    (Название, Аудитория и проблема, Owner и команда) сохраняются дословно из текущего файла — их
    кит из кода не выводит и затирать не вправе. -> относительный путь, если паспорт есть и обновлён;
    None — если паспорта нет (не-родительский / не-китовый репозиторий): бамп из-за этого не падает.
    """
    p = root / _KIT_PASSPORT_REL
    if not p.is_file():
        return None
    # Импорт локальный: планировщик — тяжёлая зависимость (git/аудит репозитория), нужен только на
    # реальном бампе кита, а не при каждом импорте devtools.
    from ai_ops_kit.planning import passport_generator as pg
    existing = p.read_text(encoding="utf-8")
    merged = pg.merge_owner_sections(existing, pg.generate(root))
    p.write_text(merged, encoding="utf-8")
    return _KIT_PASSPORT_REL


def bump(root: Path, new: str, title: str, date: str, body: str = "") -> list:
    """Поднять версию до `new` во всех поверхностях + раздел CHANGELOG + release-newsfragment.

    -> список изменённых относительных путей. Бросает ValueError на битом semver/ненайденной версии."""
    if not _SEMVER.match(new):
        raise ValueError(f"версия '{new}' не по semver X.Y.Z")
    old = current_version(root)
    if new == old:
        raise ValueError(f"версия уже {new} — нечего поднимать")
    channel = _channel(root)
    changed = []
    for rel, pattern, repl in _surfaces(old, new, channel):
        _apply(root, rel, pattern, repl)
        changed.append(rel)
    # CHANGELOG: раздел новой версии. Дренаж очереди, если он возможен; иначе — ручной раздел.
    changed += _record_changelog(root, new, title, date, body, channel)
    # Product Passport кита: машинные разделы — снимок под новую версию (разделы владельца сохранены).
    passport_rel = refresh_kit_passport(root)
    if passport_rel:
        changed.append(passport_rel)
    return changed


def check(root: Path) -> list:
    """Все версионные поверхности == VERSION? -> список рассинхронов (пусто = согласовано)."""
    ver = current_version(root)
    channel = _channel(root)
    bad = []
    checks = {
        "manifest/ai-ops-manifest.yaml": rf"(?m)^  package_version:\s*{re.escape(ver)}\s*$",
        "registry/release-claims.yaml": rf"(?m)^version:\s*{re.escape(ver)}\s*$",
        "registry/release-notes.yaml": rf"(?m)^version:\s*{re.escape(ver)}\s*$",
        "README.md": rf"v{re.escape(ver)} {re.escape(channel)}",
        "ROADMAP.md": rf"v{re.escape(ver)} {re.escape(channel)}",
    }
    for rel, pat in checks.items():
        if not re.search(pat, (root / rel).read_text(encoding="utf-8")):
            bad.append(rel)
    return bad


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="release_bump.py")
    ap.add_argument("version", nargs="?", help="целевая версия X.Y.Z")
    ap.add_argument("--title", default="", help="заголовок раздела CHANGELOG")
    ap.add_argument("--date", default="", help="дата релиза YYYY-MM-DD (называет вызывающий)")
    ap.add_argument("--body", default="", help="тело раздела CHANGELOG (опционально)")
    ap.add_argument("--root", default=str(PKG))
    ap.add_argument("--check", action="store_true", help="проверить согласованность версий, не менять")
    a = ap.parse_args(argv[1:])
    root = Path(a.root)
    if a.check:
        bad = check(root)
        if bad:
            print("РАССИНХРОН версий: " + ", ".join(bad) + f" (VERSION={current_version(root)})")
            return 1
        print(f"RELEASE-BUMP-OK: версия {current_version(root)} согласована во всех поверхностях.")
        return 0
    if not a.version or not a.title or not a.date:
        print("нужны <X.Y.Z>, --title и --date (в --check они не нужны)")
        return 1
    try:
        changed = bump(root, a.version, a.title, a.date, a.body)
    except (ValueError, OSError) as e:
        print(f"ОШИБКА: {e}")
        return 1
    print(f"RELEASE-BUMP: версия -> {a.version}. Изменено ({len(changed)}):")
    for c in changed:
        print(f"  {c}")
    print("Дальше: проверьте `--check`, соберите валидаторы и создайте PR `chore(release): ... v" + a.version + "`.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
