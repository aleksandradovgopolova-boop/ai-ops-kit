"""Автонарезка задач-кандидатов и приёмка пачкой (эпик auto-slice-candidates).

Доказывает семь свойств на ФИКСТУРАХ (чистые, без живого плана репозитория):
  1. непокрытое направление роадмапа (исходы есть, работ нет) даёт кандидата;
  2. покрытое направление (под ним есть работа) кандидата НЕ даёт;
  3. открытая находка из findings/from-children даёт кандидата — union обоих источников её включает;
  4. plan.yaml НЕ меняется листингом/сухим прогоном (байт-в-байт);
  5. после приёмки (apply) принятый кандидат — work item плана, а комментарии/работы уцелели;
  6. повторная приёмка того же кандидата дубля не создаёт (идемпотентность);
  7. закрытая находка (became_work) кандидата НЕ даёт.

Приёмка — ЕДИНСТВЕННОЕ место, что пишет план; без apply=True не пишется ничего (предохранитель:
кит сам активную работу не дописывает — решает владелец).
"""
from __future__ import annotations

import yaml
import pytest

from ai_ops_kit.engops import kit_feedback
from ai_ops_kit.intelligence import roadmap_candidates as rc
from ai_ops_kit.planning import candidate_intake as ci
from ai_ops_kit.planning import delivery_plan as dp
from ai_ops_kit.cli.candidates_cli import gather_candidates

pytestmark = pytest.mark.unit


# Комментарий-канарейка: приёмка обязана его сохранить (plan.yaml насыщен комментариями, ruamel нет).
_CANARY = "# CANARY-KEEP-ME: этот комментарий обязан пережить приёмку кандидатов"

_PLAN_TEXT = f"""# planning/plan.yaml — фикстура авто-нарезки кандидатов.
schema_version: 1
kind: delivery-plan

goals:
  - id: covered-direction
    title: Покрытое направление
    outcome:
      shipped_thing: false
  - id: uncovered-direction
    title: Непокрытое направление
    outcome:
      new_thing: false

work:
  {_CANARY}
  - id: existing-work
    title: Существующая работа под покрытым направлением
    type: engineering
    goal: covered-direction
    status: todo
    owner_role: engineer
    write_scope: [src/]
"""


def _fixture_repo(tmp_path):
    (tmp_path / "planning").mkdir(parents=True, exist_ok=True)
    (tmp_path / "planning" / "plan.yaml").write_text(_PLAN_TEXT, encoding="utf-8")
    return tmp_path


def _write_obs(kit_root, oid, *, state, cls="defect", child="bnbm"):
    d = kit_root / kit_feedback.KIT_DIR
    d.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "kind": "KitObservation", "id": oid,
           "at": "2026-09-21T00:00:00+00:00", "statement": f"наблюдение {oid} из прогона",
           "observation_class": cls, "severity": "p1", "state": state,
           "child": {"name": child, "path": f"/tmp/{child}"},
           "evidence": [{"kind": "note", "text": "e"}]}
    (d / f"{oid}.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")


# ── 1 + 2: направления роадмапа ──────────────────────────────────────────────────────────────────

def test_uncovered_direction_yields_candidate(tmp_path):
    repo = _fixture_repo(tmp_path)
    proj = rc.project_uncovered_directions(repo)
    assert proj["readable"] is True
    ids = [c["id"] for c in proj["candidates"]]
    assert "cand-dir-uncovered-direction" in ids
    c = next(c for c in proj["candidates"] if c["id"] == "cand-dir-uncovered-direction")
    assert c["source"] == "roadmap-direction"
    assert c["source_goal"] == "uncovered-direction"
    assert c["status"] == "draft" and c["active"] is False
    assert c["requires_human_decision"] is True


def test_covered_direction_yields_no_candidate(tmp_path):
    repo = _fixture_repo(tmp_path)
    ids = [c["id"] for c in rc.project_uncovered_directions(repo)["candidates"]]
    assert "cand-dir-covered-direction" not in ids


def test_missing_plan_is_honest_unknown_not_empty(tmp_path):
    """Плана нет — честное «не знаю» (readable: false), а НЕ пустой список как «всё покрыто»."""
    proj = rc.project_uncovered_directions(tmp_path)  # без planning/plan.yaml
    assert proj["readable"] is False
    assert proj["candidates"] == []
    assert proj.get("note")


# ── 3 + 7: находки и union источников ────────────────────────────────────────────────────────────

def test_union_includes_open_finding_and_roadmap_direction(tmp_path):
    repo = _fixture_repo(tmp_path)
    _write_obs(repo, "obs-open", state="delivered")
    cands = gather_candidates(repo)
    ids = [c["id"] for c in cands]
    assert "cand-dir-uncovered-direction" in ids          # источник роадмапа
    assert any(c.get("source_observation") == "obs-open" for c in cands)  # источник находок


def test_closed_finding_yields_no_candidate(tmp_path):
    repo = _fixture_repo(tmp_path)
    _write_obs(repo, "obs-closed", state="became_work")
    cands = gather_candidates(repo)
    assert not any(c.get("source_observation") == "obs-closed" for c in cands)


