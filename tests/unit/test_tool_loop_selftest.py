"""Селфтест tool_loop, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from tool_loop import (  # noqa: F401 — имена, которые использует тело
    Path,
    parse_action,
    run_loop,
    run_review,
    tool_broker,
)


@pytest.mark.slow
def test_tool_loop_selftest():
    import tempfile
    import subprocess
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # parse
    expect("parse: JSON в тексте", parse_action('бла {"op":"read","path":"a"} бла')["op"] == "read")
    expect("parse: битый JSON -> error", parse_action("нет json").get("error") == "no-json")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "-C", td, "init", "-q"])
        subprocess.run(["git", "-C", td, "config", "user.email", "t@t"])
        subprocess.run(["git", "-C", td, "config", "user.name", "t"])
        (root / "src").mkdir()
        (root / "f").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"]); subprocess.run(["git", "-C", td, "commit", "-q", "-m", "i"])

        # сценарный mock-предложитель: пишет в scope, пробует вне scope, shell, done
        script = [
            {"op": "write", "path": "src/a.ts", "content": "hello"},   # разрешено
            {"op": "write", "path": "config/x.yaml", "content": "y"},  # вне scope -> denied
            {"op": "shell", "command": "echo ok"},                     # execution
            {"done": True, "summary": "готово"},
        ]
        it = iter(script)
        proposer = lambda ctx: next(it)
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        rep = run_loop(proposer, root, pol, budget={"max_model_calls": 10})

        expect("остановка по done", rep["stopped"] == "done")
        expect("write в scope исполнен", (root / "src" / "a.ts").exists()
               and any(e["op"] == "write" and e["ok"] for e in rep["executed"]))
        expect("write вне scope запрещён и НЕ создан",
               not (root / "config" / "x.yaml").exists()
               and any(e["op"] == "write" for e in rep["denied"]))
        expect("shell исполнен (evidence)", any(e["op"] == "shell" and e["ok"] for e in rep["executed"]))
        expect("model_calls посчитаны", rep["model_calls"] == 4)

        # budget обрывает петлю
        it2 = iter([{"op": "read", "path": "f"}] * 10)
        rep2 = run_loop(lambda c: next(it2), root, pol, budget={"max_model_calls": 2})
        expect("budget обрывает петлю", rep2["stopped"].startswith("budget") and rep2["model_calls"] == 2)

        # max_steps-предохранитель
        it3 = iter([{"op": "read", "path": "f"}] * 100)
        rep3 = run_loop(lambda c: next(it3), root, pol, max_steps=3)
        expect("max_steps-предохранитель", rep3["stopped"] == "max_steps" and rep3["steps"] == 3)

        # finding аудита: модель ДОЛЖНА видеть содержимое прочитанного файла в контексте
        (root / "readme.txt").write_text("SENTINEL_CONTENT_42", encoding="utf-8")
        seen = {}

        def prop_read(ctx):
            seen["ctx"] = ctx
            if not seen.get("did_read"):
                seen["did_read"] = True
                return {"op": "read", "path": "readme.txt"}
            return {"done": True, "summary": "прочитал"}

        run_loop(prop_read, root, pol, budget={"max_model_calls": 5})
        expect("модель ВИДИТ содержимое прочитанного файла в контексте",
               "SENTINEL_CONTENT_42" in seen.get("ctx", ""))

        # finding живого прогона: битый JSON НЕ убивает прогон — до N корректирующих переспросов.
        # Модель «оступается» дважды (bad-json), потом отдаёт валидный write + done.
        seq = iter([
            {"error": "bad-json"}, {"error": "bad-json"},
            {"op": "write", "path": "src/rec.ts", "content": "ok"}, {"done": True},
        ])
        rep_rec = run_loop(lambda c: next(seq), root, pol, budget={"max_model_calls": 10})
        expect("bad-json: петля восстановилась после переспросов -> done",
               rep_rec["stopped"] == "done" and (root / "src" / "rec.ts").exists())

        # корректирующая подсказка попала в контекст переспроса
        cap = {}
        seq2 = iter([{"error": "bad-json"}, {"done": True}])
        def prop_corr(ctx):
            cap["ctx"] = ctx
            return next(seq2)
        run_loop(prop_corr, root, pol, budget={"max_model_calls": 5})
        expect("bad-json: модель получает корректирующую подсказку про JSON",
               "ОШИБКА РАЗБОРА" in cap.get("ctx", ""))

        # много битых подряд -> честная остановка bad-proposal (не вечный цикл)
        rep_bad = run_loop(lambda c: {"error": "bad-json"}, root, pol,
                           budget={"max_model_calls": 10}, max_bad_proposals=3)
        expect("bad-json: N подряд -> честная остановка bad-proposal",
               rep_bad["stopped"].startswith("bad-proposal"))

        # анти-флейл (finding живого прогона): чтение по кругу -> read-cap отклоняет лишние reads
        rep_flail = run_loop(lambda c: {"op": "read", "path": "f"}, root, pol,
                             budget={"max_model_calls": 30}, max_steps=12, max_consecutive_reads=5)
        capped = [t for t in rep_flail["transcript"] if not t.get("allowed") and "read-cap" in (t.get("reason") or "")]
        expect("read-cap: чтение по кругу отклоняется после лимита", len(capped) > 0)

        # но НОРМАЛЬНЫЙ поток (2 чтения -> write -> done) не задет read-cap'ом
        norm = iter([{"op": "read", "path": "f"}, {"op": "read", "path": "f"},
                     {"op": "write", "path": "src/z.ts", "content": "z"}, {"done": True}])
        rep_norm = run_loop(lambda c: next(norm), root, pol, budget={"max_model_calls": 10},
                            max_consecutive_reads=5)
        expect("read-cap: нормальный поток (2 read -> write -> done) не задет",
               rep_norm["stopped"] == "done" and (root / "src" / "z.ts").exists())

        # v2.83: независимый ревьюер (writer ≠ judge) под READ-ONLY политикой
        ro = tool_broker.Policy(level="read-only")
        # (a) прямой вердикт pass
        rev_pass = run_review(lambda c: {"kind": "reviewer-result", "gate": "code_review",
                                         "status": "pass", "checks": [{"id": "logic", "status": "pass"}]},
                              root, ro, "code_review", budget={"max_model_calls": 5})
        expect("reviewer: терминальный вердикт pass возвращён",
               rev_pass["result"] and rev_pass["result"]["status"] == "pass"
               and rev_pass["result"]["gate"] == "code_review")
        # (b) ревьюер физически НЕ может писать (read-only): попытка write отклонена, затем вердикт fail
        rev_seq = iter([{"op": "write", "path": "src/evil.ts", "content": "x"},
                        {"kind": "reviewer-result", "gate": "code_review", "status": "fail",
                         "checks": [{"id": "logic", "status": "fail"}], "blockers": ["баг в ветке"]}])
        rev_wr = run_review(lambda c: next(rev_seq), root, ro, "code_review", budget={"max_model_calls": 5})
        expect("reviewer: write ОТКЛОНЁН (read-only судья, не автор) + файл не создан",
               rev_wr["denied"] and not (root / "src" / "evil.ts").exists())
        expect("reviewer: вердикт fail с blockers", rev_wr["result"]["status"] == "fail"
               and rev_wr["result"]["blockers"])
        # (c) ревьюер читает файл -> содержимое в контексте вердикта
        (root / "reviewme.txt").write_text("REVIEW_SENTINEL_7", encoding="utf-8")
        cap_r = {}
        rseq = iter([{"op": "read", "path": "reviewme.txt"},
                     {"kind": "reviewer-result", "gate": "code_review", "status": "pass",
                      "checks": [{"id": "x", "status": "pass"}]}])
        def rprop(ctx):
            cap_r["ctx"] = ctx
            return next(rseq_it)
        rseq_it = rseq
        run_review(rprop, root, ro, "code_review", budget={"max_model_calls": 5})
        expect("reviewer: ВИДИТ содержимое прочитанного файла в контексте",
               "REVIEW_SENTINEL_7" in cap_r.get("ctx", ""))
        # (d) не вынес вердикт за лимит -> result=None (гейт останется неподтверждённым)
        rev_none = run_review(lambda c: {"op": "read", "path": "f"}, root, ro, "code_review",
                              budget={"max_model_calls": 20}, max_reads=3)
        expect("reviewer: без вердикта за лимит -> result=None (честный не-pass)",
               rev_none["result"] is None)
        # (e) rc10: жадная reasoning-модель читает до лимита, затем на ФОРС-ХОДЕ заключает вердикт
        #     (раньше молча уходила в no-verdict). Форс-ход даёт заключить по прочитанному, НЕ фабрикуя.
        def greedy_then_verdict(c):
            if "ЛИМИТ ЧТЕНИЙ ИСЧЕРПАН" in c:
                return {"kind": "reviewer-result", "gate": "code_review", "status": "pass",
                        "checks": [{"id": "ok", "status": "pass"}]}
            return {"op": "read", "path": "f"}
        rev_fv = run_review(greedy_then_verdict, root, ro, "code_review",
                            budget={"max_model_calls": 20}, max_reads=3)
        expect("reviewer rc10: форс-ход после исчерпания чтений -> вердикт вынесен (не тихий no-verdict)",
               rev_fv["result"] is not None and rev_fv["stopped"] == "verdict"
               and len(rev_fv["reads"]) == 3)

    assert ok, "перенесённый селфтест tool_loop: см. строки FAIL в выводе"
