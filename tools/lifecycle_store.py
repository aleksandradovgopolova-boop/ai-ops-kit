"""Совместимость: плоское имя lifecycle_store -> ai_ops_kit.lifecycle.lifecycle_store.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.lifecycle.lifecycle_store as _target

sys.modules[__name__] = _target
