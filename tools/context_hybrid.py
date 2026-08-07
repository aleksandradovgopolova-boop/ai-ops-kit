"""Совместимость: плоское имя context_hybrid -> ai_ops_kit.context.context_hybrid.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.context.context_hybrid as _target

sys.modules[__name__] = _target
