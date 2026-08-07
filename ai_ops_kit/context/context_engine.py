"""Алиас: context.context_engine -> плоский модуль context_engine (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import context_engine as _target

sys.modules[__name__] = _target
