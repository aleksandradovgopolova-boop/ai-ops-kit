"""SR-5/6: секционная валидация обязательных артефактов — три состояния, объявленные данными.

SR-6: заполнена / нет / пуста — три различимых состояния, пустая секция не выдаётся за заполненную
и не сворачивается в отсутствующую. SR-5: список секций — данные в product-operating-model.yaml,
не в коде.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from ai_ops_kit.planning import artifact_sections as AS
from ai_ops_kit.planning import repo_audit as RA

KIT = Path(__file__).resolve().parents[2]


# ── SR-6: три состояния секции ──

def test_three_states_are_distinguished():
    text = (
        "# Doc\n\n"
        "## Context\nреальное содержание тут\n\n"
        "## Components\n<!-- только подсказка, тела нет -->\n\n"
        # 'Failure Modes' отсутствует вовсе
    )
    states = {x["name"]: x["state"] for x in AS.section_states(
        text, ["Context", "Components", "Failure Modes"])}
    assert states["Context"] == AS.FILLED
    assert states["Components"] == AS.EMPTY, "заголовок без тела — EMPTY, не FILLED и не MISSING"
    assert states["Failure Modes"] == AS.MISSING


def test_empty_is_not_missing_and_not_filled():
    text = "# D\n\n## Goals\n\n"          # заголовок есть, тело пусто
    st = AS.section_states(text, ["Goals"])[0]
    assert st["state"] == AS.EMPTY
    assert st["state"] not in (AS.MISSING, AS.FILLED)


# ── SR-5: секции объявлены данными (добавление не требует правки Python) ──

def test_required_sections_declared_as_data_for_architecture():
    pom = yaml.safe_load((KIT / "registry" / "product-operating-model.yaml").read_text(encoding="utf-8"))
    sysc = next(c for c in pom["contours"] if c["id"] == "system_architecture")
    arch = next(s for s in sysc["source_of_truth"] if s["path"] == "ARCHITECTURE.md")
    assert arch.get("required_sections"), "секции ARCHITECTURE.md должны быть объявлены данными (SR-5)"
    # валидатор читает именно это объявление, а не хардкод
    rep = AS.report(KIT)
    paths = {a["path"] for a in rep["artifacts"]}
    assert "ARCHITECTURE.md" in paths


# ── интеграция в контур-аудит (доходит до человека через doctor) ──

def test_repo_audit_reports_section_findings(tmp_path):
    (tmp_path / "ARCHITECTURE.md").write_text(
        "# Architecture\n\n"
        "## Context\nнастоящий контекст\n\n"
        "## System Overview\n<!-- подсказка -->\n\n"      # пусто
        "## Components\nесть\n\n"
        "## Data Flows\nесть\n\n"
        "## Failure Modes\nесть\n\n",
        # 'Known Limitations' отсутствует
        encoding="utf-8")
    ev = {"tree_readable": True}
    model = RA._contours.load_model()
    sysc = next(c for c in model["contours"] if c["id"] == "system_architecture")
    row = RA._contour_state(tmp_path, sysc, ev, model)
    sf = {f["path"]: f for f in row["section_findings"]}
    assert "ARCHITECTURE.md" in sf
    assert "System Overview" in sf["ARCHITECTURE.md"]["empty_sections"]
    assert "Known Limitations" in sf["ARCHITECTURE.md"]["missing_sections"]
    assert "Context" not in sf["ARCHITECTURE.md"]["empty_sections"]


def test_seeded_draft_sections_read_as_empty_not_filled(tmp_path):
    """Свежий черновик из шаблона: разделы есть, но пусты — честное EMPTY, не FILLED."""
    tpl = (KIT / "templates" / "system" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    states = {x["name"]: x["state"] for x in AS.section_states(
        tpl, ["Context", "System Overview", "Failure Modes"])}
    assert set(states.values()) == {AS.EMPTY}, "в шаблоне разделы присутствуют, но тела нет — EMPTY"


def test_kit_dogfoods_filled_architecture_sections():
    """У самого кита объявленные обязательные секции ARCHITECTURE.md заполнены (не пусты)."""
    rep = AS.report(KIT)
    arch = next(a for a in rep["artifacts"] if a["path"] == "ARCHITECTURE.md")
    empty = [x["name"] for x in arch["sections"] if x["state"] != AS.FILLED]
    assert not empty, f"у кита пустые/отсутствующие обязательные секции архитектуры: {empty}"
