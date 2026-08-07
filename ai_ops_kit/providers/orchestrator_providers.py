"""Алиас: providers.orchestrator_providers -> плоский модуль orchestrator_providers (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import orchestrator_providers as _target

sys.modules[__name__] = _target
