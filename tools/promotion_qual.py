"""Совместимость: плоское имя promotion_qual -> ai_ops_kit.devtools.promotion_qual.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.devtools.promotion_qual as _target

sys.modules[__name__] = _target
