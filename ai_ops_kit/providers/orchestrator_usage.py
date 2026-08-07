"""Алиас: providers.orchestrator_usage -> плоский модуль orchestrator_usage (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import orchestrator_usage as _target

sys.modules[__name__] = _target
