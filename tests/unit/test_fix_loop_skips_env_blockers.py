"""Fix-цикл не зацикливает писателя на нехватке инструментов (поле 02–03.09.2026).

Провал проверки из-за отсутствующего в среде прогона тулчейна (exit 127 / `command not found` /
`no module named`) писатель починить НЕ может — он не ставит инструменты. Прежде такой провал шёл
ему на итерацию как обычный блокер, и fix-цикл гонял его бесконечно (зависание живого заезда на
нехватке ruff/pytest/pyyaml). `_review_fix_context` теперь пропускает env-обусловленные провалы:
остались только они -> None -> цикл честно завершается NOT_READY, а не крутит писателя вхолостую.

Это НЕ создаёт ложного green: `ready_for_pr` считается отдельно (env-квалификация уже в base_ok);
здесь гасится только бесполезный ретрай.
"""
from ai_ops_kit.engine.ai_ops_run_reporting import _review_fix_context


def _rep(checks=None, reviews=None, unmet=None, security=None):
    return {"ready_for_pr": False, "overall_status": "not-ready", "error": "",
            "checks": checks or {}, "reviews": reviews or [],
            "gates": {"unmet": unmet or []}, "security_scan": security or {}}


def _env_check(cmd="ruff"):
    # exit 127 = command not found: инструмента нет в среде прогона.
    return {"status": "fail", "runs": [{"ok": False, "exit_code": 127, "command": cmd,
                                        "output_tail": f"{cmd}: command not found"}]}


def _code_check():
    # честный красный код: тулчейн есть, тест реально падает.
    return {"status": "fail", "runs": [{"ok": False, "exit_code": 1, "command": "pytest",
                                        "output_tail": "FAILED test_x::test_y\n1 failed"}]}


def test_env_symptom_check_does_not_retry_the_writer():
    # Единственный блокер — недоступный инструмент: писателя звать бессмысленно -> None (цикл завершится).
    assert _review_fix_context(_rep(checks={"lint": _env_check("ruff")})) is None


def test_real_code_failure_still_retries_the_writer():
    ctx = _review_fix_context(_rep(checks={"test": _code_check()}))
    assert ctx is not None and "проверка test" in ctx


def test_mixed_feeds_only_the_real_failure_not_the_env_one():
    ctx = _review_fix_context(_rep(checks={"lint": _env_check("ruff"), "test": _code_check()}))
    assert ctx is not None
    assert "проверка test" in ctx        # реальный провал кода — писателю
    assert "проверка lint" not in ctx    # env-обусловленный — пропущен


def test_modulenotfound_is_env_not_code_even_on_exit_1():
    chk = {"status": "fail", "runs": [{"ok": False, "exit_code": 1, "command": "python -m mypy",
                                       "output_tail": "ModuleNotFoundError: No module named 'yaml'"}]}
    assert _review_fix_context(_rep(checks={"typecheck": chk})) is None


def test_env_check_plus_real_review_blocker_still_retries():
    # env-проверку пропускаем, но реальный блокер ревью остаётся -> писателю есть что чинить.
    rep = _rep(checks={"lint": _env_check()},
               reviews=[{"gate": "code_review", "status": "fail",
                         "blockers": ["не обработан edge-case пустого входа"]}])
    ctx = _review_fix_context(rep)
    assert ctx is not None and "code_review" in ctx
