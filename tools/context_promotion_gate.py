"""Совместимость: плоское имя context_promotion_gate -> ai_ops_kit.context.context_promotion_gate.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.context.context_promotion_gate as _target

sys.modules[__name__] = _target
