"""Алиас: providers.orchestrator -> плоский модуль orchestrator (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import orchestrator as _target

sys.modules[__name__] = _target
