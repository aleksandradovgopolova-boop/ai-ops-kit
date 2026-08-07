"""Алиас: devtools.bench_lite -> плоский модуль bench_lite (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401
import bench_lite as _target

sys.modules[__name__] = _target
