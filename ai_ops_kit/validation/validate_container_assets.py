#!/usr/bin/env python3
"""Validate container isolation assets (v2.90, P0.2 runtime jail).

Брокер (tool_broker) даёт enforceable-подмножество ВНУТРИ процесса. Настоящую изоляцию ФС/
ресурсов/привилегий даёт КОНТЕЙНЕР (containers/Dockerfile + run-sandboxed.sh). Этот валидатор
стережёт, чтобы ассеты не растеряли ключевые гарантии jail'а: если кто-то уберёт `--cap-drop`,
`--read-only`, лимиты или non-root — тест упадёт (декларация проверяется, как везде в ките).

ЧЕСТНО: валидатор проверяет маркеры изоляции и статический контракт запуска (COPY, import root,
последний ENTRYPOINT, наличие файла модуля в build context), а не поднимает контейнер.
Сборку/запуск образа выполняет Docker-хост пользователя (в CI-песочнице кита pull базового образа
может быть закрыт egress-прокси).

Использование:
  validate_container_assets.py            # проверить поставляемые containers/*
  validate_container_assets.py --runtime-floor  # фактические версии внутри build; stdlib-only
Возврат 0 — ок, 1 — ошибки.
"""
from __future__ import annotations

import sys
import json
import shlex
import re
import posixpath
import subprocess
from pathlib import Path

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])
REFERENCE_BASE = "node:22-trixie-slim"
REFERENCE_NODE_MAJOR = 22
RUNTIME_CHECK = ["python3", "/opt/ai-ops-kit/ai_ops_kit/validation/validate_container_assets.py", "--runtime-floor"]
# Обязательные маркеры (что гарантирует каждый ассет).
DOCKERFILE_REQUIRED = {
    "FROM ": "базовый образ",
    "USER runner": "non-root пользователь (не root внутри контейнера)",
    "openspec": "OpenSpec CLI для гейта specification",
    "pyyaml": "зависимость движка",
    "/opt/ai-ops-kit": "кит скопирован в образ",
    "ENTRYPOINT": "энтрипоинт движка",
    # Credential-less git для PUSH, зашитый в образ (defense-in-depth — держится и без wrapper'а).
    "GIT_ASKPASS=/bin/false": "нет источника логина/пароля для git push (жёсткая недоставка средой)",
    "GIT_TERMINAL_PROMPT=0": "push по HTTPS без креды падёт быстро, не виснет в промпте",
    "GIT_CONFIG_KEY_0=credential.helper": "credential helper отключён внутри образа (нет креды push)",
}
WRAPPER_REQUIRED = {
    "docker run": "запуск контейнера",
    "--read-only": "root-fs только для чтения",
    "dst=/work": "writable только смонтированный worktree",
    "--tmpfs": "writable временные каталоги без записи на root-fs",
    "--memory": "лимит памяти",
    "--cpus": "лимит CPU",
    "--pids-limit": "лимит процессов",
    "--cap-drop": "сброс Linux capabilities",
    "no-new-privileges": "запрет эскалации привилегий",
    # v2.93 worktree-only: монтируется ОДНОРАЗОВЫЙ клон, а не основной child; доставка — host-слоем
    "git clone": "одноразовый клон child (основной репо не монтируется в контейнер)",
    "src=${CLONE}": "в /work монтируется клон, НЕ основной child-репозиторий",
    # v2.113: доставка вынесена в scoped-deliverer (только ветки прогона) — вызывается из wrapper
    "deliver-run-branches.sh": "доставка ТОЛЬКО веток прогона через scoped host-deliverer",
    # Credential-less git для PUSH (ПЕРВЫЙ рубеж недоставки — среда, не regex block_push).
    "GIT_ASKPASS=/bin/false": "нет источника логина/пароля для git push из модельной петли",
    "GIT_TERMINAL_PROMPT=0": "push по HTTPS без креды падёт быстро, не виснет в промпте",
    "GIT_CONFIG_KEY_0=credential.helper": "credential helper отключён (нет канала креды для push)",
}
# Анти-маркер: основной child НЕ должен монтироваться как writable напрямую (регресс worktree-only).
WRAPPER_FORBIDDEN = {
    "src=${CHILD_ABS},dst=/work": "основной child смонтирован в /work напрямую (нарушает worktree-only; монтируй клон)",
}


def _instructions(text):
    """Только логические инструкции; комментарий не считается настройкой запуска."""
    pending = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pending += line.removesuffix("\\") + " "
        if line.endswith("\\"):
            continue
        parts = pending.strip().split(None, 1)
        yield parts[0].upper(), parts[1] if len(parts) == 2 else ""
        pending = ""
    if pending.strip():
        yield "INCOMPLETE", pending.strip()


