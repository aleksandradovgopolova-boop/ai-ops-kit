"""Алиас: engine.execution_pipeline -> плоский модуль execution_pipeline (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import execution_pipeline as _target

sys.modules[__name__] = _target
