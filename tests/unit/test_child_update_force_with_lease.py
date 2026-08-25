"""Lane A3: шаблон child-update использует --force-with-lease и минимальные permissions.

Автообновление дочки пушит ветку обновления. Прежний `git push -f` перетирал чужие коммиты
на ветке, если кто-то успел запушить свою работу между fetch и push. `--force-with-lease`
безопаснее: отказывается пушить, если удалённая ветка ушла вперёд.

Тест проверяет:
1. Шаблон содержит `git push --force-with-lease` (не `-f`).
2. Permissions задекларированы явно (не дефолтный read/write на всё).
"""
from __future__ import annotations

from pathlib import Path

import yaml

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "templates" / "ci" / "ai-ops-update.yml"


def test_force_with_lease_used() -> None:
    """Шаблон использует --force-with-lease, а не -f."""
    content = TEMPLATE_PATH.read_text()

    # Должен быть --force-with-lease
    assert "--force-with-lease" in content, "шаблон не содержит --force-with-lease"

    # Не должно быть git push -f (но может быть git push --force, если кто-то напишет полностью)
    # Проверяем именно опасную короткую форму
    lines = content.split("\n")
    for line in lines:
        if "git push" in line and "-f" in line and "--force-with-lease" not in line:
            # Может быть -f в других контекстах, проверяем именно git push -f
            if "git push -f" in line or "git push  -f" in line:
                raise AssertionError(f"найден опасный git push -f: {line}")


def test_permissions_declared() -> None:
    """Permissions задекларированы явно на верхнем уровне."""
    doc = yaml.safe_load(TEMPLATE_PATH.read_text())
    perms = doc.get("permissions")
    assert perms is not None, "permissions не задекларированы на верхнем уровне"
    assert isinstance(perms, dict), "permissions должны быть словарём"

    # Проверяем, что contents и pull-requests явно указаны
    assert "contents" in perms, "contents не указан в permissions"
    assert "pull-requests" in perms, "pull-requests не указан в permissions"
