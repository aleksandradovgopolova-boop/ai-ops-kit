"""Алиас: gates.regression_evidence -> плоский модуль regression_evidence (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import regression_evidence as _target

sys.modules[__name__] = _target
