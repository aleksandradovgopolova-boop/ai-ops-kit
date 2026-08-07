"""Совместимость: плоское имя spec_levels -> ai_ops_kit.gates.spec_levels.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.gates.spec_levels as _target

sys.modules[__name__] = _target
