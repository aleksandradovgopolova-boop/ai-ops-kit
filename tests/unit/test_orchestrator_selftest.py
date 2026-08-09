"""Селфтест orchestrator, вынесенный из продакшн-модуля (v3.30).

Тело перенесено ДОСЛОВНО: цель — убрать 270 строк тестового кода из модуля, который едет в
child-репозиторий, а не переписать проверки. Гранулярность (одна pytest-функция вместо
пятнадцати) — осознанная плата за отсутствие риска: перенос без правок нельзя сломать.
Дробление на отдельные тесты — отдельный шаг, когда для него будет повод.

Прежний вход `python3 tools/orchestrator.py --selftest` удалён вместе с функцией; чеклист и
CI-группа execution обновлены.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import yaml

import orchestrator_usage
from orchestrator import (  # noqa: F401 — часть имён нужна телу селфтеста
    PKG, _http_post_json, build_role_prompt, load_state,
    make_claude_cli_provider, make_provider, mock_provider, run_workflow, save_state,
)


class _LiveCallStats:
    """Живой доступ к orchestrator_usage._CALL_STATS.

    drain_call_stats() ПЕРЕСОЗДАЁТ список (`global _CALL_STATS; _CALL_STATS = []`), поэтому имя,
    импортированное один раз, после первого слива указывает на осиротевший объект. В отдельном
    процессе (как селфтест запускался раньше) слива не случалось и подмены никто не замечал; в
    общем pytest-прогоне — случается. Читаем через модуль, а не по снимку имени."""

    def __len__(self):
        return len(orchestrator_usage._CALL_STATS)

    def __getitem__(self, i):
        return orchestrator_usage._CALL_STATS[i]


_CALL_STATS = _LiveCallStats()


@pytest.mark.unit
@pytest.mark.slow   # тяжёлая обёртка селфтеста: в быстрый профиль не входит
def test_orchestrator_selftest(capsys):
    """Перенесённое тело. `ok` накапливает вердикт, как в исходной функции."""
    ok = True
    # evidence, эмулирующий выполненные блокирующие гейты QUICK (в реальном прогоне
    # его дают reviewer-стадии/валидаторы; в mock — подаём явно, чтобы дойти до done)
    quick_evidence = {
        "intake_completeness": {"status": "pass", "provided": ["classified_type", "size", "risk"]},
        "implementation_verification": {"status": "pass",
            "provided": ["build_passed", "lint_passed", "typecheck_passed", "tests_passed", "tested_revision"]},
    }
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 1. без evidence блокирующие гейты не выполнены -> workflow BLOCKED (не done)
        sb, rdb = run_workflow("QUICK", "поправить опечатку в README", root, verbose=False)
        if sb["status"] == "blocked" and set(sb.get("unmet_gates", [])) == {
                "intake_completeness", "implementation_verification"} and len(sb["completed_checks"]) == 4:
            print("PASS QUICK без evidence: 4 стадии, но статус blocked (гейты не выполнены)")
        else:
            ok = False; print(f"FAIL ожидался blocked с невыполненными гейтами, получено {sb['status']}")
        if (rdb / "GateReport.json").exists():
            print("PASS GateReport.json записан")
        else:
            ok = False; print("FAIL нет GateReport.json")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 2. с полным evidence -> done
        state, run_dir = run_workflow("QUICK", "поправить опечатку в README", root,
                                      verbose=False, gate_evidence=quick_evidence)
        if state["status"] != "done" or len(state["completed_checks"]) != 4:
            ok = False; print("FAIL QUICK с evidence не дошёл до done")
        else:
            print("PASS QUICK с evidence: 4 стадии, статус done")
        # resume: удалить состояние последней стадии и перезапустить
        st = load_state(run_dir)
        st["completed_checks"] = st["completed_checks"][:2]
        st["status"] = "in-progress"; st["next_action"] = "local-verify"
        save_state(run_dir, st)
        state2, _ = run_workflow("QUICK", "поправить опечатку в README", root,
                                 verbose=False, gate_evidence=quick_evidence)
        if state2["status"] == "done" and len(state2["completed_checks"]) == 4:
            print("PASS resume: продолжил с прерванного места до done")
        else:
            ok = False; print("FAIL resume не сработал")
        # изоляция judge: в handoff только published-артефакты
        h = json.loads((run_dir / "TaskHandoff.json").read_text(encoding="utf-8"))
        if all(a.startswith(".ai/runtime/") and "stage-" in a for a in h["published_artifacts"]):
            print("PASS handoff содержит только опубликованные артефакты")
        else:
            ok = False; print("FAIL handoff содержит лишнее")
        # judge-промпт содержит read-only guard
        wf = yaml.safe_load((PKG / "registry" / "workflows.yaml").read_text(encoding="utf-8"))["workflows"]["QUICK"]
        judge_stage = next(s for s in wf["stages"] if s.get("review_mode") == "read-only")
        ag = yaml.safe_load((PKG / "registry" / "agents.yaml").read_text(encoding="utf-8"))
        idx = {a["id"]: a for a in ag["agents"]}
        p = build_role_prompt(judge_stage, judge_stage["owner"], idx, "t", {})
        if "read-only" in p and "рассуждения предыдущих ролей тебе не передаются" in p:
            print("PASS judge-промпт изолирован (read-only guard)")
        else:
            ok = False; print("FAIL нет read-only guard в judge-промпте")
        # v2.57: judge, вернувший JSON reviewer-result, -> валидный stage-*.reviewer.json
        def json_judge(prompt):
            if "read-only" in prompt:   # judge-стадия
                return ('Заключение.\n{"schema_version":1,"kind":"reviewer-result",'
                        '"gate":"code_review","status":"pass",'
                        '"checks":[{"id":"style","status":"pass"}]}')
            return "готово"
        st_j, run_dir_j = run_workflow("QUICK", "структурный вердикт judge", root,
                                       provider=json_judge, verbose=False, fresh=True)
        rj = list(Path(run_dir_j).glob("stage-*.reviewer.json"))
        if rj:
            print("PASS judge пишет структурный reviewer.json (не regex)")
        else:
            ok = False; print("FAIL reviewer.json не создан из JSON-вердикта judge")
    # --collect-evidence: вердикты reviewer-стадий собираются, НО детерминированные гейты
    # (build/lint/typecheck/tests) словом «pass» не закрываются (дисциплина evidence v2.16) —
    # QUICK остаётся blocked без реальных доказательств. Раньше тест ждал done — это была дыра.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        def verdict_provider(role_prompt):
            return "status: passed\nРезультат стадии готов согласно контракту роли."
        sc, _ = run_workflow("QUICK", "поправить опечатку", root, provider=verdict_provider,
                             verbose=False, collect=True)
        if sc["status"] == "blocked" and "implementation_verification" in sc.get("unmet_gates", []):
            print("PASS collect-evidence: слова ревьюера не закрывают детерминированные гейты -> blocked")
        else:
            ok = False; print(f"FAIL ожидался blocked на implementation_verification, получено {sc['status']}")
    # аудит-лог (v2.20): append-only запись действия ИИ появляется после прогона
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        run_workflow("QUICK", "починить опечатку", root, verbose=False)
        run_workflow("QUICK", "починить ещё раз", root, verbose=False, fresh=True)
        log = root / ".ai" / "runtime" / "interaction-log.jsonl"
        recs = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()] if log.exists() else []
        if len(recs) == 2 and all({"ts", "workflow", "status", "provider"} <= set(r) for r in recs):
            print("PASS audit-log: append-only записи действий ИИ (ts/workflow/status/provider)")
        else:
            ok = False; print(f"FAIL audit-log: ожидалось 2 валидных записи, получено {len(recs)}")

    # провайдер-адаптер (v2.18): mock офлайн; живой требует ключ (честная ошибка без него)
    import os as _os
    if make_provider("mock") is mock_provider:
        print("PASS provider: mock — офлайн-провайдер по умолчанию")
    else:
        ok = False; print("FAIL provider: mock не резолвится в mock_provider")
    _saved = _os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        make_provider("anthropic")("тест")
        ok = False; print("FAIL provider: anthropic без ключа должен падать честной ошибкой")
    except SystemExit:
        print("PASS provider: anthropic без ключа -> честная ошибка (не тихий mock)")
    finally:
        if _saved is not None:
            _os.environ["ANTHROPIC_API_KEY"] = _saved
    try:
        make_provider("bogus")
        ok = False; print("FAIL provider: неизвестный провайдер должен падать")
    except SystemExit:
        print("PASS provider: неизвестный провайдер -> ошибка")
    # openai-compatible (v2.39): DeepSeek/local через base_url; ключ из env, без — честная ошибка
    _b = _os.environ.pop("OPENAI_COMPATIBLE_BASE_URL", None)
    try:
        make_provider("openai-compatible", "deepseek-chat")
        ok = False; print("FAIL openai-compatible без BASE_URL должен падать")
    except SystemExit:
        print("PASS openai-compatible без BASE_URL -> ошибка")
    _os.environ["OPENAI_COMPATIBLE_BASE_URL"] = "https://api.deepseek.com/chat/completions"
    _kb = _os.environ.pop("OPENAI_COMPATIBLE_API_KEY", None)
    try:
        try:
            make_provider("openai-compatible")   # без model
            ok = False; print("FAIL openai-compatible без model должен падать")
        except SystemExit:
            print("PASS openai-compatible без --model -> ошибка")
        try:
            make_provider("openai-compatible", "deepseek-chat")("тест")   # base есть, ключа нет
            ok = False; print("FAIL openai-compatible без ключа должен падать")
        except SystemExit:
            print("PASS openai-compatible c BASE_URL, но без ключа -> честная ошибка")
    finally:
        if _b is None:
            _os.environ.pop("OPENAI_COMPATIBLE_BASE_URL", None)
        else:
            _os.environ["OPENAI_COMPATIBLE_BASE_URL"] = _b
    # v3.9.0 First-class Claude Code Adapter: claude-cli провайдер, runner заменяет subprocess.run
    # (не весь вызов) — production-path (time.monotonic, json parse, _record_call, retries) проходит полностью.
    # v3.21.1 (Runtime Trust Recovery): тест ловит NameError('time') — runner возвращает объект с
    # returncode/stdout/stderr, а не текст напрямую. Если import time сломан, тест упадёт на time.monotonic().
    import json as _test_json
    class _FakeResult:
        def __init__(self, stdout="", returncode=0, stderr=""):
            self.stdout = stdout
            self.returncode = returncode
            self.stderr = stderr
    _seen = {}
    _call_stats_before = len(_CALL_STATS)
    def _fake_runner(cmd):
        _seen["cmd"] = cmd
        return _FakeResult(stdout=_test_json.dumps({
            "result": "PROPOSED-ACTIONS-JSON",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "model": "claude-opus",
            "total_cost_usd": 0.01
        }))
    _prov = make_claude_cli_provider(model="claude-opus", runner=_fake_runner)
    _out = _prov("сгенерируй tool-loop действия")
    if _out == "PROPOSED-ACTIONS-JSON":
        print("PASS claude-cli: возвращает текст-предложение модели (кит исполняет)")
    else:
        ok = False; print("FAIL claude-cli: не вернул текст провайдера")
    # v3.21.1 регрессия: _record_call вызван (usage измеряется), time.monotonic() не упал
    _call_stats_after = len(_CALL_STATS)
    if _call_stats_after > _call_stats_before:
        _last_call = _CALL_STATS[-1]
        _has_tokens = _last_call.get("input_tokens") == 100 and _last_call.get("output_tokens") == 50
        _has_cost = _last_call.get("cost_usd_est") is not None
        _has_latency = _last_call.get("latency") is not None and _last_call["latency"] >= 0
        if _has_tokens and _has_latency:
            print("PASS claude-cli: production-path пройден (time.monotonic + _record_call + usage)")
        else:
            ok = False; print(f"FAIL claude-cli: production-path неполный — tokens={_has_tokens}, latency={_has_latency}, call={_last_call}")
    else:
        ok = False; print("FAIL claude-cli: _record_call не вызван (production-path не пройден)")
    _c = _seen.get("cmd") or []
    _allowed = []
    if "--allowedTools" in _c:
        _i = _c.index("--allowedTools") + 1
        while _i < len(_c) and not _c[_i].startswith("--"):
            _allowed.append(_c[_i]); _i += 1
    _read_only = bool(_allowed) and set(_allowed) <= {"Read", "Grep", "Glob"} and "Read" in _allowed
    _no_mutate = not any(t in _c for t in ("Write", "Edit", "Bash"))
    if "-p" in _c and _read_only and _no_mutate:
        print("PASS claude-cli: read-only (Read/Grep/Glob) -> Claude читает, но НЕ мутирует/не исполняет")
    else:
        ok = False; print("FAIL claude-cli: инструменты не ограничены read-only (риск прямого действия Claude в обход кита)")
    if callable(make_provider("claude-cli")):
        print("PASS claude-cli: зарегистрирован как first-class провайдер")
    else:
        ok = False; print("FAIL claude-cli: не резолвится через make_provider")
    # v3.21.1 регрессия: retry-loop + sleep проходят без NameError
    _retry_calls = []
    def _flaky_runner(cmd):
        _retry_calls.append(1)
        if len(_retry_calls) < 3:
            return _FakeResult(returncode=1, stderr="transient error")
        return _FakeResult(stdout=_test_json.dumps({"result": "ok", "usage": {}}))
    _retry_prov = make_claude_cli_provider(runner=_flaky_runner)
    _retry_out = _retry_prov("тест retry")
    if _retry_out == "ok" and len(_retry_calls) == 3:
        print("PASS claude-cli: retry-loop + sleep работают (3 попытки, time.monotonic не упал)")
    else:
        ok = False; print(f"FAIL claude-cli: retry не сработал — calls={len(_retry_calls)}, out={_retry_out}")
        if _kb is not None:
            _os.environ["OPENAI_COMPATIBLE_API_KEY"] = _kb

    # v2.74 (finding живого прогона): _http_post_json ретраит ТРАНЗИЕНТНЫЕ сбои (SSL-timeout
    # оборвал задачу). Монкипатчим urlopen + sleep: 2 сетевых сбоя -> успех; 4xx не ретраится.
    import urllib.request as _ur
    import urllib.error as _ue
    import time as _time
    _real_open, _real_sleep = _ur.urlopen, _time.sleep
    _time.sleep = lambda *_a, **_k: None                     # без реальных пауз в тесте

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok": true}'

    try:
        calls = {"n": 0}
        def flaky(req, timeout=0):
            calls["n"] += 1
            if calls["n"] < 3:
                raise _ue.URLError("ssl handshake timed out")
            return _Resp()
        _ur.urlopen = flaky
        r = _http_post_json("http://x", {}, {}, retries=3)
        expect_ok = r.get("ok") is True and calls["n"] == 3
        print(("PASS" if expect_ok else "FAIL")
              + " http-retry: 2 транзиентных сбоя -> успех на 3-й попытке")
        ok = ok and expect_ok

        calls2 = {"n": 0}
        def not_found(req, timeout=0):
            calls2["n"] += 1
            raise _ue.HTTPError("http://x", 404, "not found", {}, None)
        _ur.urlopen = not_found
        try:
            _http_post_json("http://x", {}, {}, retries=3)
            ok = False; print("FAIL http-retry: 404 не должен возвращать успех")
        except _ue.HTTPError:
            good = calls2["n"] == 1                          # 4xx не ретраится
            print(("PASS" if good else "FAIL") + " http-retry: 4xx (404) не ретраится (1 попытка)")
            ok = ok and good
    finally:
        _ur.urlopen = _real_open
        _time.sleep = _real_sleep

    # execution budget (v2.38): max_model_calls останавливает до завершения стадий
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        st, rd = run_workflow("QUICK", "любая задача", root, verbose=False,
                              budget={"max_model_calls": 1})
        if st["status"] == "blocked" and st.get("budget_exceeded") and st["budget"]["model_calls"] == 1 \
                and len(st["completed_checks"]) == 1:
            print("PASS budget: max_model_calls=1 -> 1 стадия, blocked с budget_exceeded")
        else:
            ok = False; print(f"FAIL budget не сработал: {st.get('status')}, "
                              f"calls={st.get('budget',{}).get('model_calls')}")

    assert ok, "перенесённый селфтест orchestrator: см. строки FAIL в выводе"
