"""Селфтест architecture_baseline, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from architecture_baseline import (  # noqa: F401 — имена, которые использует тело
    AXES,
    Path,
    analyze,
    check,
)


@pytest.mark.slow
def test_architecture_baseline_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        b = analyze(td, sha="deadbeef")
        expect("все 12 осей присутствуют", all(ax in b for ax in AXES))
        expect("check валиден на пустом дереве", check(b) == [])
        expect("пустой репо -> module_map not_detected",
               b["module_map"]["top_level_code_dirs"] == "not_detected")
        expect("пустой репо -> риск про отсутствие ADR",
               any("ADR" in r for r in b["risks"]))
        expect("sha помечен (read-only на SHA)", b["sha"] == "deadbeef")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src" / "features").mkdir(parents=True)
        (root / "src" / "shared").mkdir(parents=True)
        (root / "src" / "features" / "api.ts").write_text(
            "import { z } from 'zod';\nconst r = router.get('/x', () => {});\n", encoding="utf-8")
        (root / "package.json").write_text(
            '{"dependencies":{"anthropic":"^1","zod":"^3"},"devDependencies":{"vitest":"^1"}}',
            encoding="utf-8")
        (root / "migrations").mkdir()
        (root / "Dockerfile").write_text("FROM node", encoding="utf-8")
        b = analyze(td, sha="abc123")
        expect("FSD boundary детектится", "FSD (feature-sliced)" in b["boundaries"]["detected"])
        expect("node deps посчитаны", b["dependencies"]["node"]["dependencies"] == 2)
        expect("express route детектится", "express route" in b["api_surface"])
        expect("миграции детектятся", "migrations" in b["data_and_migrations"]["migration_dirs"])
        expect("anthropic SDK-интеграция детектится", "anthropic" in b["integrations"]["sdk_providers"])
        expect("Dockerfile -> deployment", "Dockerfile" in b["deployment"]["deploy_configs"])
        expect("zod -> input_validation_present", b["security_boundaries"]["input_validation_present"])
        expect("check валиден на реальном дереве", check(b) == [])

    # честность: не выдумывает секреты — только имена env-переменных
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".env.example").write_text("ANTHROPIC_API_KEY=sk-REAL-SECRET-VALUE\nDB_URL=x\n", encoding="utf-8")
        b = analyze(td)
        names = b["integrations"].get("env_var_names", [])
        expect("env: только имена, значение секрета не утекает",
               "ANTHROPIC_API_KEY" in names and not any("sk-REAL" in str(x) for x in names))

    assert ok, "перенесённый селфтест architecture_baseline: см. строки FAIL в выводе"
