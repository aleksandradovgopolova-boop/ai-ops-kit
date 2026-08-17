"""ШОВ: после обновления кита вопрос «что дальше» у дочки продолжает отвечать (F-030).

ПОЧЕМУ ОТДЕЛЬНЫМ ФАЙЛОМ И ЧЕРЕЗ `next_work`. Правило «закрытая работа живёт в history» пришло к
дочкам без миграции, и цена замерена дважды: «Окошко» — план стал невалидным сразу после обновления
(0 ошибок до, 28 после); ИИ-Среда, замер 17.08.2026 на копии обновления — `./ai-ops next`
ОТКАЗЫВАЕТСЯ отвечать и печатает 32 ошибки, по одной на каждую закрытую работу. Обновление у дочек
по умолчанию автоматическое: правило меняли у нас, а ломалось у них.

Поэтому проверяется не «миграция переложила записи» (это внутренность), а ГЛАВНЫЙ вопрос владельца:
после обновления кит по-прежнему говорит, что делать дальше. Тест, который смотрел бы только на
содержимое файлов, остался бы зелёным при сломанном ответе.

МУТАЦИОННЫЙ ЗАМЕР (17.08.2026) — в двух состояниях, зелено без мутации и красно с ней:
  • перенос выключен целиком                      -> test_after_migration_the_kit_answers_what_is_next
  • пометка «результат не записан» не ставится     -> test_migration_does_not_invent_results
  • валидатор снова требует место перепроверки     -> test_after_migration_the_kit_answers_what_is_next
  • повторный запуск переносит второй раз          -> test_second_run_changes_nothing
  • план без закрытых работ всё равно перезаписан  -> test_a_plan_with_nothing_to_move_is_left_alone
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.planning import delivery_plan as dp
from ai_ops_kit.planning import next_work as nw

KIT = Path(__file__).resolve().parents[2]
UP = KIT / "migrations" / "3.36-to-3.37-plan-history" / "up.py"
DOWN = KIT / "migrations" / "3.36-to-3.37-plan-history" / "down.py"

# План дочки ДО обновления: закрытые работы лежат в активном плане, потому что так было можно.
# Форма взята с настоящей дочки (ИИ-Среда): у закрытых работ нет ни `result`, ни места перепроверки.
PLAN_BEFORE = """\
schema_version: 1
kind: delivery-plan
goals:
  - id: g1
    status: active
work:
  # Комментарий владельца, который переписывание yaml не сохранит, — см. docstring миграции.
  - id: zakryta-davno
    title: Работа, закрытая до правила
    type: quality
    goal: g1
    status: done
    owner_role: engineer
    depends_on: []
    write_scope: [src/]
    value: high
  - id: zakryta-po-pravilam
    title: Работа, закрытая по правилам
    type: quality
    goal: g1
    status: done
    owner_role: engineer
    depends_on: []
    write_scope: [src/]
    value: medium
    result: механизм выпущен и подтверждён полем
    commit: abc123abc123
  - id: idet-sejchas
    title: Работа, которую можно взять
    type: quality
    goal: g1
    status: todo
    owner_role: engineer
    depends_on: [zakryta-davno]
    write_scope: [src/]
    value: high
"""

ROADMAP = """\
# ROADMAP

## Сейчас

- `g1` — направление, под которым идёт работа.

## Следующий результат

- `g1` — то же направление глазами пользователя.

## Дальше

- Крупное потом.

## Later

