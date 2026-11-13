"""Выражения workflow GitHub, которые убивают ВЕСЬ файл: контекст там, где он недоступен (#1409).

ЗАЧЕМ. `${{ runner.temp }}` в `env` уровня job сделал ручной замер производительности невозможным:
GitHub отвергал файл целиком, ручной dispatch не появлялся, а каждый push давал красный «прогон»
за 0 с. YAML при этом корректен, bash и Python в шагах — тоже; тесты разбора такого не видят.

ЧТО. Ключи уровня workflow/job (`env`, `runs-on`, `if`, `concurrency`) сверяются с таблицей
доступности контекстов GitHub. Уровень шага не проверяется: там `runner`/`steps` разрешены, а
ошибка в шаге не убивает файл — её покажет сам прогон.

  python -m ai_ops_kit.devtools.workflow_contexts [ФАЙЛ.yml ...]
По умолчанию — `.github/workflows/*.yml` и `templates/ci/*.yml`. Возврат: 0 — чисто, 1 — находки.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parents[2]
DEFAULT_GLOBS = (".github/workflows/*.yml", "templates/ci/*.yml")

# https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability
WORKFLOW_ENV = frozenset({"github", "secrets", "inputs", "vars"})
JOB_ALLOWED = {
    "env": frozenset({"github", "needs", "strategy", "matrix", "vars", "secrets", "inputs"}),
    "runs-on": frozenset({"github", "needs", "strategy", "matrix", "vars", "inputs"}),
    "if": frozenset({"github", "needs", "vars", "inputs"}),
    "concurrency": frozenset({"github", "needs", "strategy", "matrix", "inputs", "vars"}),
}
_EXPR = re.compile(r"\$\{\{(.*?)\}\}", re.S)
_QUOTED = re.compile(r"'(?:[^']|'')*'")
# Имя контекста — идентификатор перед `.`/`[`, который не продолжает другое имя (`full-gate.result`).
_CONTEXT = re.compile(r"(?<![\w.-])([A-Za-z_][\w-]*)\s*[.\[]")


def used_contexts(value, bare_expression: bool = False) -> set[str]:
    """Имена контекстов в выражениях значения (строки, списки, словари — рекурсивно).

    bare_expression — значение целиком выражение без `${{ }}` (так GitHub читает `if`).
    """
    if isinstance(value, dict):
        return set().union(*(used_contexts(v, bare_expression) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(used_contexts(v, bare_expression) for v in value))
    if not isinstance(value, str):
        return set()
    expressions = _EXPR.findall(value) or ([value] if bare_expression else [])
    return {m for e in expressions for m in _CONTEXT.findall(_QUOTED.sub("''", e))}


def violations(doc) -> list[str]:
    """Находки одного разобранного workflow: `<место>: <контекст>`."""
    if not isinstance(doc, dict):
        return []
    found = [f"env: {c}" for c in sorted(used_contexts(doc.get("env") or {}) - WORKFLOW_ENV)]
    jobs = doc.get("jobs") if isinstance(doc.get("jobs"), dict) else {}
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for key, allowed in JOB_ALLOWED.items():
            if key in job:
                bad = used_contexts(job[key], bare_expression=key == "if") - allowed
                found += [f"jobs.{job_id}.{key}: {c}" for c in sorted(bad)]
    return found


def check_files(paths) -> dict[str, list[str]]:
    """{путь: находки} только для файлов с находками. Неразбираемый YAML — тоже находка."""
    result = {}
    for path in paths:
        try:
            found = violations(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            found = [f"не читается: {type(exc).__name__}"]
        if found:
            result[str(path)] = found
    return result


def default_paths(root: Path = KIT) -> list[Path]:
    return sorted(p for pattern in DEFAULT_GLOBS for p in root.glob(pattern))


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    paths = [Path(a) for a in args] or default_paths()
    bad = check_files(paths)
    for path, found in bad.items():
        for item in found:
            print(f"{path}: {item} — контекст недоступен на этом уровне, GitHub отвергнет файл целиком")
    print(f"WORKFLOW-CONTEXTS: {'находок ' + str(sum(map(len, bad.values()))) if bad else 'OK'} "
          f"(файлов {len(paths)})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