def _check_launch_context(root, target_rel):
    root = Path(root).resolve()
    target = root / target_rel
    errors = []
    if not target.is_file() or not target.resolve().is_relative_to(root):
        errors.append(f"Dockerfile: нет launch target {target_rel} внутри build context")
    ignore = root / "containers/Dockerfile.dockerignore"
    if not ignore.is_file():
        ignore = root / ".dockerignore"
    if not ignore.is_file():
        return errors
    # Консервативный контракт: потенциальное исключение target запрещено даже с поздним !.
    # Это не полный Docker evaluator. Классы/однозвёздочные пути расширяются, а не сужаются.
    candidates = [target_rel.as_posix(), *(p.as_posix() for p in target_rel.parents if str(p) != ".")]
    for line in ignore.read_text(encoding="utf-8").splitlines():
        rule = line.strip()
        if not rule or rule.startswith(("#", "!")) or rule == ".":
            continue
        if "\\" in rule:
            errors.append("Dockerfile: .dockerignore с escape-паттерном требует отдельной проверки launch target")
            continue
        rule = posixpath.normpath(rule.strip("/"))
        tokens = re.findall(r"\*\*/|\*|\?|\[[^\]]*\]|.", rule)
        pattern = "(?:.*/)?" + "".join(
            "(?:.*/)?" if t == "**/" else ".*" if t == "*" else "." if t == "?" or t.startswith("[")
            else re.escape(t) for t in tokens)
        if any(re.fullmatch(pattern, candidate) for candidate in candidates):
            errors.append(f"Dockerfile: .dockerignore может исключать launch target {target_rel}: {line}")
    return errors


def _check_launch_target(text, root):
    """Узкий контракт эталонного Dockerfile, без импорта/исполнения его target."""
    errors = []
    instructions = list(_instructions(text))
    if sum(op == "FROM" for op, _ in instructions) != 1:
        errors.append("Dockerfile: контракт запуска поддерживает ровно один FROM (без multi-stage)")
    entries = [arg for op, arg in instructions if op == "ENTRYPOINT"]
    expected = ["python3", "-P", "-m", "ai_ops_kit.engine.ai_ops_run"]
    try:
        entry = json.loads(entries[-1]) if entries else None
    except ValueError:
        entry = None
    if entry != expected:
        errors.append(f"Dockerfile: ENTRYPOINT должен быть {json.dumps(expected)}")
    pythonpath = None
    copied_root = False
    try:
        for op, arg in instructions:
            if op not in {"ENV", "COPY"}:
                continue
            words = shlex.split(arg)
            if op == "COPY" and words == [".", "/opt/ai-ops-kit"]:
                copied_root = True
            if op == "ENV":
                if words and words[0] == "PYTHONPATH":  # legacy ENV key value
                    pythonpath = " ".join(words[1:])
                else:
                    for word in words:
                        key, sep, value = word.partition("=")
                        if key == "PYTHONPATH" and sep:
                            pythonpath = value
    except ValueError:
        errors.append("Dockerfile: не удалось разобрать ENV/COPY контракта запуска")
    if pythonpath != "/opt/ai-ops-kit":
        errors.append("Dockerfile: PYTHONPATH должен быть /opt/ai-ops-kit для запуска из /work")
    if not copied_root:
        errors.append("Dockerfile: нет инструкции COPY . /opt/ai-ops-kit для launch target")
    target_rel = Path("ai_ops_kit/engine/ai_ops_run.py")
    errors += _check_launch_context(root, target_rel)
    if any(op == "INCOMPLETE" for op, _ in instructions):
        errors.append("Dockerfile: незавершённая инструкция контракта запуска")
    return errors


def _check_runtime_contract(text):
    instructions = list(_instructions(text))
    bases = [arg for op, arg in instructions if op == "FROM"]
    defaults = [arg for op, arg in instructions if op == "ARG" and arg.startswith("BASE_IMAGE=")]
    errors = []
    if bases != [REFERENCE_BASE] and not (bases == ["${BASE_IMAGE}"]
                                        and defaults == [f"BASE_IMAGE={REFERENCE_BASE}"]):
        errors.append(f"Dockerfile: reference BASE_IMAGE должен быть {REFERENCE_BASE}")
    copied = False
    guarded = False
    for op, arg in instructions:
        if op == "COPY":
            try:
                copied |= shlex.split(arg) == [".", "/opt/ai-ops-kit"]
            except ValueError:
                errors.append("Dockerfile: не удалось разобрать COPY перед runtime guard")
        if op == "RUN":
            try:
                guarded |= copied and json.loads(arg) == RUNTIME_CHECK
            except ValueError:
                pass  # shell RUN не доказывает fail-closed запуск runtime guard
    if not guarded:
        errors.append("Dockerfile: нет exec-form RUN --runtime-floor после COPY кита")
    if not any(op == "RUN" and "npm_config_engine_strict=true npm i " in arg
               for op, arg in instructions):
        errors.append("Dockerfile: npm install должен проверять engines (npm_config_engine_strict=true)")
    return errors


