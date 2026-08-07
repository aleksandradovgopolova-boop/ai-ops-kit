"""Алиас: context.context_retrieval -> плоский модуль context_retrieval (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import context_retrieval as _target

sys.modules[__name__] = _target
