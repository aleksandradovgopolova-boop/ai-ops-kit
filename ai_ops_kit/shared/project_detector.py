"""Алиас: shared.project_detector -> плоский модуль project_detector (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import project_detector as _target

sys.modules[__name__] = _target
