"""Совместимость: плоское имя run_plan -> ai_ops_kit.engine.run_plan.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.engine.run_plan as _target

sys.modules[__name__] = _target
