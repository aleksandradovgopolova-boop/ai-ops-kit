"""Реальный no-model smoke эталонного образа на коммите HEAD (#1478).

Собирает containers/Dockerfile настоящим Docker'ом — это минуты и сеть, поэтому тест запускается
ТОЛЬКО по признаку AI_OPS_IMAGE_SMOKE=1, который ставит тот, кто зовёт (CI-workflow
container-smoke). Без признака — skip: обычные группы образов не собирают. С признаком отсутствие
Docker (BLOCKED, код 2) — провал, а не skip: вызвавший проверку обязан получить результат.
Путь кода и fail-closed ветки покрыты без Docker в tests/unit/test_container_image_smoke.py.
"""
from __future__ import annotations

import os

import pytest

import validate_container_assets as vca

pytestmark = [pytest.mark.live, pytest.mark.slow]


@pytest.mark.skipif(os.environ.get("AI_OPS_IMAGE_SMOKE") != "1",
                    reason="реальная сборка образа — только по AI_OPS_IMAGE_SMOKE=1 (CI container-smoke)")
def test_reference_image_builds_and_starts_cli_on_head():
    code, lines = vca.image_smoke()
    print("\n".join(lines))
    assert code == 0, "\n".join(lines)
    assert lines[0].startswith("CONTAINER-IMAGE-SMOKE-OK")
