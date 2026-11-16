#!/usr/bin/env python3
"""Автовыпуск дочки (#1548): новая версия на main -> проверки дочки -> «выпуск готов» -> тег и Release.

Зовётся шагами `templates/ci/ai-ops-release.yml` ИЗ КЛОНА кита на пине `installed_version` (как линт
дочки): в дочку едет только workflow, код выпуска — нет. Включается владельцем в `.ai-ops.yaml`:

    release:
      enabled: true               # опт-ин; без него workflow только говорит «выключено»
      version_file: VERSION       # необязательно; иначе VERSION / package.json / pyproject / Cargo.toml
      checks: ["npm test"]        # необязательно; иначе команды build/test из профиля стека кита
      allow_unchecked: false      # проверить нечем -> выпуск НЕ выходит (по умолчанию)

ЧЕСТНОСТЬ. Нет команды проверки для стека — это «не проверено», а не «прошло»: выпуск не выходит,
пока владелец явно не разрешил `allow_unchecked`. Раздела версии в CHANGELOG нет — выпуск не выходит.
Слой для владельца (маркеры `<!-- owner-layer:start/end -->`) проверяется правилами кита; без
маркеров тело — раздел целиком, и итог прямо говорит, что проверка слоя не применялась.

Подкоманды:  plan | checks | notes | summary   (см. main; вывод — JSON или markdown)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])
if str(PKG) not in sys.path:
    sys.path.insert(0, str(PKG))

import yaml  # noqa: E402

from ai_ops_kit.devtools import release_bump  # noqa: E402

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
STAGES = {"off": "автовыпуск выключен", "idle": "новой версии нет", "checks": "идут проверки",
          "ready": "выпуск готов", "published": "выпущено", "refused": "выпуск не выходит"}


def config(root: Path) -> dict:
    try:
        doc = yaml.safe_load((Path(root) / ".ai-ops.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    rel = doc.get("release") if isinstance(doc, dict) else None
    return rel if isinstance(rel, dict) else {}


def _toml_version(text: str, table: str) -> str | None:
    m = re.search(rf"^\[{re.escape(table)}\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    v = m and re.search(r'^version\s*=\s*"([^"]+)"', m.group(1), re.M)
    return v.group(1) if v else None


def version_of(root: Path, cfg: dict | None = None) -> tuple:
    """-> (версия, источник) | (None, причина). Объявленный файл сильнее угаданного."""
    root = Path(root)
    declared = (cfg or {}).get("version_file")
    candidates = [declared] if declared else ["VERSION", "package.json", "pyproject.toml", "Cargo.toml"]
    for name in candidates:
        path = root / str(name)
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if path.name == "package.json":
            try:
                ver = json.loads(text).get("version")
            except ValueError:
                ver = None
        elif path.name == "pyproject.toml":
            ver = _toml_version(text, "project") or _toml_version(text, "tool.poetry")
        elif path.name == "Cargo.toml":
            ver = _toml_version(text, "package")
        else:
            ver = text.strip()
        ver = str(ver or "").strip().removeprefix("v")
        if _SEMVER.match(ver):
            return ver, str(name)
        if declared:
            return None, f"в {name} нет версии вида X.Y.Z"
    return None, "версия не найдена (VERSION / package.json / pyproject.toml / Cargo.toml)"


def plan(root: Path, *, tag_exists: bool) -> dict:
    cfg = config(root)
    if cfg.get("enabled") is not True:
        return {"stage": "off", "needed": False, "reason": "включите release.enabled: true в .ai-ops.yaml"}
    version, source = version_of(root, cfg)
    if not version:
        return {"stage": "refused", "needed": False, "reason": source}
    tag = f"v{version}"
    if tag_exists:
        return {"stage": "idle", "needed": False, "version": version, "tag": tag,
                "reason": f"{tag} уже выпущен"}
    return {"stage": "checks", "needed": True, "version": version, "tag": tag, "version_source": source,
            "reason": f"версия {version} из {source}, тега {tag} нет"}


def check_commands(root: Path, profile: dict) -> tuple:
    """-> ([(где, команда)], [что не проверено]). Объявленные владельцем сильнее профиля."""
    declared = config(root).get("checks")
    if declared:
        return [(".", str(c)) for c in declared], []
    cmds, unchecked = [], []
    for st in profile.get("stacks") or []:
        where, lang = st.get("path") or ".", st.get("language") or "?"
        c = st.get("commands") or {}
        if not c.get("test"):
            unchecked.append(f"{lang} ({where}): нет команды тестов")
        for cmd in (st.get("install_command"), c.get("build"), c.get("test")):
            if cmd:
                cmds.append((where, cmd))
    if not profile.get("stacks"):
        unchecked.append("стек не определён — проверять нечем")
    return cmds, unchecked


def run_checks(root: Path, profile: dict) -> dict:
    cmds, unchecked = check_commands(root, profile)
    results = []
    for where, cmd in cmds:
        proc = subprocess.run(cmd, shell=True, cwd=Path(root) / where, check=False)  # noqa: S602 — команды дочки
        results.append({"where": where, "command": cmd, "ok": proc.returncode == 0})
        if proc.returncode:
            break
    failed = [r for r in results if not r["ok"]]
    allow = config(root).get("allow_unchecked") is True
    ok = bool(results) and not failed and (not unchecked or allow)
    reason = ("проверки прошли" if ok else f"не прошла: {failed[0]['command']}" if failed
              else "не проверено: " + "; ".join(unchecked or ["нет ни одной команды"]))
    return {"ok": ok, "results": results, "unchecked": unchecked, "reason": reason}


def _section(text: str, version: str) -> str:
    head = re.compile(rf"^##\s+\[?v?{re.escape(version)}\]?(?:\s|$)")
    out: list = []
    for line in text.splitlines():
        if out and line.startswith("## "):
            break
        if out or head.match(line):
            out.append(line)
    return "\n".join(out).strip()


def notes(root: Path, version: str, changelog_url: str = "") -> dict:
    """Тело выпуска -> {ok, body, owner_layer_checked, reason}."""
    path = Path(root) / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    section = _section(text, version)
    if not section:
        return {"ok": False, "body": "", "owner_layer_checked": False,
                "reason": f"в CHANGELOG.md нет раздела '## [{version}]'"}
    i, j = section.find(release_bump.OWNER_START), section.find(release_bump.OWNER_END)
    layer = section[i + len(release_bump.OWNER_START):j].strip() if 0 <= i < j else None
    if not layer:
        return {"ok": True, "body": section, "owner_layer_checked": False,
                "reason": "слой для владельца не размечен — тело = раздел целиком, проверка слоя не применялась"}
    try:
        issues = release_bump.check_owner_layer(layer, release_bump.release_rules(PKG))
    except ValueError as e:
        return {"ok": False, "body": "", "owner_layer_checked": False, "reason": str(e)}
    if issues:
        return {"ok": False, "body": "", "owner_layer_checked": True,
                "reason": "слой для владельца не прошёл проверку: " + "; ".join(issues[:3])}
    link = f"\n\n---\n\nПолный список изменений — [CHANGELOG.md]({changelog_url})." if changelog_url else ""
    return {"ok": True, "body": layer + link, "owner_layer_checked": True, "reason": "слой для владельца проверен"}


def summary(stage: str, detail: str = "", version: str = "") -> str:
    head = f"### Выпуск {version}: {STAGES.get(stage, stage)}" if version else f"### Выпуск: {STAGES.get(stage, stage)}"
    return head + (f"\n\n{detail}" if detail else "") + "\n"


def _emit(path: str | None, text: str) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)


def main(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="child_release.py")
    ap.add_argument("cmd", choices=["plan", "checks", "notes", "summary"])
    ap.add_argument("--root", default=".")
    ap.add_argument("--tag-exists", default="0")
    ap.add_argument("--profile")
    ap.add_argument("--version", default="")
    ap.add_argument("--changelog-url", default="")
    ap.add_argument("--out")
    ap.add_argument("--stage", default="checks")
    ap.add_argument("--detail", default="")
    a = ap.parse_args(argv)
    root = Path(a.root)
    if a.cmd == "plan":
        print(json.dumps(plan(root, tag_exists=a.tag_exists == "1"), ensure_ascii=False))
        return 0
    if a.cmd == "checks":
        profile = json.loads(Path(a.profile).read_text(encoding="utf-8")) if a.profile else {}
        res = run_checks(root, profile)
        print(json.dumps(res, ensure_ascii=False))
        _emit(os.environ.get("GITHUB_STEP_SUMMARY"), summary("checks" if res["ok"] else "refused",
                                                             res["reason"], a.version))
        return 0 if res["ok"] else 1
    if a.cmd == "notes":
        res = notes(root, a.version, a.changelog_url)
        if res["ok"] and a.out:
            Path(a.out).write_text(res["body"] + "\n", encoding="utf-8")
        print(res["reason"])
        return 0 if res["ok"] else 1
    _emit(os.environ.get("GITHUB_STEP_SUMMARY"), summary(a.stage, a.detail, a.version))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
