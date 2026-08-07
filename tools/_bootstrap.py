#!/usr/bin/env python3
"""_bootstrap.py — shared sys.path setup for tools/ and validation/ modules."""
from __future__ import annotations
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
for _p in (str(PKG / "tools"), str(PKG / "validation")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
