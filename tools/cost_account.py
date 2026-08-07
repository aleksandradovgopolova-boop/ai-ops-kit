"""Совместимость: плоское имя cost_account -> ai_ops_kit.providers.cost_account.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.providers.cost_account as _target

sys.modules[__name__] = _target
