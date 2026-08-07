"""Совместимость: плоское имя review_branch -> ai_ops_kit.delivery.review_branch.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.delivery.review_branch as _target

sys.modules[__name__] = _target
