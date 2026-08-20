#!/usr/bin/env python3
"""Версионные шаблоны Product Operating Layer и состояние артефакта Missing/Invalid/Outdated/Valid (PR-5).

Реестр (`registry/artifact-registry.yaml`) объявляет ФОРМУ; здесь — код, который держит официальные
ШАБЛОНЫ этой формы и умеет сказать, в каком состоянии находится экземпляр артефакта. Три задачи:

  1. МАШИННАЯ ВАЛИДАЦИЯ ШАБЛОНОВ (`check`). Каждый артефакт реестра с шаблоном обязан иметь файл
     шаблона; версия в файле = версии в реестре; шаблон содержит ВСЕ обязательные разделы
     (markdown) или поля (yaml), объявленные в реестре. Плюс главное правило миграций: нельзя
     поднять версию шаблона, не положив миграцию на каждый шаг (иначе «совместимость либо миграция»
     из PR-5 остаётся словом без исполнения).

  2. ЧЕТЫРЕ СОСТОЯНИЯ ЭКЗЕМПЛЯРА (`state_of`), А НЕ ДВА. `is_file()` != «заполнен» (F-018/F-027):
     файл на диске может быть пустым (Invalid) или отставшим от версии шаблона (Outdated).
        missing  — файла нет;
        invalid  — есть, но структура нарушена: нет маркера версии или обязательного раздела/поля;
        outdated — структура цела, но версия шаблона старее реестра — нужна миграция;
        valid    — есть, структура полна, версия актуальна.
     Порядок — лестница ухудшения; сворачивать «пусто» в «есть» запрещено так же, как unknown в ok.

  3. МИГРАЦИИ ВЕРСИЙ (`missing_migrations`). Отдельная ось от миграций пакета; раскладка и правило —
     в `migrations/product-layer-templates/README.md`.

Состояние экземпляра (state_of) — логика формы; отчёт по репозиторию и CLI `ai-ops validate
product-layer` строит работа `product-layer-validation` поверх этой функции, не дублируя её.

Использование:
  product_templates.py check [--json]                 # шаблоны валидны и покрывают реестр
  product_templates.py state <repo> [--json]           # состояние экземпляров артефактов в репо
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from ai_ops_kit.planning import artifact_registry as AR

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])
TEMPLATES_DIR = PKG / "templates" / "product-layer"
MIGRATIONS_DIR = PKG / "migrations" / "product-layer-templates"

MISSING, INVALID, OUTDATED, VALID = "missing", "invalid", "outdated", "valid"

_HEADER = re.compile(r"^#{1,6}\s+(.*\S)\s*$", re.MULTILINE)


def _markdown_headers(text: str) -> list:
    return [m.group(1).strip() for m in _HEADER.finditer(text)]


def _has_section(headers: list, section: str) -> bool:
    """Раздел присутствует, если хоть один заголовок СОДЕРЖИТ его текст (устойчиво к нумерации/суффиксам)."""
    s = section.strip()
    return any(s in h for h in headers)


def required_migration_steps(version: int) -> list:
    """Шаги миграции, обязательные для шаблона версии V: (1->2), (2->3), …, (V-1->V). V<=1 -> []."""
    return [(n, n + 1) for n in range(1, int(version or 1))]


def _step_dir(artifact_id: str, frm: int, to: int, pkg_root: Path = PKG) -> Path:
    return Path(pkg_root) / "migrations" / "product-layer-templates" / artifact_id / f"v{frm}-to-v{to}"


def missing_migrations(reg: dict, pkg_root: Path = PKG) -> list:
    """Отсутствующие шаги миграции для артефактов с версией шаблона > 1. -> список ошибок.

    Правило PR-5: подъём версии обязан прийти со своей миграцией. Без этого дочка на старой версии
    не догонит новую, а гейт «совместимость либо миграция» окажется беззубым.
    """
    errs = []
    for a in AR.artifacts(reg):
        tpl = a.get("template")
        if not isinstance(tpl, dict) or not isinstance(tpl.get("version"), int):
            continue
        for frm, to in required_migration_steps(tpl["version"]):
            d = _step_dir(a["id"], frm, to, pkg_root)
            for script in ("up.py", "down.py"):
                if not (d / script).is_file():
                    errs.append(f"артефакт '{a['id']}': нет миграции шаблона v{frm}->v{to} "
                                f"({d.relative_to(pkg_root)}/{script}) — версию нельзя поднять без миграции")
    return errs


def check(reg: dict | None = None, pkg_root: Path = PKG) -> list:
    """Машинная валидация шаблонов: покрытие реестра, версии, обязательные разделы/поля, миграции.
    -> список ошибок (пустой = все шаблоны валидны).
    """
    reg = reg or AR.load()
    root = Path(pkg_root)
    errs = []
    for a in AR.artifacts(reg):
        aid = a.get("id")
        tpl = a.get("template")
        if not isinstance(tpl, dict) or not tpl.get("path"):
            continue                                   # directory — шаблона нет по определению
        tpath = root / tpl["path"]
        if not tpath.is_file():
            errs.append(f"артефакт '{aid}': шаблон не найден: {tpl['path']}")
            continue
        declared = tpl.get("version")
        actual = AR._read_template_version(tpath)
        if actual is None:
            errs.append(f"артефакт '{aid}': шаблон {tpl['path']} не объявляет версию "
                        f"(маркер template-version/template_version)")
        elif actual != declared:
            errs.append(f"артефакт '{aid}': версия шаблона {tpl['path']} = {actual}, "
                        f"в реестре = {declared}")
        struct = a.get("structure") or {}
        try:
            text = tpath.read_text(encoding="utf-8")
        except OSError as e:
            errs.append(f"артефакт '{aid}': шаблон не читается: {e}")
            continue
        if a.get("format") == "markdown":
            headers = _markdown_headers(text)
            for sec in struct.get("required_sections") or []:
                if not _has_section(headers, sec):
                    errs.append(f"артефакт '{aid}': в шаблоне нет обязательного раздела «{sec}»")
        elif a.get("format") == "yaml":
            try:
                data = yaml.safe_load(text) or {}
            except yaml.YAMLError as e:
                errs.append(f"артефакт '{aid}': шаблон-yaml не разбирается: {e}")
                data = {}
            if not isinstance(data, dict):
                data = {}
            for field in struct.get("required_fields") or []:
                if field not in data:
                    errs.append(f"артефакт '{aid}': в шаблоне нет обязательного поля '{field}'")
    errs.extend(missing_migrations(reg, pkg_root))
    return errs


def _resolve_instance(repo_root: Path, rel: str) -> Path | None:
    """Экземпляр артефакта в репозитории с учётом project/custom-оверлея. -> путь или None."""
    for pre in ("", ".ai/project/", ".ai/custom/"):
        p = Path(repo_root) / (pre + rel)
        if p.exists():
            return p
    return None


def state_of(repo_root: Path, artifact: dict, reg: dict | None = None) -> dict:
    """Состояние ЭКЗЕМПЛЯРА артефакта в репозитории: missing/invalid/outdated/valid + причина.

    Проверяется СОДЕРЖИМОЕ, а не факт файла: пустой или неполный артефакт — Invalid, отставший по
    версии — Outdated. Оба честнее «Valid», и подмена запрещена так же, как unknown->ok.
    """
    reg = reg or AR.load()
    kind = artifact.get("kind")
    rel = artifact.get("path") or ""
    inst = _resolve_instance(repo_root, rel)
    if inst is None:
        return {"state": MISSING, "reason": f"нет файла {rel}"}

    if kind == "directory":
        return ({"state": VALID, "reason": "каталог на месте"} if inst.is_dir()
                else {"state": INVALID, "reason": f"{rel} существует, но это не каталог"})

    declared = ((artifact.get("template") or {}).get("version"))
    struct = artifact.get("structure") or {}
    try:
        text = inst.read_text(encoding="utf-8")
    except OSError as e:
        return {"state": INVALID, "reason": f"файл не читается: {e}"}

    if artifact.get("format") == "markdown":
        version = AR._read_template_version(inst)
        headers = _markdown_headers(text)
        missing_sec = [s for s in (struct.get("required_sections") or []) if not _has_section(headers, s)]
        if version is None:
            return {"state": INVALID, "reason": "нет маркера версии шаблона"}
        if missing_sec:
            return {"state": INVALID, "reason": f"нет обязательных разделов: {', '.join(missing_sec[:4])}"}
        if isinstance(declared, int) and version < declared:
            return {"state": OUTDATED, "reason": f"версия шаблона {version} < {declared} — нужна миграция"}
        return {"state": VALID, "reason": "структура полна, версия актуальна"}

    if artifact.get("format") == "yaml":
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as e:
            return {"state": INVALID, "reason": f"yaml не разбирается: {e}"}
        if not isinstance(data, dict):
            return {"state": INVALID, "reason": "yaml не является mapping"}
        version = data.get("template_version")
        missing_f = [f for f in (struct.get("required_fields") or []) if f not in data]
        if not isinstance(version, int):
            return {"state": INVALID, "reason": "нет поля template_version"}
        if missing_f:
            return {"state": INVALID, "reason": f"нет обязательных полей: {', '.join(missing_f)}"}
        if isinstance(declared, int) and version < declared:
            return {"state": OUTDATED, "reason": f"версия шаблона {version} < {declared} — нужна миграция"}
        return {"state": VALID, "reason": "поля на месте, версия актуальна"}

    return {"state": INVALID, "reason": f"неизвестный format '{artifact.get('format')}'"}


def report(repo_root: Path, reg: dict | None = None) -> dict:
    """Состояние всех артефактов реестра в репозитории. -> {artifact_id: {state, reason}} + свод."""
    reg = reg or AR.load()
    out = {a["id"]: state_of(repo_root, a, reg) for a in AR.artifacts(reg)}
    counts = {s: sum(1 for v in out.values() if v["state"] == s)
              for s in (MISSING, INVALID, OUTDATED, VALID)}
    return {"artifacts": out, "counts": counts,
            "valid": counts[MISSING] == 0 and counts[INVALID] == 0 and counts[OUTDATED] == 0}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="product_templates.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").add_argument("--json", action="store_true")
    st = sub.add_parser("state")
    st.add_argument("repo")
    st.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv if argv is not None else sys.argv[1:])

    try:
        reg = AR.load()
    except AR.RegistryCorrupt as exc:
        print(f"ШАБЛОНЫ СЛОЯ: реестр недостоверен: {exc}")
        return 1

    if ns.cmd == "check":
        errs = check(reg)
        if ns.json:
            print(json.dumps({"errors": errs, "ok": not errs}, ensure_ascii=False, indent=2))
        elif errs:
            print("ШАБЛОНЫ СЛОЯ: ошибки:")
            for x in errs:
                print(f"  - {x}")
        else:
            print("ШАБЛОНЫ СЛОЯ-OK: все шаблоны версионны, покрывают реестр и мигрируемы.")
        return 1 if errs else 0

    rep = report(Path(ns.repo), reg)
    if ns.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2)); return 0
    for aid, v in rep["artifacts"].items():
        print(f"  {v['state']:9} {aid}: {v['reason']}")
    c = rep["counts"]
    print(f"\nСОСТОЯНИЕ СЛОЯ: valid {c['valid']} · outdated {c['outdated']} · "
          f"invalid {c['invalid']} · missing {c['missing']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
