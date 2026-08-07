"""Совместимость: плоское имя model_comparison -> ai_ops_kit.devtools.model_comparison.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.devtools.model_comparison as _target

sys.modules[__name__] = _target
