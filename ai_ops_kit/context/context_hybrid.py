"""Алиас: context.context_hybrid -> плоский модуль context_hybrid (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import context_hybrid as _target

sys.modules[__name__] = _target
