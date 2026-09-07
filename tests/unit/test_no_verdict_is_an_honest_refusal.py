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
    # проза без JSON -> parse_action не разбирает -> петля исчерпывается в no-verdict.
    # issue #591: счётчик вызовов делает МЕДЛИТЕЛЬНОСТЬ видимой тесту — ревьюер, не выносящий
    # вердикта, НЕ мелется max_reads+2 витков (в поле это были ~84 мин): K=2 -> ≤ K+2 на гейт.
    calls = {"n": 0}

    def stalling_reviewer(_p):
        calls["n"] += 1
        return "Я пока не могу вынести вердикт по этому диффу."

    report = _run(child_root, stalling_reviewer, "nv1")

    entry = _ux(report)
    assert entry is not None, "гейт ux_review исчез из reviews — тот самый молчаливый ступор"
    assert entry.get("closed_as") == "refused"
    assert entry.get("status") == "fail"
    reason = entry.get("reason") or ""
    assert "не вынес вердикт" in reason, reason
    assert "нет заключения reviewer" not in reason, "общая формулировка врала о причине"
    assert "ux_review" in report["gates"]["unmet"], "работа не должна тихо пройти без вердикта"
    # issue #591: медлительность видна тесту. Живой прогон гонит НЕСКОЛЬКО ai-review гейтов (ux,
    # design_system, accessibility, visual_regression), каждый — свой run_review. Фикс держит КАЖДЫЙ
    # гейт в ≤ K+2 витков (K=2): всего ≤ N_гейтов·(K+2), а не N·(max_reads+2)=N·8 старой молотилки.
    n_gates = len(report.get("reviews") or [])
    assert n_gates >= 1
    assert calls["n"] <= n_gates * 4, (
        f"ревьюер смолот {calls['n']} раз на {n_gates} гейт(ов) (~{calls['n'] // max(n_gates, 1)}/гейт) "
        f"— молотилка (N·(max_reads+2)={n_gates * 8}) вернулась")


@pytest.mark.unit
def test_provider_refusal_names_the_empty_answer(child_root):
    """Провайдер судьи вернул ПУСТО на блокирующем гейте -> причина названа человеческими словами
    («пустой»), не «нет заключения». #570-follow-up (07.09): пустой/структурно-немой ответ ведёт в
    awaiting_reviewer (handoff оркестратору), а не в глухой no-verdict — но гейт по-прежнему НЕ
    закрыт (0 false-green), и причина названа честно."""
    from ai_ops_kit.providers.response_contract import ProviderRefusal
    _init_git(child_root)

    def refuses(_p):
        raise ProviderRefusal("empty_answer", "claude -p вернул пустой result",
                              "claude-cli", "claude-code-local")

    report = _run(child_root, refuses, "nv2")
    entry = _ux(report)
    assert entry is not None and entry.get("closed_as") == "awaiting_reviewer"
    assert "пустой" in (entry.get("reason") or ""), entry
    assert "ux_review" in report["gates"]["unmet"]


ENG_SIGNALS = {"task_type": "ENGINEERING", "size": "small", "risk": "low", "affected_areas": ["core"]}


def _run_eng(child_root, reviewer, feature):
    """Живой прогон ENGINEERING-задачи (гейт code_review блокирующий) с подменённым ревьюером."""
    ops = iter([{"op": "write", "path": f"src/{feature}.py", "content": "def g():\n    return 1\n"},
                 {"done": True}])
    return execution_pipeline.run_pipeline(
        task="engineering task", signals=ENG_SIGNALS, child_root=child_root,
        proposer=lambda ctx: next(ops), budget={"max_model_calls": 30}, feature=feature,
        commit=True, isolate=True, install_deps=False, review=True, reviewer_proposer=reviewer)


def _cr(report):
    return next((r for r in (report.get("reviews") or []) if r["gate"] == "code_review"), None)


@pytest.mark.unit
def test_empty_answer_on_blocking_gate_opens_awaiting_and_writes_request(child_root):
    """#570-follow-up (07.09): ПУСТОЙ ответ провайдера (структурно немой) на БЛОКИРУЮЩЕМ code_review
    -> awaiting_reviewer + записан машиночитаемый запрос на ревью (не generic no-verdict, не
    hard-error). Гейт остаётся НЕ закрытым (0 false-green), причина названа честно («пустой»)."""
    from ai_ops_kit.providers.response_contract import ProviderRefusal
    from ai_ops_kit.engine import reviewer_handoff
    _init_git(child_root)

    def refuses(_p):
        raise ProviderRefusal("empty_answer", "claude -p вернул пустой result (rc=0)",
                              "claude-cli", "claude-code-local")

    report = _run_eng(child_root, refuses, "cr_empty")
    e = _cr(report)
    assert e is not None and e.get("closed_as") == "awaiting_reviewer", report.get("reviews")
    assert "пустой" in (e.get("reason") or ""), e
    assert "code_review" in report["gates"]["unmet"]           # блокирующий гейт не закрыт
    # запрос на ревью РЕАЛЬНО записан (оркестратор знает, что заполнить) — под child_root/.ai
    assert reviewer_handoff.request_path(child_root, "code_review").is_file()


@pytest.mark.unit
def test_env_unavailable_on_blocking_gate_opens_awaiting_via_flow(child_root):
    """Тот же handoff и для структурной недоступности среды (вложенный claude -p оборвался ДО модели)
    на живом пути run_pipeline — awaiting_reviewer, запрос записан, гейт не закрыт."""
    from ai_ops_kit.providers.orchestrator_providers import ProviderEnvUnavailableError
    from ai_ops_kit.engine import reviewer_handoff
    _init_git(child_root)

    def env_down(_p):
        raise ProviderEnvUnavailableError("claude-cli", "duration_api_ms:0")

    report = _run_eng(child_root, env_down, "cr_env")
    e = _cr(report)
    assert e is not None and e.get("closed_as") == "awaiting_reviewer", report.get("reviews")
    assert "code_review" in report["gates"]["unmet"]
    assert reviewer_handoff.request_path(child_root, "code_review").is_file()


@pytest.mark.unit
def test_analysis_without_verdict_stays_named_refusal_not_awaiting(child_root):
    """Граница: ревьюер ДАЛ разбор, но БЕЗ вердикта (проза, не пустой/структурно-немой ответ) ->
    остаётся НАЗВАННЫМ no-verdict (refused), НЕ awaiting. Не всякий no-verdict — handoff."""
    _init_git(child_root)
    report = _run_eng(child_root, lambda _p: "Пока не могу заключить по этому диффу.", "cr_prose")
    e = _cr(report)
    assert e is not None and e.get("closed_as") == "refused", report.get("reviews")
    assert "code_review" in report["gates"]["unmet"]


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
