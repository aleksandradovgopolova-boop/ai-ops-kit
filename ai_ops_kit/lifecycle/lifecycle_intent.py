"""Алиас: lifecycle.lifecycle_intent -> плоский модуль lifecycle_intent (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import lifecycle_intent as _target

sys.modules[__name__] = _target
