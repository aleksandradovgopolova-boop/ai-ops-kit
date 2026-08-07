"""Алиас: engops.commit_policy -> плоский модуль commit_policy (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import commit_policy as _target

sys.modules[__name__] = _target
