"""Проектные lifecycle hooks; внутренний вход из доставленного team_hook.py."""
from __future__ import annotations

import argparse
import json
import sys

import yaml

from ai_ops_kit.lifecycle import project_session as sessions


def hook(runtime, payload):
    event = payload.get("hook_event_name")
    if event == "Stop":
        try:
            root = sessions.project_root(payload["cwd"])
            if not sessions.required(root):
                return {}
            verdict = sessions.verify(root, runtime, payload["session_id"])
            if verdict["accepted"]:
                return {}
            reason = "AI Ops не подтвердил выполнение: " + verdict["reason"]
        except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as exc:
            reason = "AI Ops не подтвердил выполнение: " + str(exc)
        # В Codex exit 2 / decision:block создают новый модельный ход. Ошибка
        # проверки не должна превращаться в платный цикл или новую постановку.
        return {"continue": False, "stopReason": reason, "systemMessage": reason}
    root = sessions.project_root(payload["cwd"])
    session = payload["session_id"]
    if not sessions.required(root):
        return {}
    if event == "UserPromptSubmit":
        task = sessions.begin(root, runtime, session, payload["prompt"], payload.get("turn_id"))
        if task["status"] == "blocked":
            return {"decision": "block", "reason": task["blocker"] + " " + task["next_step"]}
        context = (f"AI Ops сохранил задачу {task['request_id']}; runtime={runtime}; session_id={session}. "
                   f"Прочитай .ai/managed/{sessions.POLICY} и исполни штатный процесс до завершения. "
                   "Исходный запрос уже сохранён; не проси пользователя запускать CLI.")
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}
    if event == "SessionStart":
        current = sessions.binding(root)
        context = f"AI Ops: проект {current['root']}, ветка {current['branch']}, версия {current['version']}. "
        try:
            task = sessions.load(root, runtime, session)
        except FileNotFoundError:
            task = None
        if task:
            context += (f"Сохранённая задача {task['request_id']} ({task['status']}). "
                        "Прочитай её из .ai/runtime/sessions/; перед продолжением проверь текущую привязку. ")
        context += f"Общий канон: .ai/managed/{sessions.POLICY}."
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}
    raise ValueError(f"неподдерживаемое событие: {event}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="hook", choices=("hook", "run", "verify"))
    parser.add_argument("--runtime", required=True, choices=tuple(sessions.RUNTIMES))
    parser.add_argument("--session")
    parser.add_argument("--signals")
    args = parser.parse_args(argv)
    try:
        if args.action == "hook":
            raw = sys.stdin.buffer.read(262145)
            if len(raw) > 262144:
                raise ValueError("payload hook превышает 256 KiB")
            result = hook(args.runtime, json.loads(raw))
        else:
            from pathlib import Path
            root = sessions.project_root(Path.cwd())
            if args.action == "verify":
                result = sessions.verify(root, args.runtime, args.session)
            else:
                signals = json.loads(args.signals or "{}")
                if not isinstance(signals, dict):
                    raise ValueError("signals должен быть JSON object")
                from ai_ops_kit.engine import pipeline_helpers
                missing = pipeline_helpers.missing_intake_signals(signals)
                if missing:
                    raise ValueError("; ".join(pipeline_helpers.intake_signals_hint(missing))
                                     + ". Запуск не начат; уточни signals той же сохранённой задачи.")
                result = sessions.execute(root, args.runtime, args.session, signals)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result.get("accepted") or result.get("status") == "accepted" else 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError) as exc:
        if args.action == "hook":
            reason = f"AI Ops: {exc}. Сохранённая задача не считается принятой."
            print(json.dumps({"continue": False, "stopReason": reason, "systemMessage": reason},
                             ensure_ascii=False))
            return 0
        print(f"AI Ops: {exc}. Сохранённая задача не считается принятой.", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
