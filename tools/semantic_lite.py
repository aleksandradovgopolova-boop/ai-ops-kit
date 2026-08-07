"""Совместимость: плоское имя semantic_lite -> ai_ops_kit.context.semantic_lite.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.context.semantic_lite as _target

sys.modules[__name__] = _target
