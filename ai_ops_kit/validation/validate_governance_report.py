#!/usr/bin/env python3
"""validate_governance_report.py — governance-отчёт соответствия ПРОДУКТА дочки стандарту на PR.

SR-17: добавляется в СУЩЕСТВУЮЩУЮ джобу дочки (`ai-ops-validate.yml`) отдельным шагом, а не второй
джобой того же смысла. Первая часть той джобы — здоровье установки (validate_ai_ops_child,
check-update); эта часть — соответствие стандарту. Так время не удваивается и мест отказа не два.

SR-18: отчёт — машиночитаемый артефакт со схемой (schemas/governance-report.schema.json) и версией
(`report_version`); `--out` кладёт его в область дочки, откуда шаг CI поднимает его как артефакт
прогона (история PR) — а не оставляет текстом в логе.

SR-19: этот шаг НЕ добавляет девятый блокирующий гейт. Отчёт advisory — он ВСЕГДА возвращает 0 и
только показывает четыре числа и override; право блокировать имеет лишь проверка с измеренным нулём
ложных (issue #605 §5), это следующие срезы. Здесь — доставка отчёта, не его сила.

SR-20..23: см. ai_ops_kit/planning/governance_report — closed_by у каждой строки, override с
причиной/сроком, `not_applicable` == число активных override, четыре числа с суммой.

Тонкий процесс-вход: вся логика в planning/governance_report (её же зовут тесты); здесь — разбор
аргументов, запись файла и печать. Так модуль-сборщик ПРОВЕДЁН В КОНТУР (не-тестовый импортёр), а
не остаётся дормантным.

Использование:  validate_governance_report.py [repo] [--out FILE] [--json]
Возврат ВСЕГДА 0 (advisory): нет .ai-ops.yaml — репозиторий не дочка, отчёт пуст, тоже 0.
Требует pyyaml.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:                                          # v3.34: валидатор двурежимен
    from ai_ops_kit.validation import _bootstrap   # noqa: F401 — импорт пакетом (после pip install)
except ImportError:                                # запуск скриптом: корня на пути ещё нет,
    import _bootstrap                              # noqa: F401 — и положить его может только он сам

from ai_ops_kit.planning import governance_report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="validate_governance_report.py",
                                 description="Governance-отчёт соответствия продукта стандарту (SR-17..23)")
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--out", help="записать отчёт JSON в этот файл (SR-18: артефакт в истории дочки)")
    ap.add_argument("--json", action="store_true", help="печатать отчёт как JSON")
    ns = ap.parse_args(argv if argv is not None else sys.argv[1:])

    root = Path(ns.repo)
    rep = governance_report.build(root)
    if ns.out:
        out = Path(ns.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if ns.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(governance_report.render(rep))
    return 0   # advisory (SR-19): доставка отчёта не заводит блокирующий гейт


if __name__ == "__main__":
    raise SystemExit(main())
