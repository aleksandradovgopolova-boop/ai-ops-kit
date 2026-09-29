"""Первый план открывается продуктовым шагом, который назвал владелец (#1203).

Репетиция первого часа на «Нитях» (29.09): владелец в ответах онбординга назвал следующий результат
для пользователя («уже после первой заметки человек видит хотя бы одну связь»), а первый план
состоял из семи работ «Описать: …», и первой рекомендовалась «Описать: Planning & Execution». Сессия
сама не согласилась и предложила начать с продуктового шага. Решение владельца: описания процессов
остаются — они важны там, где описания нет, — меняется только то, что идёт первым.

  * владелец назвал следующий результат -> работа к нему первая, под целью первого приоритета, и
    `next` советует её; описания контуров остаются в плане;
  * не назвал / это лишь догадка кита -> продуктовой работы нет (кит продуктовых целей не выдумывает);
  * ROADMAP берёт «Следующий результат» из слова владельца, а не пишет «нужно ваше слово»;
  * у выбранной работы нет области записи -> параллельность с ней не обещается.
"""
from __future__ import annotations

import subprocess

import pytest
import yaml

from ai_ops_kit.planning import contours as C
from ai_ops_kit.planning import delivery_plan as P
from ai_ops_kit.planning import next_work as NW
from ai_ops_kit.planning import product_bootstrap as B
from ai_ops_kit.planning import roadmap as RM

MODEL = C.load_model()
OUTCOME = "Уже после первой заметки человек видит хотя бы одну связь."


def _und(status):
    return {"reconstructed": {"next_outcome": {"value": OUTCOME, "status": status}}}


@pytest.mark.parametrize("status", ["user_confirmed", "verified"])
def test_owner_named_outcome_becomes_the_first_product_step(status):
    step = B.first_product_step(_und(status))
    assert step["goal"] == B.FIRST_OUTCOME_GOAL and step["value"] == "high"
    assert step["title"] == "Первый результат для пользователя: Уже после первой заметки человек " \
                            "видит хотя бы одну связь"      # без хвостовой точки: заголовок, не фраза
    assert step["depends_on"] == []


@pytest.mark.parametrize("status", ["inferred", "partial", "missing", "unknown"])
def test_kit_guess_is_not_turned_into_a_product_step(status):
    assert B.first_product_step(_und(status)) is None


def test_no_outcome_no_product_step():
    assert B.first_product_step({"reconstructed": {}}) is None


# ── на настоящем дереве: ответ владельца -> план и совет ───────────────────────────────────────


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "prod"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def main(): pass\n", encoding="utf-8")
    (root / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for cfg in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(root), "config", *cfg], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    return root


def _answer_next_outcome(root):
    p = root / ".ai" / "project" / "onboarding-answers.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"answers": {"next_outcome": OUTCOME}}, allow_unicode=True),
                 encoding="utf-8")


def test_owner_answer_puts_the_product_step_first_and_keeps_the_descriptions(repo):
    _answer_next_outcome(repo)
    B.apply(repo)
    plan = P.load(repo)
    assert P.validate(plan, MODEL)["errors"] == []
    assert RM.check(repo, plan)["errors"] == [], RM.check(repo, plan)["errors"]
    assert [g["id"] for g in P.goals(plan)][0] == B.FIRST_OUTCOME_GOAL
    ids = [w["id"] for w in plan["work"]]
    assert ids[0] == "reach-first-user-outcome"
    assert any(i.startswith("describe-") for i in ids[1:]), "описания процессов пропали из плана"
    # Здесь описаний НЕТ ВОВСЕ, и кит закрывает их сам цепочкой: её голова держит остальные и
    # честно выходит первой («описание процессов важно, если его нет» — слово владельца 29.09).
    # Продуктовый шаг при этом готов к работе и стоит в очереди, а не пропал.
    rep = NW.compute(repo)
    ready = [r["id"] for r in rep["ready"]]
    assert "reach-first-user-outcome" in ready


def test_when_descriptions_wait_for_the_owner_the_product_step_is_recommended(repo):
    """Форма «Нитей»: описания ждут слова владельца (цепочки нет) -> первой советуется продуктовая работа."""
    _answer_next_outcome(repo)
    B.apply(repo)
    plan = P.load(repo)
    for w in plan["work"]:
        if w["id"].startswith("describe-"):
            w["depends_on"], w["human_decision"] = [], "нужен ответ владельца"
    (repo / "planning" / "plan.yaml").write_text(yaml.safe_dump(plan, allow_unicode=True,
                                                                sort_keys=False), encoding="utf-8")
    rep = NW.compute(repo)
    assert rep["next_best"]["id"] == "reach-first-user-outcome"
    assert "работает на цель первого приоритета" in rep["next_best"]["why"]


def test_roadmap_takes_the_next_result_from_the_owner(repo):
    _answer_next_outcome(repo)
    B.apply(repo)
    text = (repo / "ROADMAP.md").read_text(encoding="utf-8")
    section = text.split("## Следующий результат", 1)[1].split("## Дальше", 1)[0]
    assert "Уже после первой заметки человек видит хотя бы одну связь" in section
    assert "нужно ваше слово" not in section


def test_without_owner_answer_the_plan_is_unchanged(repo):
    B.apply(repo)
    plan = P.load(repo)
    assert [g["id"] for g in P.goals(plan)] == [B.BASELINE_GOAL]
    assert not any(w["id"] == "reach-first-user-outcome" for w in plan["work"])


# ── параллельность с работой без области записи не обещается ──────────────────────────────────


def test_no_parallel_promise_when_the_chosen_work_has_no_write_scope(tmp_path):
    (tmp_path / "planning").mkdir()
    (tmp_path / "planning" / "plan.yaml").write_text(yaml.safe_dump(
        {"schema_version": 1, "kind": "delivery-plan",
         "goals": [{"id": "g1", "status": "active", "outcome": {"works": False}}],
         "work": [{"id": "a-product", "title": "продукт", "type": "engineering", "goal": "g1",
                   "status": "todo", "owner_role": "engineer", "value": "high", "depends_on": []},
                  {"id": "b-docs", "title": "описать", "type": "docs", "goal": "g1",
                   "status": "todo", "owner_role": "engineer", "value": "low", "depends_on": [],
                   "write_scope": ["context/"]}]}, allow_unicode=True), encoding="utf-8")
    (tmp_path / "ROADMAP.md").write_text(
        "# ROADMAP\n\n## Сейчас\n\n- `g1` — результат\n\n## Следующий результат\n\n- `n` — x\n\n"
        "## Дальше\n\n- y\n\n## Later\n\n- z — не сейчас\n", encoding="utf-8")
    rep = NW.compute(tmp_path)
    assert rep["next_best"]["id"] == "a-product"
    assert rep["parallel_with"] == []
