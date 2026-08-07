"""Совместимость: плоское имя repo_graph -> ai_ops_kit.context.repo_graph.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.context.repo_graph as _target

sys.modules[__name__] = _target
