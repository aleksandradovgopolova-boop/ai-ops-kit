"""Алиас: gates.evidence_collector -> плоский модуль evidence_collector (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import evidence_collector as _target

sys.modules[__name__] = _target
