#!/usr/bin/env python3
"""Сверка декларации required checks с workflow и классической защитой GitHub.

Без данных GitHub результат защиты — unknown (exit 2), а не PASS.
--github-repo OWNER/REPO читает только GET branches/<branch> и .../protection через gh.
--github-snapshot FILE воспроизводит проверку по сохранённым ответам (не live-аудит).
Snapshot: repository, branch, branch_response и protection_response; каждый ответ
содержит status (HTTP code) и body (JSON object). Неполный/недоступный ответ даёт unknown.
Проверка contexts не подтверждает rulesets, исключения и права обхода.
"""
from __future__ import annotations

import itertools
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import yaml


def _workflow_dir(root: Path) -> Path:
    return root / ".github" / "workflows"


def _contexts_file(root: Path) -> Path:
    return root / "quality" / "required-contexts.yaml"


def _matrix_combinations(matrix: object) -> list[dict]:
    if not isinstance(matrix, dict):
        raise ValueError("dynamic/invalid matrix")
    axes = {k: v for k, v in matrix.items() if k not in ("include", "exclude")}
    if any(not isinstance(v, list) for v in axes.values()):
        raise ValueError("dynamic/invalid matrix axis")
    original = [dict(zip(axes, values)) for values in itertools.product(*axes.values())] if axes else []
    exclusions = matrix.get("exclude", [])
    if not isinstance(exclusions, list) or any(not isinstance(x, dict) for x in exclusions):
        raise ValueError("invalid matrix.exclude")
    original = [combo for combo in original
                if not any(all(combo.get(k) == v for k, v in exclusion.items()) for exclusion in exclusions)]
    combinations = [dict(combo) for combo in original]
    additions = matrix.get("include", [])
    if not isinstance(additions, list):
        raise ValueError("invalid matrix.include")
    for addition in additions:
        if not isinstance(addition, dict):
            raise ValueError("invalid matrix.include")
        matches = [i for i, combo in enumerate(original)
                   if all(k not in combo or combo[k] == v for k, v in addition.items())]
        if matches:
            for i in matches:
                combinations[i].update(addition)
        else:
            combinations.append(dict(addition))
    return combinations


def _job_names(job_id: str, job: dict) -> list[tuple[str, set[str]]]:
    strategy = job.get("strategy", {})
    if not isinstance(strategy, dict):
        raise ValueError("invalid strategy")
    matrix = strategy.get("matrix")
    combinations = _matrix_combinations(matrix) if matrix is not None else [{}]
    names = []
    for combo in combinations:
        name = job.get("name")
        if name is not None:
            if not isinstance(name, str):
                raise ValueError("invalid job name")
            for key, value in combo.items():
                name = re.sub(r"\$\{\{\s*matrix\." + re.escape(key) + r"\s*\}\}",
                              lambda _, value=value: str(value), name)
            if "${{" in name:
                raise ValueError("unresolved job name")
        else:
            suffix = ", ".join(str(value) for value in combo.values())
            name = f"{job_id} ({suffix})" if suffix else job_id
        aliases = {name}
        # Legacy declaration names only 'group'; resolve to the full GitHub name,
        # retaining ambiguity detection across workflows and matrix combinations.
        if name == job_id:
            aliases.add(job_id)
        if "name" not in job and "group" in combo:
            aliases.add(f"{job_id} ({combo['group']})")
        names.append((name, aliases))
    return names


