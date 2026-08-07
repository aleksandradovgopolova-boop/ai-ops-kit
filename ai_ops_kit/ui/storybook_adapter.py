"""Алиас: ui.storybook_adapter -> плоский модуль storybook_adapter (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import storybook_adapter as _target

sys.modules[__name__] = _target
