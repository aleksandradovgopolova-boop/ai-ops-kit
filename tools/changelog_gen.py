"""Совместимость: плоское имя changelog_gen -> ai_ops_kit.devtools.changelog_gen.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.devtools.changelog_gen as _target

sys.modules[__name__] = _target
