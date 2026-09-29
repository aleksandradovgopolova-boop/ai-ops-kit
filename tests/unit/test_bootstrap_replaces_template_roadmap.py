"""Заготовка ROADMAP кита заменяется направлением из фактов, как заготовка плана (#1204).

Репетиция первого часа на «Нитях» (29.09): установщик положил `ROADMAP.md` с целями-заглушками
`goal-id-N`, bootstrap увидел «файл уже есть» и не тронул его — план в том же случае заменялся, а
направление нет. Ответы владельца до ROADMAP не дошли, `propose` советовал «начать двигать
безымянное направление (задай имя через `ai-ops model`)». Здесь проверяется, что:

  * заготовка (все цели — заглушки) заменяется, и после bootstrap заглушек нет;
  * направление, где есть хоть одно своё имя цели, не трогается — это уже слово человека;
  * советы кита после этого не говорят о безымянном направлении и не печатают команд.
"""
from __future__ import annotations

import subprocess

import pytest

from ai_ops_kit.intelligence import product_advice as PA
from ai_ops_kit.planning import plan_model as PM
from ai_ops_kit.planning import product_bootstrap as B

_TEMPLATE = ("# ROADMAP — куда идёт продукт\n\n## Сейчас\n\n- `goal-id-1` — _какая боль решается_\n\n"
             "## Следующий результат\n\n- `goal-id-2` — _пользователь может …_\n\n## Дальше\n\n- _x_\n\n"
             "## Later\n\n- _y_\n")


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


def test_kit_template_roadmap_is_replaced(repo):
    (repo / "ROADMAP.md").write_text(_TEMPLATE, encoding="utf-8")
    act = next(a for a in B.plan(repo)["actions"] if a["path"].endswith("ROADMAP.md"))
    assert act["will_write"] and act["replaces_template"]
    B.apply(repo)
    assert "goal-id-" not in (repo / "ROADMAP.md").read_text(encoding="utf-8")


def test_roadmap_with_an_owner_goal_is_left_alone(repo):
    own = _TEMPLATE.replace("`goal-id-1` — _какая боль решается_", "`first-link` — связь сразу видна")
    (repo / "ROADMAP.md").write_text(own, encoding="utf-8")
    B.apply(repo)
    assert (repo / "ROADMAP.md").read_text(encoding="utf-8") == own


def test_advice_after_bootstrap_has_no_unnamed_direction(repo):
    (repo / "ROADMAP.md").write_text(_TEMPLATE, encoding="utf-8")
    B.apply(repo)
    needs = " ".join(r["need"] for r in PA.recommend(str(repo))["recommendations"])
    assert "безымянное направление" not in needs, needs


def test_unnamed_label_carries_no_command():
    assert "`" not in PM.UNNAMED_GOAL_LABEL and "ai-ops" not in PM.UNNAMED_GOAL_LABEL
