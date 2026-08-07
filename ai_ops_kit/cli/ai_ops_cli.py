"""Алиас: cli.ai_ops_cli -> плоский модуль ai_ops_cli (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import ai_ops_cli as _target

sys.modules[__name__] = _target
