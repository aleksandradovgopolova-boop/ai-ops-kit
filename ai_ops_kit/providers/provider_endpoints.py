"""Алиас: providers.provider_endpoints -> плоский модуль provider_endpoints (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import provider_endpoints as _target

sys.modules[__name__] = _target
