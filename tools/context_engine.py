"""Совместимость: плоское имя context_engine -> ai_ops_kit.context.context_engine.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.context.context_engine as _target

sys.modules[__name__] = _target
