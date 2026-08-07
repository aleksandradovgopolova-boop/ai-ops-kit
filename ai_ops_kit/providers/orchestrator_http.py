"""Алиас: providers.orchestrator_http -> плоский модуль orchestrator_http (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import orchestrator_http as _target

sys.modules[__name__] = _target
