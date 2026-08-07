"""Совместимость: плоское имя session_boundary -> ai_ops_kit.engops.session_boundary.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.engops.session_boundary as _target

sys.modules[__name__] = _target
