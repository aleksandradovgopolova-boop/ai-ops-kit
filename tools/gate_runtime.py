"""Совместимость: плоское имя gate_runtime -> ai_ops_kit.gates.gate_runtime.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.gates.gate_runtime as _target

sys.modules[__name__] = _target
