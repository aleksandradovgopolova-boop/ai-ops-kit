"""Привязка проектной задачи к checkout и наблюдаемому запуску штатного CLI (#1434).

Локальные записи не удостоверяют личность человека и не заменяют required CI.
В частности, наличие конфигурации не доказывает доверие хукам в runtime.
"""
from __future__ import annotations

import hashlib
import contextlib
import json
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path

import yaml

from ai_ops_kit.shared import lifecycle_store
from ai_ops_kit.lifecycle import session_migration_store

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
            "branch": git(root, "rev-parse", "--abbrev-ref", "HEAD"),
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


@contextlib.contextmanager
def session_lock(path):
    """Не ждать чужого writer бесконечно; тот же lock-файл, что у ledger."""
    try:
        import fcntl
    except ImportError as exc:
        raise ValueError("обязательная блокировка сессии недоступна") from exc
    path = Path(str(path) + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("сессию уже обрабатывает другой процесс; проверь сохранённый исход, не создавай новый запрос") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@session_migration_store.guarded
def begin(root, runtime, session, prompt, turn=None, *, continuation_validator=None):
    root = project_root(root)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 131072:
        raise ValueError("постановка пуста или превышает бюджет 128 KiB")
    directory = session_dir(root, runtime, session)
    with session_lock(directory / "requests"):
        return _begin(root, runtime, session, prompt, turn, directory, continuation_validator)


def _begin(root, runtime, session, prompt, turn, directory, continuation_validator):
    if turn is not None and (not isinstance(turn, str) or not turn.strip() or len(turn) > 1024):
        raise ValueError("неверный turn_id")
    # Идентичность события, не текст: одинаковые новые запросы остаются разными.
    request = digest(json.dumps([runtime, session, turn]))[:32] if turn else uuid.uuid4().hex
    replay = list(directory.glob(f"*.inputs/{request}.json")) if turn else []
    if replay:
        task = load(root, runtime, session)
        expected = input_receipt(task, prompt, turn, request)
        if len(replay) != 1 or json.loads(replay[0].read_text()) != expected:
            raise ValueError("повтор пользовательского ввода конфликтует или относится к прежней задаче")
        if task.get("status") == "accepted" or task.get("input_latest") != request or continuation_validator is None:
            raise ValueError("поздний повтор пользовательского ввода не является новым запросом")
        continuation_validator(root, runtime, session, task)
        return task
    previous = directory / f"{request}.json"
    if previous.exists():
        task = load(root, runtime, session)
        if (task["request_id"] != request or task.get("turn_id") != turn or task.get("prompt") != prompt
                or task.get("input_latest")):
            raise ValueError("повтор события не совпадает с активной постановкой; сохранённые задачи не изменены")
        return task
    if (directory / "active.json").exists():
        active = load(root, runtime, session)
        claim = directory / (active["request_id"] + ".execution-claim")
        if active.get("status") != "accepted" and (claim.exists() or claim.is_symlink() or active.get("status") != "pending"
                or any(key in active for key in ("execution", "intake", "preparation", "provider_preparation", "state_migration"))):
            if continuation_validator is None:
                raise ValueError("предыдущая попытка уже закреплена; продолжи сохранённую задачу и проверь её исход")
            continuation_validator(root, runtime, session, active)
            path = directory / (active["request_id"] + ".inputs") / (request + ".json")
            relative = str(path.relative_to(root))
            if git(root, "ls-files", "--", relative) or not git(root, "check-ignore", "--", relative):
                raise ValueError("пользовательский ввод требует ignored runtime path вне публичного Git")
            result = lifecycle_store.durable_create_batch(directory, {
                str(path.relative_to(directory)): json.dumps(input_receipt(active, prompt, turn, request),
                                                            ensure_ascii=False, indent=2)})
            if not result.get("ok"):
                raise ValueError("не удалось сохранить immutable пользовательский ввод: " + str(result.get("error")))
            active.setdefault("input_receipts", {})[str(path.relative_to(root))] = digest(path.read_bytes())
            active.setdefault("input_events", []).append(relative)
            active["input_latest"] = request
            write(directory / (active["request_id"] + ".json"), active)
            return active
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


def input_receipt(task, prompt, turn, event):
    """Локальная постановка пользователя: никогда не ApprovalRecord или verdict."""
    return {"kind": "current-session-input", "schema_version": 1, "event_id": event,
            "request_id": task["request_id"], "runtime": task["runtime"],
            "session_id": task["session_id"], "turn_id": turn, "prompt": prompt,
            "identity_scope": "reliable" if turn else "unreliable"}


@contextlib.contextmanager
def termination_guard():
    """SIGTERM внешнего runtime должен пройти через cleanup собственной группы."""
    def terminate(signum, frame):
        raise InterruptedError("SIGTERM: исход исполнения неизвестен")
    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def run_process(command, root, directory, *, timeout=300, progress=None):
    """Ограниченный процесс с видимым прогрессом и диагностикой на диске."""
    stdout, stderr = directory / "process.stdout.log", directory / "process.stderr.log"
    started = time.monotonic()
    with stdout.open("wb") as out, stderr.open("wb") as err, termination_guard():
        with subprocess.Popen(command, cwd=root, stdout=out, stderr=err, start_new_session=True) as process:
            try:
                while True:
                    if progress:
                        progress(f"AI Ops: процесс pid={process.pid}, прошло {int(time.monotonic() - started)} с; "
                                 f"диагностика: {stdout}, {stderr}")
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    try:
                        code = process.wait(timeout=min(15, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                # Владеем всей группой: не оставляем потомков даже после выхода родителя.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    # Группа уже завершилась; дождаться учёта выхода непосредственного ребёнка.
                    process.wait()
                process.wait()
    tails = []
    for path in (stdout, stderr):
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - 4096))
            tails.append(handle.read().decode("utf-8", errors="replace"))
    return subprocess.CompletedProcess(command, code, *tails)


def load(root, runtime, session):
    session_migration_store.incomplete(root)
    directory = session_dir(root, runtime, session)
    active = json.loads((directory / "active.json").read_text(encoding="utf-8"))
    request = active["request_id"]
    if not isinstance(request, str) or len(request) != 32 or any(c not in "0123456789abcdef" for c in request):
        raise ValueError("повреждён request_id")
    task = json.loads(within(directory, f"{request}.json").read_text(encoding="utf-8"))
    if task.get("runtime") != runtime or task.get("session_id") != session or task.get("request_id") != request:
        raise ValueError("подтверждение принадлежит другой задаче/сессии/runtime")
    return task


def artifact_inputs(root, fid):
    """Полный состав артефактов, включая ignored и отсутствие будущих файлов."""
    files = {}
    for relative in (f"features/{fid}", f".ai/runplan/{fid}", f"openspec/changes/{fid}"):
        for path in within(root, relative).rglob("*"):
            if path.is_symlink():
                raise ValueError("симлинк в артефактах текущей задачи не подтверждён")
            if path.is_file():
                key = str(path.relative_to(root))
                files[key] = digest(within(root, key).read_bytes())
    request = fid.removeprefix("session-")
    inputs = {}
    for directory in within(root, ".ai/runtime/sessions").glob(f"project-*/{request}.inputs"):
        if directory.is_symlink() or directory.parent.is_symlink():
            raise ValueError("симлинк в пользовательском вводе не подтверждён")
        if git(root, "ls-files", "--", str(directory.relative_to(root))):
            raise ValueError("пользовательский ввод попал в публичный Git")
        for path in directory.rglob("*"):
            if path.is_symlink() or not path.is_file():
                raise ValueError("неверный файл пользовательского ввода")
            relative = str(path.relative_to(root))
            git(root, "check-ignore", "--", relative)
            inputs[relative] = digest(path.read_bytes())
        task = json.loads((directory.parent / (request + ".json")).read_text())
        if inputs != task.get("input_receipts", {}):
            raise ValueError("состав пользовательского ввода изменён или запись не завершена")
    for task_path in within(root, ".ai/runtime/sessions").glob(f"project-*/{request}.json"):
        task = json.loads(task_path.read_text())
        events = task.get("input_events", [])
        if (task.get("input_receipts", {}) != inputs or not isinstance(events, list)
                or len(events) != len(inputs) or set(events) != set(inputs)
                or (events and Path(events[-1]).stem != task.get("input_latest"))):
            raise ValueError("пользовательский ввод или порядок событий отсутствует/изменён")
    files.update(inputs)
    return files


@session_migration_store.guarded
def verify(root, runtime, session):
    with session_lock(session_dir(root, runtime, session) / "requests"):
        return _verify(root, runtime, session)


def _verify(root, runtime, session):
    task = load(root, runtime, session)
    current = binding(root, "session-" + task["request_id"])
    receipt = task.get("execution") or {}
    expected = receipt.get("completion_binding") or task.get("binding")
    same = expected == current
    if receipt.get("mode") == "current-session" and task.get("status") != "accepted":
        same = all(current.get(k) == expected.get(k) for k in
                   ("root", "branch", "version", "managed_sha256", "config_sha256"))
    if not same:
        raise ValueError("checkout, ветка, версия или правила изменились; прежнее подтверждение не применимо")
    if task.get("status") != "accepted":
        return {"accepted": False, "status": task["status"],
                "reason": task.get("blocker") or "штатный процесс ещё не выполнен"}
    success = (receipt.get("verification_ready") is True if receipt.get("mode") == "current-session"
               else receipt.get("exit_code") == 0)
    if not success or not receipt.get("files"):
        raise ValueError("нет подтверждения фактического успешного запуска")
    for relative, checksum in receipt["files"].items():
        if digest(within(root, relative).read_bytes()) != checksum:
            raise ValueError(f"артефакт изменён после проверки: {relative}")
    if (receipt.get("mode") == "current-session"
            and artifact_inputs(root, "session-" + task["request_id"]) != receipt.get("artifact_inputs")):
        raise ValueError("состав артефактов изменён после проверки")
    if (receipt.get("mode") == "current-session"
            and task.get("input_events", []) != receipt.get("input_events", [])):
        raise ValueError("порядок пользовательского ввода изменён после проверки")
    result_root = within(root, receipt.get("worktree") or ".")
    if (git(result_root, "rev-parse", "HEAD") != receipt.get("revision")
            or source_digest(result_root, "session-" + task["request_id"]) != receipt.get("result_sha256")):
        raise ValueError("результат/рабочая копия изменены после проверки")
    return {"accepted": True, "status": "accepted", "request_id": task["request_id"]}


def pending(root, runtime, session):
    """Читать ещё не исполненную постановку; подготовка не снимает guards запуска."""
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
    if (within(session_dir(root, runtime, session), task["request_id"] + ".execution-claim").exists()
            or within(session_dir(root, runtime, session), task["request_id"] + ".execution-claim").is_symlink()):
        raise ValueError("попытка исполнения уже закреплена; проверь сохранённый исход")
    return task


@session_migration_store.guarded
def save_preparation(root, runtime, session, request, preparation, reason=None):
    with session_lock(session_dir(root, runtime, session) / "requests"):
        task = pending(root, runtime, session)
        if task["request_id"] != request:
            raise ValueError("активная постановка сменилась во время подготовки")
        task.pop("intake", None)
        task["preparation"] = preparation
        task["blocker"] = reason
        task["next_step"] = ("Заполни спецификацию по сохранённой постановке; затем продолжи тот же "
                             "project_session run без нового запроса и без повторной передачи signals. "
                             "До готовности спецификации содержательную работу не начинай.") if reason else None
        write(session_dir(root, runtime, session) / f"{request}.json", task)
        return task


@session_migration_store.guarded
def save_intake(root, runtime, session, request, signals, missing, *, autonomous=False):
    """Факт реально запрошенных CLI данных, не догадка по пользовательскому тексту."""
    directory = session_dir(root, runtime, session)
    with session_lock(directory / "requests"):
        task = pending(root, runtime, session)
        if task["request_id"] != request:
            raise ValueError("постановка сменилась при уточнении intake")
        task["intake"] = {"mode": "autonomous" if autonomous else "current-session",
                          "signals": signals, "missing": missing}
        write(directory / (request + ".json"), task)
    return task


@session_migration_store.guarded
def claim_execution(root, runtime, session, task, execution, next_step=None):
    """Активный запрос и claim фиксируются под тем же lock, что новый submit."""
    directory = session_dir(root, runtime, session)
    with session_lock(directory / "requests"):
        current = pending(root, runtime, session)
        if current["request_id"] != task["request_id"]:
            raise ValueError("активная постановка сменилась перед claim")
        if current.get("binding") != task.get("binding"):
            raise ValueError("binding изменена после чтения постановки; перечитай сохранённое состояние")
        claim = directory / (task["request_id"] + ".execution-claim")
        descriptor = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        for key in ("input_receipts", "input_latest", "input_events"):
            if key in current:
                task[key] = current[key]
        task.pop("intake", None)
        task.update(status="running", execution=execution, blocker=None, next_step=next_step)
        write(directory / (task["request_id"] + ".json"), task)
    return task


@session_migration_store.guarded
def execute(root, runtime, session, signals, *, provider=None, request=None, timeout=300, progress=None):
    """Запустить существующий фасад с теми же guards и единственной execution-claim."""
    root = project_root(root)
    task = pending(root, runtime, session)
    if request is not None and task["request_id"] != request:
        raise ValueError("активная постановка сменилась после подготовки; новая задача не исполняется со старыми signals")
    if runtime == "codex" and provider in (None, "codex-app-server"):
        from ai_ops_kit.providers import codex_native
        provider = codex_native.NAME
        readiness = codex_native.readiness(root)
        current = pending(root, runtime, session)
        if current["request_id"] != task["request_id"]:
            raise ValueError("активная постановка сменилась во время native readiness; исполнение не начато")
        task = current
        if not readiness["ready"]:
            readiness["signals"] = dict(signals)
            task.update(provider_preparation=readiness, blocker=readiness["reason"],
                        next_step=readiness["next_step"])
            write(session_dir(root, runtime, session) / f"{task['request_id']}.json", task)
            return task
        task.update(provider_preparation=dict(readiness, signals=dict(signals)), blocker=None, next_step=None)
    fid = "session-" + task["request_id"]
    report_path = within(root, f"features/{fid}/run-report.json")
    command = [str(root / "ai-ops"), "run", task["prompt"], str(root), "--execute",
               "--feature", fid, "--runtime", runtime, "--session", session,
               "--signals", json.dumps(signals, ensure_ascii=False), "--json"]
    if provider:
        command += ["--provider", provider]
    task = claim_execution(root, runtime, session, task, {"command": command})
    path = session_dir(root, runtime, session) / f"{task['request_id']}.json"
    try:
        result = run_process(command, root, session_dir(root, runtime, session), timeout=timeout, progress=progress)
        if not report_path.is_file():
            detail = (result.stderr or result.stdout or "нет диагностики процесса").strip()[-4096:]
            raise ValueError(f"штатный запуск завершился (exit={result.returncode}), отчёт не создан: {detail}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if (result.returncode != 0 or report.get("kind") != "execution-pipeline"
                or report.get("ready_for_pr") is not True or report.get("provider") in (None, "mock")
                or (provider == "codex-app-server" and report.get("provider") != provider)
                or report.get("workitem_id") != fid or report.get("runtime") != runtime
                or Path(report.get("child_root", "")).resolve() != root):
            detail = str(report.get("error") or report.get("overall_status") or "нет подтверждения готовности")[-4096:]
            raise ValueError(f"процесс не подтвердил готовность (exit={result.returncode}): {detail}; "
                             f"см. {report_path.relative_to(root)}")
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
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        task.update(status="blocked", blocker=f"исполнение прервано ({type(exc).__name__}); исход неизвестен",
                    next_step="Проверь сохранённые логи, claim, worktree и отчёт. Автоматический повтор запрещён.")
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
        task.update(status="blocked", blocker=str(exc), next_step="Исправить названную причину; продолжить сохранённую задачу.")
    write(path, task)
    return task
