"""Алиас: delivery.review_branch -> плоский модуль review_branch (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import review_branch as _target

sys.modules[__name__] = _target
