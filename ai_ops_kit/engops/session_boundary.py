"""Алиас: engops.session_boundary -> плоский модуль session_boundary (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import session_boundary as _target

sys.modules[__name__] = _target
