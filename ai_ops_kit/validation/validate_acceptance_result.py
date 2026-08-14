#!/usr/bin/env python3
"""Проверка структурного результата сверки критериев приёмки (B2-14, 2026-08-14).

Ревьюер сверки возвращает не прозу «всё выполнено», а структуру: вердикт ПО КАЖДОМУ объявленному
критерию с ЦИТАТОЙ как основанием. Валидатор держит эту структуру честной — он единственное место,
где «вердикт вынесен» отличается от «вердикт выглядит вынесенным»:

  1. schema_version/kind на месте; kind == 'acceptance-result';
  2. criteria — непустой список; у каждого элемента id и status ∈ met|unmet|undetermined;
  3. вердикты покрывают РОВНО объявленные критерии: ни пропуска, ни дубля, ни выдуманного id.
     Пропущенный критерий — это НЕ «выполнен по умолчанию»: без него сверка неполна, и её нельзя
     называть сверкой (тот же инвариант, что `unavailable != 0`);
  4. `met` ОБЯЗАН иметь непустые quote и source: «выполнен» без основания неопровержим, а именно
     неопровержимое утверждение и дало ложный green B2-14;
  5. `unmet`/`undetermined` обязаны иметь reason или quote — честность симметрична: нельзя
     фабриковать ни «выполнено», ни «не выполнено» (та же симметрия, что в reviewer-result).

Почему валидатор отдельный, а не расширение `validate_reviewer_result`: там вердикт ОДИН на гейт
(status), здесь — по одному на критерий, и главное поле (`quote`) в reviewer-result отсутствует.
Смешать их значило бы ослабить оба контракта до пересечения.

Использование:  validate_acceptance_result.py <result.json> [--criteria AC-1,AC-2] [--json]
Возврат 0 — валиден, 1 — ошибки.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CRITERION_STATUS = {"met", "unmet", "undetermined"}


def check(data: dict, criterion_ids=None) -> list:
    """Ошибки формы вердикта. criterion_ids — объявленные id (None = «не знаю, не проверяю охват»).

    Различие None и пустого множества здесь такое же, как в `validate_reviewer_result._gate_ids`:
    «охват не проверялся» и «критериев нет» — разные факты, и путать их дороже, чем передать None.
    """
    errors = []
    if not isinstance(data, dict):
        return ["результат не является объектом"]
    if data.get("schema_version") is None:
        errors.append("нет schema_version")
    if data.get("kind") != "acceptance-result":
        errors.append("kind должен быть 'acceptance-result'")

    crits = data.get("criteria")
    if not isinstance(crits, list) or not crits:
        errors.append("criteria должен быть непустым списком")
        return errors

    seen = []
    for c in crits:
        if not isinstance(c, dict) or not c.get("id"):
            errors.append("критерий требует id:str")
            continue
        cid = str(c["id"])
        seen.append(cid)
        st = c.get("status")
        if st not in CRITERION_STATUS:
            errors.append(f"{cid}: status '{st}' не в {sorted(CRITERION_STATUS)}")
            continue
        quote = str(c.get("quote") or "").strip()
        source = str(c.get("source") or "").strip()
        reason = str(c.get("reason") or "").strip()
        if st == "met" and not quote:
            errors.append(f"{cid}: status=met без quote — «выполнен» без основания не проверяем")
        if st == "met" and not source:
            errors.append(f"{cid}: status=met без source — непонятно, где искать цитату")
        if st in ("unmet", "undetermined") and not (reason or quote):
            errors.append(f"{cid}: status={st} требует reason или quote (вердикт без причины)")

    dupes = sorted({i for i in seen if seen.count(i) > 1})
    if dupes:
        errors.append(f"дубли вердиктов по критериям: {', '.join(dupes)}")
    if criterion_ids is not None:
        declared = {str(i) for i in criterion_ids}
        got = set(seen)
        missing = sorted(declared - got)
        extra = sorted(got - declared)
        if missing:
            errors.append(f"нет вердикта по критериям: {', '.join(missing)} — сверка неполна")
        if extra:
            errors.append(f"вердикт по необъявленным критериям: {', '.join(extra)}")
    return errors


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    crit_ids = None
    for a in argv:
        if a.startswith("--criteria="):
            crit_ids = [x.strip() for x in a.split("=", 1)[1].split(",") if x.strip()]
    data = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    errors = check(data, crit_ids)
    if "--json" in argv:
        print(json.dumps({"errors": errors}, ensure_ascii=False, indent=2))
    elif errors:
        print("ACCEPTANCE-RESULT: ошибки:")
        for e in errors:
            print(f"  - {e}")
    else:
        print("ACCEPTANCE-RESULT-OK: структура валидна.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