def _workflow_inventory(workflow_dir: Path) -> tuple[dict, dict, list[str]]:
    by_workflow, aliases, errors = {}, {}, []
    if not workflow_dir.is_dir():
        return {}, {}, ["workflow directory missing"]
    for path in sorted([*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")]):
        try:
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(workflow, dict) or not isinstance(workflow.get("jobs"), dict):
                raise ValueError("jobs must be a mapping")
            names = []
            for job_id, job in workflow["jobs"].items():
                if not isinstance(job, dict):
                    raise ValueError(f"invalid job {job_id}")
                for name, job_aliases in _job_names(job_id, job):
                    qualified = format_context(path.stem, name)
                    names.append(name)
                    for alias in job_aliases:
                        for key in (alias, format_context(path.stem, alias)):
                            aliases.setdefault(key, set()).add(qualified)
            by_workflow[path.stem] = names
        except (OSError, yaml.YAMLError, ValueError, TypeError) as exc:
            errors.append(f"{path.name}: {exc}")
    return by_workflow, aliases, errors


def extract_jobs_from_workflows(workflow_dir: Path) -> dict[str, list[str]]:
    """Имена status checks, включая name и полные matrix suffix; .yml и .yaml."""
    return _workflow_inventory(workflow_dir)[0]


def format_context(workflow_name: str, job_id: str) -> str:
    return f"{workflow_name} / {job_id}"


def load_declared_contexts(root: Path) -> list[str] | None:
    """None означает отсутствующую/некорректную декларацию, никогда успешный skip."""
    try:
        doc = yaml.safe_load(_contexts_file(root).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    contexts = doc.get("contexts") if isinstance(doc, dict) else None
    if (not isinstance(contexts, list) or not contexts
            or any(not isinstance(x, str) or not x.strip() for x in contexts)
            or len(set(contexts)) != len(contexts)):
        return None
    return contexts


def mandatory_contexts(root: Path) -> tuple[set[str], list[str]]:
    """Состав обязательных CI из premerge + required-contexts, с тем же resolver aliases/matrix.

    Только чтение объявлений; это не проверка actual protection и не доказательство CI-успеха.
    Повреждённый источник возвращает ошибки, не пустой успешный состав.
    """
    root = Path(root)
    try:
        doc = json.loads((root / "quality/premerge-checks.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return set(), [f"premerge-checks: {exc}"]
    jobs, aliases, errors = _workflow_inventory(_workflow_dir(root))
    actual = {format_context(w, name) for w, names in jobs.items() for name in names}
    required = set()
    if not isinstance(doc, dict) or not doc:
        return required, ["premerge-checks: неверная декларация"]
    for workflow, names in doc.items():
        if (not isinstance(workflow, str) or Path(workflow).name != workflow
                or Path(workflow).suffix not in {".yml", ".yaml"}
                or not isinstance(names, list) or not names or any(not isinstance(n, str) for n in names)
                or len(set(names)) != len(names)):
            errors.append(f"{workflow}: неверные имена проверок")
            continue
        required.update(format_context(Path(workflow).stem, name) for name in names)
    declared = load_declared_contexts(root)
    if declared is None:
        errors.append("required-contexts: нет годной декларации")
    for name in declared or []:
        matches = aliases.get(name, set())
        if len(matches) != 1:
            errors.append(f"{name}: неизвестный/неоднозначный required context")
        required.update(matches)
    errors.extend(f"{name}: отсутствует CI job" for name in sorted(required - actual))
    return required, errors


def read_github_snapshot(repository: str, branch: str = "main") -> dict:
    """Два bounded GET, без изменений настройки, credentials или fallback при отказе."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must be OWNER/REPO")
    snapshot = {"repository": repository, "branch": branch}
    for key, suffix in (("branch_response", ""), ("protection_response", "/protection")):
        endpoint = f"repos/{repository}/branches/{quote(branch, safe='')}{suffix}"
        try:
            completed = subprocess.run(
                ["gh", "api", "--method", "GET", endpoint], capture_output=True,
                text=True, timeout=30, check=False,
            )
            if completed.returncode:
                # Do not copy raw stderr/token-bearing diagnostics into reports.
                response = {"status": None, "error": "GitHub GET failed"}
                match = re.search(r"HTTP (\d{3})", completed.stderr)
                if match:
                    response["status"] = int(match[1])
            else:
                response = {"status": 200, "body": json.loads(completed.stdout)}
        except (OSError, subprocess.TimeoutExpired, ValueError):
            response = {"status": None, "error": "GitHub GET unavailable or invalid JSON"}
        snapshot[key] = response
    return snapshot


def _response_contexts(response: object, *, summary: bool = False) -> set[str] | None:
    """Только явный HTTP200 с корректной схемой является свидетельством."""
    if not isinstance(response, dict) or response.get("status") != 200:
        return None
    body = response.get("body")
    if not isinstance(body, dict):
        return None
    if summary:
        body = body.get("protection")
        if not isinstance(body, dict):
            return None
    if "required_status_checks" not in body:
        return None
    checks = body["required_status_checks"]
    if checks is None:
        return set()
    if not isinstance(checks, dict):
        return None
    contexts = checks.get("contexts", [])
    applications = checks.get("checks", [])
    if (not isinstance(contexts, list) or not isinstance(applications, list)
            or any(not isinstance(x, str) or not x.strip() for x in contexts)
            or any(not isinstance(x, dict) or not isinstance(x.get("context"), str)
                   or not x["context"].strip() for x in applications)
            or not ({"contexts", "checks"} & checks.keys())):
        return None
    return set(contexts) | {x["context"] for x in applications}


def _emitted_context_index(jobs_by_workflow: dict[str, list[str]]) -> dict[str, set[str]]:
    """Exact GitHub names only; declaration aliases never enter the API lookup."""
    emitted = {}
    for workflow, names in jobs_by_workflow.items():
        for name in names:
            emitted.setdefault(name, set()).add(format_context(workflow, name))
    return emitted


def _compare_protection(declared: list[str], aliases: dict, snapshot: object,
                        emitted_names: dict[str, set[str]]) -> dict:
    result = {"status": "unknown", "contexts": None, "missing_required": [],
              "unexpected_required": [], "unresolved_required": [],
              "message": "GitHub protection evidence not supplied"}
    if (not isinstance(snapshot, dict) or not isinstance(snapshot.get("repository"), str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", snapshot["repository"])
            or not isinstance(snapshot.get("branch"), str) or not snapshot["branch"]):
        return result
    result.update(repository=snapshot["repository"], branch=snapshot["branch"])
    full = _response_contexts(snapshot.get("protection_response"))
    summary = _response_contexts(snapshot.get("branch_response"), summary=True)
    observed = full if full is not None else summary
    result["message"] = "Full branch protection unavailable or malformed"
    if observed is None:
        return result
    result["contexts"] = sorted(observed)
    expected = set().union(*(aliases.get(ctx, set()) for ctx in declared))
    resolved = set()
    for ctx in sorted(observed):
        candidates = emitted_names.get(ctx, set())
        if len(candidates) != 1:
            result["unresolved_required"].append(ctx)
        else:
            resolved.update(candidates)
    result["missing_required"] = sorted(ctx for ctx in declared
                                        if not (aliases.get(ctx, set()) & resolved))
    result["unexpected_required"] = sorted(resolved - expected)
    result["drift_detected"] = bool(result["missing_required"] or result["unexpected_required"]
                                    or result["unresolved_required"])
    if full is not None:
        result["status"] = "fail" if result["drift_detected"] else "pass"
        result["message"] = "Classic branch-protection contexts compared; rulesets/bypasses not audited"
        if summary is not None and summary != full:
            result.update(status="unknown", message="GitHub responses disagree; re-read required")
    return result


def validate(root: Path, *, github_snapshot: dict | None = None) -> dict:
    jobs_by_wf, aliases, errors = _workflow_inventory(_workflow_dir(root))
    actual = sorted(format_context(wf, name) for wf, names in jobs_by_wf.items() for name in names)
    declared = load_declared_contexts(root)
    if declared is None:
        errors.append("quality/required-contexts.yaml missing or invalid")
    missing = sorted(ctx for ctx in declared or [] if ctx not in aliases)
    ambiguous = sorted(ctx for ctx in declared or [] if len(aliases.get(ctx, set())) > 1)
    expected = set().union(*(aliases.get(ctx, set()) for ctx in declared or []))
    workflow_ok = not (errors or missing or ambiguous)
    protection = _compare_protection(
        declared or [], aliases, github_snapshot, _emitted_context_index(jobs_by_wf))
    status = "fail" if not workflow_ok else protection["status"]
    return {"declared": sorted(declared) if declared is not None else None,
            "actual": actual, "missing_jobs": missing, "ambiguous_jobs": ambiguous,
            "undeclared_jobs": sorted(set(actual) - expected), "workflow_errors": errors,
            "workflow_ok": workflow_ok, "protection": protection, "status": status,
            "ok": status == "pass"}


def format_report(result: dict) -> str:
    lines = [f"Workflow: {'pass' if result['workflow_ok'] else 'fail'}",
             f"GitHub branch protection: {result['protection']['status']}",
             result['protection']['message']]
    for key in ("missing_jobs", "ambiguous_jobs", "workflow_errors"):
        if result[key]:
            lines.append(f"{key}: " + "; ".join(result[key]))
    for key in ("missing_required", "unexpected_required", "unresolved_required"):
        if result['protection'][key]:
            lines.append(f"{key}: " + "; ".join(result['protection'][key]))
    lines.append(f"Result: {result['status']}")
    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Repository root")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    ap.add_argument("--selftest", action="store_true", help="Show test location")
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--github-repo", help="Read live classic protection for OWNER/REPO via gh")
    source.add_argument("--github-snapshot", type=Path, help="Read saved API snapshot (not live)")
    ap.add_argument("--branch", default="main")
    args = ap.parse_args()
    if args.selftest:
        print("Проверки валидатора — в tests/contracts/test_required_contexts_match_jobs.py")
        return 0
    snapshot, evidence_error = None, None
    try:
        if args.github_repo:
            snapshot = read_github_snapshot(args.github_repo, args.branch)
        elif args.github_snapshot:
            snapshot = json.loads(args.github_snapshot.read_text(encoding="utf-8"))
            if not isinstance(snapshot, dict) or snapshot.get("branch") != args.branch:
                raise ValueError("snapshot branch mismatch or invalid object")
    except (OSError, ValueError) as exc:
        snapshot = None
        evidence_error = f"GitHub evidence unavailable: {type(exc).__name__}"
    result = validate(Path(args.root).resolve(), github_snapshot=snapshot)
    result["evidence_kind"] = "live" if args.github_repo else "saved-snapshot" if args.github_snapshot else "none"
    if evidence_error:
        result["protection"]["message"] = evidence_error
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else format_report(result))
    return {"pass": 0, "fail": 1, "unknown": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
