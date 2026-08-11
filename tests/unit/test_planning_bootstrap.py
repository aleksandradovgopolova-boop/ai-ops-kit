"""BOOTSTRAP: онбординг заканчивается РАБОТОЙ, а не документацией (тир 4).

ЧТО БЫЛО НЕ ТАК. Первый сценарий объявлен как `… ASK -> BOOTSTRAP -> PLAN -> RECOMMEND`, и семь
стадий из девяти работали. BOOTSTRAP существовал СТРОКОЙ в реестре: кит не создавал ни `ROADMAP.md`,
ни `planning/plan.yaml`. Владелец, ответив на вопросы, оставался там же, где был, — с пониманием и
без плана; `next` честно отвечал «плана нет». Обещание не выполнялось ничем.

Три вида проверок, как требует инженерный цикл кита:
  * positive     — план создаётся, проходит собственный валидатор, и `next` по нему СОВЕТУЕТ;
  * fail-closed  — существующее не перезаписывается, битый план не затирается;
  * side-effect  — кит не выдумывает продуктовых фактов: там, где ответа нет, стоит пометка.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_ops_kit.planning import product_bootstrap as B
from ai_ops_kit.planning import contours as C
from ai_ops_kit.planning import delivery_plan as P
from ai_ops_kit.planning import next_work as NW
from ai_ops_kit.planning import roadmap as RM
from ai_ops_kit.ui import presenter as PR

MODEL = C.load_model()


@pytest.fixture
def repo(tmp_path):
    """Живой продукт без описания: код есть, направления и плана нет — типичный вход онбординга."""
    root = tmp_path / "prod"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def main(): pass\n", encoding="utf-8")
    (root / "supabase" / "migrations").mkdir(parents=True)
    (root / "supabase" / "migrations" / "0001.sql").write_text("create table t(id int);\n",
                                                               encoding="utf-8")
    (root / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for cfg in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(root), "config", *cfg], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    return root


# ── positive ──────────────────────────────────────────────────────────────────────────────────

def test_bootstrap_produces_a_plan_that_next_can_actually_use(repo):
    """ГЛАВНОЕ: после bootstrap кит СОВЕТУЕТ работу, а не сообщает, что плана нет."""
    before = NW.compute(repo)
    assert not before["plan_present"], "фикстура уже содержит план — тест потерял смысл"

    B.apply(repo)
    assert (repo / "planning" / "plan.yaml").is_file()
    assert (repo / "ROADMAP.md").is_file()

    # План проходит СВОЙ валидатор — иначе кит создал бы файл, который сам же считает негодным.
    plan = P.load(repo)
    val = P.validate(plan, MODEL)
    assert val["errors"] == [], val["errors"]
    assert not P.is_template(plan), "план помечен заготовкой — `next` не станет по нему советовать"

    # Направление удовлетворяет контракту четырёх горизонтов.
    assert RM.check(repo, plan)["errors"] == [], RM.check(repo, plan)["errors"]

    after = NW.compute(repo)
    assert after["plan_present"] and after["next_best"], "работа объявлена, а совета нет"
    assert after["next_best"]["why"], "совет без обоснования — это порядок строк, а не выбор"


def test_work_items_are_derived_from_the_audit_not_invented(repo):
    """Каждая работа соответствует контуру с незакрытым источником истины — это вывод, а не выдумка."""
    from ai_ops_kit.planning import repo_audit as A
    und = A.run(repo)
    items = B.work_items(und, MODEL, repo)
    open_contours = {r["contour"] for r in und["audit"]["contours"] if r["state"] != A.VERIFIED}
    named = {list(w["affects"])[0] for w in items}
    assert named == open_contours, f"план разошёлся с аудитом: {named ^ open_contours}"
    for w in items:
        assert w["owner_role"] in (MODEL.get("roles") or {}), f"роль вне реестра: {w['owner_role']}"
        assert w["why"], "работа без причины выглядит как бюрократия — её справедливо не делают"
        assert not any(k in w for k in ("runtime", "model", "provider", "assignee")), \
            "в плане назван исполнитель, а не роль"


def test_work_is_a_chain_but_answers_do_not_block_the_chain(repo):
    """Восемь готовых работ сразу — тот самый список из четырнадцати пунктов, который убивает продукт.
    Поэтому то, что кит может закрыть сам, выстроено в ЦЕПОЧКУ — по одной работе за раз.

    Но работа, ждущая ответа владельца, стоит ОТДЕЛЬНО. Сначала я связал в цепочку всё подряд, и
    первая же работа с `human_decision` заблокировала все остальные: сразу после bootstrap кит
    отвечал «готовой к работе задачи сейчас нет» — онбординг снова заканчивался не работой.
    """
    from ai_ops_kit.planning import repo_audit as A
    items = B.work_items(A.run(repo), MODEL, repo)
    assert len(items) >= 2
    waiting = [w for w in items if w.get("human_decision")]
    doable = [w for w in items if not w.get("human_decision")]
    assert all(w["depends_on"] == [] for w in waiting), \
        "работа, ждущая человека, поставлена в зависимость от другой работы"
    for i, w in enumerate(doable):
        assert w["depends_on"] == ([doable[i - 1]["id"]] if i else []), \
            "то, что кит делает сам, должно идти по одному"
    # И ни одна работа не ждёт того, что ждёт человека: иначе ответ блокирует всю цепочку.
    waiting_ids = {w["id"] for w in waiting}
    assert not [w for w in doable if set(w["depends_on"]) & waiting_ids]


def test_dry_run_writes_nothing(repo):
    """Запись в чужой репозиторий владелец обязан увидеть ДО того, как она произошла."""
    rep = B.plan(repo)
    assert rep["will_write"], "нечего создавать в репозитории без плана — это дефект детекта"
    assert not (repo / "planning" / "plan.yaml").exists()
    assert not (repo / "ROADMAP.md").exists()
    # И сообщение спрашивает решение, а не рапортует.
    msg = PR.from_bootstrap(rep, applied=False)
    assert msg["status"] == "needs_input" and msg["decision"]["question"]


# ── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_existing_files_are_never_overwritten(repo):
    """Существующий файл — ФАКТ О ПРОДУКТЕ, и он сильнее любого шаблона кита."""
    (repo / "ROADMAP.md").write_text("# моё направление\n\n## Сейчас\n\n- `g1` — моя цель\n",
                                     encoding="utf-8")
    (repo / "planning").mkdir()
    mine = ("schema_version: 1\nkind: delivery-plan\n"
            "goals:\n  - {id: g1, status: active}\n"
            "work:\n  - {id: my-01, title: Моя работа, type: engineering, goal: g1, "
            "status: todo, owner_role: engineer}\n")
    (repo / "planning" / "plan.yaml").write_text(mine, encoding="utf-8")

    rep = B.apply(repo)
    assert rep["written"] == [], f"кит перезаписал работу человека: {rep['written']}"
    assert len(rep["skipped"]) == 2
    assert (repo / "planning" / "plan.yaml").read_text(encoding="utf-8") == mine
    assert "моё направление" in (repo / "ROADMAP.md").read_text(encoding="utf-8")


def test_kit_template_is_replaced_because_it_holds_no_facts(repo):
    """Заготовку кита ЗАМЕНЯЕМ: в ней пример работы, и она прямо помечена как заготовка.

    Разница с предыдущим тестом принципиальна: там был план человека, здесь — пример кита, который
    иначе навсегда остался бы на месте настоящего плана и блокировал `next`.
    """
    (repo / "planning").mkdir()
    tpl = Path("templates/planning/plan.yaml").read_text(encoding="utf-8")
    (repo / "planning" / "plan.yaml").write_text(tpl, encoding="utf-8")
    assert P.is_template(P.load(repo))

    rep = B.apply(repo)
    assert any(w["path"].endswith("plan.yaml") for w in rep["written"]), rep
    assert not P.is_template(P.load(repo)), "заготовка осталась заготовкой"


def test_corrupt_plan_is_not_silently_replaced(repo):
    """Перезаписать файл, который не удалось прочитать, значит уничтожить чью-то работу."""
    (repo / "planning").mkdir()
    (repo / "planning" / "plan.yaml").write_text("goals: [ не закрытая скобка\n", encoding="utf-8")
    rep = B.apply(repo)
    assert rep["error"] and rep["written"] == []
    msg = PR.from_bootstrap(rep, applied=True)
    assert msg["status"] == "blocked"


# ── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_product_goals_are_asked_for_not_invented(repo):
    """КИТ НЕ ВЫДУМЫВАЕТ ПРОДУКТОВЫХ ФАКТОВ.

    Цели продукта, боли пользователей и «следующий результат» из кода не выводятся. На их месте
    обязана стоять пометка, а не правдоподобный текст: сгенерированное направление, которое читается
    как настоящее, — худший исход онбординга, чем его отсутствие.
    """
    B.apply(repo)
    text = (repo / "ROADMAP.md").read_text(encoding="utf-8")
    assert text.count("нужно ваше слово") >= 3, text
    for horizon in ("## Сейчас", "## Следующий результат", "## Дальше", "## Later"):
        assert horizon in text, f"нет горизонта {horizon}"
    # Единственная цель, объявленная китом, — про сам кит, а не про продукт.
    plan = P.load(repo)
    assert [g["id"] for g in P.goals(plan)] == [B.BASELINE_GOAL]


def test_promise_matches_reality_when_every_work_waits_for_the_owner(repo):
    """Обещание «спроси что дальше — назову работу» ЛОЖНО, если каждая работа ждёт ответа.

    Тот же разрыв обещания, из-за которого правится тир 4, только на один шаг позже: кит сообщил бы
    «готово, спроси что дальше», а на «что дальше» ответил бы «ждёт решения человека».
    """
    all_waiting = {"written": [{"path": "planning/plan.yaml", "what": "план"}], "skipped": [],
                   "work_items": 3, "awaiting_human": 3, "ready_without_human": 0,
                   "blocking_questions": 3, "error": None}
    msg = PR.from_bootstrap(all_waiting, applied=True)
    assert msg["status"] == "needs_input", "обещана готовая работа там, где её нет"
    out = PR.render(msg, audience="product")
    assert "onboarding-answers.yaml" in out, "не сказано, куда отвечать"

    mixed = dict(all_waiting, awaiting_human=1, ready_without_human=2)
    assert PR.from_bootstrap(mixed, applied=True)["status"] == "ok"


def test_bootstrap_is_idempotent(repo):
    """Второй запуск ничего не меняет: иначе повторная команда затирала бы уже сделанную работу."""
    B.apply(repo)
    first = (repo / "planning" / "plan.yaml").read_text(encoding="utf-8")
    rep = B.apply(repo)
    assert rep["written"] == []
    assert (repo / "planning" / "plan.yaml").read_text(encoding="utf-8") == first


def test_write_scope_never_points_into_the_kit(repo):
    """Область записи работы человека не должна вести в служебные каталоги кита.

    `.ai/runtime/active-work.yaml` ведёт сам кит; предлагать владельцу «описать» его — приглашение
    править не своё.
    """
    from ai_ops_kit.planning import repo_audit as A
    for w in B.work_items(A.run(repo), MODEL, repo):
        for s in w["write_scope"]:
            assert not s.startswith(".ai/"), f"{w['id']}: область записи ведёт в кит ({s})"


def test_declared_paths_are_honoured(repo):
    """Монорепо объявил свои пути — bootstrap пишет ТУДА, а не в корень (связка с тиром 3)."""
    (repo / ".ai-ops.yaml").write_text(
        "schema_version: 1\nkind: ai-ops-child-config\n"
        "product_operating_model:\n  paths:\n"
        "    plan: apps/web/planning/plan.yaml\n    roadmap: apps/web/ROADMAP.md\n",
        encoding="utf-8")
    B.apply(repo)
    assert (repo / "apps" / "web" / "planning" / "plan.yaml").is_file()
    assert (repo / "apps" / "web" / "ROADMAP.md").is_file()
    assert not (repo / "planning" / "plan.yaml").exists(), "запись ушла в корень мимо объявления"
