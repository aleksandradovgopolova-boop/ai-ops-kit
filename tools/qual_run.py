"""Совместимость: плоское имя qual_run -> ai_ops_kit.devtools.qual_run.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.devtools.qual_run as _target

sys.modules[__name__] = _target
