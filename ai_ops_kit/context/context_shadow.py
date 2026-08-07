"""Алиас: context.context_shadow -> плоский модуль context_shadow (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import context_shadow as _target

sys.modules[__name__] = _target
