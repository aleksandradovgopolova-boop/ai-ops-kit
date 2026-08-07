"""Совместимость: плоское имя model_router -> ai_ops_kit.providers.model_router.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.providers.model_router as _target

sys.modules[__name__] = _target
