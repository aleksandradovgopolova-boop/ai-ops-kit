"""Совместимость: плоское имя evolution_triggers -> ai_ops_kit.lifecycle.evolution_triggers.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.lifecycle.evolution_triggers as _target

sys.modules[__name__] = _target
