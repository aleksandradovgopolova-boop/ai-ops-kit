"""Алиас: context.context_cost -> плоский модуль context_cost (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import context_cost as _target

sys.modules[__name__] = _target
