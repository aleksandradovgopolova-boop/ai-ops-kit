"""Алиас: engine.pipeline_helpers -> плоский модуль pipeline_helpers (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import pipeline_helpers as _target

sys.modules[__name__] = _target
