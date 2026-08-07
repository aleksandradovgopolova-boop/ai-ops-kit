"""Совместимость: плоское имя usage_ledger -> ai_ops_kit.providers.usage_ledger.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.providers.usage_ledger as _target

sys.modules[__name__] = _target
