"""Совместимость: плоское имя delegation_advisor -> ai_ops_kit.engops.delegation_advisor.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.engops.delegation_advisor as _target

sys.modules[__name__] = _target
