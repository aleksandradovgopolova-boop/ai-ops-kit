"""Совместимость: плоское имя orchestrator_usage -> ai_ops_kit.providers.orchestrator_usage.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.providers.orchestrator_usage as _target

sys.modules[__name__] = _target
