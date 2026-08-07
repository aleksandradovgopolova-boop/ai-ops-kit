"""Совместимость: плоское имя atomic_planner -> ai_ops_kit.engine.atomic_planner.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.engine.atomic_planner as _target

sys.modules[__name__] = _target
