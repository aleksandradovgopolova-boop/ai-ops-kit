"""Совместимость: плоское имя architecture_baseline -> ai_ops_kit.engops.architecture_baseline.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.engops.architecture_baseline as _target

sys.modules[__name__] = _target
