"""Совместимость: плоское имя ai_ops_cli -> ai_ops_kit.cli.ai_ops_cli.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.cli.ai_ops_cli as _target

sys.modules[__name__] = _target
