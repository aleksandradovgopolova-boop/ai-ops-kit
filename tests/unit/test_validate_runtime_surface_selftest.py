"""Селфтест validate_runtime_surface, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_runtime_surface import (  # noqa: F401 — имена, которые использует тело
    PKG,
    Path,
    check_runtime_surface,
    check_skill_descriptions,
)


@pytest.mark.slow
def test_validate_runtime_surface_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "ok-skill").mkdir()
        (root / "ok-skill" / "SKILL.md").write_text(
            "---\nname: ok\ndescription: короткое описание в бюджете\n---\n# тело", encoding="utf-8")
        (root / "fat-skill").mkdir()
        (root / "fat-skill" / "SKILL.md").write_text(
            "---\nname: fat\ndescription: " + ("очень длинное " * 40) + "\n---\n# тело", encoding="utf-8")
        over = check_skill_descriptions(root)
        expect("раздутое описание детектируется", any(o["skill"] == "fat-skill" for o in over))
        expect("короткое описание проходит", not any(o["skill"] == "ok-skill" for o in over))

    expect("runtime_surface отсутствует -> валидно (экспорт всего)", check_runtime_surface({}) == [])
    expect("runtime_surface enabled='all' валиден",
           check_runtime_surface({"runtime_surface": {"skills": {"enabled": "all"}}}) == [])
    expect("runtime_surface enabled=[список] валиден",
           check_runtime_surface({"runtime_surface": {"commands": {"enabled": ["ai-run"]}}}) == [])
    expect("runtime_surface enabled=число -> ошибка",
           check_runtime_surface({"runtime_surface": {"skills": {"enabled": 5}}}) != [])

    # ключевой инвариант: РЕАЛЬНЫЕ поставляемые скиллы кита в бюджете
    real_over = check_skill_descriptions(PKG / "skills")
    expect("все поставляемые скиллы кита ≤300 символов",
           not real_over)
    if real_over:
        print("  превышают:", ", ".join(f"{o['skill']}({o['chars']})" for o in real_over))

    assert ok, "перенесённый селфтест validate_runtime_surface: см. строки FAIL в выводе"
