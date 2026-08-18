"""«Что идёт сейчас» отвечается по ДВУМ источникам: реестр рантайма и план.

Работа `what-is-running-answered-from-the-plan`. ЗАМЕР 18.08.2026 на самом ките: `ai-ops status`
печатал «Сейчас ничего не идёт. Работа не начата.» при СЕМИ работах в статусе `in_progress` в плане.
Проба тогда же: одной работе поставили `in_progress` — ответ не изменился ни одним словом.

Приёмка этой работы объявлена ПРОБОЙ ШВА, а не модульным тестом: работа в плане со статусом
`in_progress` обязана менять ответ команды `status`. Поэтому главный тест здесь зовёт CLI ПРОЦЕССОМ
на подготовленном репозитории — путь человека целиком, включая слой человеческого языка.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ai_ops_kit.planning import delivery_plan as dp
from ai_ops_kit.ui import presenter

KIT_ROOT = Path(__file__).resolve().parents[2]

PLAN = """schema_version: 1
kind: delivery-plan
goals:
  - id: g1
    status: active
work:
  - id: wi-alpha
    title: Альфа — экспорт заказов
    type: engineering
    goal: g1
    status: {alpha}
    owner_role: engineer
    depends_on: []
    write_scope: [src/]
    value: high
  - id: wi-beta
    title: Бета — отчёт по неделе
    type: engineering
    goal: g1
    status: todo
    owner_role: engineer
    depends_on: []
    write_scope: [docs/]
    value: medium
