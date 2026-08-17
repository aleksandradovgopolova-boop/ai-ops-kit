#!/usr/bin/env python3
"""Откат: перенесённые миграцией работы возвращаются в активный план.

ОБРАТИМА ЧАСТИЧНО, И ЭТО НАЗВАНО. Возвращаются ТОЛЬКО записи с пометкой
`migrated_without_result: true` — то есть ровно те, которые создала up. Работы, закрытые по правилам
(с названным результатом и местом перепроверки), в активный план не возвращаются: они там и не были.
Пометка и служебный `result` снимаются, чтобы запись выглядела как до миграции.

Комментарии yaml, потерянные при переписывании файла, откатом не восстанавливаются — их не
восстановит ничто, и обещать это нельзя.

Аргумент — корень child-репозитория.
"""
import sys
from pathlib import Path

MARK = "migrated_without_result"


def main(root):
    try:
        import yaml
    except ImportError:
        print("откат миграции плана: нет pyyaml — возврат не выполнен", file=sys.stderr)
        return 1
    root = Path(root)
    plan_path, hist_path = root / "planning" / "plan.yaml", root / "history" / "plan-history.yaml"
    if not (plan_path.is_file() and hist_path.is_file()):
        print("откат миграции плана: плана или истории нет — возвращать нечего")
        return 0

    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    hist = yaml.safe_load(hist_path.read_text(encoding="utf-8")) or {}
    hist_work = hist.get("work") if isinstance(hist.get("work"), list) else []
    back = [w for w in hist_work if isinstance(w, dict) and w.get(MARK)]
    if not back:
        print("откат миграции плана: записей, созданных миграцией, нет")
        return 0

    restored = []
    for w in back:
        entry = {k: v for k, v in w.items() if k not in (MARK, "result")}
        restored.append(entry)
    plan["work"] = (plan.get("work") or []) + restored
    hist["work"] = [w for w in hist_work if not (isinstance(w, dict) and w.get(MARK))]

    plan_path.write_text(yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), encoding="utf-8")
    hist_path.write_text(yaml.safe_dump(hist, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"откат миграции плана: возвращено в активный план работ {len(restored)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
