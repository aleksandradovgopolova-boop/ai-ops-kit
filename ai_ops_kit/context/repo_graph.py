"""Алиас: context.repo_graph -> плоский модуль repo_graph (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import repo_graph as _target

sys.modules[__name__] = _target
