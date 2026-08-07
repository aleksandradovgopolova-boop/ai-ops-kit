"""Алиас: devtools.retrieval_bench -> плоский модуль retrieval_bench (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401
import retrieval_bench as _target

sys.modules[__name__] = _target
