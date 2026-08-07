"""Совместимость: плоское имя retrieval_bench -> ai_ops_kit.devtools.retrieval_bench.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.devtools.retrieval_bench as _target

sys.modules[__name__] = _target
