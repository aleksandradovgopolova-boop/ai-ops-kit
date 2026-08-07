"""Алиас: engine.pipeline_failure -> плоский модуль pipeline_failure (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import pipeline_failure as _target

sys.modules[__name__] = _target
