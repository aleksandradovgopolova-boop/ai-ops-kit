"""Гранулярные тесты generate_runtime (мигрировано из test_generate_runtime_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from generate_runtime import (
    Path,
    RUNTIMES,
    check_drift,
    generate,
)


@pytest.fixture
def generated_files(tmp_path):
    return generate(tmp_path, verbose=False)


@pytest.mark.unit
class TestGenerate:
    def test_all_commands_generated(self, generated_files):
        expect = {"quick", "engineering", "product", "research"}
        got = {p.stem.replace("ai-", "") for p in generated_files}
        assert expect.issubset(got)

    def test_engineering_content(self, generated_files):
        sample = next(p for p in generated_files if p.stem == "ai-engineering" and "claude-code" in str(p))
        text = sample.read_text(encoding="utf-8")
        for token in ("requirements-writer", "plan-reviewer", "read-only", "implementation_verification"):
            assert token in text, f"в ai-engineering нет '{token}'"

    def test_ai_run_for_each_runtime(self, generated_files):
        rn_files = [p for p in generated_files if p.stem == "ai-run"]
        assert len(rn_files) == len(RUNTIMES)

    def test_ai_run_content(self, generated_files):
        rn_files = [p for p in generated_files if p.stem == "ai-run"]
        rn_text = next((p.read_text(encoding="utf-8") for p in rn_files if "claude-code" in str(p)), "")
        for token in ("ai_ops_run.py", "канонический вход", "run-report.json", "совместимый алиас"):
            assert token in rn_text, f"в ai-run нет '{token}'"

    def test_ai_start_task_for_each_runtime(self, generated_files):
        st_files = [p for p in generated_files if p.stem == "ai-start-task"]
        assert len(st_files) == len(RUNTIMES)

    def test_ai_start_task_content(self, generated_files):
        st_files = [p for p in generated_files if p.stem == "ai-start-task"]
        st_text = next((p.read_text(encoding="utf-8") for p in st_files if "claude-code" in str(p)), "")
        for token in ("routing-policy.yaml", "CRITICAL", "human approval", "workflow"):
            assert token in st_text, f"в ai-start-task нет '{token}'"

    def test_ai_start_task_full_flow(self, generated_files):
        st_files = [p for p in generated_files if p.stem == "ai-start-task"]
        st_text = next((p.read_text(encoding="utf-8") for p in st_files if "claude-code" in str(p)), "")
        for token in ("concurrency_preflight.py", "worktree.py", "workitem.py", "active_work.py",
                      "workitems/", ".ai/managed/commands/task/ai-start-task.md"):
            assert token in st_text, f"ai-start-task разошёлся с canonical: нет '{token}'"

    def test_ai_ops_init_for_each_runtime(self, generated_files):
        it_files = [p for p in generated_files if p.stem == "ai-ops-init"]
        assert len(it_files) == len(RUNTIMES)

    def test_ai_ops_init_content(self, generated_files):
        it_files = [p for p in generated_files if p.stem == "ai-ops-init"]
        it_text = next((p.read_text(encoding="utf-8") for p in it_files if "claude-code" in str(p)), "")
        for token in ("installer/ai_ops.py", "repo-onboarding", "doctor"):
            assert token in it_text, f"в ai-ops-init нет '{token}'"

    def test_no_drift_on_fresh(self, tmp_path):
        generate(tmp_path, verbose=False)
        assert not check_drift(tmp_path)


@pytest.mark.unit
class TestRuntimeFilter:
    def test_single_runtime_no_foreign_adapters(self, tmp_path):
        only_claude = generate(tmp_path, verbose=False, runtimes=["claude-code"])
        has_codex = any("codex" in str(p) for p in only_claude)
        assert not has_codex
        assert all("claude-code" in str(p) for p in only_claude)

    def test_command_filter(self, tmp_path):
        filtered = generate(tmp_path, verbose=False, runtimes=["claude-code"],
                            command_filter={"ai-run", "ai-quick"})
        names = {p.stem for p in filtered}
        assert names == {"ai-run", "ai-quick"}
