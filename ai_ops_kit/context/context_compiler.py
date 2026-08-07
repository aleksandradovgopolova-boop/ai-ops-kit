"""Алиас: context.context_compiler -> плоский модуль context_compiler (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import context_compiler as _target

sys.modules[__name__] = _target
