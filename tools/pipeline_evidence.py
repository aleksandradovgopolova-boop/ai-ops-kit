"""Совместимость: плоское имя pipeline_evidence -> ai_ops_kit.engine.pipeline_evidence.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.engine.pipeline_evidence as _target

sys.modules[__name__] = _target
