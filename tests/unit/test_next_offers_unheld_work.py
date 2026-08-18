"""«Что взять МНЕ»: из готовых работ вычитается то, что держат другие.

Работа `next-offers-work-nobody-holds`. Два условия владельца 18.08.2026: она не думает о том, как
устроить эту работу, а участник не беспокоится, что дублирует чужое. Заявка потребителя #150: сессия B
взяла работу, которую уже держала сессия A, — половина труда ушла в закрытый пустой дубль.

Важность и непересечение по `write_scope` кит считал и раньше. Отсутствовало ровно одно: `next`
отвечал на вопрос РЕПОЗИТОРИЯ («какая работа следующая»), а не участника («что взять мне»).
"""
import os
import subprocess
from pathlib import Path

import pytest

from ai_ops_kit.lifecycle import active_work as aw
from ai_ops_kit.planning import next_work
from ai_ops_kit.ui import presenter

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
    status: todo
    owner_role: engineer
    depends_on: []
    write_scope: [src/export/]
    value: high
  - id: wi-beta
    title: Бета — отчёт по неделе
    type: engineering
    goal: g1
    status: todo
    owner_role: engineer
    depends_on: []
    write_scope: [src/report/]
    value: medium
"""


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "planning").mkdir(parents=True)
    (root / ".ai" / "runtime").mkdir(parents=True)
    (root / "planning" / "plan.yaml").write_text(PLAN, encoding="utf-8")
    # ROADMAP по контракту кита: горизонты «Сейчас» и «Следующий результат» обязательны, цели
    # называются в обратных кавычках. Без валидного направления `next` (справедливо) отвечает про
    # ошибки описания, и проверять вычитание было бы нечем.
    (root / "ROADMAP.md").write_text(
        "# Направление продукта\n\n## Сейчас\n- `g1` — выпустить экспорт и отчёт\n\n"
        "## Следующий результат\n- пользователь выгружает заказы за неделю сам\n\n"
        "## Дальше\n- аналитика по выгрузкам\n\n## Не берём\n- мобильное приложение\n",
        encoding="utf-8")
    (root / "f.txt").write_text("x\n", encoding="utf-8")
    for a in (["init", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-m", "init"]):
        subprocess.run(["git", *a], cwd=root, capture_output=True)
    return root


def _reg(repo):
    return repo / ".ai" / "runtime" / "active-work.yaml"


class TestHeldWorkIsSubtracted:
    def test_offer_moves_to_the_free_work(self, repo, capsys):
        first = next_work.compute(repo, me="session:bbbb")["next_best"]
        assert first["id"] == "wi-alpha", "порядок по ценности сломан — дальше проверять нечего"

        aw.register(_reg(repo), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"], "session:aaaa")
        capsys.readouterr()
        rep = next_work.compute(repo, me="session:bbbb")
        assert rep["next_best"]["id"] == "wi-beta", \
            "предложена работа, которую держит другая сессия — ровно случай #150"
        assert [h["id"] for h in rep["held_by_others"]] == ["wi-alpha"]
        assert rep["held_by_others"][0]["owner_session"] == "session:aaaa", \
            "держатель не назван: участник не может ни подождать, ни спросить"

    def test_everything_held_is_said_plainly(self, repo, capsys):
        aw.register(_reg(repo), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"], "session:aaaa")
        aw.register(_reg(repo), "wi-beta", "ai-ops/wi-beta", ["src/report/"], "session:cccc")
        capsys.readouterr()
        rep = next_work.compute(repo, me="session:bbbb")
        assert rep["next_best"] is None, "выдана взятая работа вместо честного «всё держат»"
        assert len(rep["held_by_others"]) == 2

        msg = presenter.from_next_work(rep)
        assert "держат другие" in (msg.get("headline") or ""), msg
        assert "session:aaaa" in msg["summary"] or "session:cccc" in msg["summary"], msg["summary"]

    def test_my_own_claim_is_mine_not_someone_elses(self, repo, capsys):
        aw.register(_reg(repo), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"], "session:bbbb")
        capsys.readouterr()
        rep = next_work.compute(repo, me="session:bbbb")
        assert [h["id"] for h in rep["held_by_me"]] == ["wi-alpha"]
        assert rep["held_by_others"] == [], \
            "своя же работа посчитана чужой — участник будет ждать сам себя"

    def test_unknown_identity_is_fail_closed_and_named(self, repo, capsys):
        """Личность не измерилась — считаем заявки чужими (не предлагать возможно занятое) и ГОВОРИМ,
        что личности нет. Обратное («личности нет, значит всё моё») выдало бы занятое за свободное."""
        aw.register(_reg(repo), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"], "session:aaaa")
        capsys.readouterr()
        rep = next_work.compute(repo, me=None)
        assert [h["id"] for h in rep["held_by_others"]] == ["wi-alpha"]
        assert rep["holders_reach"]["identity"] is False

    def test_reach_is_named_in_the_answer(self, repo, capsys):
        """Пока публикация выключена, «никто не держит» проверено только для этой машины — и ответ
        обязан это сказать, а не выдавать локальное состояние за координацию."""
        aw.register(_reg(repo), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"], "session:aaaa")
        aw.register(_reg(repo), "wi-beta", "ai-ops/wi-beta", ["src/report/"], "session:cccc")
        capsys.readouterr()
        rep = next_work.compute(repo, me="session:bbbb")
        msg = presenter.from_next_work(rep)
        assert rep["holders_reach"]["published"] is False
        assert "машин" in (msg.get("why_it_matters") or "").lower(), msg


class TestClaimFromAnotherMachine:
    """Пара из приёмки: публикация выключена -> честно «вижу только свою машину»; включена -> чужая
    заявка ВИДНА и работа не предлагается.

    Именно здесь вычитание держателей и делает работу: локальная карта `_active_map` читает ТОЛЬКО
    свой файл, поэтому опубликованная заявка другой машины в `resolve` не попадает вовсе — без
    вычитания кит предложил бы взятое, имея все данные, чтобы этого не делать.
    """

    def _publish_foreign_claim(self, repo, wid, machine="ноутбук-коллеги"):
        aw.publish_claim(repo, {"id": wid, "workitem": wid, "branch": f"ai-ops/{wid}",
                                "status": "in-progress", "affected_areas": ["src/export/"],
                                "owner_session": "session:zzzz", "machine": machine,
                                "started_at": "2026-08-18T10:00:00+00:00"})

    def test_published_foreign_claim_hides_the_work(self, repo):
        (repo / ".ai-ops.yaml").write_text("team_coordination:\n  publish: true\n", encoding="utf-8")
        self._publish_foreign_claim(repo, "wi-alpha")
        rep = next_work.compute(repo, me="session:bbbb")
        assert [h["id"] for h in rep["held_by_others"]] == ["wi-alpha"], \
            "чужая опубликованная заявка не увидена — вычитать было нечем"
        assert rep["next_best"]["id"] == "wi-beta", \
            "предложена работа, взятая на другой машине: ровно то, ради чего носитель и делался"
        assert rep["holders_reach"]["published"] is True

    def test_without_publication_the_same_claim_is_invisible_and_that_is_said(self, repo):
        """КОНТРОЛЬ и вторая половина пары: та же заявка при выключенной публикации не видна — и кит
        обязан сказать, что видит только свою машину, а не молчать."""
        self._publish_foreign_claim(repo, "wi-alpha")
        rep = next_work.compute(repo, me="session:bbbb")
        assert rep["held_by_others"] == []
        assert rep["holders_reach"]["published"] is False
        assert "только" in rep["holders_reach"]["note"].lower(), rep["holders_reach"]["note"]


class TestSeamIdentityReachesTheAnswer:
    """ШОВ: личность спрашивающего обязана ДОЕЗЖАТЬ от команды до отбора работы.

    Найдено проверкой проб самого кита: у механизма были охранные пробы и НЕ БЫЛО пробы шва —
    отключённый вызов остался бы незамеченным, потому что модульные тесты зовут `compute` напрямую и
    передают личность сами. Здесь личность приходит из процесса команды, как у человека.
    """

    def test_next_json_carries_the_asker_identity(self, repo, capsys):
        import json
        import sys
        aw.register(_reg(repo), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"], "session:aaaa")
        capsys.readouterr()
        r = subprocess.run(
            [sys.executable, str(Path(next_work.__file__).parents[2] / "ai_ops_kit" / "cli" / "ai_ops_cli.py"),
             "next", str(repo), "--json"],
            capture_output=True, text=True,
            cwd=str(Path(next_work.__file__).parents[2]),
            env={"PATH": "/usr/bin:/bin", "HOME": str(repo),
                 "PYTHONPATH": str(Path(next_work.__file__).parents[2])})
        assert r.returncode == 0, r.stdout + r.stderr
        rep = json.loads(r.stdout)
        assert (rep.get("asked_by") or "").startswith(("session:", "pid:")), \
            f"личность не доехала до отбора работы: asked_by={rep.get('asked_by')!r}"
        assert [h["id"] for h in rep["held_by_others"]] == ["wi-alpha"], rep["held_by_others"]


class TestControls:
    def test_no_claims_no_subtraction(self, repo):
        rep = next_work.compute(repo, me="session:bbbb")
        assert rep["held_by_others"] == [] and rep["held_by_me"] == []
        assert rep["next_best"]["id"] == "wi-alpha"

    def test_dead_holder_does_not_hide_work(self, repo, capsys):
        aw.register(_reg(repo), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"], "pid:999999")
        capsys.readouterr()
        rep = next_work.compute(repo, me=f"pid:{os.getpid()}")
        assert rep["held_by_others"] == [], "работу спрятал процесс, которого нет"
        assert rep["next_best"]["id"] == "wi-alpha"

    def test_finished_claim_does_not_hide_work(self, repo, capsys):
        aw.register(_reg(repo), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"], "session:aaaa")
        aw.finish_cmd(_reg(repo), "wi-alpha", status="done")
        capsys.readouterr()
        rep = next_work.compute(repo, me="session:bbbb")
        assert rep["held_by_others"] == []

    def test_plan_rule_role_not_assignee_is_untouched(self, repo, capsys):
        """Держателя называет РЕЕСТР РАНТАЙМА, а не план: правило «роль, а не исполнитель» остаётся.
        Проверяется по поведению, а не по слову в файле: план с полем `assignee` невалиден, и держателя
        из него взять нельзя — вычитание работает ровно из заявки."""
        plan = (repo / "planning" / "plan.yaml")
        plan.write_text(plan.read_text(encoding="utf-8").replace(
            "    value: high", "    value: high\n    assignee: вася", 1), encoding="utf-8")
        rep = next_work.compute(repo, me="session:bbbb")
        assert any("assignee" in e or "исполнител" in e.lower() for e in rep["plan_errors"]), \
            f"поле исполнителя в плане принято молча: {rep['plan_errors']}"
