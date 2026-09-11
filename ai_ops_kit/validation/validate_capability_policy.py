#!/usr/bin/env python3
"""Честность capability-policy: 7 осей задают настройки намерением, planned не выдан за готовое (#644).

Настройки задаются intent-level выбором по оси (registry/capability-policy.yaml), а не набором
флагов. Этот вход проверяет, что реестр ЧЕСТЕН: у каждого выбора валидный status, `default` —
implemented-выбор (по умолчанию не включаем непостроенное), а объявленный mechanism резолвится.
Логику держит ai_ops_kit/checks/capability_policy (слой primitives); здесь — тонкий process-вход
(CI/doctor), который тянет её ВНИЗ, без восходящего ребра.

Использование:
  validate_capability_policy.py           # проверить реестр кита
Возврат 0 — честен, 1 — есть нарушения.
"""
from __future__ import annotations

import sys

try:                                          # двурежимный, как соседние валидаторы
    from ai_ops_kit.validation import _bootstrap   # noqa: F401 — импорт пакетом (после pip install)
except ImportError:                                # запуск скриптом: корня на пути ещё нет,
    import _bootstrap                              # noqa: F401 — и положить его может только он сам
from ai_ops_kit.checks import capability_policy as cp   # noqa: E402


def main(argv=None) -> int:
    errs = cp.honesty_errors()
    for e in errs:
        print(f"  [FAIL] {e}")
    if errs:
        print(f"CAPABILITY-POLICY-FAIL: нарушений {len(errs)}")
        return 1
    axes = cp.load_policy().get("axes") or {}
    print(f"CAPABILITY-POLICY-OK: {len(axes)} осей, статусы валидны, default implemented, "
          "mechanism резолвятся.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
