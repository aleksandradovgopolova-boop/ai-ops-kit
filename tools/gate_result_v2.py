"""Совместимость: плоское имя gate_result_v2 -> ai_ops_kit.gates.gate_result_v2.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля, не копия:
иначе состояние разъедется между двумя путями импорта.

_bootstrap импортируется ПЕРВЫМ и кладёт корень репозитория в sys.path — без этого
`import ai_ops_kit...` падает при запуске файла напрямую (`python3 tools/gate_result_v2.py`)
и в child-репозитории, где PYTHONPATH не задан. Локально это скрывала
editable-установка.
"""
import sys

import _bootstrap  # noqa: F401 — кладёт корень и tools/validation в sys.path
import ai_ops_kit.gates.gate_result_v2 as _target

sys.modules[__name__] = _target
