"""Совместимость: плоское имя run_report -> ai_ops_kit.lifecycle.run_report.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.lifecycle.run_report as _target

sys.modules[__name__] = _target