"""


def _repo(tmp_path, *, alpha="todo", registry=None):
    root = tmp_path / "repo"
    (root / "planning").mkdir(parents=True)
    (root / ".ai" / "runtime").mkdir(parents=True)
    (root / ".ai-ops.yaml").write_text("project:\n  name: repo\n", encoding="utf-8")
    (root / "planning" / "plan.yaml").write_text(PLAN.format(alpha=alpha), encoding="utf-8")
    if registry is not None:
        (root / ".ai" / "runtime" / "active-work.yaml").write_text(registry, encoding="utf-8")
    for a in (["init"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-m", "init"]):
        subprocess.run(["git", *a], cwd=root, capture_output=True)
    return root


def _status(root):
    r = subprocess.run(
        [sys.executable, str(KIT_ROOT / "ai_ops_kit" / "cli" / "ai_ops_cli.py"), "status", str(root)],
        capture_output=True, text=True, cwd=str(KIT_ROOT),
        env={"PATH": "/usr/bin:/bin", "HOME": str(root), "PYTHONPATH": str(KIT_ROOT)})
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


class TestSeamPlanChangesTheAnswer:
    """Проба шва из приёмки: объявленная в плане идущая работа обязана менять ответ `status`."""

    def test_in_progress_in_plan_changes_the_answer(self, tmp_path):
        quiet = _status(_repo(tmp_path / "a", alpha="todo"))
        loud = _status(_repo(tmp_path / "b", alpha="in_progress"))
        assert quiet != loud, \
            "ответ не изменился от того, что в плане объявлена идущая работа — ровно замер 18.08.2026"
        assert "ничего не идёт" in quiet, quiet
        assert "расход" in loud.lower(), \
            f"расхождение плана с заявками не названо: {loud}"
        assert "Альфа" in loud, f"человек не видит, О КАКОЙ работе речь: {loud}"

    def test_answer_names_the_two_facts_it_judges_by(self, tmp_path):
        """«Ничего не идёт» обязано называть основание: это не «я всё осмотрел», а два конкретных
        факта. Иначе «не знаю» снова читается как «нет»."""
        out = _status(_repo(tmp_path, alpha="todo"))
        assert "заявок на работу нет" in out.lower() and "в плане" in out.lower(), out

    def test_registry_and_plan_agree_no_false_alarm(self, tmp_path):
        """КОНТРОЛЬ: заявка есть и она про ТУ ЖЕ работу — расхождения нет, тревоги быть не должно."""
        reg = ("schema_version: 1\nkind: active-work\nactive:\n"
               "  - id: wi-alpha\n    workitem: wi-alpha\n    title: Альфа — экспорт заказов\n"
               "    branch: ai-ops/alpha\n    status: in_progress\n    session: cli\n"
               "    machine: test\n")
        out = _status(_repo(tmp_path, alpha="in_progress", registry=reg))
        assert "расход" not in out.lower(), f"ложная тревога при согласии двух источников: {out}"
        assert "работа идёт" in out.lower(), out


class TestCrosscheckIsNotAThirdSourceOfTruth:
    """Сверка складывает два существующих источника и не заводит третий."""

    def test_declared_running_reads_the_plan_only(self, tmp_path):
        root = _repo(tmp_path, alpha="in_progress")
        rep = dp.crosscheck_running(root, [], registry_exists=False)
        assert [w["id"] for w in rep["declared"]] == ["wi-alpha"]
        assert [w["id"] for w in rep["only_in_plan"]] == ["wi-alpha"]
        assert rep["registry_exists"] is False and rep["plan_exists"] is True

    def test_matching_registration_removes_the_divergence(self, tmp_path):
        root = _repo(tmp_path, alpha="in_progress")
        rep = dp.crosscheck_running(root, [{"workitem": "wi-alpha"}], registry_exists=True)
        assert rep["only_in_plan"] == [], rep
        assert rep["registry_count"] == 1

    def test_missing_plan_is_not_a_crash(self, tmp_path):
        """Плана нет — законное состояние молодого репозитория: сверка возвращает пустоту и
        говорит, что плана нет, а не падает и не выдумывает."""
        root = tmp_path / "bare"
        root.mkdir()
        rep = dp.crosscheck_running(root, [], registry_exists=False)
        assert rep["plan_exists"] is False and rep["declared"] == []

    def test_corrupt_plan_is_raised_not_swallowed(self, tmp_path):
        root = _repo(tmp_path, alpha="todo")
        (root / "planning" / "plan.yaml").write_text("work: [не-словарь\n", encoding="utf-8")
        with pytest.raises(dp.PlanCorrupt):
            dp.crosscheck_running(root, [], registry_exists=False)


class TestPresenterNamesDivergenceOnBothBranches:
    """Расхождение называется и при пустом реестре, и при живой работе."""

    def _cross(self, ids):
        return {"plan_exists": True, "registry_exists": False,
                "declared": [{"id": i, "title": f"работа {i}"} for i in ids],
                "only_in_plan": [{"id": i, "title": f"работа {i}"} for i in ids],
                "registry_count": 0}

    def test_empty_registry_with_declared_work_is_not_ok(self):
        msg = presenter.from_active_work({"active": []}, crosscheck=self._cross(["wi-1"]))
        assert msg["status"] == "degraded", \
            "расхождение подано как норма — это форма ложного green в самом частом вопросе"

    def test_live_work_plus_divergence_is_still_reported(self):
        """Половина расхождения при живой работе: заявка на одно, план объявляет идущим ещё что-то.
        Прежний код в этой ветке не смотрел на план вовсе."""
        msg = presenter.from_active_work(
            {"active": [{"id": "wi-9", "workitem": "wi-9", "title": "живая", "status": "in_progress"}]},
            crosscheck=self._cross(["wi-1"]))
        assert msg["status"] == "degraded", msg
        assert "без заявки" in (msg.get("why_it_matters") or ""), msg

    def test_no_crosscheck_at_all_keeps_the_old_answer(self):
        """Совместимость: вызывающий без сверки (например JSON-путь или чужой код) получает прежний
        ответ, а не тревогу из пустоты."""
        msg = presenter.from_active_work({"active": []})
        assert msg["status"] == "ok" and "ничего не идёт" in msg["headline"].lower()

    @pytest.mark.parametrize("k,form", [(1, "работа объявлена идущей"),
                                        (2, "работы объявлены идущими"),
                                        (5, "работ объявлено идущими")])
    def test_numbers_agree_with_words(self, k, form):
        """Строку читает человек: «в плане 1 работа объявлена идущими» — брак, который замер увидел
        сразу же на живом ответе."""
        msg = presenter.from_active_work(
            {"active": []}, crosscheck=self._cross([f"wi-{i}" for i in range(k)]))
        assert form in msg["summary"], msg["summary"]


class TestJsonPathStillWorks:
    """JSON-путь ответа не задет: он отдаёт реестр, и потребитель у него другой."""

    def test_json_status_is_valid_json_or_empty(self, tmp_path):
        root = _repo(tmp_path, alpha="in_progress")
        r = subprocess.run(
            [sys.executable, str(KIT_ROOT / "ai_ops_kit" / "cli" / "ai_ops_cli.py"),
             "status", str(root), "--json"],
            capture_output=True, text=True, cwd=str(KIT_ROOT),
            env={"PATH": "/usr/bin:/bin", "HOME": str(root), "PYTHONPATH": str(KIT_ROOT)})
        assert r.returncode == 0, r.stdout + r.stderr
        if r.stdout.strip():
            json.loads(r.stdout)