# ── 4: сухой прогон не пишет ─────────────────────────────────────────────────────────────────────

def test_dry_run_does_not_touch_plan_file(tmp_path):
    repo = _fixture_repo(tmp_path)
    p = repo / "planning" / "plan.yaml"
    before = p.read_bytes()
    rep = ci.accept_candidates(repo, ["cand-dir-uncovered-direction"],
                               rc.project_uncovered_directions(repo)["candidates"], apply=False)
    assert rep["applied"] is False
    assert len(rep["to_add"]) == 1
    assert p.read_bytes() == before          # байт-в-байт


# ── 5: приёмка добавляет работу и сохраняет комментарии/работы ───────────────────────────────────

def test_accept_adds_work_and_preserves_comments(tmp_path):
    repo = _fixture_repo(tmp_path)
    p = repo / "planning" / "plan.yaml"
    cands = rc.project_uncovered_directions(repo)["candidates"]
    rep = ci.accept_candidates(repo, ["cand-dir-uncovered-direction"], cands, apply=True)
    assert rep["applied"] is True
    assert [it["id"] for it in rep["to_add"]] == ["uncovered-direction"]

    text = p.read_text(encoding="utf-8")
    assert _CANARY in text                                  # комментарий уцелел
    assert "id: existing-work" in text                      # прежняя работа уцелела

    plan = dp.load(repo)
    work_ids = {w["id"] for w in dp.items(plan)}
    assert "uncovered-direction" in work_ids and "existing-work" in work_ids
    new = next(w for w in dp.items(plan) if w["id"] == "uncovered-direction")
    assert new["status"] == "todo"
    assert new["goal"] == "uncovered-direction"
    assert new["source"] == "roadmap-direction"

    # Итоговый план обязан проходить validate (валидные type/owner_role/goal/status).
    report = dp.validate(plan, root=repo)
    assert report["errors"] == [], report["errors"]


# ── 6: идемпотентность ───────────────────────────────────────────────────────────────────────────

def test_reaccept_is_idempotent(tmp_path):
    repo = _fixture_repo(tmp_path)
    cands = rc.project_uncovered_directions(repo)["candidates"]
    ci.accept_candidates(repo, ["cand-dir-uncovered-direction"], cands, apply=True)

    # Второй прогон: кандидат уже стал работой — дубля быть не должно.
    rep2 = ci.accept_candidates(repo, ["cand-dir-uncovered-direction"], cands, apply=True)
    assert rep2["to_add"] == []
    assert "uncovered-direction" in rep2["skipped_existing"]

    plan = dp.load(repo)
    ids = [w["id"] for w in dp.items(plan)]
    assert ids.count("uncovered-direction") == 1            # ровно одна, не две


# ── F1: кандидат-находка без source_goal в МНОГОЦЕЛЕВОМ плане ─────────────────────────────────────

_FINDING_CAND = {
    "id": "cand-obs-x", "title": "Разобрать наблюдение из прогона", "type": "investigation",
    "owner_role": "product-manager", "status": "draft", "active": False,
    "requires_human_decision": True, "source": "child-finding",
    "source_observation": "obs-x", "rationale": "наблюдение из прогона дочки",
}


def test_finding_without_goal_in_multigoal_plan_is_skipped_not_written(tmp_path):
    """Кандидат-находка без направления в многоцелевом плане НЕ пишется молча (иначе work item без
    goal — ошибка валидатора): уходит в skipped_no_goal, план не тронут, валидатор проходит."""
    repo = _fixture_repo(tmp_path)                 # фикстура многоцелевая (2 цели)
    p = repo / "planning" / "plan.yaml"
    before = p.read_bytes()
    rep = ci.accept_candidates(repo, ["cand-obs-x"], [_FINDING_CAND], apply=True)
    assert rep["to_add"] == []
    assert rep["applied"] is False
    assert any(s["id"] == "cand-obs-x" for s in rep["skipped_no_goal"])
    assert p.read_bytes() == before                # байт-в-байт: ничего не записано
    assert dp.validate(dp.load(repo), root=repo)["errors"] == []


def test_finding_accepted_with_explicit_goal_is_valid(tmp_path):
    """С явным --goal кандидат-находка становится валидным work item с проставленным направлением."""
    repo = _fixture_repo(tmp_path)
    rep = ci.accept_candidates(repo, ["cand-obs-x"], [_FINDING_CAND],
                               goal="uncovered-direction", apply=True)
    assert rep["applied"] is True
    assert [it["id"] for it in rep["to_add"]] == ["obs-x"]
    plan = dp.load(repo)
    w = next(w for w in dp.items(plan) if w["id"] == "obs-x")
    assert w["goal"] == "uncovered-direction"
    assert dp.validate(plan, root=repo)["errors"] == []


