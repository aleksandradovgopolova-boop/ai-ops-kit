#!/usr/bin/env python3
"""Проверка реестра мутационных проб (`quality/mutation-probes.yaml`, 2026-08-14).

Реестр называет ОХРАННЫЕ проверки механизмов и тесты, которые обязаны краснеть при их снятии.
Прогон проб (`ai_ops_kit/devtools/mutation_probe.py`) медленный; этот валидатор — быстрая половина,
которая держит реестр честным и потому годится в каждый прогон CI:

  1. schema_version/kind на месте; kind == 'mutation-probes'; id уникальны;
  2. у пробы есть file/find/replace_with/tests/why, и `why` не пустое: проба без объяснения, ЧТО
     она охраняет, через месяц станет обрядом, который снимут первым;
  3. файл существует, а образец охраны встречается в нём РОВНО ОДИН раз. Ноль — реестр отстал от
     кода (охрана переписана, проба молча перестала что-либо проверять — тот самый класс, против
     которого весь механизм). Больше одного — мутация неоднозначна;
  4. `replace_with` не равен `find`: мутация, ничего не меняющая, «убивает» мутанта всегда;
  5. каждый названный тест существует.

Использование:  validate_mutation_probes.py [repo] [--json]
Возврат 0 — валиден, 1 — ошибки.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])
PROBES_REL = "quality/mutation-probes.yaml"
KIND = "mutation-probes"
REQUIRED = ("id", "file", "find", "replace_with", "tests", "why")


def check(data: dict, root=None) -> list:
    """Ошибки реестра. `root` задан -> проверяются и файлы с образцами (иначе только форма)."""
    errors = []
    if not isinstance(data, dict):
        return ["реестр не является объектом"]
    if data.get("schema_version") is None:
        errors.append("нет schema_version")
    if data.get("kind") != KIND:
        errors.append(f"kind должен быть '{KIND}'")
    probes = data.get("probes")
    if not isinstance(probes, list) or not probes:
        errors.append("probes должен быть непустым списком")
        return errors

    ids = [p.get("id") for p in probes if isinstance(p, dict)]
    dup = sorted({i for i in ids if i and ids.count(i) > 1})
    if dup:
        errors.append(f"дубли id проб: {', '.join(map(str, dup))}")

    for p in probes:
        if not isinstance(p, dict):
            errors.append("элемент probes не является объектом"); continue
        pid = p.get("id") or "<без id>"
        for k in REQUIRED:
            if not p.get(k):
                errors.append(f"проба '{pid}': нет {k}")
        if not str(p.get("why") or "").strip():
            continue
        if p.get("find") is not None and p.get("find") == p.get("replace_with"):
            errors.append(f"проба '{pid}': replace_with совпадает с find — мутация ничего не меняет, "
                          f"такой мутант «убит» всегда")
        tests = p.get("tests") or []
        if not isinstance(tests, list):
            errors.append(f"проба '{pid}': tests должен быть списком"); tests = []
        if root is not None:
            for t in tests:
                if not (Path(root) / str(t)).is_file():
                    errors.append(f"проба '{pid}': тест '{t}' не существует")
            f = Path(root) / str(p.get("file") or "")
            if not f.is_file():
                errors.append(f"проба '{pid}': файл '{p.get('file')}' не существует")
            elif p.get("find"):
                hits = f.read_text(encoding="utf-8").count(str(p["find"]))
                if hits == 0:
                    errors.append(f"проба '{pid}': образец охраны НЕ НАЙДЕН в {p.get('file')} — "
                                  f"реестр отстал от кода, и проба молча ничего не проверяет")
                elif hits > 1:
                    errors.append(f"проба '{pid}': образец встречается {hits} раз(а) в "
                                  f"{p.get('file')} — мутация неоднозначна")
    return errors


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    args = [a for a in argv if not a.startswith("--")]
    root = Path(args[0]) if args else PKG
    p = root / PROBES_REL
    if not p.is_file():
        print(f"РЕЕСТРА ПРОБ НЕТ: ожидался {PROBES_REL}")
        return 1
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    errors = check(data, root=root)
    if "--json" in argv:
        print(json.dumps({"errors": errors}, ensure_ascii=False, indent=2))
    elif errors:
        print("MUTATION-PROBES: ошибки:")
        for e in errors:
            print(f"  - {e}")
    else:
        print(f"MUTATION-PROBES-OK: {len(data.get('probes') or [])} проб(ы), образцы найдены.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
