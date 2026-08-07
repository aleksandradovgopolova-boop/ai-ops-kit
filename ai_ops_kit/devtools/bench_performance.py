"""Алиас: devtools.bench_performance -> плоский модуль bench_performance (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401
import bench_performance as _target

sys.modules[__name__] = _target
