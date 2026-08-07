"""Алиас: gates.invariants -> плоский модуль invariants (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import invariants as _target

sys.modules[__name__] = _target
