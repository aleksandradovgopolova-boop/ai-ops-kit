"""Алиас: providers.usage_ledger -> плоский модуль usage_ledger (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import usage_ledger as _target

sys.modules[__name__] = _target
