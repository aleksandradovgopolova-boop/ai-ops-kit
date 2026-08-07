"""Совместимость: плоское имя tool_loop -> ai_ops_kit.engine.tool_loop.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.engine.tool_loop as _target

sys.modules[__name__] = _target
