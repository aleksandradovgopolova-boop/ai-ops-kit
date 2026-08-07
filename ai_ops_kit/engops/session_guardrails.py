"""Алиас: engops.session_guardrails -> плоский модуль session_guardrails (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import session_guardrails as _target

sys.modules[__name__] = _target
