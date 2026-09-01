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
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


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
    # CHANGELOG: новый раздел под [Unreleased]
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
    changed.append("CHANGELOG.md")
    # release-newsfragment (towncrier требует запись на ветке; заодно фиксирует релиз)
    frag = root / "newsfragments" / f"release-v{new}.chore.md"
    frag.write_text(f"Релиз v{new} ({channel}): {title}\n", encoding="utf-8")
    changed.append(str(frag.relative_to(root)))
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
