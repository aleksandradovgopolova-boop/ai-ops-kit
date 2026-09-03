"""Вердикт называет дефицит среды средой, а не «гейт не закрыт» (поле 02–03.09.2026).

Когда детерминированные проверки отработали (напр. pytest прошёл), а инструмент недоступен
(ruff/typecheck -> exit 127), гейт остаётся незакрытым — но это среда, не код. Обобщённое «гейт не
закрыт» читается как «правка плохая». `_env_degraded_note`/`_env_skipped_checks` называют такие
проверки явно: отработавшее — зелено, эти ворота ПРОПУЩЕНЫ (среда), не провалены (код).
"""
from ai_ops_kit.engine.pipeline_failure import _env_degraded_note, _env_skipped_checks


def _env_check(cmd="ruff", tail=None, exit_code=127):
    return {"status": "fail", "runs": [{"ok": False, "exit_code": exit_code, "command": cmd,
                                        "output_tail": tail if tail is not None else f"{cmd}: command not found"}]}


def _code_check():
    return {"status": "fail", "runs": [{"ok": False, "exit_code": 1, "command": "pytest",
                                        "output_tail": "FAILED test_x::test_y\n1 failed"}]}


def _pass_check():
    return {"status": "pass", "runs": [{"ok": True, "exit_code": 0, "command": "pytest",
                                        "output_tail": "42 passed"}]}


def test_env_symptom_check_is_named_as_environment():
    skipped = _env_skipped_checks({"lint": _env_check("ruff")})
    assert [n for n, _ in skipped] == ["lint"]


def test_note_calls_it_environment_not_a_code_defect():
    note = _env_degraded_note({"lint": _env_check("ruff")})
    assert note is not None
    assert "lint" in note
    assert "дефицит среды" in note and "не дефект кода" in note
    assert "ПРОПУЩЕНЫ" in note and "не провалены" in note   # честно в обе стороны


def test_real_code_failure_is_not_named_as_environment():
    assert _env_skipped_checks({"test": _code_check()}) == []
    assert _env_degraded_note({"test": _code_check()}) is None


def test_passing_checks_produce_no_note():
    assert _env_degraded_note({"test": _pass_check()}) is None


def test_mixed_names_only_the_env_check():
    note = _env_degraded_note({"lint": _env_check("ruff"), "test": _code_check(), "unit": _pass_check()})
    assert note is not None
    assert "lint" in note
    assert "test" not in note and "unit" not in note


def test_modulenotfound_counts_as_environment_even_on_exit_1():
    chk = _env_check("python -m mypy", tail="ModuleNotFoundError: No module named 'yaml'", exit_code=1)
    assert [n for n, _ in _env_skipped_checks({"typecheck": chk})] == ["typecheck"]
