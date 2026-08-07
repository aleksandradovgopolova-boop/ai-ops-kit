"""Совместимость: плоское имя storybook_adapter -> ai_ops_kit.ui.storybook_adapter.

Код переехал в пакет. Здесь алиас через sys.modules — ОДИН объект модуля,
не копия: иначе состояние разъедется между двумя путями импорта.
"""
import sys

import ai_ops_kit.ui.storybook_adapter as _target

sys.modules[__name__] = _target
