"""Совместимость: плоское имя health_tech -> ai_ops_kit.intelligence.health_tech.

Код живёт в пакете. Здесь алиас через sys.modules — ОДИН объект модуля, не копия.
_bootstrap кладёт корень репозитория в sys.path (см. tools/health_product.py).
"""
import sys

import _bootstrap  # noqa: F401 — кладёт корень и tools/validation в sys.path

if __name__ == "__main__":
    import runpy

    runpy.run_module("ai_ops_kit.intelligence.health_tech", run_name="__main__", alter_sys=True)
else:
    import ai_ops_kit.intelligence.health_tech as _target

    sys.modules[__name__] = _target
