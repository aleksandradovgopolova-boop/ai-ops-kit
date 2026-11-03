"""Проектные lifecycle hooks; внутренний вход из доставленного team_hook.py."""
from __future__ import annotations

import argparse
import json
import sys

import yaml

from ai_ops_kit.lifecycle import project_session as sessions


def current_session(root, runtime, session, task, signals):
    """Штатный controller готовит работу для уже открытого tool loop, без модели."""
    from pathlib import Path
    import subprocess
    from ai_ops_kit.gates import gate_executor
    signals = dict(signals)
    calibrated = gate_executor.risk_calibrated_config(root)
    if calibrated is not None and "risk_calibrated_enforcement" not in (signals.get("gates") or {}):
        signals["gates"] = dict(signals.get("gates") or {}, risk_calibrated_enforcement=calibrated)
    fid = "session-" + task["request_id"]
    directory = sessions.session_dir(root, runtime, session)
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / "engine/ai_ops_run.py"),
               "run", task["prompt"], str(root), "--engine", "controller", "--runtime", runtime,
               "--session", session, "--feature", fid, "--signals", json.dumps(signals), "--json"]
    task = sessions.claim_execution(root, runtime, session, task,
                {"mode": "current-session", "command": command, "signals": signals},
                "Открытый агент исполняет стадии RunPlan. План не подтверждает приёмку; "
                "нужны артефакты, обязательные gates, независимое review и применимый CI.")
    path = directory / (task["request_id"] + ".json")
    try:
        result = sessions.run_process(command, root, directory, timeout=30,
                                      progress=lambda message: print(message, file=sys.stderr, flush=True))
        report_path = sessions.within(root, f"features/{fid}/run-report.json")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if (result.returncode != 0 or report.get("kind") != "run-report" or report.get("status") != "planned"
                or report.get("execution") != "planned" or report.get("workitem_id") != fid
                or report.get("runtime") != runtime or report.get("lifecycle_errors")):
            raise ValueError("controller не подтвердил подготовку: " + str(report.get("error") or result.stderr)[-4096:])
        from ai_ops_kit.cli.project_session_completion import record_prepared
        record_prepared(root, task)
    except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        task.update(status="blocked", blocker=f"controller: {type(exc).__name__}: {exc}",
                    next_step="Проверь сохранённые логи и артефакты. Claim сохранён; повтор автоматически не запускается.")
    sessions.write(path, task)
    return task


def resume_current(root, runtime, session, task):
    """Чтение handoff после compact: изменения продукта ожидаемы, смена контекста — нет."""
    current = sessions.binding(root, "session-" + task["request_id"])
    if any(current.get(key) != task["binding"].get(key) for key in
           ("root", "branch", "version", "managed_sha256", "config_sha256")):
        raise ValueError("контекст проектной сессии изменился; проверь сохранённую работу")
    for relative, checksum in task["execution"]["files"].items():
        if sessions.digest(sessions.within(root, relative).read_bytes()) != checksum:
            raise ValueError("подготовленный артефакт изменён: " + relative)
    return task


def native_provider_hook(directory):
    """Машинный вывод отдельного native hook: библиотека providers возвращает данные."""
    from ai_ops_kit.providers import codex_native_hook
    try:
        result = codex_native_hook.main(directory)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result = codex_native_hook.denied("Native hook input/state rejected: " + type(exc).__name__)
    print(json.dumps(result, ensure_ascii=False))


