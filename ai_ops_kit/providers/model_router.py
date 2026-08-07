"""Алиас: providers.model_router -> плоский модуль model_router (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import model_router as _target

sys.modules[__name__] = _target
