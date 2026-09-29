#!/usr/bin/env python3
"""release_bump.py — одной командой поднять версию во ВСЕХ поверхностях релиза.

ПОВОД (замер 01.09.2026, выпуск v3.39.1). Версию бампали РУКАМИ в восьми файлах: VERSION,
manifest.package_version, release-claims.version, release-notes.version, README, ROADMAP, раздел
CHANGELOG и release-newsfragment. Рассинхрон ловят валидаторы (validate_release_claims,
validate_ai_first_registry), но уже ПОСТФАКТУМ — класс «объявлено, но не автоматизировано». Здесь
одна формула правит все поверхности сразу; канал берётся из release-claims (не зашит).

Использование:
  release_bump.py <X.Y.Z> --title "заголовок раздела CHANGELOG" --date YYYY-MM-DD
                  --headline "один абзац «что меняется для вас»" [--after-release "…"]
                  [--root .] [--body "строка/строки под заголовком"]
  release_bump.py --check [--root .]   # версия одинакова во всех поверхностях?
  release_bump.py --release-notes X.Y.Z [--changelog-url URL]   # тело GitHub Release в stdout

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

ОПИСАНИЕ ВЫПУСКА — СООБЩЕНИЕ ЧЕЛОВЕКУ (#1210). Раздел CHANGELOG — инженерный журнал; его целиком
копировали в GitHub Release и прятали в JSON PR обновления дочки. Теперь бамп собирает СЛОЙ ВЛАДЕЛЬЦА
(слой A) — абзац «что меняется для вас» (`--headline`, обязателен в CLI), известные ограничения из
фрагментов типа `limit` (явное «Нет», если их нет), «что дальше» и ссылку на полный раздел — и кладёт
его в начало раздела версии между маркерами `OWNER_START`/`OWNER_END`. Ниже остаётся полный вывод
towncrier (слой B). Машины достают слой A функциями `owner_layer`/`release_body`/`whats_new`
(`--release-notes` для release.yml); раздела без маркеров (старые выпуски) они не выдумывают —
отдают прежнее содержимое и так и говорят.
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

# ── Слой владельца (слой A) ────────────────────────────────────────────────────────────────────
# Маркеры, по которым release.yml и PR обновления дочки достают слой A из раздела версии.
OWNER_START = "<!-- owner-layer:start -->"
OWNER_END = "<!-- owner-layer:end -->"

# Названия блоков и пределы — из `registry/communication-policy.yaml -> release_notes` (правила ведёт
# соседняя работа #1210). Пока их там нет, действуют эти значения по умолчанию — те же ключи и числа,
# что в общем контракте, чтобы появление правил в реестре не меняло форму уже собранных выпусков.
_DEFAULT_BLOCK_TITLES = {
    "headline": "Что меняется для вас",
    "whats_in": "Что вошло",
    "behaviour_changes": "Что изменится в поведении",
    "who_is_affected": "Кого касается",
    "known_limits": "Известные ограничения",
    "after_release": "Что дальше",
    "details": "Подробности",
}
_DEFAULT_MAX_WORDS = 250
_DEFAULT_MAX_ITEM_CHARS = 200
_DEFAULT_AFTER_RELEASE = ("Обновление приходит PR-ом `ai-ops update` в ваш репозиторий; отдельных "
                          "шагов после выпуска не объявлено.")
_NO_LIMITS = "Нет (ограничений к этому выпуску не заявлено)."
# Фрагмент ограничения: `<slug>.limit.md` или с номером towncrier `<slug>.limit.1.md`.
_LIMIT_FRAGMENT = re.compile(r"\.limit(?:\.\d+)?\.md$")
# Номер версии в абзаце «что меняется для вас» — запрещён: человеку важен смысл, версия в заголовке.
_VERSION_IN_TEXT = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b")


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


def release_notes_policy(root: Path) -> dict:
    """Названия блоков и пределы слоя A. -> {titles, max_words, max_item_chars}.

    Источник — `registry/communication-policy.yaml -> release_notes`, если раздел там есть; иначе
    значения по умолчанию (`_DEFAULT_*`). Нечитаемый реестр — тоже умолчания: бамп не падает из-за
    чужого файла, а правила, которых нет, не выдумываются."""
    rules: dict = {}
    p = root / "registry" / "communication-policy.yaml"
    if p.is_file():
        try:
            import yaml  # локально: devtools зовут и без pyyaml (только --check)
            rules = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("release_notes") or {}
        except Exception:                               # noqa: BLE001 — нечитаемые правила = умолчания
            rules = {}
    if not isinstance(rules, dict):
        rules = {}
    layer_raw = rules.get("layer_a")
    layer: dict = layer_raw if isinstance(layer_raw, dict) else {}
    titles = dict(_DEFAULT_BLOCK_TITLES)
    if isinstance(rules.get("block_titles"), dict):
        titles.update({str(k): str(v) for k, v in rules["block_titles"].items() if v})
    return {"titles": titles,
            "max_words": int(layer.get("max_words") or _DEFAULT_MAX_WORDS),
            "max_item_chars": int(layer.get("max_item_chars") or _DEFAULT_MAX_ITEM_CHARS)}


def limit_fragments(root: Path) -> list:
    """Известные ограничения из очереди: тексты фрагментов `*.limit.md` (строки склеены в одну)."""
    return [" ".join(p.read_text(encoding="utf-8").split())
            for p in _pending_fragments(root) if _LIMIT_FRAGMENT.search(p.name)]


def _check_headline(headline: str) -> str:
    """Абзац «что меняется для вас»: непустой, ОДИН абзац, без номера версии. -> очищенный текст."""
    text = (headline or "").strip()
    if not text:
        raise ValueError("нужен --headline: один абзац «что меняется для вас» — без него выпуск "
                         "выходит инженерным журналом, а не сообщением человеку")
    if re.search(r"\n\s*\n", text):
        raise ValueError("--headline должен быть ОДНИМ абзацем (найдена пустая строка внутри)")
    if _VERSION_IN_TEXT.search(text):
        raise ValueError("--headline без номера версии: версия уже в заголовке раздела, человеку "
                         "нужен смысл выпуска")
    return " ".join(text.split())


def owner_layer_block(headline: str, limits: list, after_release: str, policy: dict) -> str:
    """Слой A между маркерами: headline, known_limits, after_release, details. Бросает ValueError,
    если слой длиннее `max_words` или пункт ограничения длиннее `max_item_chars` — проверка ДО
    записи файлов, чтобы отказ ничего не менял."""
    t = policy["titles"]
    for item in limits:
        if len(item) > policy["max_item_chars"]:
            raise ValueError(f"ограничение длиннее {policy['max_item_chars']} знаков — сократите "
                             f"фрагмент `*.limit.md`: «{item[:60]}…»")
    limits_md = "\n".join(f"- {x}" for x in limits) if limits else _NO_LIMITS
    after = " ".join((after_release or _DEFAULT_AFTER_RELEASE).split())
    inner = (f"**{t['headline']}.** {_check_headline(headline)}\n\n"
             f"**{t['known_limits']}**\n\n{limits_md}\n\n"
             f"**{t['after_release']}.** {after}\n\n"
             f"**{t['details']}.** Полный список изменений — раздел этой версии в CHANGELOG.md.")
    words = len(inner.split())
    if words > policy["max_words"]:
        raise ValueError(f"описание выпуска для владельца — {words} слов при пределе "
                         f"{policy['max_words']}: сократите --headline или ограничения")
    return f"{OWNER_START}\n{inner}\n{OWNER_END}"


def _drain_changelog(root: Path, new: str, date: str, title: str, body: str,
                     owner: str = "") -> None:
    """Слить накопленные newsfragments в раздел CHANGELOG и очистить очередь — через `towncrier build`.

    towncrier вставляет раздел `## [<new>] — <date>` под маркером (из title_format) и УДАЛЯЕТ фрагменты.
    Затем шапку доводим до формата кита `## [<new>] — <date> · <title>` и, если задано, вкладываем `body`
    ведущим абзацем — ровно ту шапку ждёт извлечение записок в release.yml и соседние проверки. Слой
    владельца (`owner`, если задан) встаёт сразу под шапкой, выше `body` и вывода towncrier. В конце
    ГЕЙТ: очередь обязана опустеть; иначе — ошибка (релиз не имеет права выйти с недренированной очередью).
    """
    subprocess.run([sys.executable, "-m", "towncrier", "build", "--yes", "--version", new,
                    "--date", date], cwd=str(root), check=True, capture_output=True, text=True)
    ch = root / "CHANGELOG.md"
    txt = ch.read_text(encoding="utf-8")
    header = f"## [{new}] — {date}"
    decorated = header + (f" · {title}" if title else "")
    if owner:
        decorated += "\n\n" + owner
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


def _record_changelog(root: Path, new: str, title: str, date: str, body: str, channel: str,
                      owner: str = "") -> list:
    """Записать раздел CHANGELOG новой версии. -> список изменённых относительных путей.

    Если дренаж возможен И очередь непуста — сгребаем накопленные заявления в раздел через towncrier
    (очередь очищается). Иначе — прежний ручной раздел под `## [Unreleased]` + release-newsfragment
    (towncrier требует запись на ветке): путь для не-китового/офлайн-репозитория и тестовых фикстур."""
    if _towncrier_ready(root) and _pending_fragments(root):
        _drain_changelog(root, new, date, title, body, owner)
        return ["CHANGELOG.md"]
    # Ручной раздел: репозиторий без towncrier-дренажа. Раздел вставляем под [Unreleased].
    ch = root / "CHANGELOG.md"
    ctxt = ch.read_text(encoding="utf-8")
    section = f"## [{new}] — {date} · {title}\n"
    if owner:
        section += "\n" + owner + "\n"
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


def bump(root: Path, new: str, title: str, date: str, body: str = "",
         headline: str | None = None, after_release: str = "") -> list:
    """Поднять версию до `new` во всех поверхностях + раздел CHANGELOG + release-newsfragment.

    `headline` задан -> в начало раздела ложится слой владельца (см. `owner_layer_block`); он
    проверяется ДО любой записи, так что отказ ничего не меняет. `headline=None` — раздел без слоя A
    (фикстуры и не-китовые репозитории); CLI выпуска без `--headline` отказывает (см. `main`).
    -> список изменённых относительных путей. Бросает ValueError на битом semver/ненайденной версии."""
    if not _SEMVER.match(new):
        raise ValueError(f"версия '{new}' не по semver X.Y.Z")
    old = current_version(root)
    if new == old:
        raise ValueError(f"версия уже {new} — нечего поднимать")
    owner = ("" if headline is None else
             owner_layer_block(headline, limit_fragments(root), after_release, release_notes_policy(root)))
    channel = _channel(root)
    changed = []
    for rel, pattern, repl in _surfaces(old, new, channel):
        _apply(root, rel, pattern, repl)
        changed.append(rel)
    # CHANGELOG: раздел новой версии. Дренаж очереди, если он возможен; иначе — ручной раздел.
    changed += _record_changelog(root, new, title, date, body, channel, owner)
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


# ── Извлечение слоя A: release.yml (тело GitHub Release) и PR обновления дочки ─────────────────
def version_section(text: str, version: str) -> str:
    """Раздел CHANGELOG версии: от `## [version]` до следующего `## ` (не включая). Нет — ''."""
    out: list = []
    head = re.compile(rf"^## \[{re.escape(version)}\]")
    for line in text.splitlines():
        if out and line.startswith("## "):
            break
        if out or head.match(line):
            out.append(line)
    return "\n".join(out).strip()


def owner_layer(text: str, version: str) -> str | None:
    """Слой A версии — текст между маркерами в её разделе. None — раздела или маркеров нет."""
    sec = version_section(text, version)
    i, j = sec.find(OWNER_START), sec.find(OWNER_END)
    if i < 0 or j < i:
        return None
    return sec[i + len(OWNER_START):j].strip() or None


def release_body(text: str, version: str, changelog_url: str = "") -> str:
    """Тело GitHub Release: слой A + ссылка на полный раздел. Без маркеров (выпуски до #1210) —
    раздел целиком, как раньше. Раздела нет — '' (release.yml откажет, тег не создастся)."""
    layer = owner_layer(text, version)
    if layer is None:
        return version_section(text, version)
    link = (f"Полный список изменений этой версии — [CHANGELOG.md]({changelog_url})."
            if changelog_url else "Полный список изменений этой версии — в CHANGELOG.md.")
    return f"{layer}\n\n---\n\n{link}"


def whats_new(old_version, new_version, text: str | None = None, max_versions: int = 6,
              max_chars: int = 1500) -> dict:
    """Слой A каждой версии между old (исключая) и new (включая) — для PR обновления дочки.

    -> {status: ok|empty, versions: [{version, title, owner_layer: bool}], text}. Версия без
    маркеров показывается заголовком раздела, и об этом сказано; больше `max_versions` — остаток
    назван числом; слой длиннее `max_chars` обрезан с пометкой. Заголовки — тем же разбором, что
    `changelog_slice` (`changelog_gen.headlines_between`), чтобы две выдачи не разошлись."""
    from ai_ops_kit.devtools import changelog_gen
    if text is None:
        text = (PKG / "CHANGELOG.md").read_text(encoding="utf-8")
    heads = changelog_gen.headlines_between(old_version, new_version, text=text, limit=10_000)
    if not heads:
        return {"status": "empty", "versions": [],
                "text": (f"Что нового для вас: между {old_version or '—'} и {new_version} разделов в "
                         f"CHANGELOG кита не нашлось — назвать изменения не могу.")}
    versions, parts = [], [f"Что нового для вас — по версиям ({len(heads)}):"]
    for head in heads[:max_versions]:
        ver, _, title = head.partition(" — ")
        layer = owner_layer(text, ver)
        versions.append({"version": ver, "title": title, "owner_layer": layer is not None})
        if layer is None:
            parts.append(f"### {head}\n\nОписания для владельца у этой версии нет (выпуск собран до "
                         f"него) — показан только заголовок раздела CHANGELOG.")
            continue
        if len(layer) > max_chars:
            layer = layer[:max_chars].rstrip() + " … (обрезано — полный текст в CHANGELOG кита)"
        parts.append(f"### {ver}" + (f" — {title}" if title else "") + f"\n\n{layer}")
    if len(heads) > max_versions:
        parts.append(f"…и ещё версий: {len(heads) - max_versions} — их описания в CHANGELOG кита.")
    return {"status": "ok", "versions": versions, "text": "\n\n".join(parts)}


def _print_release_notes(root: Path, version: str, changelog_url: str) -> int:
    """`--release-notes`: тело Release в stdout. 0 — есть; 1 — раздела версии нет (причина в stderr)."""
    body = release_body((root / "CHANGELOG.md").read_text(encoding="utf-8"), version, changelog_url)
    if not body:
        print(f"в CHANGELOG.md нет раздела [{version}] — добавьте раздел '## [{version}] — <дата>'",
              file=sys.stderr)
        return 1
    print(body)
    return 0


def _parse_args(argv):
    ap = argparse.ArgumentParser(prog="release_bump.py")
    ap.add_argument("version", nargs="?", help="целевая версия X.Y.Z")
    ap.add_argument("--title", default="", help="заголовок раздела CHANGELOG")
    ap.add_argument("--date", default="", help="дата релиза YYYY-MM-DD (называет вызывающий)")
    ap.add_argument("--body", default="", help="тело раздела CHANGELOG (опционально)")
    ap.add_argument("--headline", default="",
                    help="один абзац «что меняется для вас», без номера версии (обязателен)")
    ap.add_argument("--after-release", default="", help="что дальше после выпуска (опционально)")
    ap.add_argument("--root", default=str(PKG))
    ap.add_argument("--check", action="store_true", help="проверить согласованность версий, не менять")
    ap.add_argument("--release-notes", metavar="X.Y.Z", default="",
                    help="напечатать тело GitHub Release версии (слой A + ссылка), ничего не менять")
    ap.add_argument("--changelog-url", default="", help="ссылка на CHANGELOG для --release-notes")
    return ap.parse_args(argv[1:])


def main(argv) -> int:
    a = _parse_args(argv)
    root = Path(a.root)
    if a.release_notes:
        return _print_release_notes(root, a.release_notes, a.changelog_url)
    if a.check:
        bad = check(root)
        if bad:
            print("РАССИНХРОН версий: " + ", ".join(bad) + f" (VERSION={current_version(root)})")
            return 1
        print(f"RELEASE-BUMP-OK: версия {current_version(root)} согласована во всех поверхностях.")
        return 0
    if not a.version or not a.title or not a.date or not a.headline.strip():
        print("нужны <X.Y.Z>, --title, --date и --headline (один абзац «что меняется для вас», без "
              "номера версии); в --check и --release-notes они не нужны")
        return 1
    try:
        changed = bump(root, a.version, a.title, a.date, a.body,
                       headline=a.headline, after_release=a.after_release)
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
