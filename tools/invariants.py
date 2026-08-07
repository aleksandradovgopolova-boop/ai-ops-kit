"""Совместимость: плоское имя invariants -> ai_ops_kit.gates.invariants.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.gates.invariants as _target

sys.modules[__name__] = _target
