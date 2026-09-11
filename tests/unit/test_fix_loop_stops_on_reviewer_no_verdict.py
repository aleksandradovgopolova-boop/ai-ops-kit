"""Fix-loop не зацикливает писателя+ревьюера на «ревьюер не вынес вердикт» (issue #577).

НАХОДКА ПОЛЯ (живой заезд 07.09.2026, wow-repo). Гейт code_review не «висит в бесконечном while» —
все циклы ограничены. Дыра в ОДНОМ месте: `_review_fix_context` перезапускал писателя И ревьюера на
блоке no-verdict, хотя перезапуск писателя такой блок починить НЕ может. Ревью, закрытое
`closed_as="refused"` (независимый ревьюер не вынес разбираемого вердикта / провайдер судьи отказал),
несёт status fail/warn, и прежде шло писателю как обычный блокер → fix-loop (ai_ops_run_exec)
перезапускал пайплайн → снова _run_reviews → снова спавн `claude -p`. За (fix_attempts+1)×гейты×reads
медленных subprocess это часы, PR не открывается.

Здесь доказываем ДВЕ стороны фильтра по `closed_as` (по образцу env-скипа,
test_fix_loop_skips_env_blockers.py):
- refused как ЕДИНСТВЕННЫЙ блокер -> `_review_fix_context` возвращает None -> fix-loop делает break
  -> пайплайн НЕ перезапускается (ревьюер/писатель НЕ спавнится второй раз), прогон честно NOT_READY;
- содержательный fail (`closed_as` не refused) с реальными блокерами ВСЁ ЕЩЁ ретраит писателя —
  фильтр не убил полезный ретрай.

Это чинит СИМПТОМ-ПЕТЛЮ, а НЕ заставляет ревьюера родить вердикт (отдельная задача).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_ops_kit.engine import ai_ops_run
from ai_ops_kit.engine.ai_ops_run_reporting import _review_fix_context


# --- сторона 1: единица решения (_review_fix_context) ------------------------------------------

def _rep(reviews=None, checks=None, unmet=None, security=None):
    return {"ready_for_pr": False, "overall_status": "not-ready", "error": "",
            "checks": checks or {}, "reviews": reviews or [],
            "gates": {"unmet": unmet or []}, "security_scan": security or {}}


def _refused_review(gate="code_review"):
    # так пишет pipeline_evidence._run_reviews при no-verdict: status fail, но closed_as=refused.
    return {"gate": gate, "status": "fail", "closed_as": "refused",
            "reason": "независимый ревьюер не вынес вердикт", "blockers": None}


def _blocked_review(gate="code_review"):
    # содержательный отрицательный вердикт судьи: реальные блокеры, closed_as=blocked.
    return {"gate": gate, "status": "fail", "closed_as": "blocked",
            "blockers": ["не обработан edge-case пустого входа"]}


def test_refused_review_alone_does_not_retry_the_writer():
    # ревьюер молчит и это единственный блокер -> звать писателя бессмысленно -> None (цикл завершится).
    assert _review_fix_context(_rep(reviews=[_refused_review()])) is None


def test_substantive_fail_review_still_retries_the_writer():
    ctx = _review_fix_context(_rep(reviews=[_blocked_review()], unmet=["code_review"]))
    assert ctx is not None and "code_review" in ctx


def test_mixed_feeds_only_the_substantive_review_not_the_refused_one():
    ctx = _review_fix_context(_rep(reviews=[_refused_review("code_review"),
                                            _blocked_review("architecture_review")]))
    assert ctx is not None
    assert "architecture_review" in ctx          # содержательный fail — писателю
    assert "code_review" not in ctx              # refused (no-verdict) — пропущен


def test_advisory_review_is_not_treated_as_refused():
    # closed_as="advisory" (калибровка) несёт status warn — это НЕ refused, ретрай сохраняется как раньше.
    rev = {"gate": "code_review", "status": "warn", "closed_as": "advisory",
           "blockers": ["мелкое замечание стиля"]}
    ctx = _review_fix_context(_rep(reviews=[rev]))
    assert ctx is not None and "code_review" in ctx


# --- сторона 2: поведение всего fix-loop (счётчик перезапусков пайплайна) -----------------------

def _git_repo(root: Path):
    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        subprocess.run(["git", "-C", str(root), *a], capture_output=True)
    (root / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "i"], capture_output=True)


_REP_REFUSED = {
    "ready_for_pr": False, "kind": "execution-pipeline",
    "gates": {"unmet": ["code_review"]}, "checks": {},
    "reviews": [{"gate": "code_review", "status": "fail", "closed_as": "refused",
                 "reason": "независимый ревьюер не вынес вердикт", "blockers": None}],
}
_REP_BLOCKED = {
    "ready_for_pr": False, "kind": "execution-pipeline",
    "gates": {"unmet": ["code_review"]}, "checks": {},
    "reviews": [{"gate": "code_review", "status": "fail", "closed_as": "blocked",
                 "blockers": ["не обработан edge-case пустого входа"]}],
}
_REP_READY = {"ready_for_pr": True, "kind": "execution-pipeline", "gates": {"unmet": []},
              "loop": {"applied_writes": 1}}

# план БЕЗ escalation_ladder: fix-loop идёт по обычному ретраю писателя, не по quality-эскалации.
_PLAN_NO_LADDER = {
    "kind": "RunModelPlan",
    "implementation": {"kind": "ModelResolutionResult", "resolved": True, "role": "implementation",
                       "model_id": "deepseek-chat", "provider": "deepseek", "cost_basis": "money-mode",
                       "fallback": {}, "escalation_ladder": []},
    "code_review": {"resolved": False, "role": "code_review"},
    "security_review": {"resolved": False, "role": "security_review"},
    "preferred_writer_tier": {"tier": "cheap-api", "reason": "простой класс"},
}


def _run_fix_loop(root, rep_sequence):
    """Прогнать реальный fix-loop ai_ops_run.run с мокнутым run_pipeline-счётчиком.
    Возвращает (rep, calls) — сколько раз пайплайн (а значит и ревьюер внутри) был запущен."""
    ep = {"key_env": "X_KEY", "base_url": "http://x/api"}
    trust = {"ready": True, "preflight": {"ready": True, "blocks": []}}
    seq = iter(rep_sequence)
    calls = {"n": 0}

    def _count(*a, **k):
        calls["n"] += 1
        return dict(next(seq))

    with patch("ai_ops_kit.providers.model_router.plan_run", return_value=_PLAN_NO_LADDER), \
         patch("ai_ops_kit.providers.provider_endpoints.key_available", return_value=True), \
         patch("ai_ops_kit.providers.provider_endpoints.endpoint_for", return_value=ep), \
         patch("ai_ops_kit.engine.ai_ops_run._load_klp_by_env", return_value={}), \
         patch("ai_ops_kit.engine.ai_ops_run._provider_trust", return_value=trust), \
         patch("ai_ops_kit.providers.orchestrator.make_openai_provider",
               side_effect=lambda *a, **k: (lambda prompt: {"done": True})), \
         patch("ai_ops_kit.engine.execution_pipeline.run_pipeline", side_effect=_count):
        rep = ai_ops_run.run(
            task_text="добавить a",
            signals={"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]},
            child_root=root, engine="pipeline", provider_name="openai-compatible", model=None,
            proposer=lambda c: {"done": True}, feature="nv577", review_fix_attempts=2)
    return rep, calls["n"]


@pytest.mark.unit
def test_fix_loop_does_not_respawn_pipeline_on_reviewer_no_verdict(tmp_path):
    """refused-ревью -> fix-loop НЕ перезапускает пайплайн: ревьюер спавнится РОВНО один раз, NOT_READY."""
    root = tmp_path / "refused"
    root.mkdir()
    _git_repo(root)
    # даём длинную последовательность ready-отчётов ПОСЛЕ первого: если бы петля перезапустилась,
    # она бы дошла до ready и «починилась». Мы доказываем, что она НЕ перезапускается вовсе.
    rep, calls = _run_fix_loop(root, [_REP_REFUSED, _REP_READY, _REP_READY])
    assert calls == 1, f"пайплайн (и ревьюер внутри) перезапущен {calls} раз — петля на no-verdict жива"
    assert rep.get("ready_for_pr") is not True, "прогон обязан честно завершиться NOT_READY, а не починиться"


@pytest.mark.unit
def test_fix_loop_still_retries_pipeline_on_substantive_blocker(tmp_path):
    """КОНТРОЛЬ: содержательный fail (closed_as!=refused) ВСЁ ЕЩЁ перезапускает пайплайн (ретрай жив)."""
    root = tmp_path / "blocked"
    root.mkdir()
    _git_repo(root)
    rep, calls = _run_fix_loop(root, [_REP_BLOCKED, _REP_READY])
    assert calls == 2, f"реальный блокер должен вызвать ретрай писателя (ожидали 2 запуска, было {calls})"
    assert rep.get("ready_for_pr") is True, "после ретрая на реальном блокере прогон дошёл до ready"
