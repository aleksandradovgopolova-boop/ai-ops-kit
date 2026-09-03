"""Канал наблюдений о ките из продуктового репозитория (17.08.2026).

ШВЫ, а не наличие функций. Пять свойств — по одному на каждый способ, которым такой канал умирает:

  1. дефект без улики НЕ записывается: иначе канал производит утверждения, за которые некому
     отвечать (кит уже платил за это в обратную сторону — evidence-слой и ложный green);
  2. трение и вопрос БЕЗ улик записываются: требовать доказательство от впечатления значит запретить
     о нём говорить;
  3. доставка — это ДВЕ записи: копия в ките И состояние в дочке. Одно без другого не считается,
     иначе наблюдение соберётся дважды или дочке соврут;
  4. решение по наблюдению возвращается В ДОЧКУ, и отклонение без причины невозможно: канал в одну
     сторону перестают наполнять;
  5. один и тот же текст даёт ОДИН файл и не сбрасывает уже принятое решение.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.engops import kit_feedback as kf

STATEMENT = "кит обновил себя сам, при том что в настройках стоит обновление только через запрос"


def _child(tmp_path, name="ii-sreda"):
    d = tmp_path / name
    (d / ".ai").mkdir(parents=True)
    return d


def _kit(tmp_path):
    d = tmp_path / "kit"
    d.mkdir()
    (d / "VERSION").write_text("3.36.10\n", encoding="utf-8")
    return d


@pytest.mark.critical_path
@pytest.mark.unit
class TestEvidenceIsRequiredOnlyWhereItMeansSomething:
    def test_defect_without_evidence_is_refused(self, tmp_path):
        """Свойство 1. Мутация «писать всё подряд» обязана краснеть здесь."""
        child = _child(tmp_path)
        p, created, errors = kf.record(child, STATEMENT, observation_class="defect")
        assert created is False
        assert not p.exists()
        assert any("требует улику" in e for e in errors)

    def test_friction_without_evidence_is_recorded(self, tmp_path):
        """Свойство 2: впечатление — законное наблюдение, просто не дефект."""
        child = _child(tmp_path)
        p, created, errors = kf.record(child, "процесс кита мешает, когда задача уже описана",
                                       observation_class="friction")
        assert created is True and errors == []
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert doc["observation_class"] == "friction"
        assert kf.evidenced(doc) is False

    def test_class_is_derived_from_evidence_when_not_declared(self, tmp_path):
        child = _child(tmp_path)
        ev = kf.evidence_from_args([".ai/runtime/last-update-report.json=\"pull_request\": null"],
                                   None, None)
        p, created, errors = kf.record(child, STATEMENT, evidence=ev)
        assert created is True and errors == []
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert doc["observation_class"] == "defect", "улика есть — по умолчанию это дефект"
        assert doc["evidence"][0]["path"].endswith("last-update-report.json")
        assert "pull_request" in doc["evidence"][0]["quote"]

    def test_evidence_without_path_is_caught(self, tmp_path):
        child = _child(tmp_path)
        _, created, errors = kf.record(child, STATEMENT,
                                       evidence=[{"kind": "file", "quote": "что-то"}])
        assert created is False and any("без path" in e for e in errors)

    def test_note_is_not_evidence(self, tmp_path):
        """Пояснение уликой не считается — иначе «дефект с уликой» делался бы из любого текста."""
        child = _child(tmp_path)
        ev = kf.evidence_from_args(None, None, ["мне кажется, дело в этом"])
        _, created, errors = kf.record(child, STATEMENT, evidence=ev, observation_class="defect")
        assert created is True, "запись идёт: заметка — законная часть наблюдения"
        doc = yaml.safe_load(kf.child_path(child, kf.make_id(STATEMENT)).read_text(encoding="utf-8"))
        assert doc["evidence"][0]["kind"] == "note"
        assert errors == []


@pytest.mark.critical_path
@pytest.mark.unit
class TestDeliveryIsTwoRecords:
    def test_collect_writes_to_kit_and_marks_the_child(self, tmp_path):
        """Свойство 3. Копия без отметки соберётся ещё раз; отметка без копии соврёт дочке."""
        child, kit = _child(tmp_path), _kit(tmp_path)
        ev = kf.evidence_from_args(["src/a.py=строка"], None, None)
        kf.record(child, STATEMENT, evidence=ev)
        rep = kf.collect(kit, [child])
        assert len(rep["delivered"]) == 1 and rep["errors"] == []
        oid = rep["delivered"][0]["id"]
        assert kf.kit_path(kit, oid).is_file(), "копии в ките нет — доставки не было"
        in_child = yaml.safe_load(kf.child_path(child, oid).read_text(encoding="utf-8"))
        assert in_child["state"] == "delivered"
        assert in_child["delivered_to"]["kit_root"].endswith("kit")

    def test_second_collect_does_not_deliver_again(self, tmp_path):
        child, kit = _child(tmp_path), _kit(tmp_path)
        kf.record(child, STATEMENT, evidence=kf.evidence_from_args(["src/a.py=строка"], None, None))
        kf.collect(kit, [child])
        rep = kf.collect(kit, [child])
        assert rep["delivered"] == [] and len(rep["already"]) == 1

    def test_dry_run_writes_nothing(self, tmp_path):
        """Запись в чужое дерево человек вправе увидеть до того, как она произошла."""
        child, kit = _child(tmp_path), _kit(tmp_path)
        kf.record(child, STATEMENT, evidence=kf.evidence_from_args(["src/a.py=строка"], None, None))
        rep = kf.collect(kit, [child], dry_run=True)
        assert len(rep["delivered"]) == 1
        assert not (kit / "findings").exists()
        oid = kf.make_id(STATEMENT)
        assert yaml.safe_load(kf.child_path(child, oid).read_text(encoding="utf-8"))["state"] == "new"

    def test_unevidenced_travels_but_is_named(self, tmp_path):
        """Наблюдение без улик доезжает — и названо тем, что оно есть. Не отказ и не тишина."""
        child, kit = _child(tmp_path), _kit(tmp_path)
        kf.record(child, "кит мешает на описанной задаче", observation_class="friction")
        rep = kf.collect(kit, [child])
        assert len(rep["delivered"]) == 1 and len(rep["unevidenced"]) == 1

    def test_unreadable_observation_is_an_error_not_silence(self, tmp_path):
        child, kit = _child(tmp_path), _kit(tmp_path)
        bad = child / kf.CHILD_DIR / "obs-broken.yaml"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("statement: [не закрыт\n", encoding="utf-8")
        rep = kf.collect(kit, [child])
        assert rep["errors"], "битое наблюдение обязано быть названо, а не пропущено молча"


@pytest.mark.critical_path
@pytest.mark.unit
class TestAnswerComesBack:
    def test_decision_reaches_the_child(self, tmp_path):
        """Свойство 4: судьба наблюдения видна там, где его записали."""
        child, kit = _child(tmp_path), _kit(tmp_path)
        kf.record(child, STATEMENT, evidence=kf.evidence_from_args(["src/a.py=строка"], None, None))
        oid = kf.collect(kit, [child])["delivered"][0]["id"]
        doc, errors = kf.set_state(kit, child, oid, "became_work",
                                   reason="принято", work_item="update-policy-enforced")
        assert errors == [] and doc["state"] == "became_work"
        in_child = yaml.safe_load(kf.child_path(child, oid).read_text(encoding="utf-8"))
        assert in_child["state"] == "became_work"
        assert in_child["became_work"] == "update-policy-enforced"

    def test_rejection_without_a_reason_is_impossible(self, tmp_path):
        child, kit = _child(tmp_path), _kit(tmp_path)
        kf.record(child, STATEMENT, evidence=kf.evidence_from_args(["src/a.py=строка"], None, None))
        oid = kf.collect(kit, [child])["delivered"][0]["id"]
        doc, errors = kf.set_state(kit, child, oid, "rejected")
        assert doc is None and any("без причины" in e for e in errors)
        in_child = yaml.safe_load(kf.child_path(child, oid).read_text(encoding="utf-8"))
        assert in_child["state"] == "delivered", "неудачное решение не должно портить состояние"

    def test_status_shows_waiting_and_decided(self, tmp_path):
        child, kit = _child(tmp_path), _kit(tmp_path)
        kf.record(child, STATEMENT, evidence=kf.evidence_from_args(["src/a.py=строка"], None, None))
        kf.record(child, "второе замечание про процесс", observation_class="friction")
        oid = kf.make_id(STATEMENT)
        kf.collect(kit, [child])
        kf.set_state(kit, child, oid, "accepted", reason="воспроизведено")
        rep = kf.status(child)
        assert rep["total"] == 2
        assert [d["state"] for d in rep["decided"]] == ["accepted"]
        assert len(rep["waiting"]) == 1


@pytest.mark.unit
class TestIdentityIsStable:
    def test_same_statement_gives_one_file(self, tmp_path):
        """Свойство 5а: журнал не наполняется копиями одного наблюдения."""
        child = _child(tmp_path)
        ev = kf.evidence_from_args(["src/a.py=строка"], None, None)
        p1, c1, _ = kf.record(child, STATEMENT, evidence=ev)
        p2, c2, _ = kf.record(child, STATEMENT, evidence=ev)
        assert p1 == p2 and c1 is True and c2 is False
        assert len(list((child / kf.CHILD_DIR).glob("*.yaml"))) == 1

    def test_repeating_does_not_reset_a_decision(self, tmp_path):
        """Свойство 5б: сказать второй раз — не значит вернуть наблюдение в начало."""
        child, kit = _child(tmp_path), _kit(tmp_path)
        ev = kf.evidence_from_args(["src/a.py=строка"], None, None)
        kf.record(child, STATEMENT, evidence=ev)
        oid = kf.collect(kit, [child])["delivered"][0]["id"]
        kf.set_state(kit, child, oid, "rejected", reason="не воспроизводится")
        kf.record(child, STATEMENT, evidence=ev)
        doc = yaml.safe_load(kf.child_path(child, oid).read_text(encoding="utf-8"))
        assert doc["state"] == "rejected"

    def test_id_does_not_depend_on_the_child(self, tmp_path):
        """Одно и то же наблюдение с двух дочек — один id: так видно, что это ПОВТОР, а не два случая.
        Ровно этого не хватало 15.08, когда F-032 подтвердился независимо на второй дочке."""
        a, b = _child(tmp_path, "child-a"), _child(tmp_path, "child-b")
        ev = kf.evidence_from_args(["src/a.py=строка"], None, None)
        pa, _, _ = kf.record(a, STATEMENT, evidence=ev)
        pb, _, _ = kf.record(b, STATEMENT, evidence=ev)
        assert pa.name == pb.name


@pytest.mark.critical_path
@pytest.mark.unit
class TestOwnerReachesItThroughTheCommand:
    """Разводка: механизм бесполезен, если владелец до него не доходит своей командой.

    У кита это уже случалось дважды — классификация роутера работала внутри превью и наружу не
    выходила (F-015), исправление точки входа лежало в шаблоне и не доезжало до дочки (F-032).
    Поэтому проверяем не модуль, а команду.
    """

    def _cli(self):
        sys.path.insert(0, str(PKG_ROOT / "tools"))
        from ai_ops_kit.cli import ai_ops_cli
        return ai_ops_cli

    def test_command_records_with_evidence(self, tmp_path, capsys):
        child = _child(tmp_path)
        rc = self._cli().main(["feedback", STATEMENT, str(child),
                               "--evidence-file", ".ai/runtime/last-update-report.json=null",
                               "--severity", "p0"])
        out = capsys.readouterr().out
        assert rc == 0
        assert list((child / kf.CHILD_DIR).glob("*.yaml")), "команда прошла, а наблюдения нет"
        assert "Записал" in out

    def test_command_refuses_a_defect_without_evidence(self, tmp_path, capsys):
        child = _child(tmp_path)
        rc = self._cli().main(["feedback", STATEMENT, str(child), "--class", "defect"])
        out = capsys.readouterr().out
        assert rc == 1
        assert not list((child / kf.CHILD_DIR).glob("*.yaml"))
        assert "не на что опереться" in out or "Записать не могу" in out

    def test_command_without_text_shows_the_fate(self, tmp_path, capsys):
        """Канал двусторонний: та же команда без текста отвечает «что стало со сказанным»."""
        child, kit = _child(tmp_path), _kit(tmp_path)
        kf.record(child, STATEMENT, evidence=kf.evidence_from_args(["src/a.py=строка"], None, None))
        oid = kf.collect(kit, [child])["delivered"][0]["id"]
        kf.set_state(kit, child, oid, "became_work", reason="принято", work_item="w-1")
        rc = self._cli().main(["feedback", str(child)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "замечаниями" in out or "ждёт ответа" in out


@pytest.mark.unit
def test_missing_observation_is_not_called_corrupt(tmp_path):
    """Нашлось ПЕРВОЙ ЖЕ пробой канала на настоящих наблюдениях: отсутствующее наблюдение сообщало
    «не разобран (FileNotFoundError)» — то есть звало искать порчу файла там, где надо искать
    опечатку в id. Модуль, который сам требует отличать «не знаю» от «нет», не вправе путать это
    у себя."""
    child, kit = _child(tmp_path), _kit(tmp_path)
    doc, errors = kf.set_state(kit, child, "obs-которого-нет", "accepted", reason="—")
    assert doc is None
    assert any("нет ни в ките, ни в дочке" in e for e in errors)
    assert not any("не разобран" in e for e in errors)
