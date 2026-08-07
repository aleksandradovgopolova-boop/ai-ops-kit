"""Алиас: security.security_review_cascade -> плоский модуль security_review_cascade (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import security_review_cascade as _target

sys.modules[__name__] = _target
