"""Привязка проектной задачи к checkout и наблюдаемому запуску штатного CLI (#1434).

Локальные записи не удостоверяют личность человека и не заменяют required CI.
В частности, наличие конфигурации не доказывает доверие хукам в runtime.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path

import yaml

from ai_ops_kit.shared import lifecycle_store

MARKER = "ai-ops-kit:project-session"
BEGIN = "<!-- AI-OPS-PROJECT-SESSION:BEGIN -->"
END = "<!-- AI-OPS-PROJECT-SESSION:END -->"
POLICY = "templates/runtime/team-session.md"
RUNTIMES = {"claude-code": ".claude/settings.json", "codex": ".codex/hooks.json"}
EVENTS = ("SessionStart", "UserPromptSubmit", "Stop")


def digest(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def within(root, relative):
    path = Path(root) / relative
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError(f"путь выходит за проект: {relative}")
    return path


def git(root, *args):
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, timeout=10, check=False)
    if proc.returncode:
        raise ValueError(f"git {' '.join(args)} недоступен: {proc.stderr.strip()[:200]}")
    return proc.stdout.removesuffix("\n")


def project_root(cwd):
    return Path(git(Path(cwd), "rev-parse", "--show-toplevel")).resolve()


def hook_group(runtime):
    if runtime not in RUNTIMES:
        raise ValueError("неподдерживаемый runtime")
    # Не используем CLAUDE_PROJECT_DIR прежнего проекта и не меняем cwd процесса.
    command = ('r=$(git rev-parse --show-toplevel) || exit 2; '
               'f="$r/.ai/managed/templates/runtime/team_hook.py"; '
               '[ -f "$f" ] || { echo "AI Ops: нет проектного hook; нужен штатный update" >&2; exit 2; }; '
               f'exec "${{AI_OPS_PYTHON:-python3}}" "$f" --runtime {runtime} # {MARKER}')
    return {"hooks": [{"type": "command", "command": command, "timeout": 15}]}


def instruction_block():
    return (f"{BEGIN}\nПроект использует AI Ops. Общие правила обоих runtime: "
            f"`.ai/managed/{POLICY}`. Прочитай их до содержательной задачи и после восстановления.\n"
            "Наличие этого блока не подтверждает запуск процесса; завершение проверяет проектный hook.\n"
            f"{END}\n")


def configuration_problems(root):
    root = Path(root)
    problems = []
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = within(root, name)
        if not path.is_file() or instruction_block() not in path.read_text(encoding="utf-8"):
            problems.append(f"{name}: общий проектный вход отсутствует или изменён")
    for runtime, relative in RUNTIMES.items():
        try:
            doc = json.loads(within(root, relative).read_text(encoding="utf-8"))
            if doc.get("disableAllHooks") is True:
                problems.append(f"{relative}: хуки отключены")
            for event in EVENTS:
                if hook_group(runtime) not in doc.get("hooks", {}).get(event, []):
                    problems.append(f"{relative}: нет штатного {event}")
        except (OSError, ValueError, AttributeError, TypeError):
            problems.append(f"{relative}: настройки не читаются")
    return problems


def required(root):
    cfg = yaml.safe_load(within(root, ".ai-ops.yaml").read_text(encoding="utf-8"))
    return isinstance(cfg, dict) and (cfg.get("standard") or {}).get("team_session") == "required"


def source_digest(root, feature=None):
    ignored = (".ai/runtime/", ".ai/generated/", ".ai/usage/", ".ai/managed/", ".ai/worktrees/")
    if feature:
        ignored += (f"features/{feature}/",)
    files = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    values = {}
    for relative in sorted(set(files)):
        if not relative or relative.startswith(ignored):
            continue
        path = within(root, relative)
        values[relative] = (digest(path.read_bytes()), path.stat().st_mode & 0o111) if path.is_file() else None
    return digest(json.dumps(values, sort_keys=True))


def require_checked_tree(root, feature):
    paths = [".", ":(exclude).ai/runtime", ":(exclude).ai/generated", ":(exclude).ai/usage",
             ":(exclude).ai/worktrees", f":(exclude)features/{feature}"]
    if (git(root, "diff", "--name-only", "HEAD", "--", *paths)
            or git(root, "ls-files", "--others", "--exclude-standard", "--", *paths)):
        raise ValueError("содержимое результата не соответствует проверенной revision: рабочая копия изменена")


def binding(root, feature=None):
    root = project_root(root)
    managed = within(root, ".ai/managed")
    cfg = yaml.safe_load(within(root, ".ai-ops.yaml").read_text(encoding="utf-8"))
    version = within(managed, "VERSION").read_text(encoding="utf-8").strip()
    if not isinstance(cfg, dict) or (cfg.get("parent") or {}).get("installed_version") != version:
        raise ValueError("версия managed не совпадает с .ai-ops.yaml; нужен штатный update")
    if not os.access(within(root, "ai-ops"), os.X_OK):
        raise ValueError("точка входа ./ai-ops отсутствует или не исполняется")
    problems = configuration_problems(root)
    if problems:
        raise ValueError("; ".join(problems))
    # Хэш всего managed включает политику и её реализацию; не только номер версии.
    checksums = {}
    for p in sorted(managed.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            relative = p.relative_to(managed).as_posix()
            checksums[relative] = digest(within(managed, relative).read_bytes())
    if POLICY not in checksums:
        raise ValueError("общая политика не доставлена; нужен штатный update")
    return {"root": str(root), "head": git(root, "rev-parse", "HEAD"),
            "branch": git(root, "symbolic-ref", "--quiet", "--short", "HEAD"),
            "version": version, "managed_sha256": digest(json.dumps(checksums, sort_keys=True)),
            "config_sha256": digest((root / ".ai-ops.yaml").read_bytes()),
            "source_sha256": source_digest(root, feature)}


def session_dir(root, runtime, session):
    if runtime not in RUNTIMES or not isinstance(session, str) or not session.strip():
        raise ValueError("нужны поддерживаемый runtime и непустой session_id")
    return within(root, f".ai/runtime/sessions/project-{digest(runtime + ':' + session)[:32]}")


def write(path, data):
    result = lifecycle_store.durable_write_json(path, data)
    if not result.get("ok"):
        raise OSError(f"не удалось сохранить постановку/подтверждение: {result.get('error')}")


def begin(root, runtime, session, prompt, turn=None):
    root = project_root(root)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 131072:
        raise ValueError("постановка пуста или превышает бюджет 128 KiB")
    directory = session_dir(root, runtime, session)
    request = uuid.uuid4().hex
    task = {"schema_version": 1, "request_id": request, "session_id": session,
            "runtime": runtime, "turn_id": turn, "prompt": prompt, "status": "pending"}
    # Постановка сохраняется ДО диагностики, в том числе при повреждённой установке.
    write(directory / f"{request}.json", task)
    write(directory / "active.json", {"request_id": request})
    try:
        task["binding"] = binding(root, "session-" + request)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        task.update(status="blocked", blocker=str(exc), next_step="Восстановить установку штатным update и повторить задачу.")
    write(directory / f"{request}.json", task)
    return task


def load(root, runtime, session):
    directory = session_dir(root, runtime, session)
    active = json.loads((directory / "active.json").read_text(encoding="utf-8"))
    request = active["request_id"]
    if not isinstance(request, str) or len(request) != 32 or any(c not in "0123456789abcdef" for c in request):
        raise ValueError("повреждён request_id")
    task = json.loads(within(directory, f"{request}.json").read_text(encoding="utf-8"))
    if task.get("runtime") != runtime or task.get("session_id") != session or task.get("request_id") != request:
        raise ValueError("подтверждение принадлежит другой задаче/сессии/runtime")
    return task


def verify(root, runtime, session):
    task = load(root, runtime, session)
    if task.get("binding") != binding(root, "session-" + task["request_id"]):
        raise ValueError("checkout, ветка, версия или правила изменились; прежнее подтверждение не применимо")
    if task.get("status") != "accepted":
        return {"accepted": False, "status": task["status"],
                "reason": task.get("blocker") or "штатный процесс ещё не выполнен"}
    receipt = task.get("execution") or {}
    if receipt.get("exit_code") != 0 or not receipt.get("files"):
        raise ValueError("нет подтверждения фактического успешного запуска")
    for relative, checksum in receipt["files"].items():
        if digest(within(root, relative).read_bytes()) != checksum:
            raise ValueError(f"артефакт изменён после проверки: {relative}")
    result_root = within(root, receipt.get("worktree") or ".")
    if (git(result_root, "rev-parse", "HEAD") != receipt.get("revision")
            or source_digest(result_root, "session-" + task["request_id"]) != receipt.get("result_sha256")):
        raise ValueError("результат/рабочая копия изменены после проверки")
    return {"accepted": True, "status": "accepted", "request_id": task["request_id"]}


def execute(root, runtime, session, signals, *, provider=None):
    """Запустить СУЩЕСТВУЮЩИЙ фасад; не свой tool loop и не новая система gates.

    signals классифицирует текущий runtime по общему канону. Нельзя подтвердить
    вызов другого prompt либо принять найденный до вызова run-report.
    """
    root = project_root(root)
    task = load(root, runtime, session)
    if task.get("binding") != binding(root, "session-" + task["request_id"]):
        raise ValueError("проект изменился после постановки; нужна новая постановка из текущего checkout")
    if task.get("status") != "pending":
        raise ValueError("запуск уже учтён; повтор требует новой постановки")
    fid = "session-" + task["request_id"]
    report_path = within(root, f"features/{fid}/run-report.json")
    if report_path.exists():
        raise ValueError("отчёт существовал до запуска: чужое/старое evidence не принимается")
    # Два параллельных вызова одной постановки не должны запустить две модели.
    claim = within(session_dir(root, runtime, session), task["request_id"] + ".execution-claim")
    try:
        descriptor = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("попытка исполнения уже закреплена; проверь сохранённый исход") from None
    os.close(descriptor)
    command = [str(root / "ai-ops"), "run", task["prompt"], str(root), "--execute",
               "--feature", fid, "--runtime", runtime, "--session", session,
               "--signals", json.dumps(signals, ensure_ascii=False), "--json"]
    if provider:
        command += ["--provider", provider]
    task.update(status="running", execution={"command": command})
    path = session_dir(root, runtime, session) / f"{task['request_id']}.json"
    write(path, task)
    try:
        # stdout остаётся у вызывающего runtime. Подтверждение берётся с диска и из exit code.
        result = subprocess.run(command, cwd=root, check=False, capture_output=True, text=True)
        if not report_path.is_file():
            detail = (result.stderr or result.stdout or "нет диагностики процесса").strip()[-4096:]
            raise ValueError(f"штатный запуск завершился (exit={result.returncode}), отчёт не создан: {detail}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if (result.returncode != 0 or report.get("kind") != "execution-pipeline"
                or report.get("ready_for_pr") is not True or report.get("provider") in (None, "mock")
                or report.get("workitem_id") != fid or report.get("runtime") != runtime
                or Path(report.get("child_root", "")).resolve() != root):
            raise ValueError(f"процесс не подтвердил готовность (exit={result.returncode}); см. {report_path.relative_to(root)}")
        workitem = yaml.safe_load(within(root, f"features/{fid}/workitem.yaml").read_text(encoding="utf-8"))
        plan = yaml.safe_load(within(root, f"features/{fid}/run-plan.yaml").read_text(encoding="utf-8"))
        journal_path = within(root, f"features/{fid}/lifecycle-journal.jsonl")
        journal = lifecycle_store.journal_read(journal_path)
        ends = [e for e in journal["events"] if e.get("kind") == "run_end"]
        if (not journal["ok"] or not ends or ends[-1].get("ready_for_pr") is not True
                or ends[-1].get("workitem_id") != fid or workitem.get("task") != task["prompt"]
                or plan.get("workitem_id") != fid or workitem.get("workflow") != plan.get("base_workflow")):
            raise ValueError("WorkItem/RunPlan/журнал не подтверждают исполнение текущей постановки")
        worktree = (report.get("isolation") or {}).get("worktree")
        result_root = within(root, worktree or ".")
        revision = (report.get("commit") or {}).get("sha")
        if not revision or git(result_root, "rev-parse", "HEAD") != revision:
            raise ValueError("проверенная revision результата не совпадает с рабочей копией")
        require_checked_tree(result_root, fid)
        files = {}
        for name in ("run-report.json", "run-plan.yaml", "workitem.yaml",
                     "lifecycle-journal.jsonl", "lifecycle-journal.jsonl.head"):
            relative = f"features/{fid}/{name}"
            files[relative] = digest(within(root, relative).read_bytes())
        task.update(status="accepted", execution={"exit_code": result.returncode, "files": files,
                    "worktree": worktree, "revision": revision, "result_sha256": source_digest(result_root, fid)})
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
        task.update(status="blocked", blocker=str(exc), next_step="Исправить названную причину; продолжить сохранённую задачу.")
    write(path, task)
    return task
