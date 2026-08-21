#!/usr/bin/env python3
"""Инвариант: проверки запускаются ТОЛЬКО через pytest (v3.30).

Прежняя роль этого валидатора — ловить дрейф между списком команд в чеклисте и командами в CI.
Списка больше нет: 201 команда переехала в pytest, чеклист сводится к `./scripts/check-full.sh`.
Валидатор перенаправлен на инвариант, который этот переезд защищает: CI не имеет права запускать
проверки в обход pytest, иначе дубль и рассинхрон вернутся — за одну сессию их ловили трижды.

Разрешено: pytest в любом виде, скрипты групп (они сами вызывают pytest), установка зависимостей,
служебные шаги. Запрещено: прямой запуск валидатора или инструмента как проверки.

  validate_agents_checklist.py [--json]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])
WORKFLOWS = PKG / ".github" / "workflows"

# Шаги, которые не являются проверками и потому не обязаны идти через pytest.
ALLOWED = (
    re.compile(r"^python3?\s+-m\s+pytest\b"),
    re.compile(r"^bash\s+\.github/ci-groups/"),
    # Установка зависимости — не проверка, и это уже было объявлено. Но образец знал только
    # голое `pip install`, а канонический способ — `python -m pip install`: он ставит пакет
    # ИМЕННО в тот интерпретатор, которым потом запускают, и потому рекомендован. Первая же
    # джоба, написанная канонически, объявлялась нарушением инварианта. Правило говорило одно,
    # образец проверял другое.
    re.compile(r"^(?:python3?\s+-m\s+)?pip\s+install\b"),
    re.compile(r"^\./scripts/check-(fast|full)\.sh"),
)


def offending_commands(root: Path = PKG):
    """Команды в workflow, которые запускают проверку мимо pytest."""
    bad = []
    for wf in sorted((root / ".github" / "workflows").glob("*.yml")):
        try:
            doc = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            bad.append((wf.name, f"нечитаемый YAML: {e}"))
            continue
        for job in (doc.get("jobs") or {}).values():
            for step in (job.get("steps") or []):
                run = step.get("run")
                if not isinstance(run, str):
                    continue
                for raw in run.splitlines():
                    line = raw.strip()
                    if not line.startswith(("python3 ", "python ")):
                        continue
                    if any(p.match(line) for p in ALLOWED):
                        continue
                    bad.append((wf.name, line))
    return bad


def main(argv):
    bad = offending_commands()
    if "--json" in argv:
        print(json.dumps({"kind": "pytest-only-invariant",
                          "offending": [{"workflow": w, "command": c} for w, c in bad]},
                         ensure_ascii=False, indent=2))
        return 1 if bad else 0
    if bad:
        print(f"PYTEST-ONLY-DRIFT: {len(bad)} проверок запускаются мимо pytest:")
        for w, c in bad:
            print(f"  {w}: {c}")
        print("  перенеси проверку в tests/ — она попадёт в свою группу CI сама")
        return 1
    print("PYTEST-ONLY-OK: CI запускает проверки только через pytest.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
