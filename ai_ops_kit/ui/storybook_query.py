"""Алиас: ui.storybook_query -> плоский модуль storybook_query (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import storybook_query as _target

sys.modules[__name__] = _target
