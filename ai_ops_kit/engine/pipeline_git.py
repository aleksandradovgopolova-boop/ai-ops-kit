"""Алиас: engine.pipeline_git -> плоский модуль pipeline_git (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import pipeline_git as _target

sys.modules[__name__] = _target
