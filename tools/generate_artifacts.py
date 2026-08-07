"""Совместимость: плоское имя generate_artifacts -> ai_ops_kit.shared.generate_artifacts.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.shared.generate_artifacts as _target

sys.modules[__name__] = _target
