"""Совместимость: плоское имя bench_performance -> ai_ops_kit.devtools.bench_performance.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.devtools.bench_performance as _target

sys.modules[__name__] = _target
