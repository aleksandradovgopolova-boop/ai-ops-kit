"""Совместимость: плоское имя commit_policy -> ai_ops_kit.engops.commit_policy.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.engops.commit_policy as _target

sys.modules[__name__] = _target
