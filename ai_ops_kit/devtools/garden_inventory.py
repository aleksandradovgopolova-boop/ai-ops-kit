"""Ограниченный структурный инвентарь существующего garden; кандидаты, не вердикты удаления."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path

import yaml

from ai_ops_kit.validation.validate_required_contexts import mandatory_contexts

SIGNALS = ("duplicate_documents", "unreferenced_agents", "stale_rules",
           "conflicting_declarations", "duplicate_checks", "retirement_gaps")
_ROLE_FIELDS = {"owner", "writer", "agent", "agent_id", "reviewer", "reviewers",
                "responsible_role", "used_by", "agents"}


def _safe(root: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        raise ValueError(f"некорректный путь в инвентаре: {rel!r}")
    path = root / rel
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"путь выходит за корень инвентаря: {rel}")
    return path


def _doc(root: Path, rel: str) -> dict:
    doc = yaml.safe_load(_safe(root, rel).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{rel}: ожидается YAML-отображение")
    return doc


def _rows(doc: dict, key: str) -> list[dict]:
    rows = doc.get(key)
    if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get("id"), str)
                                         or not r["id"].strip() for r in rows):
        raise ValueError(f"{key}: ожидается список объявлений")
    return rows


def _sources(root: Path, rel: str, ident=None) -> list[dict]:
    path = _safe(root, rel)
    if not path.is_file():
        raise ValueError(f"источник инвентаря не файл: {rel}")
    lines = path.read_text(encoding="utf-8").splitlines()
    found = []
    for index, line in enumerate(lines, 1):
        key, _, value = line.strip().removeprefix("- ").partition(":")
        if ident and key == "id" and value.strip().strip("'\"") == str(ident):
            found.append({"path": rel, "line": index})
    return found or [{"path": rel, "line": 1}]


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _role_refs(value) -> set[str]:
    refs = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _ROLE_FIELDS:
                refs.update(_strings(child))
            else:
                refs.update(_role_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(_role_refs(child))
    return refs


def _documents(root: Path) -> list[dict]:
    groups = defaultdict(list)
    for directory, pattern in (("skills", "**/SKILL.md"), ("workflows", "**/*.md")):
        base = _safe(root, directory)
        if not base.is_dir():
            raise ValueError(f"нет каталога инвентаря: {directory}")
        for path in sorted(base.glob(pattern)):
            rel = path.relative_to(root).as_posix()
            path = _safe(root, rel)
            if path.is_symlink():
                continue  # внутренний alias — не физическая копия
            text = path.read_text(encoding="utf-8")
            if text.strip():
                # Только newline/пустые завершающие строки; отступы кода и остальные пробелы значимы.
                normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"
                digest = hashlib.sha256(normalized.encode()).hexdigest()
                groups[digest].append({"path": rel, "line": 1})
    return [{"sha256": digest, "sources": sources,
             "reason": "совпадает текст; проверить назначение перед консолидацией"}
            for digest, sources in sorted(groups.items()) if len(sources) > 1]


def _conflicts(root: Path, declarations: list[tuple[dict, str]]) -> list[dict]:
    grouped = defaultdict(list)
    for row, rel in declarations:
        ident = row.get("id")
        if isinstance(ident, str) and ident:
            grouped[ident].append((row, rel))
    return [{"id": ident, "sources": [s for _, rel in members for s in _sources(root, rel, ident)],
             "reason": "один id имеет разные структурные объявления; требуется сверка"}
            for ident, members in sorted(grouped.items())
            if len({yaml.safe_dump(row, sort_keys=True) for row, _ in members}) > 1]


def _stale(root: Path, rows: list[dict], rel: str) -> list[dict]:
    replaced = {}
    for row in rows:
        for ident in _strings(row.get("supersedes")):
            replaced[ident] = row.get("id")
    out = []
    for row in rows:
        ident = row.get("id")
        retired = row.get("status") in ("retired", "deprecated", "superseded")
        successor = replaced.get(ident) or row.get("superseded_by")
        if retired or successor:
            out.append({"id": ident, "sources": _sources(root, rel, ident),
                        "reason": f"явно заменено: {successor}" if successor else "явно снято/устарело"})
    return out


def _checks(root: Path, gates: dict) -> list[dict]:
    groups = defaultdict(list)
    for ident, gate in sorted(gates.items()):
        if not isinstance(gate, dict):
            raise ValueError(f"quality/gates.yaml: {ident} не отображение")
        if not gate.get("validator"):
            continue  # ручные суждения не считаем одинаковыми по отсутствию validator
        signature = {k: v for k, v in gate.items()
                     if k not in {"id", "purpose", "retirement_condition", "evidence", "advisory_review"}}
        for key in ("applicability", "required_evidence"):
            if isinstance(signature.get(key), list) and all(isinstance(v, str) for v in signature[key]):
                signature[key] = sorted(signature[key])
        groups[yaml.safe_dump(signature, sort_keys=True)].append(ident)
    return [{"ids": ids, "sources": [s for ident in ids
             for s in _sources(root, "quality/gates.yaml", ident)],
             "reason": "совпадают validator, область и контракт; проверить скрытые параметры"}
            for ids in groups.values() if len(ids) > 1]


def _retirement(root: Path, gates: dict, owners: set[str]) -> list[dict]:
    out = []
    for ident, gate in sorted(gates.items()):
        if gate.get("blocking"):
            missing = [key for key in ("responsible_role", "retirement_condition")
                       if not isinstance(gate.get(key), str) or not gate[key].strip()
                       or gate[key].strip().casefold() in {"todo", "tbd", "unknown", "unavailable"}]
            owner = gate.get("responsible_role")
            if (not isinstance(owner, str) or owner not in owners) and "responsible_role" not in missing:
                missing.insert(0, "responsible_role")
            if missing:
                out.append({"id": ident, "missing": missing,
                            "sources": _sources(root, "quality/gates.yaml", ident)})
    return out


def _ci_lifecycle(root: Path, doc: dict, owners: set[str]) -> tuple[list, list]:
    for rel in ("quality/premerge-checks.json", "quality/required-contexts.yaml"):
        _safe(root, rel)
    workflow_dir = _safe(root, ".github/workflows")
    for path in [*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")]:
        _safe(root, path.relative_to(root).as_posix())
    names, errors = mandatory_contexts(root)
    if errors:
        raise ValueError("; ".join(errors))
    policy = doc.get("required_checks_lifecycle")
    if not isinstance(policy, dict) or any(not isinstance(v, dict) for v in policy.values()):
        raise ValueError("required_checks_lifecycle: ожидается отображение")
    gates = {name: {**policy.get(name, {}), "blocking": True} for name in sorted(names)}
    stale = [{"id": name, "sources": _sources(root, "quality/gates.yaml"),
              "reason": "метаданные CI-проверки, которой больше нет в обязательных декларациях"}
             for name in sorted(set(policy) - names)]
    return _retirement(root, gates, owners), stale


def collect(root) -> dict:
    """Read-only inventory из известных источников; ошибки чтения/формы не превращаются в []."""
    root = Path(root).resolve()
    agents = _rows(_doc(root, "registry/agents.yaml"), "agents")
    workflows = _doc(root, "registry/workflows.yaml").get("workflows")
    gates_doc = _doc(root, "quality/gates.yaml")
    gates = gates_doc.get("gates")
    if (not isinstance(workflows, dict) or not isinstance(gates, dict)
            or any(not isinstance(v, dict) for v in [*workflows.values(), *gates.values()])):
        raise ValueError("workflows/gates: ожидается отображение")
    refs = _role_refs([workflows, gates_doc, _doc(root, "registry/routing-policy.yaml")])
    conflicts = _conflicts(root, [(a, "registry/agents.yaml") for a in agents])
    stale = []
    rule_docs = []
    rule_dir = _safe(root, "rules")
    if not rule_dir.is_dir():
        raise ValueError("нет каталога инвентаря: rules")
    for path in sorted(rule_dir.glob("**/*.yaml")):
        rel = path.relative_to(root).as_posix()
        doc = _doc(root, rel)
        refs.update(_role_refs(doc))
        stale.extend(_stale(root, [doc], rel))
        rule_docs.append((doc, rel))
    conflicts.extend(_conflicts(root, rule_docs))
    for rel, keys in (("standards/architecture/rules.yaml", ("rules",)),
                      ("decisions/registry.yaml", ("principles", "episodes"))):
        doc = _doc(root, rel)
        for key in keys:
            rows = _rows(doc, key)
            conflicts.extend(_conflicts(root, [(row, rel) for row in rows]))
            stale.extend(_stale(root, rows, rel))
    unreferenced = [{"id": a.get("id"), "sources": _sources(root, a.get("file") or "registry/agents.yaml"),
                     "reason": "нет ссылки в workflow/gates/routing/rules; ручной вызов не исключён"}
                    for a in agents if a.get("id") not in refs]
    owners = {a["id"] for a in agents}
    ci_gaps, ci_stale = _ci_lifecycle(root, gates_doc, owners)
    return {"duplicate_documents": _documents(root), "unreferenced_agents": unreferenced,
            "stale_rules": stale + ci_stale, "conflicting_declarations": conflicts,
            "duplicate_checks": _checks(root, gates),
            "retirement_gaps": _retirement(root, gates, owners) + ci_gaps,
            "limits": ["Произвольная семантика прозы не измеряется: только точные копии и явные объявления.",
                       "Отсутствие статической ссылки не доказывает отсутствие ручного использования.",
                       "Кандидаты требуют решения владельца; автоматического удаления нет."]}
