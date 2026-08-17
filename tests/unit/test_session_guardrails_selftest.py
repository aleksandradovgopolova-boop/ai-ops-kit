"""Селфтест session_guardrails, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from session_guardrails import (  # noqa: F401 — имена, которые использует тело
    SESSION_ECONOMY_DEFAULTS,
    check,
    classify_context,
    completion_ritual,
    recommend,
    render_block,
)


@pytest.mark.slow
def test_session_guardrails_selftest(tmp_path):
    """ЧТО ИЗМЕНИЛОСЬ 17.08.2026. Проверка «ритуал complete при всех галочках» стояла на
    `repo_path="/repo"` — каталоге, которого нет, — и была зелёной, потому что `handoff_created`
    был константой True. Теперь пункт выводится из наличия файла, поэтому «все галочки» требуется
    СОЗДАТЬ: handoff записывается в настоящий каталог. Прежний вид проверки утверждал ровно ту
    неправду, из-за которой `ai-ops session` на живой сессии рапортовал сохранённый handoff при
    полном его отсутствии."""
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    d = SESSION_ECONOMY_DEFAULTS
    expect("classify 100k -> normal", classify_context(100_000, d) == "normal")
    expect("classify 180k -> attention", classify_context(180_000, d) == "attention")
    expect("classify 300k -> compact_recommended", classify_context(300_000, d) == "compact_recommended")
    expect("classify 450k -> new_session_recommended", classify_context(450_000, d) == "new_session_recommended")
    expect("classify None -> unknown (честно)", classify_context(None, d) == "unknown")

    snap = lambda ctx, wid="WI-1": {"kind": "SessionTelemetry", "context_current": ctx,
                                    "context_status": "estimated", "workitem_id": wid,
                                    "input_tokens": 1, "output_tokens": 1, "estimated_cost": 1.0,
                                    "cost_complete": True, "turns": 5}

    r = recommend(snap(92_000), d, next_relation="continuation", task_done=False)
    expect("тот же WI, лёгкий контекст, не завершён -> continue",
           r["outcome"] == "continue" and r["command"] is None)
    r = recommend(snap(271_000), d, next_relation="same_task", task_done=False)
    expect("тот же WI, дорогой контекст, не завершён -> compact + команда",
           r["outcome"] == "compact" and "/compact" in r["command"])
    r = recommend(snap(318_000), d, next_relation="new_independent_task", task_done=True, repo_path="/x")
    expect("новая независимая задача, задача закрыта -> clear + команда",
           r["outcome"] == "clear" and "/clear" in r["command"])
    r = recommend(snap(450_000), d, next_relation="new_independent_task", task_done=True, repo_path="/x")
    expect("контекст >400k -> new_session (гигиена важнее)",
           r["outcome"] == "new_session" and "claude" in r["command"])
    r = recommend(snap(450_000), d, next_relation="continuation", task_done=False)
    expect("контекст >400k, продолжение не завершено -> compact (не new_session)",
           r["outcome"] == "compact")
    r = recommend(snap(300_000), d, next_relation="new_independent_task", task_done=True, at_safe_boundary=False)
    expect("небезопасная граница -> defer, без команды",
           r["outcome"] == "defer" and r["command"] is None)

    # «Все галочки» теперь включают РЕАЛЬНО записанный handoff — иначе пункт `handoff_created`
    # закрыться не может, и это и есть предмет охраны.
    from ai_ops_kit.engops import session_handoff as _sh
    _sh.write(tmp_path, _sh.build(tmp_path, snap(318_000), goal="селфтест"))

    rit = completion_ritual(snap(318_000), d, workitem_id="WI-1", pr="PR#48", checks="183/183",
                            next_relation="new_independent_task", next_task="Environment Discovery",
                            repo_path=str(tmp_path))
    expect("ритуал: исход clear + NextCommand", rit["session_recommendation"]["outcome"] == "clear"
           and rit["next_command"] and check(rit) == [])
    expect("ритуал complete при всех галочках", rit["complete"] is True)
    # Обратная сторона той же охраны: без файла ритуал закрытым быть НЕ может.
    rit_no = completion_ritual(snap(318_000), d, workitem_id="WI-1", pr="PR#48", checks="183/183",
                               next_relation="new_independent_task", repo_path=str(tmp_path / "нет"))
    expect("нет handoff -> ритуал не complete", rit_no["complete"] is False)
    block = render_block(rit)
    expect("блок содержит PR/стоимость/рекомендацию/команду",
           "PR#48" in block and "Рекомендация" in block and "/clear" in block)

    # неполный ритуал -> complete False + предупреждение
    rit2 = completion_ritual(snap(92_000, wid="WI-1"), d, workitem_id="WI-1", pr=None, checks=None,
                             next_relation="continuation", committed=False)
    expect("нет PR/commit/checks -> ритуал не complete", rit2["complete"] is False)

    assert ok, "перенесённый селфтест session_guardrails: см. строки FAIL в выводе"
