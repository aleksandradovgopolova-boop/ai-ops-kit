"""Совместимость: плоское имя security_pack -> ai_ops_kit.security.security_pack.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.security.security_pack as _target

sys.modules[__name__] = _target
