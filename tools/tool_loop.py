#!/usr/bin/env python3
"""Tool-calling loop (v2.42, Execution Engine Фаза 2, срез 3 — механика петли).

Замыкает «task → controlled execution»: модель ПРЕДЛАГАЕТ действие (JSON), Policy решает
(tool_broker), Broker исполняет и собирает Evidence, результат идёт обратно в контекст —
и так до «done» / потолка budget / max_steps. Модель не решает, что ей можно; запрещённое
не исполняется, а возвращается модели как DENIED (чтобы скорректировалась).

Механика детерминирована и тестируется offline mock-предложителем. Живой предложитель —
это provider из orchestrator (anthropic/openai/openai-compatible) в JSON-режиме; его
качество проверяется живым прогоном (как Шаг A для текста), но ЛОГИКА петли — здесь и
проверяема без ключа.

Формат предложения модели (одно на шаг):
  {"op":"read|write|shell|git", "path":..., "content":..., "command":...}
  {"done": true, "summary": "..."}

Использование (программно): run_loop(proposer, root, policy, budget) -> отчёт петли.
  tool_loop.py --selftest
"""

import json
import re
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
for _p in (PKG / "tools",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import tool_broker            # noqa: E402
import budget as _budget_mod  # noqa: E402


def parse_action(text):
    """Достать JSON-предложение из ответа модели (терпимо к обрамлению текстом)."""
    if isinstance(text, dict):
        return text
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {"error": "no-json"}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"error": "bad-json"}


def make_model_proposer(provider):
    """Обернуть text-provider (orchestrator) в предложитель действий через JSON-протокол.
    Живой путь: provider = make_provider('openai-compatible', 'deepseek-chat')."""
    def propose(context):
        prompt = (
            "Ты исполнитель задачи в контролируемом рантайме. На каждом шаге верни РОВНО ОДНО "
            "действие в JSON и больше ничего:\n"
            '  {"op":"write","path":"...","content":"..."}  — создать/изменить файл\n'
            '  {"op":"shell","command":"..."}                — команда (сборка/тест/проверка)\n'
            '  {"op":"read","path":"..."}                    — прочитать файл\n'
            '  {"done":true,"summary":"..."}                 — верни ЭТО, когда задача выполнена\n'
            "Правила: НЕ повторяй уже успешно выполненный шаг (см. журнал ниже — там строки "
            "'-> OK'). Как только нужные файлы записаны и проверка (shell) прошла — сразу верни "
            "done, не пиши файл повторно. Только JSON, без пояснений.\n\n"
            "=== ЗАДАЧА И ЖУРНАЛ УЖЕ ВЫПОЛНЕННЫХ ШАГОВ ===\n" + context)
        return parse_action(provider(prompt))
    return propose


def run_loop(proposer, root, policy, budget=None, max_steps=20, base_context="",
             max_bad_proposals=3):
    """Гонять петлю до done / budget / max_steps. proposer(context)->action|{'done':true}.

    finding живого прогона: живая модель (DeepSeek) недетерминирована и иногда возвращает
    невалидный JSON. Раньше ОДНА кривая реплика обрывала весь прогон. Теперь — до
    max_bad_proposals ПОДРЯД корректирующих переспросов (модели показывают её ошибку и
    просят чистый JSON); счётчик сбрасывается на любом валидном действии.
    """
    root = Path(root)
    bud = budget if isinstance(budget, _budget_mod.Budget) else _budget_mod.Budget.from_dict(budget)
    evidence, transcript = [], []
    context = base_context
    stopped = "max_steps"
    bad_streak = 0
    for step in range(max_steps):
        try:
            bud.charge_call()                       # каждый запрос к модели — под потолком
        except _budget_mod.BudgetExceeded as e:
            stopped = f"budget: {e}"; break
        action = proposer(context)
        if not isinstance(action, dict) or action.get("error"):
            bad_streak += 1
            err = action.get("error") if isinstance(action, dict) else action
            if bad_streak >= max_bad_proposals:
                stopped = f"bad-proposal: {err}"; break
            # корректирующий переспрос: показать модели её ошибку и потребовать чистый JSON
            context += (f"\n[шаг {step}] ОШИБКА РАЗБОРА ({err}): твой ответ не распарсился как "
                        f"JSON. Верни РОВНО ОДИН JSON-объект действия и НИЧЕГО больше — без "
                        f"markdown-обрамления, без пояснений, без текста до/после.")
            continue
        bad_streak = 0
        if action.get("done"):
            stopped = "done"
            transcript.append({"step": step, "done": True, "summary": action.get("summary", "")})
            break
        ev = tool_broker.execute(action, root, policy)   # Policy решает + исполнение + Evidence
        evidence.append(ev)
        transcript.append({"step": step, "op": ev.get("op"), "allowed": ev["allowed"],
                           "ok": ev.get("ok"), "reason": ev["reason"]})
        # результат обратно в контекст (в т.ч. DENIED — чтобы модель скорректировалась).
        # ВАЖНО (finding аудита): модель должна ВИДЕТЬ содержимое/вывод, иначе read/shell слепы —
        # это не агентная петля. Передаём output_tail для read (содержимое) и shell (stdout/stderr).
        if not ev["allowed"]:
            verdict = "DENIED: " + ev["reason"]
        elif ev.get("ok"):
            verdict = "OK"
            tail = ev.get("output_tail")
            if ev.get("op") == "read":
                verdict += f"\n--- содержимое {ev.get('target')} ---\n{tail}\n--- конец ---"
            elif ev.get("op") in ("shell", "git") and tail:
                verdict += f" (exit={ev.get('exit_code')})\n--- вывод ---\n{tail}\n--- конец ---"
        else:
            verdict = f"FAILED (exit={ev.get('exit_code')}): {ev.get('output_tail') or ev.get('error', '')}"
        context += f"\n[шаг {step}] {ev.get('op')} {ev.get('target')} -> {verdict}"
    return {"schema_version": 1, "kind": "tool-loop-report",
            "stopped": stopped, "steps": len(transcript),
            "model_calls": bud.model_calls,
            "executed": [e for e in evidence if e["allowed"]],
            "denied": [e for e in evidence if not e["allowed"]],
            "evidence": evidence, "transcript": transcript}


def selftest():
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

    print("tool_loop selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
