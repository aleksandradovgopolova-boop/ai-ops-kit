"""Совместимость: плоское имя environment_map -> ai_ops_kit.engops.environment_map.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.engops.environment_map as _target

sys.modules[__name__] = _target
