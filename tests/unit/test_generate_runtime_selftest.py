"""Селфтест generate_runtime, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from generate_runtime import (  # noqa: F401 — имена, которые использует тело
    Path,
    RUNTIMES,
    check_drift,
    generate,
    tempfile,
)


@pytest.mark.slow
def test_generate_runtime_selftest():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        files = generate(root, verbose=False)
        ok = True
        expect = {"quick", "engineering", "product", "research"}
        got = {p.stem.replace("ai-", "") for p in files}
        if not expect.issubset(got):
            ok = False; print(f"FAIL нет команд для: {expect - got}")
        else:
            print(f"PASS команды сгенерированы: {sorted(got)} x {len(RUNTIMES)} runtime")
        sample = next(p for p in files if p.stem == "ai-engineering" and "claude-code" in str(p))
        text = sample.read_text(encoding="utf-8")
        for token in ("requirements-writer", "plan-reviewer", "read-only", "implementation_verification"):
            if token not in text:
                ok = False; print(f"FAIL в ai-engineering нет '{token}'")
        else:
            print("PASS содержимое включает стадии/судей/gates")
        # канонический вход ai-run (3.0-срез 1) сгенерирован для каждого runtime
        rn_files = [p for p in files if p.stem == "ai-run"]
        if len(rn_files) == len(RUNTIMES):
            print(f"PASS ai-run (канонический вход) сгенерирован для {len(RUNTIMES)} runtime")
        else:
            ok = False; print(f"FAIL ai-run не для всех runtime ({len(rn_files)}/{len(RUNTIMES)})")
        rn_text = next((p.read_text(encoding="utf-8") for p in rn_files if "claude-code" in str(p)), "")
        for token in ("ai_ops_run.py", "канонический вход", "run-report.json", "совместимый алиас"):
            if token not in rn_text:
                ok = False; print(f"FAIL в ai-run нет '{token}'")
        else:
            print("PASS ai-run — канонический контроллер (задача->исполнение->отчёт) + алиас-нота")
        # ai-start-task сохранён как совместимый алиас для каждого runtime
        st_files = [p for p in files if p.stem == "ai-start-task"]
        if len(st_files) == len(RUNTIMES):
            print(f"PASS ai-start-task сгенерирован для {len(RUNTIMES)} runtime")
        else:
            ok = False; print(f"FAIL ai-start-task не для всех runtime ({len(st_files)}/{len(RUNTIMES)})")
        st_text = next((p.read_text(encoding="utf-8") for p in st_files if "claude-code" in str(p)), "")
        for token in ("routing-policy.yaml", "CRITICAL", "human approval", "workflow"):
            if token not in st_text:
                ok = False; print(f"FAIL в ai-start-task нет '{token}'")
        else:
            print("PASS ai-start-task включает классификацию/маршрутизацию/эскалацию")
        # Ф0: генерируемая команда не должна расходиться с canonical — полный orchestration-поток
        for token in ("concurrency_preflight.py", "worktree.py", "workitem.py", "active_work.py",
                      "workitems/", ".ai/managed/commands/task/ai-start-task.md"):
            if token not in st_text:
                ok = False; print(f"FAIL ai-start-task разошёлся с canonical: нет '{token}'")
        else:
            print("PASS ai-start-task содержит полный поток (WorkItem/worktree/active-work/preflight)")
        # разговорная установка ai-ops-init сгенерирована для каждого runtime
        it_files = [p for p in files if p.stem == "ai-ops-init"]
        if len(it_files) == len(RUNTIMES):
            print(f"PASS ai-ops-init сгенерирован для {len(RUNTIMES)} runtime")
        else:
            ok = False; print(f"FAIL ai-ops-init не для всех runtime ({len(it_files)}/{len(RUNTIMES)})")
        it_text = next((p.read_text(encoding="utf-8") for p in it_files if "claude-code" in str(p)), "")
        for token in ("installer/ai_ops.py", "repo-onboarding", "doctor"):
            if token not in it_text:
                ok = False; print(f"FAIL в ai-ops-init нет '{token}'")
        else:
            print("PASS ai-ops-init включает установку/онбординг/doctor")
        if check_drift(root):
            ok = False; print("FAIL свежая генерация помечена как drift")
        else:
            print("PASS drift-детект: свежая генерация актуальна")

    # v3.14.0 срез 3: адаптеры только для настроенных рантаймов + фильтр поверхности команд
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        only_claude = generate(root, verbose=False, runtimes=["claude-code"])
        has_codex = any("codex" in str(p) for p in only_claude)
        if not has_codex and all("claude-code" in str(p) for p in only_claude):
            print("PASS runtimes=[claude-code] -> НЕ генерируются файлы codex-адаптера")
        else:
            ok = False; print("FAIL при одном рантайме всё равно созданы чужие адаптеры")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        filtered = generate(root, verbose=False, runtimes=["claude-code"],
                            command_filter={"ai-run", "ai-quick"})
        names = {p.stem for p in filtered}
        if names == {"ai-run", "ai-quick"}:
            print("PASS command_filter экспортирует только выбранные команды")
        else:
            ok = False; print(f"FAIL command_filter: ожидалось {{ai-run,ai-quick}}, получено {sorted(names)}")

    assert ok, "перенесённый селфтест generate_runtime: см. строки FAIL в выводе"
