"""Совместимость: плоское имя ui_evidence_collect -> ai_ops_kit.ui.ui_evidence_collect.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.ui.ui_evidence_collect as _target

sys.modules[__name__] = _target
