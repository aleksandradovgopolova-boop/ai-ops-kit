"""Совместимость: плоское имя kit_observability -> ai_ops_kit.devtools.kit_observability.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.devtools.kit_observability as _target

sys.modules[__name__] = _target
