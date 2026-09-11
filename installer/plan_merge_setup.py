"""Регистрация merge-driver planning/plan.yaml в дочке.

Вынесено из `installer/ai_ops.py`, который стоит на потолке module-size (монолит не растим ради
пары функций). Атрибут `planning/plan.yaml merge=ai-ops-plan` в `.gitattributes` ставит
`ensure_gitattributes`; здесь — ВТОРАЯ половина: запись `merge.ai-ops-plan.driver` в git config
дочки. Без неё git молча откатывается на обычное трёхстороннее слияние — атрибут бездействует
(built≠wired). Сам драйвер (`ai_ops_kit/planning/plan_merge_driver.py`) едет в managed-слой и
зовётся git'ом дочки оттуда.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# Имя драйвера в git config = тот же токен, что и в `.gitattributes` (…merge=ai-ops-plan).
DRIVER_NAME = "ai-ops-plan"
# Доставленный путь драйвера в дочке (managed-слой сохраняет относительный путь пакета).
DELIVERED = ".ai/managed/ai_ops_kit/planning/plan_merge_driver.py"


def ensure_plan_merge_driver(root):
    """Прописать `merge.ai-ops-plan.driver` в git config дочки. -> статус.

    Идемпотентно (git config перезаписывает то же значение). Fail-soft: без git-репозитория или при
    ошибке git тихо возвращает статус, не роняя установку (в не-git-каталоге сводить всё равно нечего).
    """
    root = Path(root)
    if not (root / ".git").exists():
        return "skipped-no-git"
    driver_cmd = f"python3 {DELIVERED} %O %A %B"
    try:
        subprocess.run(["git", "-C", str(root), "config", f"merge.{DRIVER_NAME}.name",
                        "AI Ops: структурное слияние planning/plan.yaml"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(root), "config", f"merge.{DRIVER_NAME}.driver", driver_cmd],
                       check=True, capture_output=True)
    except (subprocess.CalledProcessError, OSError):
        return "skipped-git-error"
    return "registered"


def plan_merge_report_line(status):
    """Строка отчёта установщика про драйвер плана. -> str (пустая, если драйвер не прописан)."""
    if status != "registered":
        return ""
    return ("\nMerge-driver planning/plan.yaml прописан в git config: непересекающиеся правки плана"
            " из разных работ теперь сводятся без ручного конфликта, на сомнении — обычный конфликт.")
