"""Совместимость: плоское имя security_enforcement -> ai_ops_kit.security.security_enforcement.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.security.security_enforcement as _target

sys.modules[__name__] = _target
