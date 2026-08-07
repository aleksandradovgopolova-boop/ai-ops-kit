"""Совместимость: плоское имя seam_scan -> ai_ops_kit.security.seam_scan.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.security.seam_scan as _target

sys.modules[__name__] = _target
