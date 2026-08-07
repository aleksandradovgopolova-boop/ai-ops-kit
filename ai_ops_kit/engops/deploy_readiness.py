"""Алиас: engops.deploy_readiness -> плоский модуль deploy_readiness (один объект, не копия)."""
import sys

import _bootstrap  # noqa: F401 — кладёт tools/validation в sys.path
import deploy_readiness as _target

sys.modules[__name__] = _target
