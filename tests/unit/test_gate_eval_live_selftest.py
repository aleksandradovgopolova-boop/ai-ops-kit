"""Живой прогонщик gate-евалов — проверки БЕЗ модели (C1, v3.37).

Провайдер здесь инъектируется callable'ом, но заменяет он ровно вызов модели, а не весь путь:
промпт судьи строится боевым `orchestrator.build_role_prompt`, вердикт выводится боевой цепочкой,
запись в кейс идёт тем же кодом, что и в живом прогоне. Иначе проверялась бы заглушка.
"""
from __future__ import annotations

import yaml

from ai_ops_kit.devtools import gate_evals
from ai_ops_kit.gates.gate_executor import load_gates
from ai_ops_kit.devtools import gate_eval_live

GATES = load_gates()

_FAIL = ('## Review\nфиктивный selftest\n'
         '{"schema_version":1,"kind":"reviewer-result","gate":"code_review","status":"fail",'
         '"checks":[],"blockers":["ветка --selftest ничего не вызывает"]}')
_PASS = ('## Review\nчисто\n'
         '{"schema_version":1,"kind":"reviewer-result","gate":"code_review","status":"pass",'
         '"checks":[{"id":"selftest_honest","status":"pass"}],"blockers":[]}')


def _case():
    return {
        "schema_version": 1, "kind": "gate-evaluation-case", "id": "probe-live",
        "gate": "code_review", "case_kind": "judge_output", "summary": "проба",
        "origin": {"source": "проба", "provenance": "class_repro"},
        "signals": {},
        "expected": {"status": "fail", "reason_matches": ["selftest"]},
        "input": {"task": "ревью изменения", "diff_file": "probe-live.patch",
                  "diff": "diff --git a/x b/x\n+x\n"},
        "recorded": [],
    }


def test_judge_prompt_is_the_production_prompt():
    """Свой промпт мерил бы своего судью: guard про read-only и требование структурного
    reviewer-result — часть того, чем обеспечено «зелёное»."""
    p = gate_eval_live.judge_prompt(_case(), GATES["code_review"], gate_eval_live._agents_index())
    assert "judge (read-only)" in p
    assert "reviewer-result" in p
    assert "diff --git" in p, "диф обязан доехать до судьи опубликованным артефактом"
    assert "ревью изменения" in p


def test_stable_judge_gives_agreement_and_matches_expected():
    live = gate_eval_live.run_case_live(_case(), lambda _p: _FAIL, 3, GATES)
    assert live["verdicts"] == ["fail", "fail", "fail"]
    assert live["agreement"] == "3/3"
    assert live["stable"] is True and live["matches_expected"] is True


def test_a_judge_that_flips_is_measured_not_averaged():
    """Тот же вход, разные ответы — это и есть замер, ради которого корпус заведён."""
    answers = iter([_FAIL, _PASS, _FAIL])
    live = gate_eval_live.run_case_live(_case(), lambda _p: next(answers), 3, GATES)
    assert live["verdicts"] == ["fail", "pass", "fail"]
    assert live["agreement"] == "2/3"
    assert live["stable"] is False
    assert live["matches_expected"] is False


def test_a_call_that_did_not_happen_is_not_a_verdict():
    """Третье состояние: отказ вызова записывается отдельно, а не как мнение судьи."""
    def boom(_p):
        raise RuntimeError("529 Overloaded")

    live = gate_eval_live.run_case_live(_case(), boom, 2, GATES)
    assert live["verdicts"] == []
    assert live["agreement"] == "0/0"
    assert len(live["failures"]) == 2
    assert "529 Overloaded" in live["failures"][0]
    assert live["matches_expected"] is False, "нет вердиктов — нечему совпадать с ожидаемым"


def test_recording_freezes_the_derived_verdict_and_replay_reads_it_back(tmp_path):
    cases_dir, tdir = tmp_path / "cases", tmp_path / "transcripts"
    cases_dir.mkdir()
    case = _case()
    (cases_dir / "probe-live.patch").write_text(case["input"]["diff"], encoding="utf-8")
    live = gate_eval_live.run_case_live(case, lambda _p: _FAIL, 2, GATES)
    path = gate_eval_live.record_into_case(case, live, "probe", None, cases_dir, GATES, tdir)

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert gate_evals.case_form_errors(data, path.name) == []
    assert [r["derived_status"] for r in data["recorded"]] == ["fail", "fail"]
    assert data["stability"]["agreement"] == "2/2"
    assert data["recorded"][0]["provider"] == "probe"
    assert "text" not in data["recorded"][0], "стенограмма живёт файлом улики, а не строкой в кейсе"
    assert (tdir / data["recorded"][0]["transcript"]).is_file()
    assert "diff" not in data["input"], "диф живёт .patch-файлом и обратно в YAML не дублируется"

    cases, errors = gate_evals.load_cases(cases_dir, tdir)
    assert errors == []
    assert gate_evals.replay_case(cases[0], GATES)["outcome"] == "ok"


def test_a_case_whose_transcript_is_missing_is_unavailable_not_broken(tmp_path):
    """В поставке дочки улик нет по построению: кейс обязан честно сказать «не измерено»,
    а не уронить прогон и не притвориться пройденным."""
    cases_dir, tdir = tmp_path / "cases", tmp_path / "transcripts"
    cases_dir.mkdir()
    case = _case()
    (cases_dir / "probe-live.patch").write_text(case["input"]["diff"], encoding="utf-8")
    live = gate_eval_live.run_case_live(case, lambda _p: _FAIL, 2, GATES)
    gate_eval_live.record_into_case(case, live, "probe", None, cases_dir, GATES, tdir)
    for f in tdir.glob("*.md"):
        f.unlink()

    cases, errors = gate_evals.load_cases(cases_dir, tdir)
    assert errors == [], "пропавшая улика — не поломка корпуса"
    r = gate_evals.replay_case(cases[0], GATES)
    assert r["outcome"] == "unavailable"
    assert any("стенограмм нет на месте" in d for d in r["detail"])


def test_recorded_case_goes_red_if_the_derivation_changes(tmp_path, monkeypatch):
    """ПРОБА на связке запись→replay: разбор изменился — корпус краснеет и называет кейс."""
    cases_dir, tdir = tmp_path / "cases", tmp_path / "transcripts"
    cases_dir.mkdir()
    case = _case()
    (cases_dir / "probe-live.patch").write_text(case["input"]["diff"], encoding="utf-8")
    live = gate_eval_live.run_case_live(case, lambda _p: _FAIL, 2, GATES)
    gate_eval_live.record_into_case(case, live, "probe", None, cases_dir, GATES, tdir)

    monkeypatch.setattr(gate_evals, "evidence_from_judge_output",
                        lambda gate, text, source="": None)
    rep = gate_evals.run_corpus(cases_dir=cases_dir, transcripts_dir=tdir)
    assert rep["clean"] is False
    assert rep["counts"]["drift"] == 1
    assert "probe-live" in gate_evals.format_report(rep)


def test_non_judge_cases_are_skipped_by_the_live_runner_not_silently_passed():
    """Кейс без входа для судьи живым прогоном не «проходит» — он не идёт вовсе, и это названо."""
    rep_line = gate_eval_live.format_live({
        "provider": "probe", "model": "", "repeats": 3, "results": [],
        "skipped": ["security-blocks-without-a-judge"]})
    assert "пропущены" in rep_line
    assert "security-blocks-without-a-judge" in rep_line
