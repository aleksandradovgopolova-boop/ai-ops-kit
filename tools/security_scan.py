"""Совместимость: плоское имя security_scan -> ai_ops_kit.security.security_scan.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.security.security_scan as _target

sys.modules[__name__] = _target
