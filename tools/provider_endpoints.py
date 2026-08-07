"""Совместимость: плоское имя provider_endpoints -> ai_ops_kit.providers.provider_endpoints.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.providers.provider_endpoints as _target

sys.modules[__name__] = _target
