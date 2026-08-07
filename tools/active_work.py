"""Совместимость: плоское имя active_work -> ai_ops_kit.lifecycle.active_work.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.lifecycle.active_work as _target

sys.modules[__name__] = _target
