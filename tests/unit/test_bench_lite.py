"""Unit tests for tools/bench_lite.py — the offline golden benchmark corpus.

Tests the corpus structure, case classification, scaffold, and report schema.
Avoids running the full bench (slow) — focuses on structural invariants.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import bench_lite as bl


@pytest.mark.unit
class TestCorpusStructure:
    """Tests for _cases() — the golden corpus must be well-formed."""

    def test_load_corpus_returns_list(self):
        cases = bl._cases()
        assert isinstance(cases, list)
        assert len(cases) >= 4  # at least quick_clean, review_blocks, fixloop, rubber_stamp

    def test_corpus_entries_have_required_fields(self):
        cases = bl._cases()
        for case in cases:
            assert "id" in case, f"case missing 'id': {case}"
            assert "tags" in case, f"case missing 'tags': {case}"
            assert "build" in case, f"case missing 'build': {case}"
            assert "expected" in case, f"case missing 'expected': {case}"
            assert callable(case["build"]), f"case 'build' not callable: {case['id']}"

    def test_corpus_entries_have_expected_ready_field(self):
        cases = bl._cases()
        for case in cases:
            exp = case["expected"]
            assert "ready" in exp, f"case {case['id']} expected missing 'ready'"
            assert "unmet_includes" in exp, f"case {case['id']} expected missing 'unmet_includes'"

    def test_corpus_ids_are_unique(self):
        cases = bl._cases()
        ids = [c["id"] for c in cases]
        assert len(ids) == len(set(ids)), f"Duplicate case IDs found: {[x for x in ids if ids.count(x) > 1]}"

    def test_corpus_has_safety_cases(self):
        cases = bl._cases()
        safety = [c for c in cases if c.get("category") == "safety"]
        assert len(safety) >= 1, "Corpus must have at least one safety case"

    def test_corpus_has_known_good_cases(self):
        cases = bl._cases()
        kg = [c for c in cases if c.get("category") == "known_good"]
        assert len(kg) >= 5, "Corpus must have multiple known_good cases"


@pytest.mark.unit
class TestClassify:
    """Tests for _classify() — case outcome classification."""

    def test_ok_when_expected_and_actual_match(self):
        expected = {"ready": True, "unmet_includes": []}
        actual = {"ready_for_pr": True, "unmet": []}
        assert bl._classify(expected, actual) == "ok"

    def test_false_fail_when_expected_ready_but_not_actual(self):
        expected = {"ready": True, "unmet_includes": []}
        actual = {"ready_for_pr": False, "unmet": ["ux_review"]}
        assert bl._classify(expected, actual) == "false_fail"

    def test_false_green_when_expected_blocked_but_actual_ready(self):
        expected = {"ready": False, "unmet_includes": ["ux_review"]}
        actual = {"ready_for_pr": True, "unmet": []}
        assert bl._classify(expected, actual) == "false_green"

    def test_mismatch_when_ready_matches_but_gates_differ(self):
        expected = {"ready": False, "unmet_includes": ["ux_review"]}
        actual = {"ready_for_pr": False, "unmet": ["visual_regression"]}
        assert bl._classify(expected, actual) == "mismatch"

    def test_ok_when_both_blocked_same_gate(self):
        expected = {"ready": False, "unmet_includes": ["ux_review"]}
        actual = {"ready_for_pr": False, "unmet": ["ux_review"]}
        assert bl._classify(expected, actual) == "ok"


@pytest.mark.unit
class TestScaffold:
    """Tests for _scaffold() — minimal git repo creation."""

    def test_scaffold_creates_git_repo(self, tmp_path):
        branch = bl._scaffold(tmp_path)
        assert (tmp_path / ".git").is_dir()
        assert (tmp_path / "pyproject.toml").is_file()
        assert (tmp_path / "seed").is_file()
        assert branch  # non-empty branch name

    def test_scaffold_has_clean_status(self, tmp_path):
        bl._scaffold(tmp_path)
        result = subprocess.run(
            ["git", "-C", str(tmp_path), "status", "--porcelain"],
            capture_output=True, text=True)
        assert result.stdout.strip() == ""


@pytest.mark.unit
class TestBenchVersion:
    """Tests for bench version constant."""

    def test_bench_version_is_string(self):
        assert isinstance(bl.BENCH_VERSION, str)
        assert bl.BENCH_VERSION


@pytest.mark.unit
class TestReviewers:
    """Tests for the scripted reviewer factories."""

    def test_pass_reviewer_reads_then_passes(self):
        rev = bl._pass_reviewer("src/foo.py")
        # First call: should request read
        result1 = rev("some prompt without marker")
        assert '"op": "read"' in result1 or '"op":"read"' in result1
        # Second call with marker: should pass
        result2 = rev("prompt --- src/foo.py ---")
        assert '"status":"pass"' in result2 or '"status": "pass"' in result2

    def test_rubber_reviewer_passes_without_reading(self):
        rev = bl._rubber_reviewer()
        result = rev("any prompt")
        assert '"status":"pass"' in result or '"status": "pass"' in result

    def test_fail_reviewer_fails_after_reading(self):
        rev = bl._fail_reviewer("src/bar.py", ["missing tests"])
        result = rev("prompt --- src/bar.py ---")
        assert '"status":"fail"' in result or '"status": "fail"' in result


# run_bench() исполняет весь оффлайн-корпус (~35 c) — считаем ОДИН раз на модуль
# и переиспользуем во всех гранулярных проверках агрегатных инвариантов прогона.
@pytest.fixture(scope="module")
def bench_report():
    return bl.run_bench()


@pytest.mark.slow
@pytest.mark.nightly  # ~2.5 мин: module-scoped bench_report гоняет весь корпус — снят с пути PR в ночь (#462)
class TestRunBenchAggregate:
    """Агрегатные инварианты run_bench() (перенесены из монолитного селфтеста).

    Один прогон корпуса (module-scoped фикстура) — много гранулярных проверок:
    одно поведение = один тест, точные поля отчёта.
    """

    # --- метрики: инвариант безопасности и корректность прогона -------------------------------
    def test_no_false_green(self, bench_report):
        # движок никогда не отдаёт ready при обязательном блоке — абсолютный инвариант
        assert bench_report["metrics"]["false_green"] == 0

    def test_no_run_errors(self, bench_report):
        assert bench_report["metrics"]["error"] == 0

    def test_no_gate_composition_mismatch(self, bench_report):
        assert bench_report["metrics"]["mismatch"] == 0

    def test_no_false_fail(self, bench_report):
        # заведомо готовые кейсы доведены до ready
        assert bench_report["metrics"]["false_fail"] == 0

    def test_all_cases_pass(self, bench_report):
        assert bench_report["metrics"]["pass"] == bench_report["total"]

    def test_fix_loop_recovered(self, bench_report):
        # tool-free fix-loop реально снял блок ревью
        assert bench_report["metrics"]["fix_recovered"] >= 1

    def test_conservative_review_measured(self, bench_report):
        assert bench_report["metrics"]["review_blocked"] >= 1

    def test_report_carries_per_case_classification(self, bench_report):
        assert bench_report["total"] >= 4
        assert all("classification" in c for c in bench_report["cases"])

    # --- policy_conformance: движок исполняет ТЕКУЩУЮ policy как задумано ----------------------
    def test_policy_conformance_perfect(self, bench_report):
        pc = bench_report["policy_conformance"]
        assert pc["conformance_rate"] == 1.0
        assert pc["false_green"] == 0

    # --- quality_accuracy: пропустила ли policy корректную работу ------------------------------
    def test_engine_floor_ready(self, bench_report):
        # движок не источник false-fail ни на одном уровне impact
        assert bench_report["quality_accuracy"]["engine_floor_ready"] is True

    def test_synthetic_block_rate_honestly_labelled(self, bench_report):
        qa = bench_report["quality_accuracy"]
        rate = qa["synthetic_known_good_block_rate"]
        assert rate is not None and 0.0 <= rate <= 1.0
        assert qa["sample_size"] >= 15
        assert qa["sample_type"] == "scripted_reviewer"
        # live-rate НЕ выдаётся за измеренный
        assert qa["live_reviewer_false_fail_rate"] is None

    def test_block_attribution_covers_all_ui_gates(self, bench_report):
        qa = bench_report["quality_accuracy"]
        assert all(qa["block_attribution"].get(g, 0) >= 1 for g in bl.gate_policy.UI_GATES)

    def test_backend_impact_none_reaches_ready(self, bench_report):
        # false-fail сконцентрирован в UI-ревью, а не в backend
        bk = next((c for c in bench_report["cases"] if c["id"] == "kg_full_backend"), None)
        assert bk is not None
        assert bk["actual"].get("ready_for_pr") is True

    def test_known_good_blocked_by_exactly_expected_gates(self, bench_report):
        UI = bl.gate_policy.UI_GATES
        checked = 0
        for c in bench_report["cases"]:
            exp_by = c["expected"].get("blocked_by")
            if exp_by:
                unmet = c["actual"].get("unmet", [])
                assert set(g for g in unmet if g in UI) == set(exp_by), \
                    f"{c['id']} заблокирован не тем набором UI-гейтов"
                checked += 1
        assert checked >= 1, "ни одного кейса с expected.blocked_by — проверка вхолостую"

    # --- проекция кандидатной политики (shadow) -----------------------------------------------
    def test_candidate_strictly_reduces_block_rate(self, bench_report):
        qa = bench_report["quality_accuracy"]
        assert qa["projected_block_rate_after_calibration"] < qa["synthetic_known_good_block_rate"]

    def test_projected_released_only_internal_non_safety(self, bench_report):
        UI = bl.gate_policy.UI_GATES
        SAFE = bl.gate_policy.SAFETY_UI_GATES
        cases = bench_report["cases"]
        released = bench_report["quality_accuracy"]["projected_released"]
        for cid in released:
            c = next(x for x in cases if x["id"] == cid)
            unmet_ui = [g for g in c["actual"].get("unmet", []) if g in UI]
            assert c["ui_impact"] == "internal"
            assert not (set(unmet_ui) & set(SAFE)), \
                f"освобождён {cid} по safety-гейту"

    def test_no_user_facing_or_critical_released(self, bench_report):
        cases = bench_report["cases"]
        released = bench_report["quality_accuracy"]["projected_released"]
        released_impacts = {next(x for x in cases if x["id"] == cid)["ui_impact"]
                            for cid in released}
        assert not (released_impacts & {"user_facing", "critical"})

    def test_shadow_diffs_no_weakening_on_safety_impact(self, bench_report):
        # user_facing/critical -> ноль ослабляющих отличий кандидата
        for c in bench_report["cases"]:
            sh = c.get("shadow")
            if sh and c["ui_impact"] in ("user_facing", "critical"):
                weakening = [d for d in sh["differences"]
                             if d["effect"] in ("would_unblock", "would_skip")]
                assert not weakening, f"{c['id']} ({c['ui_impact']}) ослаблен кандидатом"

    def test_measurement_does_not_introduce_false_green(self, bench_report):
        # безопасность не ослаблена измерением/проекцией на всём корпусе
        assert bench_report["metrics"]["false_green"] == 0

    # --- v3.1.8: живое калиброванное enforcement (промоушен-критерий) --------------------------
    def test_calibrated_no_false_green(self, bench_report):
        assert bench_report["calibrated_enforcement"]["calibrated_false_green"] == 0

    def test_all_safety_regressions_blocked(self, bench_report):
        ce = bench_report["calibrated_enforcement"]
        assert ce["safety_regressions_total"] >= 2
        assert ce["safety_regressions_blocked"] == ce["safety_regressions_total"]

    def test_no_residual_false_fail(self, bench_report):
        ce = bench_report["calibrated_enforcement"]
        assert ce["residual_false_fail"] == 0
        assert ce["residual_false_fail_rate"] is None or ce["residual_false_fail_rate"] <= 0.10

    def test_evidence_releases_known_good(self, bench_report):
        # deterministic closure освобождает user_facing
        assert bench_report["calibrated_enforcement"]["evidence_released"] >= 5

    def test_calibration_strictly_reduces_block_rate(self, bench_report):
        ce = bench_report["calibrated_enforcement"]
        assert ce["calibrated_block_rate"] < ce["baseline_block_rate"]
        assert ce["reduction"] >= 0.5

    def test_remaining_calibrated_blocks_are_fail_closed(self, bench_report):
        # каждый оставшийся заблокированный calibrated known-good -> calibrated_expected.ready is False
        kgc_blocked = [c for c in bench_report["cases"]
                       if c["category"] == "known_good"
                       and "calibrated_actual" in c
                       and c["calibrated_actual"].get("ready_for_pr") is not True]
        assert all(c["calibrated_expected"].get("ready") is False for c in kgc_blocked)