def test_explicit_goal_that_does_not_resolve_is_refused(tmp_path):
    """--goal с несуществующей целью не пишет невалидный план: пропуск с внятной причиной."""
    repo = _fixture_repo(tmp_path)
    p = repo / "planning" / "plan.yaml"
    before = p.read_bytes()
    rep = ci.accept_candidates(repo, ["cand-obs-x"], [_FINDING_CAND],
                               goal="no-such-goal", apply=True)
    assert rep["to_add"] == [] and rep["applied"] is False
    assert any(s["id"] == "cand-obs-x" for s in rep["skipped_no_goal"])
    assert p.read_bytes() == before


# ── F2: коллизия slug между источниками ──────────────────────────────────────────────────────────

def test_slug_collision_reported_honestly_not_as_existing(tmp_path):
    """`cand-dir-foo` и `cand-foo` дают один slug `foo`: второй — НЕ «уже в плане», а честная коллизия
    источников (skipped_collision с указанием, с кем схлопнулся). Дубль не пишется, план валиден."""
    repo = _fixture_repo(tmp_path)
    cands = [
        {"id": "cand-dir-foo", "title": "Из направления", "type": "improvement",
         "owner_role": "product-manager", "source": "roadmap-direction",
         "source_goal": "uncovered-direction", "rationale": "a"},
        {"id": "cand-foo", "title": "Из находки", "type": "investigation",
         "owner_role": "product-manager", "source": "child-finding", "rationale": "b"},
    ]
    rep = ci.accept_candidates(repo, ["cand-dir-foo", "cand-foo"], cands, apply=True)
    assert [it["id"] for it in rep["to_add"]] == ["foo"]
    assert rep["skipped_existing"] == []                    # НЕ «уже есть»
    assert len(rep["skipped_collision"]) == 1
    assert rep["skipped_collision"][0]["id"] == "cand-foo"
    assert rep["skipped_collision"][0]["clashes_with"] == "cand-dir-foo"
    plan = dp.load(repo)
    assert [w["id"] for w in dp.items(plan)].count("foo") == 1
    assert dp.validate(plan, root=repo)["errors"] == []


# ── F3/F4: непокрытые ветки дописывания текста ──────────────────────────────────────────────────

_SINGLE_GOAL_HEAD = """schema_version: 1
kind: delivery-plan
goals:
  - id: only-goal
    title: Одно направление
    outcome:
      x: false
"""

_WORK_BLOCK = """work:
  # KEEP-TRAILING-CANARY
  - id: existing
    title: Есть работа
    type: engineering
    goal: only-goal
    status: todo
    owner_role: engineer
    write_scope: [src/]
"""

_NEW_CAND = {"id": "cand-dir-added", "title": "Новая работа", "type": "improvement",
             "owner_role": "product-manager", "source": "roadmap-direction",
             "source_goal": "only-goal", "rationale": "r"}


def _write_plan(tmp_path, text):
    (tmp_path / "planning").mkdir(parents=True, exist_ok=True)
    p = tmp_path / "planning" / "plan.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_append_when_work_is_not_the_last_block(tmp_path):
    """`work:` не последний top-level блок: вставка ПЕРЕД следующим ключом, план остаётся валиден."""
    text = _SINGLE_GOAL_HEAD + _WORK_BLOCK + "notes: хвостовой верхнеуровневый блок после work\n"
    p = _write_plan(tmp_path, text)
    rep = ci.accept_candidates(tmp_path, ["cand-dir-added"], [_NEW_CAND], apply=True)
    assert rep["applied"] is True
    out = p.read_text(encoding="utf-8")
    assert "notes: хвостовой" in out                        # хвостовой блок уцелел
    assert out.index("id: added") < out.index("notes:")     # вставлено ВНУТРЬ work, до notes
    plan = dp.load(tmp_path)                                 # парсится
    assert "added" in {w["id"] for w in dp.items(plan)}
    assert dp.validate(plan, root=tmp_path)["errors"] == []


def test_append_when_file_has_no_trailing_newline(tmp_path):
    """Файл без финального перевода строки — дописывание всё равно даёт валидный YAML."""
    text = (_SINGLE_GOAL_HEAD + _WORK_BLOCK).rstrip("\n")    # без финального \n
    p = _write_plan(tmp_path, text)
    assert not p.read_text(encoding="utf-8").endswith("\n")
    rep = ci.accept_candidates(tmp_path, ["cand-dir-added"], [_NEW_CAND], apply=True)
    assert rep["applied"] is True
    plan = dp.load(tmp_path)
    assert "added" in {w["id"] for w in dp.items(plan)}
    assert dp.validate(plan, root=tmp_path)["errors"] == []


def test_flow_style_work_block_is_refused_without_writing(tmp_path):
    """work: во flow-стиле (`[]`) — дописывать вслепую нельзя: ошибка, и на диск ничего не легло."""
    text = _SINGLE_GOAL_HEAD + "work: []\n"
    p = _write_plan(tmp_path, text)
    before = p.read_bytes()
    rep = ci.accept_candidates(tmp_path, ["cand-dir-added"], [_NEW_CAND], apply=True)
    assert rep["applied"] is False
    assert rep.get("error") and "work" in rep["error"]
    assert p.read_bytes() == before                         # F4: не записано ничего
