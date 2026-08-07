"""Алиас: context.context_promotion_gate -> плоский модуль context_promotion_gate (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import context_promotion_gate as _target

sys.modules[__name__] = _target
