"""Совместимость: плоское имя generate_runtime -> ai_ops_kit.shared.generate_runtime.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.shared.generate_runtime as _target

sys.modules[__name__] = _target