def prepare(root, runtime, session, task, signals):
    """Штатная спецификация ДО claim/модели; текущий runtime заполняет её из запроса."""
    from ai_ops_kit.engine import run_plan
    from ai_ops_kit.gates import preflight, spec_levels
    fid = "session-" + task["request_id"]
    plan = run_plan.build_plan(dict(signals, task_text=task["prompt"]), workitem_id=fid)
    classified = dict(signals, task_type=plan["base_workflow"])
    relative = f"features/{fid}/spec.yaml"
    path = sessions.within(root, relative)
    if path.resolve() != root.resolve() / relative:
        raise ValueError("запись спецификации через symlink не разрешена")
    if not preflight.requires_spec(classified) and not path.exists():
        return None
    errors, coverage = [], {}
    try:
        # create_spec дописывает разделы/сигналы. Чужой документ нельзя менять
        # даже если последующая проверка всё равно отказала бы в запуске.
        if path.exists():
            existing = yaml.safe_load(path.read_text(encoding="utf-8"))
            if (not isinstance(existing, dict) or existing.get("kind") != "spec"
                    or existing.get("workitem_id") != fid or not isinstance(existing.get("sections"), dict)):
                raise ValueError("спецификация не принадлежит сохранённой задаче или имеет неверную форму")
        _, _, created = spec_levels.create_spec(root, fid, classified)
        if created["error"]:
            errors.append(created["error"])
        coverage = spec_levels.assess_from_artifacts(classified, root, fid)
        errors += coverage["form_errors"]
        errors += ["не заполнено: " + x for x in coverage["blocking_missing"]]
        errors += ["нужно решение: " + x for x in coverage["needs_human"]]
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or doc.get("kind") != "spec" or doc.get("workitem_id") != fid:
            errors.append("спецификация не принадлежит сохранённой задаче или имеет неверную форму")
        else:
            for section in coverage["sections"]:
                entry = (doc.get("sections") or {}).get(section["id"], {})
                content = entry.get("content")
                if section["status"] == "complete" and (not isinstance(content, str) or not content.strip()):
                    errors.append("нет содержания: " + section["id"])
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
        errors.append(str(exc))
    preparation = {"spec": relative, "signals": signals, "workflow": plan["base_workflow"],
                   "coverage": coverage, "ready": not errors}
    saved = sessions.save_preparation(root, runtime, session, task["request_id"], preparation,
                                     "; ".join(errors) if errors else None)
    return saved if errors else None


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
            if task.get("preparation"):
                context += (f"Спецификация: {task['preparation']['spec']}. "
                            "Сигналы сохранены: project_session run можно продолжить без --signals. "
                            + (task.get("next_step") or ""))
            if task.get("provider_preparation"):
                context += ("Готовность native provider ещё не подтверждена; signals сохранены. "
                            + (task.get("blocker") or "") + " " + (task.get("next_step") or ""))
        context += f"Общий канон: .ai/managed/{sessions.POLICY}."
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}
    raise ValueError(f"неподдерживаемое событие: {event}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="hook", choices=("hook", "run", "verify", "finalize", "reconcile"))
    parser.add_argument("--runtime", required=True, choices=tuple(sessions.RUNTIMES))
    parser.add_argument("--session")
    parser.add_argument("--signals")
    parser.add_argument("--autonomous", action="store_true", help="явно запустить отдельного провайдера")
    parser.add_argument("--review-digests", help="JSON digests, полученные из независимого review-канала")
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
                # Подготовка не должна переписать spec, пока другой вызов уже исполняет её.
                lock = sessions.session_dir(root, args.runtime, args.session) / "preparation"
                with sessions.session_lock(lock):
                    existing = sessions.load(root, args.runtime, args.session)
                    if args.action in ("finalize", "reconcile"):
                        from ai_ops_kit.cli import project_session_completion as completion
                        digests = (json.loads(args.review_digests) if args.review_digests is not None else
                                   (existing.get("verification") or {}).get("review_digests", {}))
                        result = (completion.finalize(root, args.runtime, args.session, digests)
                                  if args.action == "finalize" else completion.reconcile(root, args.runtime, args.session))
                        print(json.dumps(result, ensure_ascii=False))
                        return 0 if result.get("status") == "accepted" else 1
                    if (not args.autonomous and existing.get("status") in ("running", "blocked")
                            and existing.get("execution", {}).get("mode") == "current-session"
                            and existing["execution"].get("prepared")):
                        result = resume_current(root, args.runtime, args.session, existing)
                        print(json.dumps(result, ensure_ascii=False))
                        return 1  # handoff всё ещё не является accepted
                    task = sessions.pending(root, args.runtime, args.session)
                    signals = (json.loads(args.signals) if args.signals is not None else
                               (task.get("preparation") or {}).get("signals") or
                               (task.get("provider_preparation") or {}).get("signals", {}))
                    if not isinstance(signals, dict):
                        raise ValueError("signals должен быть JSON object")
                    from ai_ops_kit.engine import pipeline_helpers
                    missing = pipeline_helpers.missing_intake_signals(signals)
                    if missing:
                        raise ValueError("; ".join(pipeline_helpers.intake_signals_hint(missing))
                                         + ". Запуск не начат; уточни signals той же сохранённой задачи.")
                    result = prepare(root, args.runtime, args.session, task, signals)
                    if result is None:
                        task = sessions.pending(root, args.runtime, args.session)
                        if task["request_id"] != existing["request_id"]:
                            raise ValueError("активная постановка сменилась после подготовки")
                        result = (sessions.execute(root, args.runtime, args.session, signals, request=task["request_id"],
                                                   progress=lambda message: print(message, file=sys.stderr, flush=True))
                                  if args.autonomous else current_session(root, args.runtime, args.session, task, signals))
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
