"""Происхождение утверждений и content receipts проверок.

Тип утверждения не подтверждает истинность (#1254); применимость PASS доказывает
совпадение содержимого входов. Durable I/O остаётся в LifecycleStore.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from datetime import datetime, timezone
from typing import Callable, cast

from typing import Any, Mapping, Optional

KINDS = ('FACT', 'JUDGMENT', 'REASONING', 'HUMAN_DECISION')
SOURCE_KIND = {'deterministic': 'FACT', 'ai_judgment': 'JUDGMENT', 'human': 'HUMAN_DECISION'}
LABELS = {'FACT': 'факт проверки', 'JUDGMENT': 'оценка AI',
          'REASONING': 'рассуждение AI', 'HUMAN_DECISION': 'решение человека'}


def evidence_kind(evidence: Mapping[str, Any]) -> Optional[str]:
    """Явный тип producer имеет приоритет; legacy source остаётся совместимым."""
    if 'provenance' in evidence and evidence['provenance'] is None:
        raise ValueError('provenance не может быть null во входном evidence')
    kind = evidence.get('provenance')
    if kind is not None:
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError('неизвестный тип provenance')
        source = evidence.get('source')
        if source is not None:
            if not isinstance(source, str):
                raise ValueError('неизвестный источник evidence')
            same_family = source == 'ai_judgment' and kind == 'REASONING'
            if SOURCE_KIND.get(source) != kind and not same_family:
                raise ValueError('source и provenance противоречат друг другу')
        return kind
    source = evidence.get('source')
    if source is None:
        return None  # legacy producer не объявлял происхождение: не выдумываем FACT/HUMAN
    if not isinstance(source, str) or source not in SOURCE_KIND:
        raise ValueError('неизвестный источник evidence')
    return SOURCE_KIND[source]


def describe(kind: str) -> str:
    return LABELS[kind]


STATUSES = ("PASS", "FAIL", "SKIP", "BLOCKED", "NOT_RUN")
_HEX = re.compile(r"[0-9a-f]{64}")
# Только выходы инструментов; исходники, lockfiles и конфигурация не исключаются.
_OUTPUTS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
            ".ruff_cache", ".mypy_cache"}
_SESSION_ENV = {"CODEX_THREAD_ID", "CODEX_SESSION_ID", "TERM_SESSION_ID", "ITERM_SESSION_ID",
                "CODEX_TOOL_CALL_ID", "SHLVL", "_", "OLDPWD"}
PYTEST_OUTPUTS = "pytest-hypothesis-cache-v1"
_PYTEST_OUTPUT_PATH = re.compile(
    r"\.hypothesis/(?:\.gitignore|constants/[0-9a-f]{16}(?:_nolimit)?|"
    r"unicode_data/[0-9]+\.[0-9]+\.[0-9]+/(?:charmap|codec-v2-utf-8)\.json\.gz)\Z")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def environment_digest() -> str:
    return digest({k: v for k, v in os.environ.items() if k not in _SESSION_ENV})


def file_digest(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path: str | Path, data: dict) -> None:
    """Та же надёжная запись LifecycleStore, без параллельного I/O-контракта."""
    from ai_ops_kit.shared import lifecycle_store
    result = lifecycle_store.durable_write_json(path, data)
    if not result.get("ok"):
        raise OSError(result.get("error", "receipt write failed"))


def _tree_inventory(root: str | Path) -> list:
    """Консервативно все входы дерева, включая ignored configs и untracked files.

    Внешние зависимости исключены здесь и ОБЯЗАНЫ быть учтены context adapter.
    Симлинк/ошибка чтения запрещает reuse. Удаления меняют набор путей.
    """
    root = Path(root).resolve()
    files = []
    def unreadable(error: OSError) -> None:
        raise error
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=unreadable):
        rel = Path(directory).relative_to(root)
        if rel == Path(".ai/runtime"):
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if d not in _OUTPUTS)
        for name in dirs + sorted(names):
            p = Path(directory) / name
            if p.is_symlink():
                raise ValueError("symbolic input: dependency scope unproven")
            if p.is_file():
                files.append((str(p.relative_to(root)), stat.S_IMODE(p.stat().st_mode), file_digest(p)))
    return files


def tree_digest(root: str | Path) -> str:
    return digest(_tree_inventory(root))


def _capture_inputs(root: str | Path, command: object, context: dict | None, *,
                    scope: str = "local", extra: object = None, git_context: bool = True,
                    output_contract: str | None = None) -> tuple[dict | None, str, list | None]:
    try:
        if not isinstance(context, dict) or context.get("complete") is not True:
            return None, "контекст зависимостей/toolchain/среды не подтверждён", None
        if any(not isinstance(context.get(k), str) or not _HEX.fullmatch(context[k])
               for k in ("toolchain", "dependencies", "environment")):
            return None, "неполный content context", None
        git_state = []
        if git_context and (Path(root) / ".git").exists():
            for args in (["rev-parse", "--verify", "HEAD"],
                         ["for-each-ref", "--format=%(refname)%00%(objectname)"],
                         ["diff", "--cached", "--no-ext-diff", "--no-textconv", "--binary"]):
                result = subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=15)
                if result.returncode and args[0] != "rev-parse":
                    return None, "состояние Git непроверяемо", None
                git_state.append([result.returncode, result.stdout.hex()])
        files = _tree_inventory(root)
        inputs = {"tree": digest(files), "git": digest(git_state), "command": digest(command),
                  "context": digest(context), "scope": scope, "extra": digest(extra)}
        if output_contract is not None:
            if output_contract != PYTEST_OUTPUTS:
                raise ValueError("unknown output contract")
            # Outputs остаются в полном fingerprint: их позднейшая подмена инвалидирует PASS.
            inputs["output_contract"] = digest(output_contract)
        return inputs, "содержимое входов, зависимостей, toolchain, среды и flags совпадает", files
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, "входы недоступны или зависимости непроверяемы", None


def fingerprint(root: str | Path, command: object, context: dict | None, *, scope: str = "local",
                extra: object = None, git_context: bool = True, output_contract: str | None = None) -> tuple[dict | None, str]:
    inputs, reason, _ = _capture_inputs(root, command, context, scope=scope, extra=extra,
                                        git_context=git_context, output_contract=output_contract)
    return inputs, reason


def _output_paths(root: str | Path, files: list | None, output_contract: str | None) -> set[str]:
    if output_contract != PYTEST_OUTPUTS or files is None:
        return set()
    tracked = set()
    if (Path(root) / ".git").exists():
        result = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True,
                                text=True, timeout=15, check=True)
        tracked = set(result.stdout.split("\0"))
    return {p for p, _, _ in files if p not in tracked and _PYTEST_OUTPUT_PATH.fullmatch(p)}


def _input_drift(before: dict | None, after: dict | None, files_before: list | None,
                 files_after: list | None, outputs: set[str]) -> dict:
    old = {p: (mode, sha) for p, mode, sha in files_before or []}
    new = {p: (mode, sha) for p, mode, sha in files_after or []}
    return {"before": before, "after": after,
            "changed_components": [k for k in sorted((before or {}).keys() | (after or {}).keys())
                                   if (before or {}).get(k) != (after or {}).get(k)],
            "changed_paths": [{"path": p, "role": "output" if p in outputs else "input",
                               "before": old.get(p), "after": new.get(p)}
                              for p in sorted(old.keys() | new.keys()) if old.get(p) != new.get(p)]}


def _semantic_inputs(inputs: dict | None, files: list | None, outputs: set[str]) -> dict | None:
    return {**inputs, "tree": digest([entry for entry in cast(list, files) if entry[0] not in outputs])} if inputs else None


def load(path: str | Path) -> dict:
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def state_root(root: str | Path) -> Path:
    """Общий sidecar checkout/worktrees вне судимого дерева и вне Git metadata.

    Путь привязан к каноническому common-dir. Обычный checkout тоже не должен
    становиться dirty из-за собственных receipts; .git/config/index не меняются.
    """
    root = Path(root).resolve()
    if (root / ".git").exists():
        result = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=root,
                                capture_output=True, text=True, timeout=15, check=True)
        common = Path(result.stdout.strip())
        common = (common if common.is_absolute() else root / common).resolve()
        return common.parent.parent / ".ai-ops-kit-state" / digest(str(common))
    return root


def reusable(record: dict, inputs: dict | None) -> bool:
    return bool(inputs and record.get("schema_version") == 1
                and record.get("inputs") == inputs and record.get("status") == "PASS"
                and type(record.get("exit_code")) is int and record["exit_code"] == 0
                and record.get("completed_at")
                and record.get("evidence_digest") == digest({
                    "inputs": inputs, "status": "PASS", "exit_code": 0}))


def run(root: str | Path, check: str, command: object, execute: Callable[[], dict],
        context_factory: Callable[[], dict], *, scope: str = "local", extra: object = None,
        output_contract: str | None = None) -> dict:
    """Исполнитель вызывается только при отсутствии пригодного PASS; без raw output на диске.

    execute -> {status, exit_code}. Policy/preflight проверяется ВЫЗЫВАТЕЛЕМ до run,
    даже при reuse. После исполнения повторно сверяем входы: меняющий их тест не кешируется.
    """
    if output_contract not in (None, PYTEST_OUTPUTS):
        raise ValueError("неподдерживаемый output contract")
    inputs, basis, files = _capture_inputs(root, command, context_factory(), scope=scope,
                                          extra=extra, output_contract=output_contract)
    outputs_before = _output_paths(root, files, output_contract)
    path = state_root(root) / ".ai/runtime/verification" / (digest([scope, check, command]) + ".json")
    previous = load(path)
    if reusable(previous, inputs):
        return {**previous, "reused": True, "source": str(path), "reason": basis}
    if not inputs:
        reason = basis
    elif not previous:
        reason = "нет проверяемого результата"
    elif previous.get("inputs") != inputs:
        reason = "изменились значимые входы/зависимости/flags/контекст"
    else:
        reason = f"предыдущий результат {previous.get('status', 'неполный')} не разрешает пропуск"
    result = execute()
    status, code = result.get("status", "NOT_RUN"), result.get("exit_code")
    if status not in STATUSES or (status == "PASS" and (type(code) is not int or code != 0)):
        status = "BLOCKED"
    after, _, files_after = _capture_inputs(root, command, context_factory(), scope=scope,
                                            extra=extra, output_contract=output_contract)
    outputs = outputs_before | _output_paths(root, files_after, output_contract)
    stable = inputs is not None and _semantic_inputs(inputs, files, outputs) == _semantic_inputs(after, files_after, outputs)
    if inputs is not None and not stable:
        status = "BLOCKED"
        reason = "значимые входы изменились во время исполнения; результат неприменим"
    elif stable and inputs != after:
        reason += "; изменились только объявленные outputs; PASS привязан к их фактическому содержимому после исполнения"
    record = {"schema_version": 1, "inputs": after if stable else None,
              "status": status, "exit_code": code,
              "completed_at": datetime.now(timezone.utc).isoformat(),
              "evidence_digest": digest({"inputs": after, "status": status, "exit_code": code})
              if stable else None,
              "input_observation": _input_drift(inputs, after, files, files_after, outputs)}
    atomic_json(path, record)
    return {**record, "reused": False, "source": str(path), "reason": reason,
            "reuse_eligible": stable, "input_stability": "stable" if stable else "unproven"}


def python_context(root: str | Path | None = None, *, isolated_stdlib: bool = False) -> dict:
    """Content adapter для локального Python Kit, не для произвольного product build.

    Хеширует установленные файлы, стандартную библиотеку, интерпретатор, ruff/bash.
    Среда только общим digest: значения и имена секретов не записываются.
    isolated_stdlib допустим только для команд с -I -S без внешних пакетов.
    """
    import importlib.metadata
    import shutil
    import sys
    import sysconfig
    from urllib.parse import urlparse, unquote
    try:
        root = Path(root or Path.cwd()).resolve()
        packages = []
        for dist in ([] if isolated_stdlib else importlib.metadata.distributions()):
            if dist.files is None:
                return {"complete": False}
            direct = dist.read_text("direct_url.json")
            if direct:
                editable = json.loads(direct)
                if editable.get("dir_info", {}).get("editable"):
                    source = Path(unquote(urlparse(editable.get("url", "")).path)).resolve()
                    if source != root:
                        return {"complete": False}  # внешний mutable editable не исследован
            for f in dist.files:
                p = Path(str(dist.locate_file(f)))
                if p.suffix != ".pyc" and p.is_file():
                    packages.append((str(p), file_digest(p)))
        stdlib = Path(sysconfig.get_path("stdlib"))
        tools = [(sys.executable, file_digest(sys.executable))]
        for name in ("python3", "ruff", "bash", "git"):
            exe = shutil.which(name)
            if exe:
                tools.append((exe, file_digest(exe)))
        # site-packages уже учтены через metadata; stdlib — отдельный вход.
        for directory, dirs, names in os.walk(stdlib):
            dirs[:] = sorted(d for d in dirs if d not in {"site-packages", "__pycache__"})
            for name in sorted(names):
                p = Path(directory) / name
                if p.suffix in {".py", ".so", ".dylib"}:
                    tools.append((str(p), file_digest(p)))
        for entry in ([] if isolated_stdlib else sys.path):
            p = Path(entry or Path.cwd()).resolve()
            if p.exists() and not any(p.is_relative_to(base) for base in
                                     (root, stdlib.resolve(), Path(sys.prefix).resolve())):
                return {"complete": False}
        git_config = subprocess.check_output(["git", "config", "--list", "--show-origin", "--null"], cwd=root, timeout=15)
        return {"complete": True, "toolchain": digest([sys.version, sys.platform, tools, git_config.hex()]),
                "dependencies": digest(sorted(set(packages))),
                "environment": environment_digest(),
                "adapter": "isolated-stdlib-only" if isolated_stdlib else "python-kit"}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"complete": False}
