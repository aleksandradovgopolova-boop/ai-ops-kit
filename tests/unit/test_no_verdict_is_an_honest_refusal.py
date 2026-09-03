"""Отсутствие вердикта судьи — честный отказ, который можно разобрать, а не молчаливый ступор.

НАХОДКА ПОЛЯ P0 (obs-2026-08-20, прогон в ai-ops-cockpit). Гейт code_review ОБА прогона кончился
`stopped=no-verdict, valid=false`: ревьюер не вынес разбираемого вердикта, а «живой» путь пайплайна
(`_run_reviews`) ТИХО ронял гейт голым `continue` — gate_ev не получал ключа, гейт падал на общий
`_unmet_reason` «нет заключения reviewer» (не называя ПОЧЕМУ), `_hard_stop` не распознавал
reviewer-blocked, и работа МОЛЧА вставала. Механизм, ради которого гейт существует, не срабатывал.

Здесь — сквозная проба того самого пути (`run_pipeline(review=True)` с ревьюером, который не выносит
вердикт). Ожидание: гейт НЕ исчезает молча — он остаётся неудовлетворённым с НАЗВАННОЙ причиной,
которую человек может разобрать. Это путь B (боевой), не штатный staged-путь (тот проверен в
test_judge_refusal_reaches_the_gate.py).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from ai_ops_kit.engine import execution_pipeline # noqa: E402

UI_SIGNALS = {"task_type": "QUICK", "size": "small", "risk": "low",
              "affected_areas": ["core"], "ui_changed": True}


def _init_git(root):
    subprocess.run(["git", "init"], cwd=root, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, capture_output=True)
    (root / "dummy.txt").write_text("init")
    subprocess.run(["git", "add", "."], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True)


def _run(child_root, reviewer, feature):
    ops = iter([{"op": "write", "path": f"src/{feature}.py", "content": "v = 1\n"}, {"done": True}])
    return execution_pipeline.run_pipeline(
        task="no-verdict field case", signals=UI_SIGNALS, child_root=child_root,
        proposer=lambda ctx: next(ops), budget={"max_model_calls": 30}, feature=feature,
        commit=True, isolate=True, install_deps=False, review=True, reviewer_proposer=reviewer)


def _ux(report):
    return next((r for r in (report.get("reviews") or []) if r["gate"] == "ux_review"), None)


@pytest.mark.unit
def test_no_verdict_becomes_named_refusal_not_a_silent_stall(child_root):
    """Ревьюер, не вынесший разбираемого вердикта, -> гейт НЕ исчезает: назван отказ, гейт неудовлетворён."""
    _init_git(child_root)
    # проза без JSON -> parse_action не разбирает -> петля исчерпывается в no-verdict
    report = _run(child_root, lambda _p: "Я пока не могу вынести вердикт по этому диффу.", "nv1")

    entry = _ux(report)
    assert entry is not None, "гейт ux_review исчез из reviews — тот самый молчаливый ступор"
    assert entry.get("closed_as") == "refused"
    assert entry.get("status") == "fail"
    reason = entry.get("reason") or ""
    assert "не вынес вердикт" in reason, reason
    assert "нет заключения reviewer" not in reason, "общая формулировка врала о причине"
    assert "ux_review" in report["gates"]["unmet"], "работа не должна тихо пройти без вердикта"


@pytest.mark.unit
def test_provider_refusal_names_the_empty_answer(child_root):
    """Провайдер судьи отказал (пустой ответ) -> причина названа человеческими словами, не «нет заключения»."""
    from ai_ops_kit.providers.response_contract import ProviderRefusal
    _init_git(child_root)

    def refuses(_p):
        raise ProviderRefusal("empty_answer", "claude -p вернул пустой result",
                              "claude-cli", "claude-code-local")

    report = _run(child_root, refuses, "nv2")
    entry = _ux(report)
    assert entry is not None and entry.get("closed_as") == "refused"
    assert "пустой" in (entry.get("reason") or ""), entry
    assert "ux_review" in report["gates"]["unmet"]


@pytest.mark.unit
def test_a_normal_verdict_still_closes_the_gate(child_root):
    """Обратная сторона: путь не сломан — валидный вердикт по-прежнему закрывает гейт."""
    _init_git(child_root)

    def pass_reviewer(prompt):
        if "--- src/nv3.py ---" in prompt:
            return '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
        if "src/nv3.py" in prompt:
            return '{"op":"read","path":"src/nv3.py"}'
        return '{"op":"read","path":"src/nv3.py"}'

    report = _run(child_root, pass_reviewer, "nv3")
    entry = _ux(report)
    assert entry is not None and entry["status"] == "pass"
    assert "ux_review" not in report["gates"]["unmet"]
