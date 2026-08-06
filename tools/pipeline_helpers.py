#!/usr/bin/env python3
from __future__ import annotations
"""General helper functions for the execution pipeline.

Extracted from execution_pipeline.py — profile summary, intake evidence,
gate checklist, reviewable gates, YAML parsing, openspec validation.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
for _p in (PKG / "tools", PKG / "validation"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import gate_executor  # noqa: E402


def _profile_summary(profile):
    stacks = profile.get("stacks") or []
    langs = ", ".join(s.get("language", "?") for s in stacks) or "не определён"
    cmds = {}
    for s in stacks:
        for k, v in (s.get("commands") or {}).items():
            if v and k not in cmds:
                cmds[k] = v
    return f"Стек: {langs}. Команды проверки: {cmds or 'нет'}."


def _intake_evidence(signals):
    """intake_completeness evidence из сигналов: классификация уже сделана (реальный evidence,
    не фабрикация). Маппинг сигнал->required_evidence-флаг; provided только для присутствующих."""
    sig = signals or {}
    mapping = {"classified_type": "task_type", "size": "size", "risk": "risk"}
    provided = [flag for flag, key in mapping.items() if sig.get(key)]
    if not provided:
        return None
    return {"status": "pass", "provided": provided,
            "evidence": [f"intake из сигналов: {', '.join(provided)}"]}


# v2.85 (finding аудита): гейты, которые НЕЛЬЗЯ закрывать автоматическим ревьюером той же модели —
# слишком консеквентны для self-attestation.
NO_SELF_REVIEW = {"security", "ai_red_team"}


def _reviewable_gates(gate_ids, signals):
    """v2.83/2.85: гейты плана, которые НЕЗАВИСИМЫЙ ревьюер той же модели может закрыть легитимно —
    только ai-review (writer ≠ judge), И НЕ из NO_SELF_REVIEW."""
    gates = gate_executor.load_gates()
    out = []
    for gid in gate_ids:
        if gid in NO_SELF_REVIEW:
            continue
        g = gates.get(gid) or {}
        if gate_executor.classify(g, signals) == "ai-review":
            out.append(gid)
    return out


def _gate_checklist(gate):
    """Короткий чек-лист для ревьюера: required_evidence + ответственная роль."""
    req = gate.get("required_evidence", []) or []
    role = gate.get("responsible_role", "reviewer")
    parts = [f"роль: {role}"]
    if req:
        parts.append("подтверди по факту: " + ", ".join(req))
    return "; ".join(parts)


def _parse_yaml_block(text):
    """Достать YAML-артефакт из ответа author-модели. v3.0-rc5 (finding живого прогона kimi): терпимо к
    РАЗНЫМ стилям вывода моделей — несколько ```-блоков, проза вокруг, YAML без ограды после текста."""
    import yaml
    import re
    if isinstance(text, dict):
        return text
    s = text or ""
    candidates = []
    for m in re.finditer(r"```[ \t]*[A-Za-z0-9]*\n(.*?)```", s, re.S):
        candidates.append(m.group(1))
    for marker in ("schema_version:", "kind:"):
        i = s.find(marker)
        if i >= 0:
            candidates.append(s[i:])
    candidates.append(s)
    for c in candidates:
        try:
            data = yaml.safe_load(c)
        except yaml.YAMLError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _openspec_validate(work_root, change_id):
    """v2.89: прогнать НАСТОЯЩИЙ openspec CLI на произведённом change. -> (available, ok, output)."""
    try:
        r = subprocess.run(["openspec", "validate", change_id, "--strict"],
                           cwd=str(work_root), capture_output=True, text=True, timeout=120,
                           env={**os.environ, "OPENSPEC_TELEMETRY": "0"})
        return True, r.returncode == 0, (r.stdout + r.stderr)[-600:]
    except FileNotFoundError:
        return False, False, "openspec CLI не найден в PATH (npm i -g @fission-ai/openspec)"
    except subprocess.TimeoutExpired:
        return True, False, "openspec validate: timeout"


def _authoring_specs():
    """v2.86: артефакт-гейты, которые движок умеет ЗАКРЫВАТЬ производством артефакта + детерминированной
    проверкой ФОРМЫ (не «качества»). specification обрабатывается ОТДЕЛЬНО."""
    import validate_requirements_artifact as vra
    import validate_plan_artifact as vpa
    return {
        "requirements": ("requirements.yaml", vra, "requirements-artifact",
                         "requirements: список объектов {id, statement (тестируемое требование), "
                         "acceptance: [сценарии приёмки]}"),
        "plan_readiness": ("plan.yaml", vpa, "plan-artifact",
                           "work_packages: [{id, summary, depends_on: [id,...]}], "
                           "write_scope: [пути]"),
    }


def selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    expect("pipeline_helpers: imports work", True)
    expect("pipeline_helpers: _profile_summary is callable", callable(_profile_summary))
    expect("pipeline_helpers: _intake_evidence is callable", callable(_intake_evidence))
    expect("pipeline_helpers: _reviewable_gates is callable", callable(_reviewable_gates))
    expect("pipeline_helpers: _parse_yaml_block is callable", callable(_parse_yaml_block))
    expect("pipeline_helpers: NO_SELF_REVIEW contains security", "security" in NO_SELF_REVIEW)

    print("pipeline_helpers selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(selftest())
