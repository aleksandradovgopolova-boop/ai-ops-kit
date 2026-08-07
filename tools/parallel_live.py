"""Совместимость: плоское имя parallel_live -> ai_ops_kit.engine.parallel_live.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.engine.parallel_live as _target

sys.modules[__name__] = _target