- Осознанно не берём.
"""


def _migrate(root, script=UP):
    return subprocess.run([sys.executable, str(script), str(root)],
                          capture_output=True, text=True, timeout=120)


@pytest.fixture()
def child(tmp_path):
    (tmp_path / "planning").mkdir()
    (tmp_path / "planning" / "plan.yaml").write_text(PLAN_BEFORE, encoding="utf-8")
    (tmp_path / "ROADMAP.md").write_text(ROADMAP, encoding="utf-8")
    return tmp_path


@pytest.mark.unit
@pytest.mark.regression
class TestUpdateDoesNotBreakWhatIsNext:
    def test_before_migration_the_answer_is_broken(self, child):
        """Сначала показываем, что дефект ВОСПРОИЗВЕДЁН здесь, а не только в поле.

        Без этого следующий тест ничего не доказывает: он мог бы быть зелёным и до миграции.
        """
        rep = nw.compute(child)
        assert rep["plan_errors"], "дефект не воспроизведён — тесту ниже нечего доказывать"
        # Отказ живёт в ТЕКСТЕ для человека: `compute` совет всё равно вычисляет, а не отдавать его
        # решает вывод. Поле замера (ИИ-Среда 17.08.2026) видело именно текст — «не могу предложить
        # следующую работу: описание плана содержит 32 ошибки».
        text = nw.render(rep)
        assert "✗ план:" in text, text
        assert "zakryta-davno" in text, "ошибка не названа адресно — владельцу нечего исправлять"

    def test_after_migration_the_kit_answers_what_is_next(self, child):
        """ГЛАВНОЕ: после миграции ответ «что дальше» снова получен, а не отказ."""
        r = _migrate(child)
        assert r.returncode == 0, f"миграция упала: {r.stdout}\n{r.stderr}"

        rep = nw.compute(child)
        assert rep["plan_errors"] == [], f"план всё ещё недостоверен: {rep['plan_errors']}"
        assert (rep["next_best"] or {}).get("id") == "idet-sejchas", rep.get("next_best")

        text = nw.render(rep)
        assert "Работа, которую можно взять" in text, text
        assert "ошибк" not in text.lower(), f"человеку по-прежнему говорят об ошибках: {text}"

    def test_migration_does_not_invent_results(self, child):
        """Перенос НЕ пишет за владельца, «что получилось» — это решение владельца 17.08.2026.

        Закрытая до правила работа получает честное «результат не записан» и пометку; работа,
        закрытая ПО правилам, свой результат сохраняет и пометки не получает.
        """
        assert _migrate(child).returncode == 0
        hist = yaml.safe_load((child / "history" / "plan-history.yaml").read_text(encoding="utf-8"))
        by_id = {w["id"]: w for w in hist["work"]}

        davno = by_id["zakryta-davno"]
        assert davno["migrated_without_result"] is True
        assert "результат при закрытии не записан" in davno["result"], davno["result"]
        assert not any(davno.get(k) for k in ("pr", "commit", "evidence", "finding")), \
            "миграция выдумала место перепроверки"

        po_pravilam = by_id["zakryta-po-pravilam"]
        assert "migrated_without_result" not in po_pravilam, \
            "работа с записанным результатом помечена как перенесённая без него"
        assert po_pravilam["result"] == "механизм выпущен и подтверждён полем"

    def test_second_run_changes_nothing(self, child):
        """Идемпотентность: обновление у дочек автоматическое, миграция побежит ещё не раз."""
        assert _migrate(child).returncode == 0
        after_first = (child / "history" / "plan-history.yaml").read_bytes()
        r2 = _migrate(child)
        assert r2.returncode == 0, r2.stderr
        assert (child / "history" / "plan-history.yaml").read_bytes() == after_first, \
            "повторный запуск изменил историю — записи задвоятся"
        assert nw.compute(child)["plan_errors"] == []

    def test_a_work_already_in_history_is_not_duplicated(self, child):
        """Состояние «уже в истории, но осталось и в плане» — реальное, и оно опаснее прочих.

        Так выглядит дочка, где перенос делали руками или он прервался: запись есть в обоих местах.
        Контракт истории запрещает и дубли id, и одновременное присутствие работы в плане и истории —
        то есть наивный перенос сделал бы план невалидным ДРУГИМ способом, вместо старого.
        Мутационная проба 17.08.2026: без этого теста снятие сверки по id остаётся незамеченным —
        в остальных сценариях до неё не доходит очередь (закрытых работ уже нет, ранний выход).
        """
        (child / "history").mkdir()
        (child / "history" / "plan-history.yaml").write_text(
            "schema_version: 1\nkind: delivery-plan-history\nwork:\n"
            "  - id: zakryta-davno\n    title: Работа, закрытая до правила\n    goal: g1\n"
            "    status: done\n    closed_at: '2026-08-01'\n"
            "    result: перенесено руками, результат тогда записали\n    commit: deadbeef\n",
            encoding="utf-8")

        assert _migrate(child).returncode == 0
        hist = yaml.safe_load((child / "history" / "plan-history.yaml").read_text(encoding="utf-8"))
        ids = [w["id"] for w in hist["work"]]
        assert ids.count("zakryta-davno") == 1, f"запись задвоилась: {ids}"
        assert "перенесено руками" in [w for w in hist["work"]
                                       if w["id"] == "zakryta-davno"][0]["result"], \
            "миграция переписала уже записанный результат"

        plan = yaml.safe_load((child / "planning" / "plan.yaml").read_text(encoding="utf-8"))
        assert "zakryta-davno" not in {w["id"] for w in plan["work"]}, \
            "работа осталась и в плане, и в истории — два состояния одной работы"
        assert dp.validate_history(hist["work"], plan)["errors"] == [], \
            dp.validate_history(hist["work"], plan)["errors"]

    def test_a_plan_with_nothing_to_move_is_left_alone(self, tmp_path):
        """План без закрытых работ НЕ переписывается — иначе миграция стирала бы разбор владельца.

        Комментарии yaml переписыванием теряются, и это названо в миграции прямо. Значит цена
        переписывания платится только там, где перенос действительно нужен.
        """
        (tmp_path / "planning").mkdir()
        plan = textwrap.dedent("""\
            schema_version: 1
            kind: delivery-plan
            goals:
              - id: g1
                status: active
            work:
              # ЗАМЕР, который стоил владельцу дня: этот комментарий обязан выжить.
              - id: idet-sejchas
                title: Работа, которую можно взять
                type: quality
                goal: g1
                status: todo
                owner_role: engineer
                depends_on: []
                write_scope: [src/]
                value: high
            """)
        p = tmp_path / "planning" / "plan.yaml"
        p.write_text(plan, encoding="utf-8")
        before = p.read_bytes()

        r = _migrate(tmp_path)
        assert r.returncode == 0, r.stderr
        assert p.read_bytes() == before, "план без закрытых работ переписан — комментарии потеряны"
        assert not (tmp_path / "history").exists(), "создана пустая история"

    def test_migration_keeps_hands_off_the_kit_template(self, tmp_path):
        """Заготовка кита планом продукта не является — её трогать нельзя."""
        (tmp_path / "planning").mkdir()
        p = tmp_path / "planning" / "plan.yaml"
        p.write_text("schema_version: 1\nkind: delivery-plan\ntemplate: true\n"
                     "work:\n  - id: primer\n    status: done\n", encoding="utf-8")
        before = p.read_bytes()
        assert _migrate(tmp_path).returncode == 0
        assert p.read_bytes() == before

    def test_rollback_returns_only_what_migration_created(self, child):
        """Откат возвращает в план ТОЛЬКО перенесённое без результата — остальное там и не было."""
        assert _migrate(child).returncode == 0
        r = _migrate(child, DOWN)
        assert r.returncode == 0, r.stderr

        plan = yaml.safe_load((child / "planning" / "plan.yaml").read_text(encoding="utf-8"))
        ids = {w["id"] for w in plan["work"]}
        assert "zakryta-davno" in ids, "перенесённая без результата не вернулась"
        assert "zakryta-po-pravilam" not in ids, "в активный план вернули закрытую по правилам"
        returned = [w for w in plan["work"] if w["id"] == "zakryta-davno"][0]
        assert "migrated_without_result" not in returned and "result" not in returned, \
            "служебные поля миграции остались в активном плане"


@pytest.mark.unit
class TestHistoryContractStaysStrictForNewClosures:
    """Исключение для перенесённых записей не должно стать лазейкой для новых закрытий."""

    def test_migrated_entry_is_a_warning_not_an_error(self):
        closed = [{"id": "staraya", "status": "done", "closed_at": "2026-01-01",
                   "result": "результат при закрытии не записан",
                   "migrated_without_result": True}]
        r = dp.validate_history(closed)
        assert r["errors"] == [], r["errors"]
        assert any("перенесено миграцией" in w for w in r["warnings"]), r["warnings"]

    def test_a_new_closure_without_a_place_to_recheck_is_still_an_error(self):
        closed = [{"id": "novaya", "status": "done", "closed_at": "2026-08-17",
                   "result": "сделано и проверено"}]
        r = dp.validate_history(closed)
        assert any("негде" in e for e in r["errors"]), r["errors"]

    def test_migration_mark_does_not_excuse_a_missing_result(self):
        """Пометка снимает требование места перепроверки, но НЕ требование назвать результат."""
        closed = [{"id": "pustaya", "status": "done", "closed_at": "2026-01-01",
                   "migrated_without_result": True}]
        r = dp.validate_history(closed)
        assert any("нет result" in e for e in r["errors"]), r["errors"]
