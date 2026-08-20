"""Совместимость: плоское имя health_product -> ai_ops_kit.intelligence.health_product.

Код живёт в пакете. Здесь алиас через sys.modules — ОДИН объект модуля, не копия:
иначе состояние разъедется между двумя путями импорта.

_bootstrap импортируется ПЕРВЫМ и кладёт корень репозитория в sys.path — без этого
`import ai_ops_kit...` падает при запуске файла напрямую (`python3 tools/health_product.py`)
и в child-репозитории, где PYTHONPATH не задан.

Запуск скриптом идёт через runpy, а не через подмену sys.modules: подмена ломала
`if __name__ == "__main__"` в цели, и команда молча ничего не делала с кодом 0 (v3.31.1).
"""
import sys

import _bootstrap  # noqa: F401 — кладёт корень и tools/validation в sys.path

if __name__ == "__main__":
    import runpy

    runpy.run_module("ai_ops_kit.intelligence.health_product", run_name="__main__", alter_sys=True)
else:
    import ai_ops_kit.intelligence.health_product as _target

    sys.modules[__name__] = _target
