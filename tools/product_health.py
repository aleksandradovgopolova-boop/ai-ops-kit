"""Совместимость: плоское имя product_health -> ai_ops_kit.lifecycle.product_health.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.lifecycle.product_health as _target

sys.modules[__name__] = _target
