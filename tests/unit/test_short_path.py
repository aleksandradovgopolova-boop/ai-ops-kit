"""Короткий путь для уже описанной работы (решение владельца 2026-08-17).

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ — ШВЫ, а не наличие функций. Пять свойств, каждое из которых уже ломалось в
похожих механизмах кита:

  1. заявления БЕЗ проверенного минимума не хватает (иначе кит выключает свои проверки на слово);
  2. минимум считается РАЗБОРОМ критериев, а не статусом `complete` (цена этой разницы — единственный
     ложный green квалификации, B2-14);
  3. непрочитанная спека — это «не знаю», а не «не описано» (разные сообщения человеку);
  4. после короткого пути спека РЕАЛЬНО проходит гейт полноты — иначе «короткий путь» упирался бы в
     блокировку на первом же прогоне, то есть был бы тупиком, а не путём;
  5. пропущенное — записано: у каждого отклонённого раздела есть объяснение, и есть след с решением.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.gates import spec_levels
from ai_ops_kit.planning import short_path

WID = "wi-export-csv"
SIGNALS = {"task_type": "QUICK", "size": "S", "risk": "low"}


def _spec(root, sections, level=0):
    sp = root / "features" / WID / "spec.yaml"
    sp.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "kind": "spec", "workitem_id": WID, "level": level,
           "level_name": spec_levels.LEVEL_NAME[level], "sections": sections}
    sp.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return sp


def _full_sections():
    return {
        "goal": {"status": "complete", "content": "Выгрузка заказов в CSV одной кнопкой"},
        "acceptance_criteria": {"status": "complete",
                                "content": "- AC-1: кнопка отдаёт файл\n- AC-2: в файле есть заголовки"},
        "affected_files": {"status": "complete", "content": "- src/export.py"},
    }


@pytest.mark.unit
class TestDeclaration:
    def test_signal_declares(self):
        d = short_path.declaration("сделай выгрузку", {"already_described": True})
        assert d["declared"] is True and d["source"] == "signal"

    def test_phrase_declares(self):
        d = short_path.declaration("Задача уже описана в тикете, просто сделай", {})
        assert d["declared"] is True and d["source"] == "phrase"

    def test_ordinary_task_is_not_a_declaration(self):
        """Уверенная формулировка — не заявление. Иначе короткий путь включался бы почти всегда."""
        d = short_path.declaration("Добавь выгрузку заказов в CSV с заголовками", {})
        assert d["declared"] is False


@pytest.mark.critical_path
@pytest.mark.unit
class TestMinimumIsVerifiedNotDeclared:
    def test_declaration_alone_is_not_enough(self, tmp_path):
        """Свойство 1: заявлено, но описания нет -> обычный путь и названо, чего не хватает."""
        d = short_path.assess("уже описана", dict(SIGNALS), tmp_path, WID)
        assert d["short_path"] is False
        assert set(d["missing"]) == {"goal", "acceptance_criteria", "affected_paths"}
        assert "как поймём, что готово" in d["reason"]

    def test_complete_status_without_criteria_does_not_count(self, tmp_path):
        """Свойство 2: раздел помечен complete, но пунктов из него не выходит -> НЕ засчитан.

        `complete` в спеке означает «раздел заполнен», а не «критерии есть». Если этот тест
        покраснеет от «упрощения» до проверки статуса — вернётся ровно тот класс ложного green.
        Заявленный `complete` без читаемого содержимого попадает в «не знаю», а не в «не описано»:
        так говорит разбор раздела, и он прав — сказать «критериев нет» значило бы противоречить
        файлу, в котором человек своей рукой поставил `complete`.
        """
        sections = _full_sections()
        sections["acceptance_criteria"] = {"status": "complete", "content": "   "}
        _spec(tmp_path, sections)
        d = short_path.assess("уже описана", dict(SIGNALS), tmp_path, WID)
        assert d["short_path"] is False
        assert d["minimum"]["acceptance_criteria"]["present"] is not True
        assert "acceptance_criteria" in d["unknown"] + d["missing"]

    def test_prose_criteria_count(self, tmp_path):
        """Обратная сторона того же шва: критерии прозой, без маркеров списка, ЗАСЧИТЫВАЮТСЯ.
        Требовать разметку означало бы отказывать в коротком пути за формат, а не за суть."""
        sections = _full_sections()
        sections["acceptance_criteria"] = {"status": "complete",
                                           "content": "В файле есть заголовки.\nКнопка отдаёт файл."}
        _spec(tmp_path, sections)
        d = short_path.assess("уже описана", dict(SIGNALS), tmp_path, WID)
        assert d["short_path"] is True

    def test_unreadable_spec_is_unknown_not_missing(self, tmp_path):
        """Свойство 3: битую спеку нельзя объявить «не описано» — это «не знаю»."""
        sp = tmp_path / "features" / WID / "spec.yaml"
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text("sections: [это: не, мэппинг\n", encoding="utf-8")
        d = short_path.assess("уже описана", dict(SIGNALS), tmp_path, WID)
        assert d["short_path"] is False
        assert d["unknown"], "непрочитанная спека обязана попасть в unknown"
        assert not d["missing"], "unknown и missing — разные исходы, путать нельзя"
        assert "проверить не могу" in d["reason"]

    def test_full_minimum_and_declaration_give_short_path(self, tmp_path):
        _spec(tmp_path, _full_sections())
        d = short_path.assess("уже описана", dict(SIGNALS), tmp_path, WID)
        assert d["short_path"] is True
        assert d["skipped_steps"] == list(short_path.SKIPPED_STEPS)

    def test_minimum_without_declaration_is_not_short_path(self, tmp_path):
        """Решение владельца: признак = заявление И минимум. Полного описания одного мало."""
        _spec(tmp_path, _full_sections())
        d = short_path.assess("добавь выгрузку в CSV", dict(SIGNALS), tmp_path, WID)
        assert d["short_path"] is False and d["declared"] is False

    def test_signals_and_plan_are_legal_sources(self, tmp_path):
        """Описание живёт не только в спеке кита: сигналы и work_scope плана — тоже источники."""
        (tmp_path / "planning").mkdir()
        (tmp_path / "planning" / "plan.yaml").write_text(yaml.safe_dump({
            "schema_version": 1, "kind": "delivery-plan",
            "goals": [{"id": "g1", "status": "active"}],
            "work": [{"id": WID, "title": "Выгрузка заказов в CSV", "type": "engineering",
                      "goal": "g1", "status": "todo", "owner_role": "engineer",
                      "write_scope": ["src/export.py"]}]}, allow_unicode=True), encoding="utf-8")
        signals = dict(SIGNALS, already_described=True,
                       acceptance_criteria="- AC-1: кнопка отдаёт файл")
        d = short_path.assess("сделай", signals, tmp_path, WID)
        assert d["short_path"] is True
        assert d["minimum"]["goal"]["source"] == "plan"
        assert d["minimum"]["affected_paths"]["source"] == "plan"
        assert d["minimum"]["acceptance_criteria"]["source"] == "signals"


@pytest.mark.critical_path
@pytest.mark.unit
class TestTraceIsNotADeadEnd:
    def test_spec_passes_completeness_gate_after_short_path(self, tmp_path):
        """Свойство 4 — ГЛАВНОЕ. Короткий путь на ENGINEERING-задаче обязан оставить спеку, которую
        гейт полноты пропускает: иначе прогон встанет на первом же шаге и «короткий путь» окажется
        дороже полного.
        """
        signals = dict(SIGNALS, task_type="ENGINEERING", already_described=True,
                       goal="Выгрузка заказов в CSV",
                       acceptance_criteria="- AC-1: кнопка отдаёт файл",
                       write_scope=["src/export.py"])
        d = short_path.assess("сделай", signals, tmp_path, WID)
        assert d["short_path"] is True
        tr = short_path.trace(tmp_path, WID, signals, d)
        assert tr["error"] is None
        cov = spec_levels.assess_from_artifacts(signals, tmp_path, WID)
        assert cov["level"] >= 1, "уровень короткий путь НЕ понижает"
        assert cov["blocking_missing"] == [], f"гейт полноты не пройден: {cov['blocking_missing']}"
        assert cov["form_errors"] == [], f"форма спеки испорчена: {cov['form_errors']}"
        assert cov["ready_to_implement"] is True

    def test_declined_sections_carry_the_reason(self, tmp_path):
        """Свойство 5: пропущенное объяснено. `declined` без note — ошибка формы по контракту спеки,
        и именно она делает пропуск видимым, а не тихим."""
        signals = dict(SIGNALS, task_type="ENGINEERING", already_described=True,
                       goal="Выгрузка", acceptance_criteria="- AC-1: файл отдаётся",
                       write_scope=["src/export.py"])
        d = short_path.assess("сделай", signals, tmp_path, WID)
        tr = short_path.trace(tmp_path, WID, signals, d)
        doc = yaml.safe_load((tmp_path / "features" / WID / "spec.yaml").read_text(encoding="utf-8"))
        declined = {sid: e for sid, e in doc["sections"].items() if e.get("status") == "declined"}
        assert declined, "на L1 часть разделов обязана быть отклонена явно"
        assert all(e.get("note") for e in declined.values())
        assert all("2026-08-17" in e["note"] for e in declined.values())
        assert tr["declined"]

    def test_no_section_is_declared_not_applicable(self, tmp_path):
        """Неприменимость — утверждение о задаче, отклонение — решение владельца. Подменять нельзя."""
        signals = dict(SIGNALS, task_type="PRODUCT", already_described=True,
                       goal="Выгрузка", acceptance_criteria="- AC-1: файл отдаётся",
                       write_scope=["src/export.py"])
        d = short_path.assess("сделай", signals, tmp_path, WID)
        short_path.trace(tmp_path, WID, signals, d)
        doc = yaml.safe_load((tmp_path / "features" / WID / "spec.yaml").read_text(encoding="utf-8"))
        assert not [sid for sid, e in doc["sections"].items()
                    if e.get("status") == "not_applicable"]

    def test_record_keeps_why(self, tmp_path):
        signals = dict(SIGNALS, already_described=True, goal="Выгрузка",
                       acceptance_criteria="- AC-1: файл отдаётся", write_scope=["src/export.py"])
        d = short_path.assess("сделай", signals, tmp_path, WID)
        tr = short_path.trace(tmp_path, WID, signals, d)
        rec = yaml.safe_load(Path(tr["record"]).read_text(encoding="utf-8"))
        assert rec["kind"] == "ShortPathRecord"
        assert rec["declared_by"] == "signal"
        assert set(rec["minimum_confirmed"]) == set(short_path.MINIMUM)
        assert rec["skipped_steps"] == list(short_path.SKIPPED_STEPS)
        assert "2026-08-17" in rec["decision_ref"]

    def test_existing_description_is_not_rewritten(self, tmp_path):
        """Содержимое берётся из источника, а не пересказывается: иначе спека разойдётся с тем
        описанием, по которому работа реально делается."""
        sections = _full_sections()
        _spec(tmp_path, sections)
        signals = dict(SIGNALS, already_described=True)
        d = short_path.assess("сделай", signals, tmp_path, WID)
        short_path.trace(tmp_path, WID, signals, d)
        doc = yaml.safe_load((tmp_path / "features" / WID / "spec.yaml").read_text(encoding="utf-8"))
        assert doc["sections"]["goal"]["content"] == sections["goal"]["content"]
        assert doc["sections"]["acceptance_criteria"]["content"] == \
            sections["acceptance_criteria"]["content"]
