"""Алиас: engine.pipeline_evidence -> плоский модуль pipeline_evidence (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import pipeline_evidence as _target

sys.modules[__name__] = _target
