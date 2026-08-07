"""Совместимость: плоское имя review_branch -> ai_ops_kit.delivery.review_branch.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля, не копия:
иначе состояние разъедется между двумя путями импорта.

_bootstrap импортируется ПЕРВЫМ и кладёт корень репозитория в sys.path — без этого
`import ai_ops_kit...` падает при запуске файла напрямую (`python3 tools/review_branch.py`)
и в child-репозитории, где PYTHONPATH не задан. Локально это скрывала
editable-установка.
"""
import sys

import _bootstrap  # noqa: F401 — кладёт корень и tools/validation в sys.path
import ai_ops_kit.delivery.review_branch as _target

sys.modules[__name__] = _target
