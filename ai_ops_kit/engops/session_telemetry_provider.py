"""Алиас: engops.session_telemetry_provider -> плоский модуль session_telemetry_provider (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import session_telemetry_provider as _target

sys.modules[__name__] = _target
