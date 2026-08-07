"""Совместимость: плоское имя deploy_readiness -> ai_ops_kit.engops.deploy_readiness.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.engops.deploy_readiness as _target

sys.modules[__name__] = _target
