"""Каждый гейт машиночитаемо отвечает «какую ошибку он предотвращает» — ратчет (#636, поверх #616).

ПОВОД — ВНЕШНЕЕ ПРОДУКТОВОЕ РЕВЮ 08.09.2026 (п.13). Прополка #616 уже дала по каждому advisory-гейту
ЯВНОЕ решение данными (`quality/gates.yaml` → `advisory_review`). Чего не хватало структурно:
failure mode жил ТОЛЬКО прозой в `purpose` («Класс: непроверенное исправление»), а false-positive
rate — булевым `field_evidence` + числом в комментарии. Нельзя было машинно спросить «что гейт
предотвращает и с какой частотой ложных».

ЧТО ЗДЕСЬ. Ратчет на два инлайн-поля каждого гейта:
  * `prevents` — класс дефекта (короткий ключ, вынесен из прозы purpose). Гейт без ответа —
    кандидат на снятие: так через год не заводится «Gate Garden».
  * `evidence` — {field, false_positives}. field ∈ proven|by_construction|human_by_nature|pending;
    false_positives — целое ТОЛЬКО при field: proven (наблюдение), иначе unavailable (честность как
    в usage_ledger: неизвестное = unavailable, никогда 0).

МЕХАНИЗМ РАТЧЕТА. НОВЫЙ blocking-гейт без непустого `prevents` краснеет; advisory-гейт обязан нести
и `evidence.field` (его «план» — статус поля: proven/by_construction/human_by_nature/pending). Поле
`field: proven` сверяется с `advisory_review.field_evidence: true` — два представления не вправе
разойтись молча. Границы (§26): структуризация уже принятых решений, поверхность гейтов НЕ растёт.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.gates.gate_executor import load_gates
from ai_ops_kit.validation import validate_required_contexts as contexts

PKG_ROOT = Path(__file__).resolve().parents[2]

VOCAB = {"proven", "by_construction", "human_by_nature", "pending"}

GATES = load_gates()
OWNERS = {a["id"] for a in yaml.safe_load((PKG_ROOT / "registry/agents.yaml").read_text())["agents"]}
_DOC = yaml.safe_load((PKG_ROOT / "quality" / "gates.yaml").read_text(encoding="utf-8"))
DECISIONS = (_DOC.get("advisory_review") or {}).get("decisions") or {}


def lifecycle_errors(ident, record):
    if not isinstance(record, dict):
        return [f"{ident}: нет метаданных владельца/вывода"]
    errors = []
    for key in ("responsible_role", "retirement_condition"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            errors.append(f"{ident}: обязательная проверка без {key}")
        elif record[key].strip().casefold() in {"todo", "tbd", "unknown", "unavailable"}:
            errors.append(f"{ident}: {key} содержит заглушку")
    if isinstance(record.get("responsible_role"), str) and record["responsible_role"] not in OWNERS:
        errors.append(f"{ident}: responsible_role не объявлена в registry/agents.yaml")
    return errors


mandatory_ci_checks = contexts.mandatory_contexts


def audit_ci_lifecycle(required, metadata):
    if not isinstance(metadata, dict):
        return ["required_checks_lifecycle: нет метаданных CI"]
    errors = []
    for name in sorted(required | set(metadata)):
        if name not in required:
            errors.append(f"{name}: метаданные снятой обязательной проверки надо удалить")
        else:
            errors.extend(lifecycle_errors(name, metadata.get(name)))
    return errors


def audit(gates: dict, decisions: dict) -> list[str]:
    """Единая проверка: и живые тесты, и пробы прогоняют её. Возвращает список ошибок."""
    errs: list[str] = []
    for gid, g in gates.items():
        if g.get("blocking"):
            errs.extend(lifecycle_errors(gid, g))
        prevents = g.get("prevents")
        if not (isinstance(prevents, str) and prevents.strip()):
            kind = "blocking" if g.get("blocking") else "advisory"
            errs.append(f"{gid} ({kind}): пустой prevents — гейт не отвечает, что предотвращает")
        ev = g.get("evidence")
        if not isinstance(ev, dict):
            errs.append(f"{gid}: нет evidence {{field, false_positives}}")
            continue
        field = ev.get("field")
        if field not in VOCAB:
            errs.append(f"{gid}: evidence.field='{field}' вне словаря {sorted(VOCAB)}")
        fp = ev.get("false_positives")
        # честность: целое ТОЛЬКО при field: proven; иначе строго 'unavailable' (никогда 0)
        if isinstance(fp, bool) or not (isinstance(fp, int) or fp == "unavailable"):
            errs.append(f"{gid}: false_positives={fp!r} — целое (наблюдение) или 'unavailable'")
        elif isinstance(fp, int) and field != "proven":
            errs.append(f"{gid}: целое false_positives при field='{field}' — наблюдение бывает "
                        f"только у proven; неизвестное = unavailable, никогда 0")
    # синхронизация с прополкой #616: field: proven <-> field_evidence: true
    for gid, dec in decisions.items():
        if dec.get("decision") == "removed":
            continue
        if gid not in gates:
            errs.append(f"advisory_review называет '{gid}', которого нет в gates")
            continue
        proven = (gates[gid].get("evidence") or {}).get("field") == "proven"
        if bool(dec.get("field_evidence")) != proven:
            errs.append(f"{gid}: field_evidence={dec.get('field_evidence')} расходится с "
                        f"evidence.field (proven={proven})")
    return errs


@pytest.mark.contract
def test_the_registry_answers_what_each_gate_prevents():
    assert audit(GATES, DECISIONS) == [], "\n  - ".join([""] + audit(GATES, DECISIONS))


@pytest.mark.contract
def test_every_blocking_gate_names_a_defect_class():
    """Инвариант ревю: blocking-гейт без непустого prevents недопустим."""
    for gid, g in GATES.items():
        if g.get("blocking"):
            assert (g.get("prevents") or "").strip(), f"{gid}: blocking без prevents"


@pytest.mark.contract
def test_every_advisory_gate_carries_an_evidence_field():
    """Advisory без evidence.field = гейт без плана: краснеет как ратчет."""
    for gid, g in GATES.items():
        if not g.get("blocking"):
            assert (g.get("evidence") or {}).get("field") in VOCAB, f"{gid}: advisory без evidence.field"


@pytest.mark.contract
def test_false_positive_zero_is_never_fabricated():
    """0 ложных допустим только как наблюдение (field: proven), не как удобный дефолт."""
    for gid, g in GATES.items():
        ev = g.get("evidence") or {}
        if isinstance(ev.get("false_positives"), int):
            assert ev.get("field") == "proven", f"{gid}: число ложных без полевого evidence"


# ─── пробы: реестр обязан краснеть ──────────────────────────────────────────────────────────────

@pytest.mark.contract
def test_a_blocking_gate_without_prevents_is_caught():
    g = copy.deepcopy(GATES)
    g["security"]["prevents"] = ""
    assert any("security" in e and "prevents" in e for e in audit(g, DECISIONS))


@pytest.mark.contract
@pytest.mark.parametrize("field", ["responsible_role", "retirement_condition"])
def test_new_blocking_gate_without_owner_or_retirement_is_caught(field):
    gates = copy.deepcopy(GATES)
    gates["new_blocking_gate"] = {**gates["security"], "id": "new_blocking_gate",
                                  "retirement_condition": "После снятия риска и решения владельца."}
    gates["new_blocking_gate"].pop(field, None)
    assert field not in gates["new_blocking_gate"]  # реестр действительно испорчен
    assert any("new_blocking_gate" in e and field in e for e in audit(gates, DECISIONS))


@pytest.mark.contract
def test_new_blocking_gate_with_real_owner_and_retirement_passes():
    gates = copy.deepcopy(GATES)
    gates["new_blocking_gate"] = {**gates["security"], "id": "new_blocking_gate",
                                  "retirement_condition": "Риск устранён эквивалентной проверкой."}
    assert audit(gates, DECISIONS) == []


@pytest.mark.contract
@pytest.mark.parametrize("condition", ["", " ", None, False, "TODO", "unknown"])
def test_retirement_is_a_condition_not_a_placeholder(condition):
    gates = copy.deepcopy(GATES)
    gates["security"]["retirement_condition"] = condition
    assert any("security" in e and "retirement_condition" in e for e in audit(gates, DECISIONS))


@pytest.mark.contract
def test_gate_owner_must_be_a_declared_role():
    gates = copy.deepcopy(GATES)
    gates["security"]["responsible_role"] = "nonexistent-owner"
    assert any("security" in e and "responsible_role" in e for e in audit(gates, DECISIONS))


@pytest.mark.contract
def test_declared_mandatory_ci_checks_have_owner_and_retirement():
    required, errors = mandatory_ci_checks(PKG_ROOT)
    assert errors == []
    assert audit_ci_lifecycle(required, _DOC.get("required_checks_lifecycle")) == []


@pytest.mark.contract
@pytest.mark.parametrize("field", ["responsible_role", "retirement_condition"])
def test_new_mandatory_ci_check_needs_owner_and_retirement(field):
    metadata = {"new / check": dict(_DOC["required_checks_lifecycle"]["docs / build"])}
    metadata["new / check"].pop(field)
    assert field not in metadata["new / check"]
    assert any(field in e for e in audit_ci_lifecycle({"new / check"}, metadata))


@pytest.mark.contract
@pytest.mark.parametrize("declaration", ["premerge", "required-contexts"])
def test_real_ci_declaration_change_requires_lifecycle_without_writing(tmp_path, declaration):
    quality = tmp_path / "quality"
    quality.mkdir()
    wf = tmp_path / ".github/workflows"
    wf.mkdir(parents=True)
    (wf / "docs.yml").write_text(yaml.safe_dump({"jobs": {"build": {}, "new": {}}}))
    (quality / "required-contexts.yaml").write_text(yaml.safe_dump({"contexts": ["docs / build"]}))
    path = quality / "premerge-checks.json"
    path.write_text(json.dumps({"docs.yml": ["build"]}))
    metadata = {"docs / build": _DOC["required_checks_lifecycle"]["docs / build"]}
    required, errors = mandatory_ci_checks(tmp_path)
    assert errors == [] and audit_ci_lifecycle(required, metadata) == []
    target = path if declaration == "premerge" else quality / "required-contexts.yaml"
    old = target.read_bytes()
    if declaration == "premerge":
        target.write_text(json.dumps({"docs.yml": ["build", "new"]}))
    else:
        target.write_text(yaml.safe_dump({"contexts": ["docs / build", "docs / new"]}))
    assert target.read_bytes() != old
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    required, errors = mandatory_ci_checks(tmp_path)
    assert errors == [] and "docs / new" in required
    assert any("docs / new" in e for e in audit_ci_lifecycle(required, metadata))
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.contract
def test_an_advisory_gate_without_evidence_field_is_caught():
    g = copy.deepcopy(GATES)
    g["release_safety"]["evidence"] = {"false_positives": "unavailable"}
    assert any("release_safety" in e and "field" in e for e in audit(g, DECISIONS))


@pytest.mark.contract
def test_a_fabricated_zero_false_positive_is_caught():
    g = copy.deepcopy(GATES)
    g["documentation_updated"]["evidence"] = {"field": "by_construction", "false_positives": 0}
    assert any("documentation_updated" in e and "false_positives" in e for e in audit(g, DECISIONS))


@pytest.mark.contract
def test_desync_with_advisory_review_is_caught():
    """Флип field_evidence без обновления гейта (или наоборот) — красное."""
    g = copy.deepcopy(GATES)
    g["contour_consistency"]["evidence"] = {"field": "pending", "false_positives": "unavailable"}
    assert any("contour_consistency" in e and "field_evidence" in e for e in audit(g, DECISIONS))


@pytest.mark.contract
def test_a_prevents_added_out_of_thin_air_for_a_missing_gate_is_caught():
    """advisory_review не вправе называть гейт, которого в реестре нет."""
    g = copy.deepcopy(GATES)
    dec = copy.deepcopy(DECISIONS)
    dec["ghost_gate"] = {"decision": "justified_advisory", "field_evidence": True}
    assert any("ghost_gate" in e for e in audit(g, dec))
