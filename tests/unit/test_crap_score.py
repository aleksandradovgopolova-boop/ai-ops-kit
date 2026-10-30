"""Пилот CRAP: реальное AST/FS evidence, без запуска измеряемого кода."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.devtools import crap_score as cs


def source(root, text, name="sample.py"):
    path = root / "ai_ops_kit" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def evidence(root, path, executed, missing, excluded=()):
    report = root / "coverage.json"
    data = {"meta": {"format": 3, "version": "7.10.0"}, "files": {
        path.relative_to(root).as_posix(): {
            "executed_lines": executed, "missing_lines": missing,
            "excluded_lines": list(excluded)}}}
    report.write_text(json.dumps(data), encoding="utf-8")
    binding = root / "coverage-binding.json"
    binding.write_text(json.dumps({
        "schema_version": 1, "outcome": "passed", "scope": "fixture-tests",
        "command": ["python", "-m", "pytest"], "python": "3.12.0",
        "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
        "inputs_sha256": cs.measurement_inputs(root),
    }), encoding="utf-8")
    return report, binding


def baseline(root):
    path = root / "baseline.yaml"
    path.write_text(yaml.safe_dump(cs.baseline_document([], None)), encoding="utf-8")
    return path


def run(root, base, report=None, binding=None, *extra):
    args = ["--root", str(root), "--baseline", str(base), "--json", *extra]
    if report:
        args += ["--coverage", str(report), "--coverage-binding", str(binding)]
    return cs.main(args)


@pytest.mark.parametrize("cc,cov,expected", [(1, 1, 1), (3, 0, 12), (4, .5, 6), (10, 1, 10)])
def test_original_formula(cc, cov, expected):
    assert cs.crap(cc, cov) == expected


@pytest.mark.parametrize("cc,cov", [(0, .5), (True, .5), (1, -1), (1, 1.1), (1, float("nan"))])
def test_formula_rejects_invalid_values(cc, cov):
    with pytest.raises(ValueError):
        cs.crap(cc, cov)


def test_complexity_and_scopes_do_not_double_count_nested_functions(tmp_path):
    source(tmp_path, '''class A:
    async def method(self, values):
        def inner(x):
            return x if x else 0
        return [inner(v) for v in values if v and v > 1]
class B:
    def method(self):
        return 1
''')
    rows = cs.functions(tmp_path)
    by_name = {r["name"]: r for r in rows}
    assert set(by_name) == {"A.method", "A.method.inner", "B.method"}
    assert by_name["A.method"]["complexity"] == 4  # generator, filter, and
    assert by_name["A.method.inner"]["complexity"] == 2
    assert by_name["B.method"]["complexity"] == 1
    assert 4 not in by_name["A.method"]["body_lines"]


def test_decision_rules_cover_exceptions_match_boolean_loops(tmp_path):
    source(tmp_path, '''def f(x):
    try:
        for v in x:
            while v:
                if v and x or x:
                    break
    except ValueError:
        pass
    match x:
        case 1 | 2:
            pass
        case _ if x:
            pass
        case _:
            pass
''')
    assert cs.functions(tmp_path)[0]["complexity"] == 9


def test_key_is_stable_under_lines_comments_and_literals(tmp_path):
    p = source(tmp_path, "def f(x):\n    if x:\n        return 1\n    return 0\n")
    before = cs.functions(tmp_path)[0]["key"]
    p.write_text("# shift\n\ndef f(x):\n    if x:\n        return 2\n    return 0\n")
    assert cs.functions(tmp_path)[0]["key"] == before
    p.write_text(p.read_text().replace("if x:", "if x and x:"))
    assert cs.functions(tmp_path)[0]["key"] != before


def test_duplicate_qualified_names_are_not_lost(tmp_path):
    source(tmp_path, "def f():\n    return 1\ndef f():\n    return 2\n")
    rows = cs.functions(tmp_path)
    assert len(rows) == len({r["key"] for r in rows}) == 2


def test_body_mapping_excludes_headers_decorators_docstrings_and_inner_body(tmp_path):
    p = source(tmp_path, '''@decorator
def outer():
    """Doc."""
    def inner():
        return 1
    return inner
''')
    report, binding = evidence(tmp_path, p, [1, 2, 3, 4], [5, 6])
    result = cs.analyze(tmp_path, cs.load_coverage(tmp_path, report, binding), {})
    rows = {r["name"]: r for r in result["functions"]}
    assert rows["outer"]["coverage"] == .5  # lines 4 and 6 only
    assert rows["outer.inner"]["coverage"] == 0
    assert rows["outer.inner"]["crap"] == 2


def test_excluded_lines_do_not_count_as_covered(tmp_path):
    p = source(tmp_path, "def f(x):\n    if x:\n        return 1\n    return 0\n")
    report, binding = evidence(tmp_path, p, [1, 2, 3], [], [4])
    rows = cs.analyze(tmp_path, cs.load_coverage(tmp_path, report, binding), {})["functions"]
    assert rows[0]["coverage"] == 1


def test_default_missing_evidence_is_visible_incomplete_not_zero(tmp_path, capsys):
    source(tmp_path, "def f():\n    return 1\n")
    assert run(tmp_path, baseline(tmp_path)) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "incomplete"
    row = result["functions"][0]
    assert row["coverage_status"] == "missing"
    assert row["coverage"] is row["crap"] is None


def test_new_debt_exact_threshold_and_read_only_side_effect_proof(tmp_path, capsys):
    p = source(tmp_path, "def f(x):\n    if x:\n        return 1\n    return 0\n")
    report, binding = evidence(tmp_path, p, [1], [2, 3, 4])
    base = baseline(tmp_path)
    before = {q: q.read_bytes() for q in tmp_path.rglob("*") if q.is_file()}
    assert run(tmp_path, base, report, binding) == 0
    capsys.readouterr()
    # Изменение реально произошло ДО проверки нового долга (CC 2 → 3, CRAP 6 → 12).
    p.write_text(p.read_text().replace("if x:", "if x and x:"))
    assert p.read_bytes() != before[p]
    report, binding = evidence(tmp_path, p, [1], [2, 3, 4])
    before = {q: q.read_bytes() for q in tmp_path.rglob("*") if q.is_file()}
    assert run(tmp_path, base, report, binding) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["functions"][0]["crap"] == 12
    assert result["functions"][0]["finding"] == "new_debt"
    assert before == {q: q.read_bytes() for q in tmp_path.rglob("*") if q.is_file()}


def test_stale_source_or_test_evidence_does_not_create_score(tmp_path):
    p = source(tmp_path, "def f():\n    return 1\n")
    report, binding = evidence(tmp_path, p, [1, 2], [])
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_new.py").write_text("def test_changed(): pass\n")
    result = cs.analyze(tmp_path, cs.load_coverage(tmp_path, report, binding), {})
    assert result["functions"][0]["coverage_status"] == "stale"
    assert result["functions"][0]["crap"] is None


@pytest.mark.parametrize("mutation", ["digest", "overlap", "bool_line", "out_of_bounds", "failed"])
def test_invalid_evidence_refuses_and_does_not_write(tmp_path, capsys, mutation):
    p = source(tmp_path, "def f():\n    return 1\n")
    report, binding = evidence(tmp_path, p, [1, 2], [])
    data, bind = json.loads(report.read_text()), json.loads(binding.read_text())
    row = next(iter(data["files"].values()))
    if mutation == "overlap":
        row["missing_lines"] = [2]
    elif mutation == "bool_line":
        row["executed_lines"] = [True]
    elif mutation == "out_of_bounds":
        row["executed_lines"] = [100]
    elif mutation == "failed":
        bind["outcome"] = "failed"
    report.write_text(json.dumps(data))
    if mutation != "digest":
        bind["report_sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
    else:
        bind["report_sha256"] = "0" * 64
    binding.write_text(json.dumps(bind))
    base = baseline(tmp_path)
    before = base.read_bytes()
    assert run(tmp_path, base, report, binding, "--write-baseline") == 2
    assert base.read_bytes() == before
    assert "ERROR" in capsys.readouterr().err


def test_missing_file_or_empty_denominator_stays_unknown(tmp_path):
    p = source(tmp_path, "def f():\n    return 1\n")
    source(tmp_path, "def g():\n    return 2\n", "other.py")
    report, binding = evidence(tmp_path, p, [1], [], [2])
    rows = cs.analyze(tmp_path, cs.load_coverage(tmp_path, report, binding), {})["functions"]
    assert {r["coverage_status"] for r in rows} == {"unknown", "missing"}
    assert all(r["crap"] is None for r in rows)


def test_baseline_write_then_coverage_regression_requires_explicit_reason(tmp_path, capsys):
    p = source(tmp_path, "def f(x):\n    if x and x and x and x and x and x and x and x and x:\n        return 1\n    return 0\n")
    report, binding = evidence(tmp_path, p, [1, 2, 3, 4], [])
    base = tmp_path / "new.yaml"
    assert run(tmp_path, base, report, binding, "--write-baseline") == 0
    doc = yaml.safe_load(base.read_text())
    assert doc["functions"]  # CC=10, полное покрытие: ровно порог CRAP=10
    before = base.read_bytes()
    report, binding = evidence(tmp_path, p, [1], [2, 3, 4])
    assert run(tmp_path, base, report, binding) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["functions"][0]["finding"] == "regression"
    assert run(tmp_path, base, report, binding, "--write-baseline") == 2
    assert base.read_bytes() == before
    assert run(tmp_path, base, report, binding, "--write-baseline", "--allow-raise", "Reviewed pilot debt") == 0
    assert yaml.safe_load(base.read_text())["raises"][-1]["reason"] == "Reviewed pilot debt"


def test_unknown_evidence_cannot_be_frozen(tmp_path):
    source(tmp_path, "def f():\n    return 1\n")
    base = baseline(tmp_path)
    before = base.read_bytes()
    assert run(tmp_path, base, None, None, "--write-baseline") == 2
    assert base.read_bytes() == before


@pytest.mark.parametrize("body", ["bad: [", "functions: {}", "schema_version: true", "[]"])
def test_malformed_baseline_is_not_empty_success(tmp_path, body):
    source(tmp_path, "def f():\n    return 1\n")
    base = tmp_path / "baseline.yaml"
    base.write_text(body)
    assert run(tmp_path, base) == 2


def test_syntax_error_and_missing_scan_root_are_errors(tmp_path):
    assert run(tmp_path, baseline(tmp_path)) == 2
    source(tmp_path, "def invalid(:\n")
    assert run(tmp_path, tmp_path / "baseline.yaml") == 2


@pytest.mark.parametrize("text,line", [
    ("def f(a,b): return a and b and a\n", 1),
    ("def f(\n    a,b\n): return a and b and a\n", 3),
    ("class A:\n    def f(self,a,b): return a and b and a\n", 2),
])
def test_inline_suite_never_inherits_definition_line_coverage(tmp_path, text, line):
    p = source(tmp_path, text)
    report, binding = evidence(tmp_path, p, [line], [])
    result = cs.analyze(tmp_path, cs.load_coverage(tmp_path, report, binding), {})
    row = result["functions"][0]
    assert row["complexity"] == 3
    assert row["coverage_status"] == "unknown"
    assert row["coverage"] is row["crap"] is None


def test_no_named_functions_is_not_successful_measurement(tmp_path, capsys):
    source(tmp_path, "VALUE = 1\n")
    assert run(tmp_path, baseline(tmp_path)) == 2
    assert "нет именованных функций" in capsys.readouterr().err


def test_coverage_py_virtual_excluded_eof_does_not_create_false_error(tmp_path):
    p = source(tmp_path, "def f():\n    return 1\n")
    report, binding = evidence(tmp_path, p, [1, 2], [], [3])
    result = cs.analyze(tmp_path, cs.load_coverage(tmp_path, report, binding), {})
    assert result["functions"][0]["coverage"] == 1


def test_mid_scan_change_invalidates_evidence(tmp_path, monkeypatch):
    p = source(tmp_path, "def f():\n    return 1\n")
    report, binding = evidence(tmp_path, p, [1, 2], [])
    bound = cs.load_coverage(tmp_path, report, binding)
    original = cs.functions
    def changed(root):
        p.write_text(p.read_text().replace("return 1", "return 2"))
        return original(root)
    monkeypatch.setattr(cs, "functions", changed)
    result = cs.analyze(tmp_path, bound, {})
    assert result["functions"][0]["coverage_status"] == "stale"
    assert result["functions"][0]["crap"] is None


def test_failed_atomic_replace_preserves_baseline_and_cleans_temporary_file(tmp_path, monkeypatch):
    path = tmp_path / "baseline.yaml"
    path.write_text("old baseline")
    def broken_replace(*args):
        raise OSError("simulated replacement failure")
    monkeypatch.setattr(cs.os, "replace", broken_replace)
    with pytest.raises(OSError, match="replacement failure"):
        cs._atomic_write(path, "new baseline")
    assert path.read_text() == "old baseline"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["baseline.yaml"]


def test_baseline_symlink_is_not_overwritten(tmp_path):
    target = tmp_path / "target.yaml"
    target.write_text("target baseline")
    link = tmp_path / "link.yaml"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        cs._atomic_write(link, "new baseline")
    assert link.is_symlink()
    assert target.read_text() == "target baseline"


def test_excluded_eof_cannot_hide_executed_line_outside_source(tmp_path):
    p = source(tmp_path, "def f():\n    return 1\n")
    report, binding = evidence(tmp_path, p, [1, 2, 3], [], [3])
    bound = cs.load_coverage(tmp_path, report, binding)
    with pytest.raises(ValueError, match="вне исходника"):
        cs.analyze(tmp_path, bound, {})
