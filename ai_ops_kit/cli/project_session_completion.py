"""Завершение текущего агента: штатные gates без повторного authoring или моделей.

Доверенный digest review приходит от независимого runtime/оператора, как в premerge.
Хэш собственного JSON автора не доказывает независимость; локальный файл не удостоверяет
аккаунт. Handoff и приёмка используют существующие контракты reviewer/acceptance-result.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import yaml

# Прямой дочерний процесс должен использовать ту же установленную копию.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai_ops_kit.lifecycle import project_session as sessions


def prepared(root, runtime, session, task):
    from ai_ops_kit.cli.project_session import resume_current
    if task.get("execution", {}).get("mode") != "current-session" or not task["execution"].get("prepared"):
        raise ValueError("нет подтверждённой передачи текущему агенту; сначала проверь сохранённый исход")
    return resume_current(root, runtime, session, task)


def record_prepared(root, task):
    """Восстановить факт подготовки из строго сверенных controller-артефактов, не ready."""
    from ai_ops_kit.engine import run_plan
    fid = "session-" + task["request_id"]
    signals = task["execution"].get("signals") or (task.get("preparation") or {}).get("signals")
    if not signals:
        raise ValueError("сигналы передачи не сохранены; автоматический повтор запрещён")
    plan = yaml.safe_load(sessions.within(root, f"features/{fid}/run-plan.yaml").read_text())
    item = yaml.safe_load(sessions.within(root, f"features/{fid}/workitem.yaml").read_text())
    report = json.loads(sessions.within(root, f"features/{fid}/run-report.json").read_text())
    expected = run_plan.build_plan(dict(signals, task_text=task["prompt"]), workitem_id=fid)
    if (any(plan.get(k) != expected.get(k) for k in ("workitem_id", "base_workflow", "gates", "task_hash"))
            or item.get("id") != fid or item.get("task") != task["prompt"]
            or item.get("workflow") != plan["base_workflow"]
            or report.get("kind") != "run-report" or report.get("execution") != "planned"
            or report.get("status") != "planned" or report.get("workitem_id") != fid
            or report.get("runtime") != task["runtime"] or report.get("gates") != plan["gates"]
            or report.get("lifecycle_errors")):
        raise ValueError("артефакты controller не подтверждают подготовку текущей постановки")
    task["execution"].update(signals=signals, prepared=True, files={
        f"features/{fid}/{name}": sessions.digest(sessions.within(root, f"features/{fid}/{name}").read_bytes())
        for name in ("workitem.yaml", "run-plan.yaml", "run-report.json")})


def recover_handoff(root, runtime, session, task):
    current = sessions.binding(root, "session-" + task["request_id"])
    if any(current.get(k) != task["binding"].get(k) for k in
           ("root", "branch", "version", "managed_sha256", "config_sha256")):
        raise ValueError("контекст незавершённой передачи изменился")
    claim = sessions.session_dir(root, runtime, session) / (task["request_id"] + ".execution-claim")
    if task.get("execution", {}).get("mode") != "current-session" or not claim.is_file():
        raise ValueError("исход автономного запуска не подтверждён; повтор запрещён")
    record_prepared(root, task)
    task.update(status="running", blocker=None, next_step="Продолжи сохранённый RunPlan текущим агентом; затем finalize.")
    sessions.write(claim.parent / (task["request_id"] + ".json"), task)
    return task


def artifact_inputs(root, fid):
    files = {}
    for relative in (f"features/{fid}", f".ai/runplan/{fid}", f"openspec/changes/{fid}"):
        for path in sessions.within(root, relative).rglob("*"):
            if path.is_symlink():
                raise ValueError("симлинк в артефактах текущей задачи не подтверждён")
            if path.is_file():
                key = str(path.relative_to(root))
                files[key] = sessions.digest(sessions.within(root, key).read_bytes())
    return files


def scope(task, current):
    artifacts = artifact_inputs(Path(current["root"]), "session-" + task["request_id"])
    return {"workitem_id": "session-" + task["request_id"], "request_id": task["request_id"],
            "writer_session": task["runtime"] + ":" + task["session_id"],
            "base_revision": task["binding"]["head"], "reviewed_revision": current["head"],
            "source_sha256": current["source_sha256"],
            "artifacts_sha256": sessions.digest(json.dumps(artifacts, sort_keys=True))}


def review_inputs(root, task, current, digests):
    """Проверить внешние квитанции ДО их потребления pipeline; открыть конкретные requests."""
    from ai_ops_kit.engine import acceptance_verify, pipeline_helpers, reviewer_handoff
    from ai_ops_kit.gates import gate_executor
    fid = "session-" + task["request_id"]
    handoff = sessions.session_dir(root, task["runtime"], task["session_id"]) / (task["request_id"] + ".reviews")
    plan = yaml.safe_load(sessions.within(root, f"features/{fid}/run-plan.yaml").read_text())
    signals = task["execution"]["signals"]
    needed = pipeline_helpers._reviewable_gates(plan["gates"], signals)
    _, criteria, problem = acceptance_verify.criteria_from_spec(root, fid)
    if problem:
        raise ValueError(problem)
    if criteria:
        needed = list(needed) + ["acceptance"]
    if not isinstance(digests, dict) or set(digests) - set(needed):
        raise ValueError("неизвестные review digests")
    changed = sessions.git(root, "diff", "--name-only", task["binding"]["head"], current["head"]).splitlines()
    expected, accepted, missing = scope(task, current), {}, []
    gates = gate_executor.load_gates()
    for gid in needed:
        g = gates.get(gid) or {}
        checklist = pipeline_helpers._gate_checklist(g, root=root, changed_files=set(changed))
        reviewer_handoff.open_request(handoff, gid, checklist=checklist,
            reviewed_revision=current["head"], changed_files=changed, blocking=True,
            required_evidence=g.get("required_evidence"), cause="нужно независимое ревью текущего агента")
        request_path = reviewer_handoff.request_path(handoff, gid)
        request = json.loads(request_path.read_text())
        request.update(expected, criteria=criteria if gid == "acceptance" else None,
            instructions="Независимый ревьюер проверяет весь base..HEAD и возвращает verdict и SHA256 "
            "через независимый канал. Автор не заполняет заключение за судью. Поля привязки скопировать из request.")
        sessions.write(request_path, request)
        path = reviewer_handoff.verdict_path(handoff, gid)
        try:
            raw = path.read_bytes()
            rr = json.loads(raw)
            if sessions.digest(raw) != digests.get(gid) or any(rr.get(k) != v for k, v in expected.items()):
                raise ValueError("нет доверенного digest либо привязка вердикта устарела")
            who = rr.get("reviewer")
            if (not isinstance(who, str) or not who.strip() or who.strip().casefold() in
                    reviewer_handoff._WRITER_IDENTITIES | {task["runtime"].casefold(), task["session_id"].casefold(),
                     expected["writer_session"].casefold()}):
                raise ValueError("writer не может быть независимым судьёй")
            if gid != "acceptance":
                valid, reason = reviewer_handoff.load_verdict(handoff, gid, revision=current["head"])
                if valid is None:
                    raise ValueError(reason)
            else:
                from ai_ops_kit.checks import acceptance_result
                errors = acceptance_result.check(rr, [c["id"] for c in criteria])
                if errors:
                    raise ValueError("; ".join(errors))
            accepted[gid] = {"path": str(path.relative_to(root)), "sha256": sessions.digest(raw)}
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            missing.append(f"{gid}: {exc}; {request_path.relative_to(root)}")
    return handoff, accepted, missing


def evaluate(root, runtime, session, request, attempt):
    """Работник: только проверки. Создаёт attempt-specific отчёт и durable checksum."""
    from ai_ops_kit.engine import execution_pipeline, pipeline_git, tool_broker
    from ai_ops_kit.cli.ai_ops_cli import resolve_flags
    task = prepared(root, runtime, session, sessions.load(root, runtime, session))
    verification = task["verification"]
    if task["request_id"] != request or verification["attempt"] != attempt or verification["phase"] != "running":
        raise ValueError("проверка принадлежит другой попытке")
    fid = "session-" + request
    current = sessions.binding(root, fid)
    if (current != verification["binding"] or scope(task, current) != verification["scope"]
            or not pipeline_git._tree_clean(root)):
        raise ValueError("результат изменился перед проверкой или не зафиксирован")
    if sessions.within(root, f".ai/reevaluate-evidence-{fid}.json").exists():
        raise ValueError("чужой кеш переоценки не подтверждает текущую сессию")
    handoff, reviews, missing = review_inputs(root, task, current, verification["review_digests"])
    pipeline = None
    if not missing:
        plan = yaml.safe_load(sessions.within(root, f"features/{fid}/run-plan.yaml").read_text())
        signals = task["execution"]["signals"]
        flags = resolve_flags(signals)
        acceptance = reviews.get("acceptance")
        # Это транспорт уже вынесенного независимого вердикта, не модельный callback.
        def acceptance_artifact(_prompt):
            if acceptance is None:
                raise ValueError("независимая приёмка отсутствует")
            raw = sessions.within(root, acceptance["path"]).read_bytes()
            if sessions.digest(raw) != acceptance["sha256"]:
                raise ValueError("вердикт изменён во время проверки")
            return raw.decode("utf-8")
        pipeline = execution_pipeline.run_pipeline(task["prompt"], signals, root, proposer=None,
            feature=fid, plan=plan, commit=True, reevaluate_only=True, isolate=False, install_deps=False,
            open_pr=False, sandbox=flags["sandbox"], calibrated_enforcement=True,
            strict_judge_qualified=False, review=False,
            reviewer_proposer=acceptance_artifact if acceptance else None,
            review_handoff_root=handoff, base_revision=task["binding"]["head"],
            policy=tool_broker.sandbox_policy(child_root=str(root), allow_network=False))
        if flags.get("require_fix") and (pipeline.get("regression") or {}).get("status") != "proven":
            missing.append("не подтверждён regression proof исправления")
    if (current != sessions.binding(root, fid) or scope(task, current) != verification["scope"]
            or not pipeline_git._tree_clean_after_checks(root)):
        raise ValueError("результат изменился во время проверки")
    files = dict(task["execution"]["files"])
    files.update(artifact_inputs(root, fid))
    files.update({r["path"]: r["sha256"] for r in reviews.values()})
    ready = not missing and (pipeline or {}).get("ready_for_pr") is True
    if ready:
        from ai_ops_kit.lifecycle import active_work
        # Shared registry lock тоже находится под общим deadline работника.
        if active_work.finish_cmd(root / ".ai/runtime/active-work.yaml", fid, child_root=root,
                                  published=active_work.publication_enabled(root)):
            raise ValueError("не удалось завершить запись активной работы")
    report = {"kind": "current-session-verification", "request_id": request, "attempt": attempt,
              "binding": current, "scope": scope(task, current), "pipeline": pipeline, "files": files,
              "ready_for_pr": ready, "active_work_closed": ready, "ci": "not-verified",
              "missing": missing}
    path = sessions.within(root, verification["report"])
    sessions.write(path, report)
    with sessions.session_lock(sessions.session_dir(root, runtime, session) / "requests"):
        latest = sessions.load(root, runtime, session)
        if latest["request_id"] != request or latest["verification"]["attempt"] != attempt:
            raise ValueError("активная проверка сменилась")
        latest["verification"].update(phase="finished", sha256=sessions.digest(path.read_bytes()))
        sessions.write(path.parent / (request + ".json"), latest)


def reconcile(root, runtime, session):
    """Принять только durable исход своей попытки. Не повторяет ни проверки, ни провайдера."""
    task = sessions.load(root, runtime, session)
    if not task.get("execution", {}).get("prepared"):
        return recover_handoff(root, runtime, session, task)
    task = prepared(root, runtime, session, task)
    verification = task.get("verification") or {}
    if verification.get("phase") != "finished" or not verification.get("sha256"):
        raise ValueError("исход проверки неизвестен; claim сохранён, автоматический повтор запрещён")
    raw = sessions.within(root, verification["report"]).read_bytes()
    if sessions.digest(raw) != verification["sha256"]:
        raise ValueError("отчёт проверки изменён")
    report = json.loads(raw)
    current = sessions.binding(root, "session-" + task["request_id"])
    if (report.get("kind") != "current-session-verification"
            or report.get("request_id") != task["request_id"] or report.get("attempt") != verification["attempt"]
            or report.get("binding") != verification["binding"] or current != verification["binding"]
            or report.get("scope") != verification["scope"] or report.get("scope") != scope(task, current)):
        raise ValueError("отчёт относится к другой попытке или результат изменился")
    for relative, checksum in report["files"].items():
        if sessions.digest(sessions.within(root, relative).read_bytes()) != checksum:
            raise ValueError("проверенный артефакт изменён: " + relative)
    if report.get("ready_for_pr") is True:
        pipeline = report.get("pipeline") or {}
        if (pipeline.get("ready_for_pr") is not True or pipeline.get("kind") != "execution-pipeline"
                or (pipeline.get("commit") or {}).get("sha") != current["head"]
                or (pipeline.get("loop") or {}).get("stopped") != "reevaluate-only"):
            raise ValueError("нет подтверждения штатных проверок точной ревизии")
        if report.get("active_work_closed") is not True:
            raise ValueError("нет подтверждения завершения активной работы")
        files = dict(report["files"], **{verification["report"]: verification["sha256"]})
        task["execution"].update(verification_ready=True, process_exit_code=verification.get("process_exit_code"),
            files=files, revision=current["head"], worktree=None,
            result_sha256=current["source_sha256"], completion_binding=current)
        task.update(status="accepted", blocker=None, next_step=None)
    else:
        task.update(status="running", blocker="; ".join(report.get("missing") or []) or
                    "штатные gates не подтвердили готовность; см. " + verification["report"],
                    next_step="Устрани названную причину и повтори finalize той же задачи. Не удаляй claim.")
    sessions.write(sessions.session_dir(root, runtime, session) / (task["request_id"] + ".json"), task)
    return task


def finalize(root, runtime, session, digests):
    task = prepared(root, runtime, session, sessions.load(root, runtime, session))
    if task.get("status") == "accepted":
        sessions.verify(root, runtime, session)
        return task
    previous = task.get("verification")
    if previous and previous.get("phase") not in ("finished", "failed"):
        return reconcile(root, runtime, session)
    from ai_ops_kit.engine.pipeline_git import _tree_clean
    if not _tree_clean(root):
        raise ValueError("сначала зафиксируй результат; проверки требуют чистый committed HEAD")
    directory = sessions.session_dir(root, runtime, session)
    attempt = uuid.uuid4().hex
    if previous:
        task.setdefault("verification_history", []).append(previous)
    report = directory / f"{task['request_id']}.verification-{attempt}.json"
    task["verification"] = {"attempt": attempt, "phase": "running", "review_digests": digests,
        "binding": sessions.binding(root, "session-" + task["request_id"]), "report": str(report.relative_to(root))}
    task["verification"]["scope"] = scope(task, task["verification"]["binding"])
    path = directory / (task["request_id"] + ".json")
    sessions.write(path, task)
    command = [sys.executable, str(Path(__file__).resolve()), str(root), runtime, session, task["request_id"], attempt]
    try:
        result = sessions.run_process(command, root, directory, timeout=300)
        latest = sessions.load(root, runtime, session)
        latest["verification"]["process_exit_code"] = result.returncode
        sessions.write(path, latest)
        if result.returncode:
            if latest["verification"]["phase"] == "running":
                latest["verification"]["phase"] = "failed"
                sessions.write(path, latest)
            raise ValueError((result.stderr or result.stdout)[-4096:])
    except (OSError, ValueError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        latest = sessions.load(root, runtime, session)
        latest.update(status="blocked", blocker=f"проверка прервана: {exc}", next_step="Выполни reconcile; claim сохранён.")
        sessions.write(path, latest)
        return latest
    return reconcile(root, runtime, session)


if __name__ == "__main__":
    try:
        evaluate(Path(sys.argv[1]), *sys.argv[2:])
    except (OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError) as exc:
        print(f"AI Ops finalize: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
