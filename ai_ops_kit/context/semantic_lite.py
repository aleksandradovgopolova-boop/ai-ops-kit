"""Алиас: context.semantic_lite -> плоский модуль semantic_lite (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import semantic_lite as _target

sys.modules[__name__] = _target
