"""Алиас: security.data_classification -> плоский модуль data_classification (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import data_classification as _target

sys.modules[__name__] = _target
