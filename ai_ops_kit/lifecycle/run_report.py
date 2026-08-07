"""Алиас: lifecycle.run_report -> плоский модуль run_report (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import run_report as _target

sys.modules[__name__] = _target
