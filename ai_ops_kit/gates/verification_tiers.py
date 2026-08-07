"""Алиас: gates.verification_tiers -> плоский модуль verification_tiers (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import verification_tiers as _target

sys.modules[__name__] = _target
