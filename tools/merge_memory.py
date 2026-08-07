"""Совместимость: плоское имя merge_memory -> ai_ops_kit.lifecycle.merge_memory.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.lifecycle.merge_memory as _target

sys.modules[__name__] = _target
