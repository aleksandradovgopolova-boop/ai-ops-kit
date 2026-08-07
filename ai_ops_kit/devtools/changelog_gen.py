"""Алиас: devtools.changelog_gen -> плоский модуль changelog_gen (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401
import changelog_gen as _target

sys.modules[__name__] = _target