def check_runtime_versions(python_version, node_version, root=PKG):
    """Проверка фактических версий, без установки пакетов/модели и без записи."""
    try:
        import tomllib
        manifest = tomllib.loads((Path(root) / "pyproject.toml").read_text(encoding="utf-8"))
        spec = manifest["project"]["requires-python"]
        match = re.fullmatch(r">=(\d+)\.(\d+)(?:\.(\d+))?", spec)
        if not match:
            raise ValueError("ожидается requires-python >=major.minor[.patch]")
        floor = tuple(int(n or 0) for n in match.groups())
    except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
        return [f"runtime floor: не удалось прочитать pyproject requires-python: {exc}"]
    errors = []
    if tuple(python_version)[:3] < floor:
        errors.append(f"runtime floor: Python {'.'.join(map(str, python_version))} ниже {spec}")
    node = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", node_version.strip())
    if node is None or int(node.group(1)) != REFERENCE_NODE_MAJOR:
        errors.append(f"runtime floor: нужен Node {REFERENCE_NODE_MAJOR}.x, получен {node_version!r}")
    return errors


def _runtime_main():
    try:
        probe = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5, check=True)
        node_version = probe.stdout.strip()
        errors = check_runtime_versions(tuple(sys.version_info[:3]), node_version)
    except (OSError, subprocess.SubprocessError) as exc:
        errors = [f"runtime floor: Node version probe не выполнен: {exc}"]
    if errors:
        print("CONTAINER-RUNTIME-VERSIONS: ошибки:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"CONTAINER-RUNTIME-VERSIONS-OK: Python {sys.version.split()[0]}, Node {node_version}; "
          "проверены только версии, не выполнение движка или изоляция.")
    return 0


def check_dockerfile(text, root=PKG):
    errors = [f"Dockerfile: нет '{k}' ({why})" for k, why in DOCKERFILE_REQUIRED.items() if k not in text]
    return errors + _check_launch_target(text, root) + _check_runtime_contract(text)


def check_wrapper(text):
    errs = [f"run-sandboxed.sh: нет '{k}' ({why})" for k, why in WRAPPER_REQUIRED.items() if k not in text]
    errs += [f"run-sandboxed.sh: запрещённый паттерн '{k}' ({why})"
             for k, why in WRAPPER_FORBIDDEN.items() if k in text]
    return errs


def check_assets(root=PKG):
    root = Path(root)
    errors = []
    df = root / "containers" / "Dockerfile"
    wr = root / "containers" / "run-sandboxed.sh"
    if not df.exists():
        errors.append("нет containers/Dockerfile")
    else:
        errors += check_dockerfile(df.read_text(encoding="utf-8"), root)
    if not wr.exists():
        errors.append("нет containers/run-sandboxed.sh")
    else:
        errors += check_wrapper(wr.read_text(encoding="utf-8"))
    # v2.113: scoped-deliverer обязателен и должен доставлять ТОЛЬКО ветки прогона (диф снимка)
    dl = root / "containers" / "deliver-run-branches.sh"
    if not dl.exists():
        errors.append("нет containers/deliver-run-branches.sh (scoped-доставка веток прогона)")
    else:
        dtext = dl.read_text(encoding="utf-8")
        for k, why in {"for-each-ref": "снимок ai-ops/* для дифа (доставить только изменённое)",
                       "fetch": "перенос веток прогона в основной репо",
                       "ai-ops/*": "область — только ai-ops/* ветки"}.items():
            if k not in dtext:
                errors.append(f"deliver-run-branches.sh: нет '{k}' ({why})")
    return errors


def main(argv):
    if argv == ["--runtime-floor"]:
        return _runtime_main()
    errs = check_assets()
    if errs:
        print("CONTAINER-ASSETS: ошибки:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("CONTAINER-ASSETS-OK: статический контракт запуска/runtime guard и маркеры изоляции проверены; "
          "сборка/запуск образа и реальная изоляция НЕ проверены.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
