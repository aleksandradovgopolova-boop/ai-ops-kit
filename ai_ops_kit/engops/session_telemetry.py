"""Алиас: engops.session_telemetry -> плоский модуль session_telemetry (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import session_telemetry as _target

sys.modules[__name__] = _target
