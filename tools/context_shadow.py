"""Совместимость: плоское имя context_shadow -> ai_ops_kit.context.context_shadow.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля, не копия:
иначе состояние разъедется между двумя путями импорта.

_bootstrap импортируется ПЕРВЫМ и кладёт корень репозитория в sys.path — без этого
`import ai_ops_kit...` падает при запуске файла напрямую (`python3 tools/context_shadow.py`)
и в child-репозитории, где PYTHONPATH не задан. Локально это скрывала
editable-установка.
"""
import sys

import _bootstrap  # noqa: F401 — кладёт корень и tools/validation в sys.path
import ai_ops_kit.context.context_shadow as _target

sys.modules[__name__] = _target
