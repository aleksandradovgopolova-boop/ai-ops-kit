"""Совместимость: плоское имя worktree -> ai_ops_kit.engine.worktree.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.engine.worktree as _target

sys.modules[__name__] = _target
