"""Проектные lifecycle hooks; внутренний вход из доставленного team_hook.py."""
from __future__ import annotations

import argparse
import json
import sys

import yaml

from ai_ops_kit.lifecycle import project_session as sessions
from ai_ops_kit.cli.project_session_completion import response as agent_response


@sessions.session_migration_store.guarded
def current_session(root, runtime, session, task, signals):
    """Штатный controller готовит работу для уже открытого tool loop, без модели."""
    task = revalidated_pending(root, runtime, session, task)
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
    from ai_ops_kit.cli import project_session_resume
    project_session_resume.check(root, task)
    return task


def continuation(root, runtime, session, task):
    """Разрешить только проверенную передачу текущему агенту, без запуска процесса."""
    execution = task.get("execution") or {}
    claim = sessions.session_dir(root, runtime, session) / (task["request_id"] + ".execution-claim")
    if task.get("status") == "pending" and not execution and not claim.exists() and not claim.is_symlink():
        waiting_continuation(root, runtime, session, task)
        sessions.artifact_inputs(root, "session-" + task["request_id"])
        return task
    if (execution.get("mode") != "current-session" or execution.get("prepared") is not True
            or task.get("status") not in ("running", "blocked") or claim.is_symlink()
            or not claim.is_file() or claim.read_bytes() != b""):
        raise ValueError("нет подтверждённой current-session передачи; неизвестный исход сохранён")
    import copy
    from ai_ops_kit.cli.project_session_completion import record_prepared
    checked = copy.deepcopy(task)
    record_prepared(root, checked)
    if any(execution.get("files", {}).get(path) != checksum
           for path, checksum in checked["execution"]["files"].items()):
        raise ValueError("подготовка current-session не подтверждена")
    sessions.artifact_inputs(root, "session-" + task["request_id"])
    return resume_current(root, runtime, session, task)


def waiting_continuation(root, runtime, session, task):
    """Только зафиксированный запрос данных/spec текущего агента, не fresh pending."""
    from ai_ops_kit.engine import pipeline_helpers, run_plan
    sessions.pending(root, runtime, session)
    if task.get("state_migration") and not task.get("preparation") and not task.get("intake"):
        from ai_ops_kit.lifecycle import session_migration
        return session_migration.continuation(root, task)
    intake, preparation = task.get("intake") or {}, task.get("preparation") or {}
    if intake:
        missing = pipeline_helpers.missing_intake_signals(intake.get("signals"))
        if (intake.get("mode") != "current-session" or not isinstance(intake.get("signals"), dict)
                or not missing or intake.get("missing") != missing):
            raise ValueError("ожидаемый current-session intake не подтверждён")
        return
    fid = "session-" + task["request_id"]
    path = f"features/{fid}/spec.yaml"
    if (preparation.get("mode") != "current-session" or preparation.get("ready") is not False
            or preparation.get("spec") != path or not isinstance(preparation.get("signals"), dict)):
        raise ValueError("нет подтверждённого ожидания данных текущим агентом")
    plan = run_plan.build_plan(dict(preparation["signals"], task_text=task["prompt"]), workitem_id=fid)
    spec = yaml.safe_load(sessions.within(root, path).read_text())
    if (preparation.get("workflow") != plan["base_workflow"] or not isinstance(spec, dict)
            or spec.get("kind") != "spec" or spec.get("workitem_id") != fid
            or not isinstance(spec.get("sections"), dict)):
        raise ValueError("ожидающая спецификация не принадлежит сохранённой задаче")


def intake_signals(task, raw):
    stored = ((task.get("intake") or {}).get("signals") or
              (task.get("preparation") or {}).get("signals") or
              (task.get("provider_preparation") or {}).get("signals", {}))
    provided = json.loads(raw) if raw is not None else {}
    if not isinstance(provided, dict) or not isinstance(stored, dict):
        raise ValueError("signals должен быть JSON object")
    return dict(stored, **provided)


def native_provider_hook(directory):
    """Машинный вывод отдельного native hook: библиотека providers возвращает данные."""
    from ai_ops_kit.providers import codex_native_hook
    try:
        result = codex_native_hook.main(directory)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result = codex_native_hook.denied("Native hook input/state rejected: " + type(exc).__name__)
    print(json.dumps(result, ensure_ascii=False))


