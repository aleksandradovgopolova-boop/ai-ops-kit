"""Алиас: shared.generate_artifacts -> плоский модуль generate_artifacts (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import generate_artifacts as _target

sys.modules[__name__] = _target
