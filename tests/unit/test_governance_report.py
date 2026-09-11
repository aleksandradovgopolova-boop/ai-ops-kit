"""SR-17..23: governance-отчёт соответствия продукта дочки стандарту + override (срез 2).

Проверяется КОНТРАКТ отчёта (четыре числа с суммой, closed_by у каждой строки, override с
причиной/сроком, not_applicable == активные override) и ПРОВОДКА в джобу дочки (одна джоба,
две части, машиночитаемый артефакт, без девятого блокирующего гейта).
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.planning import governance_report as G

PKG = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())
SCHEMA = json.loads((PKG / "schemas" / "governance-report.schema.json").read_text(encoding="utf-8"))
TEMPLATE = PKG / "templates" / "ci" / "ai-ops-validate.yml"
TODAY = dt.date(2026, 9, 7)


def _child(tmp_path, overrides=None) -> Path:
    """Свежая дочка с `.ai-ops.yaml`; overrides — список standard.overrides."""
    cfg = {"schema_version": 1, "kind": "ai-ops-child-config",
           "parent": {"source": "git+x", "installed_version": "1.0.0",
                      "update_channel": "qualification", "update_policy": "pr"},
           "standard": {"version": 1, "profile": "ai-product"}}
    if overrides is not None:
        cfg["standard"]["overrides"] = overrides
    (tmp_path / ".ai-ops.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return tmp_path


# ── SR §3.2: четыре числа, и сумма равна общему ──

@pytest.mark.unit
def test_counts_are_four_states_and_sum_to_total(tmp_path):
    rep = G.build(_child(tmp_path), today=TODAY)
    c = rep["counts"]
    assert set(c) == {"pass", "violated", "not_applicable", "not_checked", "total"}
    assert c["pass"] + c["violated"] + c["not_applicable"] + c["not_checked"] == c["total"]
    assert c["total"] == len(rep["rows"]), "total обязан равняться числу строк"


@pytest.mark.unit
def test_report_matches_schema_shape(tmp_path):
    rep = G.build(_child(tmp_path), today=TODAY)
    for k in SCHEMA["required"]:
        assert k in rep, f"в отчёте нет обязательного по схеме поля {k}"
    assert rep["kind"] == "governance-report" == SCHEMA["properties"]["kind"]["const"]
    row_status = set(SCHEMA["properties"]["rows"]["items"]["properties"]["status"]["enum"])
    for r in rep["rows"]:
        assert r["status"] in row_status
        assert {"requirement", "status", "closed_by"} <= set(r)


# ── SR-20: каждая строка говорит, кто её закрыл, из словаря гейтов ──

@pytest.mark.unit
def test_every_row_declares_closed_by_from_gate_vocabulary(tmp_path):
    rep = G.build(_child(tmp_path), today=TODAY)
    assert G.CLOSED_BY == ("validator", "judge", "writer", "human")
    for r in rep["rows"]:
        assert r["closed_by"] in G.CLOSED_BY, f"closed_by вне словаря: {r}"


@pytest.mark.unit
def test_closed_by_vocabulary_covers_gates_registry():
    """SR-20: словарь отчёта РАСПРОСТРАНЁН с гейтов кита — их значения обязаны быть его подмножеством."""
    gates = yaml.safe_load((PKG / "quality" / "gates.yaml").read_text(encoding="utf-8"))
    used = {g.get("closed_by") for g in (gates.get("gates") or {}).values() if g.get("closed_by")}
    assert used and used <= set(G.CLOSED_BY), f"closed_by гейтов не покрыт словарём отчёта: {used}"


# ── SR §3.2 / §5.4: not_applicable и not_checked ОБЯЗАНЫ нести причину ──

@pytest.mark.unit
def test_not_checked_and_not_applicable_carry_reason(tmp_path):
    rep = G.build(_child(tmp_path, overrides=[
        {"requirement": "ARCHITECTURE.md", "reason": "нет архитектуры", "review_by": "2099-01-01"}]),
        today=TODAY)
    for r in rep["rows"]:
        if r["status"] in ("not_applicable", "not_checked"):
            assert r.get("reason"), f"{r['status']} без причины: {r}"


# ── SR-21: override без причины не применяется и всплывает находкой ──

@pytest.mark.unit
def test_override_without_reason_is_a_finding_not_applied():
    rows = [{"requirement": "A.md::Sec", "status": G.VIOLATED, "closed_by": "validator"}]
    out, echo = G._apply_overrides(rows, [{"requirement": "A.md::Sec", "reason": "  "}], TODAY)
    # требование НЕ отключено — строка нарушения на месте
    assert any(r["requirement"] == "A.md::Sec" and r["status"] == G.VIOLATED for r in out)
    # сам override — находка (violated) и не активен
    assert any(r["status"] == G.VIOLATED and "override" in r.get("detail", "").lower() for r in out)
    assert echo[0]["active"] is False and echo[0].get("problem")


@pytest.mark.unit
def test_classify_override_empty_reason():
    assert G.classify_override({"requirement": "x", "reason": ""}, TODAY)[0] == "no_reason"


# ── SR-22: у override есть срок/условие; просроченный становится находкой ──

@pytest.mark.unit
def test_override_without_expiry_is_a_finding():
    kind, _ = G.classify_override({"requirement": "x", "reason": "есть"}, TODAY)
    assert kind == "no_expiry"


@pytest.mark.unit
def test_expired_override_is_a_finding():
    kind, _ = G.classify_override(
        {"requirement": "x", "reason": "есть", "review_by": "2020-01-01"}, TODAY)
    assert kind == "expired"


@pytest.mark.unit
def test_remove_when_condition_satisfies_expiry():
    kind, _ = G.classify_override(
        {"requirement": "x", "reason": "есть", "remove_when": "когда появится API"}, TODAY)
    assert kind == "active"


@pytest.mark.unit
def test_future_review_date_is_active():
    kind, _ = G.classify_override(
        {"requirement": "x", "reason": "есть", "review_by": "2099-01-01"}, TODAY)
    assert kind == "active"


# ── SR-23: активный override -> not_applicable, виден с причиной; not_applicable == активные ──

@pytest.mark.unit
def test_active_override_makes_requirement_not_applicable(tmp_path):
    rep = G.build(_child(tmp_path, overrides=[
        {"requirement": "ARCHITECTURE.md::Наблюдаемость", "reason": "нет телеметрии",
         "review_by": "2099-01-01"}]), today=TODAY)
    na = [r for r in rep["rows"] if r["status"] == "not_applicable"]
    assert len(na) == 1 and na[0]["requirement"] == "ARCHITECTURE.md::Наблюдаемость"
    assert na[0]["closed_by"] == "human" and na[0]["reason"] == "нет телеметрии"


@pytest.mark.unit
def test_not_applicable_equals_active_override_count(tmp_path):
    """SR-23: число not_applicable в отчёте равно числу АКТИВНЫХ override."""
    overrides = [
        {"requirement": "ARCHITECTURE.md::A", "reason": "r1", "review_by": "2099-01-01"},  # active
        {"requirement": "ARCHITECTURE.md::B", "reason": "r2", "remove_when": "cond"},       # active
        {"requirement": "ARCHITECTURE.md::C", "reason": ""},                                # no_reason
        {"requirement": "ARCHITECTURE.md::D", "reason": "r4", "review_by": "2000-01-01"},   # expired
    ]
    rep = G.build(_child(tmp_path, overrides=overrides), today=TODAY)
    active = [o for o in rep["overrides"] if o["active"]]
    assert len(active) == 2
    assert rep["counts"]["not_applicable"] == len(active)


@pytest.mark.unit
def test_overrides_are_visible_in_every_report(tmp_path):
    """SR-23: отключённое требование перечислено в отчёте, а не исчезает из него."""
    rep = G.build(_child(tmp_path, overrides=[
        {"requirement": "X::Y", "reason": "нужно", "review_by": "2099-01-01"}]), today=TODAY)
    assert rep["overrides"] and rep["overrides"][0]["requirement"] == "X::Y"
    assert rep["overrides"][0]["reason"] == "нужно"


@pytest.mark.unit
def test_apply_overrides_one_na_row_per_active_override():
    rows = [{"requirement": "A::x", "status": G.VIOLATED, "closed_by": "validator"},
            {"requirement": "B::y", "status": G.PASS, "closed_by": "validator"}]
    out, echo = G._apply_overrides(
        rows, [{"requirement": "A", "reason": "r", "review_by": "2099-01-01"}], TODAY)
    na = [r for r in out if r["status"] == G.NOT_APPLICABLE]
    assert len(na) == 1                                   # ровно одна строка на активный override
    assert not any(r["requirement"] == "A::x" for r in out)  # строки требования A погашены (префикс)
    assert any(r["requirement"] == "B::y" for r in out)      # чужие строки на месте


# ── SR-17..19: проводка в джобу дочки ──

def _jobs():
    doc = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    return doc.get("jobs") or {}


@pytest.mark.unit
def test_governance_runs_in_the_same_single_job():
    """SR-17: одна джоба, а не вторая рядом; governance-шаг внутри неё."""
    jobs = _jobs()
    assert len(jobs) == 1, f"джоба дочки должна быть одна (SR-17), нашли: {list(jobs)}"
    steps = next(iter(jobs.values()))["steps"]
    runs = " ".join(str(s.get("run", "")) for s in steps)
    assert "validate_governance_report.py" in runs, "governance-шаг не проведён в джобу дочки"
    assert "validate_ai_ops_child.py" in runs, "здоровье установки (часть 1) исчезло из той же джобы"


@pytest.mark.unit
def test_report_split_into_two_labeled_parts():
    """SR-17: отчёт разделён на «здоровье установки» и «соответствие стандарту»."""
    text = TEMPLATE.read_text(encoding="utf-8").upper()
    assert "ЗДОРОВЬЕ УСТАНОВКИ" in text, "часть 1 не помечена в шаблоне"
    assert "СООТВЕТСТВИЕ" in text and "СТАНДАРТ" in text, "часть 2 не помечена в шаблоне"


@pytest.mark.unit
def test_report_is_a_machine_readable_artifact_with_history():
    """SR-18: отчёт пишется файлом (--out) и поднимается артефактом прогона, а не остаётся в логе."""
    steps = next(iter(_jobs().values()))["steps"]
    gov = next(s for s in steps if "validate_governance_report.py" in str(s.get("run", "")))
    assert "--out" in gov["run"], "отчёт не сохраняется файлом — сравнить с прошлым нечем"
    uploads = [s for s in steps if "upload-artifact" in str(s.get("uses", ""))]
    assert uploads, "отчёт не поднимается артефактом прогона (SR-18: история PR)"
    assert any("governance-report.json" in str(s.get("with", {}).get("path", "")) for s in uploads)


@pytest.mark.unit
def test_governance_adds_no_ninth_blocking_gate():
    """SR-19: governance advisory и НЕ заводит девятый блокирующий гейт."""
    gates = yaml.safe_load((PKG / "quality" / "gates.yaml").read_text(encoding="utf-8"))
    blocking = gates.get("mvp_blocking_gates") or []
    assert len(blocking) <= 8, f"бюджет блокирующих гейтов вырос молча: {blocking}"
    assert not any("governance" in str(g).lower() for g in blocking), \
        "governance просочился в блокирующий набор (SR-19)"
    # валидатор governance не объявлен гейтом вовсе — он часть шага, а не гейт
    assert "validate-governance-report" not in (gates.get("gates") or {})


@pytest.mark.unit
def test_validator_returns_zero_advisory(tmp_path):
    """SR-19: шаг advisory — валидатор возвращает 0 даже при нарушениях и без .ai-ops.yaml."""
    script = PKG / "ai_ops_kit" / "validation" / "validate_governance_report.py"
    # без .ai-ops.yaml (репозиторий не дочка) — тоже 0
    r = subprocess.run([sys.executable, str(script), str(tmp_path)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    # с дочкой и нарушениями — по-прежнему 0 (доставка, не блокировка)
    _child(tmp_path)
    r2 = subprocess.run([sys.executable, str(script), str(tmp_path), "--json"],
                        capture_output=True, text=True, timeout=120)
    assert r2.returncode == 0
    rep = json.loads(r2.stdout)
    assert rep["kind"] == "governance-report"