@sessions.session_migration_store.guarded
def prepare(root, runtime, session, task, signals, *, autonomous=False):
    """Штатная спецификация ДО claim/модели; текущий runtime заполняет её из запроса."""
    task = revalidated_pending(root, runtime, session, task)
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
                   "mode": "autonomous" if autonomous else "current-session",
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
            from ai_ops_kit.cli import project_session_completion as completion
            # Сверить уже завершённую проверку без worker, модели и нового turn.
            # Pending/неизвестный исход не восстанавливается предположением.
            verdict = completion.stop_verdict(root, runtime, payload["session_id"])
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
        task = sessions.begin(root, runtime, session, payload["prompt"], payload.get("turn_id"),
                              continuation_validator=continuation)
        event_id = (sessions.digest(json.dumps([runtime, session, payload["turn_id"]]))[:32]
                    if payload.get("turn_id") else task.get("input_latest"))
        # Только уже сверенные/записанные bytes: никаких новых FS reads после commit.
        directory = ".ai/runtime/sessions/project-" + sessions.digest(runtime + ":" + session)[:32]
        receipt = directory + "/" + task["request_id"] + ".inputs/" + str(event_id) + ".json"
        received = receipt in task.get("input_receipts", {})
        if task["status"] == "blocked" and not received:
            return {"decision": "block", "reason": task["blocker"] + " " + task["next_step"]}
        context = (f"AI Ops сохранил задачу {task['request_id']}; runtime={runtime}; session_id={session}. "
                   f"Прочитай .ai/managed/{sessions.POLICY} и исполни штатный процесс до завершения. "
                   "Исходный запрос уже сохранён; не проси пользователя запускать CLI.")
        if received and task.get("status") != "accepted":
            context += (f" Новый пользовательский ввод сохранён в {receipt}. "
                        "Прочитай его и продолжи ту же задачу через project_session run. "
                        "Исходная постановка и RunPlan сохранены; прежнее review нужно проверить заново. "
                        "Текст пользователя не является машинным approval или приёмкой.")
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


def revalidated_pending(root, runtime, session, task):
    current = sessions.pending(root, runtime, session)
    if any(current.get(key) != task.get(key) for key in ("request_id", "binding", "prompt")):
        raise ValueError("постановка/binding изменена после чтения; перечитай сохранённое состояние")
    return current


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "migrate":
        from ai_ops_kit.cli import project_session_migrate
        return project_session_migrate.main(argv[1:])
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
            with sessions.hook_read_budget():
                with sessions.reading():
                    raw = sys.stdin.buffer.read(262145)
                    if len(raw) > 262144:
                        raise ValueError("payload hook превышает 256 KiB")
                    payload = json.loads(raw)
                result = hook(args.runtime, payload)
        else:
            from pathlib import Path
            root = sessions.project_root(Path.cwd())
            if args.action == "verify":
                result = sessions.verify(root, args.runtime, args.session)
            else:
                # Подготовка не должна переписать spec, пока другой вызов уже исполняет её.
                lock = sessions.session_dir(root, args.runtime, args.session) / "preparation"
                with sessions.session_migration_store.barrier(root), sessions.session_lock(lock):
                    existing = sessions.load(root, args.runtime, args.session)
                    if args.action in ("finalize", "reconcile"):
                        from ai_ops_kit.cli import project_session_completion as completion
                        digests = (json.loads(args.review_digests) if args.review_digests is not None else
                                   (existing.get("verification") or {}).get("review_digests", {}))
                        result = (completion.finalize(root, args.runtime, args.session, digests)
                                  if args.action == "finalize" else completion.reconcile(root, args.runtime, args.session))
                        print(json.dumps(agent_response(root, result), ensure_ascii=False))
                        return 0 if result.get("status") == "accepted" else 1
                    if (not args.autonomous and existing.get("status") in ("running", "blocked")
                            and existing.get("execution", {}).get("mode") == "current-session"
                            and existing["execution"].get("prepared")):
                        from ai_ops_kit.cli import project_session_resume
                        result = project_session_resume.validate(root, existing)
                        print(json.dumps(result, ensure_ascii=False))
                        return 1  # handoff всё ещё не является accepted
                    task = sessions.pending(root, args.runtime, args.session)
                    signals = intake_signals(task, args.signals)
                    from ai_ops_kit.engine import pipeline_helpers
                    missing = pipeline_helpers.missing_intake_signals(signals)
                    if missing:
                        sessions.save_intake(root, args.runtime, args.session, task["request_id"], signals, missing,
                                             autonomous=args.autonomous)
                        raise ValueError("; ".join(pipeline_helpers.intake_signals_hint(missing))
                                         + ". Запуск не начат; уточни signals той же сохранённой задачи.")
                    result = prepare(root, args.runtime, args.session, task, signals, autonomous=args.autonomous)
                    if result is None:
                        task = sessions.pending(root, args.runtime, args.session)
                        if task["request_id"] != existing["request_id"]:
                            raise ValueError("активная постановка сменилась после подготовки")
                        result = (sessions.execute(root, args.runtime, args.session, signals, request=task["request_id"],
                                                   progress=lambda message: print(message, file=sys.stderr, flush=True))
                                  if args.autonomous else current_session(root, args.runtime, args.session, task, signals))
            print(json.dumps(agent_response(root, result), ensure_ascii=False))
            return 0 if result.get("accepted") or result.get("status") == "accepted" else 1
    except (sessions.HookReadInterrupted, KeyboardInterrupt, OSError, ValueError,
            KeyError, TypeError, AttributeError, yaml.YAMLError) as exc:
        if args.action == "hook":
            detail = "чтение hook отменено" if isinstance(exc, KeyboardInterrupt) else str(exc)
            reason = f"AI Ops: {detail}. Сохранённая задача не считается принятой."
            print(json.dumps({"continue": False, "stopReason": reason, "systemMessage": reason},
                             ensure_ascii=False))
            return 0
        if isinstance(exc, KeyboardInterrupt):
            raise
        print(f"AI Ops: {exc}. Сохранённая задача не считается принятой.", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
