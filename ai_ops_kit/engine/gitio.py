"""Алиас: engine.gitio -> плоский модуль gitio (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import gitio as _target

sys.modules[__name__] = _target
