"""План — control plane, а не архив (`plan-as-control-plane`, 2026-08-14).

ПОВОД — ЗАМЕР, а не вкус. `planning/plan.yaml` кита был одновременно планом, бэклогом, журналом
расследований, changelog'ом и отчётом квалификации: 21 работа из 32 закрыта, и чтобы ответить «что
идёт сейчас и что взять следующим», приходилось вычитывать разбор давно оплаченных дефектов.
Управляющий файл, в котором управление занимает треть, управлять перестаёт.

ЧТО ЗАЩИЩАЕТСЯ ЗДЕСЬ (правила исполняются кодом, а не соглашением):
  * positive — закрытая работа живёт в истории, `depends_on` резолвится по ней, и вывод статусов
    закрывает такие зависимости (иначе разнос заблокировал бы весь план);
  * fail-closed — `done` в активном плане, `pr` при `todo`, `done` в истории без результата или без
    места перепроверки, работа в двух файлах сразу, битая история: каждый случай называется ошибкой;
  * side-effect proof — `next` РЕАЛЬНО отвечает по разнесённому плану кита: не «валидатор зелёный»,
    а «совет получен». Модульные тесты остались бы зелёными, если бы историю не подали в `next`, —
    именно этот шов кит нашёл на себе сам при разносе.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import delivery_plan as dp

PKG_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]

ACTIVE_ITEM = {"id": "aktivnaya", "title": "Активная работа", "type": "quality",
               "owner_role": "engineer", "status": "todo", "goal": "g1",
               "write_scope": ["ai_ops_kit/"], "depends_on": []}
GOALS = [{"id": "g1", "status": "active"}]


def _plan(*work):
    return {"schema_version": 1, "kind": "delivery-plan", "goals": GOALS, "work": list(work)}


def _closed(**over):
    out = {"id": "zakrytaya", "title": "Закрытая работа", "goal": "g1", "status": "done",
           "closed_at": "2026-08-14", "result": "механизм выпущен и подтверждён полем",
           "commit": "abc123abc123"}
    out.update(over)
    return out


# ─── positive ──────────────────────────────────────────────────────────────────────────────────

def test_dependency_on_closed_work_resolves_and_unblocks(tmp_path):
    """Зависимость от закрытой работы резолвится и НЕ блокирует.

    Главный риск разноса: `resolve` считает неизвестную зависимость блокирующей — и это правильно.
    Но после переноса закрытого в историю каждая такая зависимость стала бы неизвестной, и весь план
    оказался бы заблокирован с невнятной причиной. История обязана доехать до вывода статусов.
    """
    item = {**ACTIVE_ITEM, "depends_on": ["zakrytaya"]}
    plan = _plan(item)
    closed = [_closed()]

    rep = dp.validate(plan, closed=closed)
    res = dp.resolve(plan, tmp_path, closed=closed)

    assert rep["errors"] == [], rep["errors"]
    assert res["aktivnaya"]["status"] == "ready", res["aktivnaya"]["reasons"]
    assert res["zakrytaya"]["source"] == "history"


def test_history_of_the_kit_itself_is_valid_and_complete():
    """Side-effect proof на РЕАЛЬНЫХ файлах кита: разнос состоялся, а не описан.

    Проверяется факт: в активном плане нет ни одной закрытой работы, история непуста, и каждая её
    запись называет результат и место перепроверки.
    """
    plan = dp.load(PKG_ROOT)
    closed = dp.load_history(PKG_ROOT)

    assert closed, "история пуста — разнос не выполнен"
    assert all(w.get("status") in dp.ACTIVE_DECLARABLE for w in dp.items(plan)), (
        "в активном плане осталась закрытая работа")
    hrep = dp.validate_history(closed, plan)
    assert hrep["errors"] == [], hrep["errors"]
    prep = dp.validate(plan, closed=closed, root=PKG_ROOT)
    assert prep["errors"] == [], prep["errors"]


# ─── fail-closed ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["done", "dropped"])
def test_closed_work_in_the_active_plan_is_an_error(status):
    """`done` в активном плане — ошибка: место закрытой работы в истории.

    Утверждение о ФОРМУЛИРОВКЕ здесь не придирка: первая версия теста проверяла лишь упоминание
    файла истории, и мутация «убрать эту проверку» её не роняла — сообщение соседней ветки тоже
    упоминает файл. Читающий должен узнать, ЧТО не так («закрытая работа живёт в истории»), а не
    только куда идти.
    """
    rep = dp.validate(_plan({**ACTIVE_ITEM, "status": status}))

    assert any(f"статус '{status}'" in e and "закрытая работа живёт" in e for e in rep["errors"]), (
        rep["errors"])


def test_a_pr_with_todo_is_a_contradiction():
    """Указан PR при статусе `todo` — противоречие: PR существует, значит работа начата.

    Проверяется ФОРМА (в файле есть `pr`), а не состояние GitHub: объявленное состояние чужой
    системы стареет молча, а форма — нет.
    """
    rep = dp.validate(_plan({**ACTIVE_ITEM, "pr": 118}))

    assert any("pr" in e and "todo" in e for e in rep["errors"]), rep["errors"]


def test_in_progress_without_a_trace_is_at_least_a_warning():
    """Работа «идёт», но ни ветки, ни PR — состояние работы негде посмотреть."""
    rep = dp.validate(_plan({**ACTIVE_ITEM, "status": "in_progress"}))

    assert rep["errors"] == []
    assert any("branch" in w for w in rep["warnings"]), rep["warnings"]


def test_evidence_that_does_not_resolve_is_an_error(tmp_path):
    """Ссылка на доказательство, которого нет, хуже её отсутствия."""
    rep = dp.validate(_plan({**ACTIVE_ITEM, "evidence": "qualification/net-takogo.md"}),
                      root=tmp_path)

    assert any("не резолвится" in e for e in rep["errors"]), rep["errors"]


def test_done_in_history_needs_a_named_result_not_a_merged_pr():
    """`done` — это НЕ «PR смержен»: нужен названный результат и место перепроверки."""
    no_result = dp.validate_history([_closed(result="")], None)
    no_proof = dp.validate_history([{**_closed(), "commit": None}], None)

    assert any("result" in e for e in no_result["errors"]), no_result["errors"]
    assert any("перепроверить" in e for e in no_proof["errors"]), no_proof["errors"]


def test_the_same_work_cannot_be_active_and_closed_at_once():
    """Работа в плане И в истории — два состояния одной работы."""
    plan = _plan(ACTIVE_ITEM)
    rep = dp.validate_history([_closed(id="aktivnaya")], plan)

    assert any("одновременно" in e for e in rep["errors"]), rep["errors"]


def test_a_corrupt_history_is_not_read_as_empty(tmp_path):
    """Битая история не превращается в «зависимостей нет» — иначе это ложный green.

    Пустой список здесь означал бы «закрытой работы не было», и зависимости молча стали бы
    неизвестными. Отказ чтения называется исключением, как и у самого плана.
    """
    (tmp_path / "history").mkdir()
    (tmp_path / "history" / "plan-history.yaml").write_text("kind: sovsem-drugoe\n", encoding="utf-8")

    with pytest.raises(dp.PlanCorrupt):
        dp.load_history(tmp_path)


def test_no_history_file_is_a_legal_state(tmp_path):
    """Истории нет — законное состояние молодого репозитория, а не поломка."""
    assert dp.load_history(tmp_path) == []


# ─── waiting_on_owner: механизм готов, ждём НАЗВАННОЕ действие владельца ──────────────────────────

def test_waiting_on_owner_without_a_named_action_is_an_error():
    """fail-closed: `waiting_on_owner` без непустого `waiting_on` — фантомное состояние.

    Смысл статуса — «ждём НАЗВАННЫЙ шаг владельца». Пока шаг не назван, статус неотличим от
    застрявшей работы: ровно та ловушка, ради которой статус и заведён. Поэтому валидатор требует
    непустой `waiting_on`, а не соглашается на «ждём чего-то».
    """
    no_key = dp.validate(_plan({**ACTIVE_ITEM, "status": "waiting_on_owner"}))
    blank = dp.validate(_plan({**ACTIVE_ITEM, "status": "waiting_on_owner", "waiting_on": "  "}))

    assert any("waiting_on_owner" in e and "waiting_on" in e and "фантомное" in e
               for e in no_key["errors"]), no_key["errors"]
    assert any("waiting_on_owner" in e and "waiting_on" in e for e in blank["errors"]), blank["errors"]


def test_waiting_on_owner_with_a_reason_is_valid_and_not_running(tmp_path):
    """positive: `waiting_on_owner` с причиной валиден, но НЕ считается идущей работой.

    Работа с этим статусом не движется и не брошена — она ждёт владельца. Значит валидатор её
    принимает, `declared_running` её НЕ включает (иначе `status`/`next` считали бы её идущей и
    сверка «идёт по плану, но нет прогона» пометила бы брошенной), а `resolve` показывает её как
    `waiting_on_owner` с названной причиной, а не пересчитывает в `ready`/`blocked`/`waiting`.
    """
    reason = "владелец включает «Require merge queue» в настройках GitHub"
    plan = _plan({**ACTIVE_ITEM, "status": "waiting_on_owner", "waiting_on": reason})

    rep = dp.validate(plan)
    assert rep["errors"] == [], rep["errors"]

    # НЕ идёт: declared_running видит только in_progress.
    assert dp.declared_running(plan) == []

    # resolve сохраняет объявленный статус и причину, не подменяя выводом из графа.
    res = dp.resolve(plan, tmp_path)
    got = res["aktivnaya"]
    assert got["status"] == "waiting_on_owner", got
    assert got["source"] == "declared", got
    assert got["drift"] is None, got
    assert any(reason in r for r in got["reasons"]), got["reasons"]


def test_waiting_on_owner_lives_in_the_active_plan_not_history():
    """side-effect: waiting_on_owner — открытая работа активного плана, не закрытая.

    Статус аддитивен: он вошёл в словарь активного плана и в объявляемые, но остался вне закрытых
    (`done`/`dropped`) — waiting ≠ done ≠ in_progress. Иначе ждущая владельца работа либо уехала бы
    в историю как завершённая, либо считалась бы идущей.
    """
    assert "waiting_on_owner" in dp.ACTIVE_DECLARABLE
    assert "waiting_on_owner" in dp.DECLARABLE
    assert "waiting_on_owner" not in dp.CLOSED_DECLARABLE
    assert "waiting_on_owner" not in dp.DERIVED
