"""Живая негативная проверка изоляции эталонного контейнера (#1407).

Собирает образ из коммита, поверх него — образ-пробу, и запускает его ШТАТНОЙ обёрткой
`containers/run-sandboxed.sh` с AI_OPS_NETWORK=none. Минуты и Docker, поэтому только по признаку
AI_OPS_IMAGE_SMOKE=1 (CI container-smoke); без Docker при этом признаке — провал, а не skip.
Логика пробы и путь через обёртку без Docker — tests/unit/test_container_isolation_probe.py.
"""
from __future__ import annotations

import os

import pytest

import validate_container_assets as vca

pytestmark = [pytest.mark.live, pytest.mark.slow]


@pytest.mark.skipif(os.environ.get("AI_OPS_IMAGE_SMOKE") != "1",
                    reason="реальная проверка изоляции — только по AI_OPS_IMAGE_SMOKE=1 (CI container-smoke)")
def test_reference_container_isolation_holds_from_inside():
    code, lines = vca.isolation_smoke()
    print("\n".join(lines))
    assert code == 0, "\n".join(lines)
    assert lines[0].startswith("CONTAINER-ISOLATION-OK")
