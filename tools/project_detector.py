"""Совместимость: плоское имя project_detector -> ai_ops_kit.shared.project_detector.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.shared.project_detector as _target

sys.modules[__name__] = _target
