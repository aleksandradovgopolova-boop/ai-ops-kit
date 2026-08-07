"""Совместимость: плоское имя pipeline_helpers -> ai_ops_kit.engine.pipeline_helpers.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.engine.pipeline_helpers as _target

sys.modules[__name__] = _target
