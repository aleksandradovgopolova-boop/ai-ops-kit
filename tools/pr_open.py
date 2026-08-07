"""Совместимость: плоское имя pr_open -> ai_ops_kit.delivery.pr_open.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.delivery.pr_open as _target

sys.modules[__name__] = _target
