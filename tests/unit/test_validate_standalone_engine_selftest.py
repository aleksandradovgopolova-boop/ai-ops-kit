"""Селфтест validate_standalone_engine, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_standalone_engine import (  # noqa: F401 — имена, которые использует тело
    PKG,
    Path,
    build_managed,
    missing_closure,
    run_standalone,
    subprocess,
    tempfile,
)


@pytest.mark.slow
def test_validate_standalone_engine_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        managed = root / ".ai" / "managed"
        n = build_managed(PKG, managed)
        expect(f"managed-слой построен из managed_set ({n} файлов)", n > 0)

        miss = missing_closure(managed)
        expect(f"рантайм-замыкание движка целиком в managed (нет пропусков: {miss or 'ok'})", not miss)
        expect("движок присутствует (.ai/managed/tools/ai_ops_run.py)",
               (managed / "tools" / "ai_ops_run.py").exists())

        # временный child-репозиторий
        child = root / "childrepo"
        child.mkdir()
        subprocess.run(["git", "-C", str(child), "init", "-q"])
        subprocess.run(["git", "-C", str(child), "config", "user.email", "t@t"])
        subprocess.run(["git", "-C", str(child), "config", "user.name", "t"])
        (child / "src").mkdir()
        (child / "pyproject.toml").write_text("[tool.poetry]\n", encoding="utf-8")
        (child / "f").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", str(child), "add", "-A"])
        subprocess.run(["git", "-C", str(child), "commit", "-q", "-m", "init"])

        rep = run_standalone(managed, child)
        expect("движок отработал из managed БЕЗ parent-клона (валидный отчёт)",
               rep is not None and rep.get("kind") == "execution-pipeline")
        if rep:
            commit = rep.get("commit") or {}
            expect("standalone: реальный коммит на ветке ai-ops/* (SHA 40 hex)",
                   isinstance(commit.get("sha"), str) and len(commit.get("sha") or "") == 40
                   and (commit.get("branch") or "").startswith("ai-ops/"))
            expect("standalone: evidence на ТОЧНОМ зафиксированном SHA",
                   commit.get("evidence_on_exact_sha") is True)
            expect("standalone: ready_for_pr=True (движок довёл прогон до готовности)",
                   rep.get("ready_for_pr") is True)
            expect("standalone: containment активен (sandbox + block_push)",
                   (rep.get("containment") or {}).get("block_push") is True
                   and (rep.get("containment") or {}).get("sandbox") is True)
            expect("standalone: файл действительно записан движком в child",
                   (child / ".ai" / "worktrees" / "standalone-add" / "src" / "add.py").exists())

        # негатив: убрать файл замыкания -> completeness ловит
        (managed / "tools" / "tool_broker.py").unlink()
        expect("completeness ловит пропажу файла движка (tool_broker удалён)",
               "tools/tool_broker.py" in missing_closure(managed))

    assert ok, "перенесённый селфтест validate_standalone_engine: см. строки FAIL в выводе"
