"""Unit tests for tools/spec_levels.py — spec level classification and coverage assessment."""
from __future__ import annotations

import pytest

from ai_ops_kit.gates import spec_levels


@pytest.mark.unit
class TestClassify:
    """Tests for classify(): deterministic spec level selection from signals."""

    def test_quick_task_is_l0(self):
        result = spec_levels.classify({"task_type": "QUICK"})
        assert result["level"] == 0
        assert result["level_name"] == "L0 QUICK"

    def test_engineering_task_is_l1(self):
        result = spec_levels.classify({"task_type": "ENGINEERING"})
        assert result["level"] == 1
        assert result["level_name"] == "L1 ENGINEERING"

    def test_product_task_is_l2(self):
        result = spec_levels.classify({"task_type": "PRODUCT"})
        assert result["level"] == 2
        assert result["level_name"] == "L2 PRODUCT"

    def test_critical_task_is_l3(self):
        result = spec_levels.classify({"task_type": "CRITICAL"})
        assert result["level"] == 3
        assert result["level_name"] == "L3 CRITICAL"

    def test_critical_risk_escalates_to_l3(self):
        result = spec_levels.classify({"task_type": "QUICK", "risk": "critical"})
        assert result["level"] == 3
        assert any("эскалация" in r for r in result["reason"])

    def test_secret_boundary_escalates_to_l3(self):
        result = spec_levels.classify({"task_type": "ENGINEERING", "secret_boundary": True})
        assert result["level"] == 3

    def test_user_facing_change_escalates_to_l2(self):
        result = spec_levels.classify({
            "task_type": "QUICK",
            "measurable_behavior": True,
            "user_facing_change": True,
        })
        assert result["level"] == 2

    def test_requested_lower_level_not_silent(self):
        """Requesting a lower level than signals require must NOT silently downgrade."""
        result = spec_levels.classify({"task_type": "ENGINEERING", "requested_level": 0})
        assert result["level"] == 1  # stays at L1
        assert result["escalated_from"] == 0

    def test_requested_higher_level_accepted(self):
        """Requesting a higher level is allowed (escalation up)."""
        result = spec_levels.classify({"task_type": "QUICK", "requested_level": 2})
        assert result["level"] == 2

    def test_default_task_type_is_quick(self):
        result = spec_levels.classify({})
        assert result["level"] == 0


@pytest.mark.unit
class TestRequiredSections:
    """Tests for required_sections(): cumulative section lists per level."""

    def test_l0_sections(self):
        sections = spec_levels.required_sections(0)
        assert "goal" in sections
        assert "scope" in sections
        assert "acceptance_criteria" in sections

    def test_l1_includes_l0(self):
        l0 = set(spec_levels.required_sections(0))
        l1 = set(spec_levels.required_sections(1))
        assert l0 <= l1
        assert "verification_strategy" in l1

    def test_l3_includes_all_levels(self):
        all_sections = set(spec_levels.required_sections(3))
        assert "goal" in all_sections           # L0
        assert "requirements" in all_sections   # L1
        assert "problem" in all_sections        # L2
        assert "threat_model" in all_sections   # L3


@pytest.mark.unit
class TestAssess:
    """Tests for assess(): spec coverage evaluation."""

    def test_empty_quick_has_blocking_missing(self):
        result = spec_levels.assess({"task_type": "QUICK"})
        assert result["blocking_missing"] != []
        assert result["ready_to_implement"] is False

    def test_full_l0_is_ready(self):
        provided = {s: {"status": "complete"} for s in spec_levels.LEVEL_SECTIONS[0]}
        result = spec_levels.assess({"task_type": "QUICK"}, provided)
        assert result["ready_to_implement"] is True
        assert result["blocking_missing"] == []

    def test_not_applicable_does_not_block(self):
        provided = {s: {"status": "not_applicable", "note": "N/A"} for s in spec_levels.LEVEL_SECTIONS[0]}
        result = spec_levels.assess({"task_type": "QUICK"}, provided)
        assert result["ready_to_implement"] is True

    def test_declined_without_note_is_form_error(self):
        provided = {s: {"status": "complete"} for s in spec_levels.LEVEL_SECTIONS[0]}
        provided["scope"] = {"status": "declined"}  # no note
        result = spec_levels.assess({"task_type": "QUICK"}, provided)
        assert result["form_errors"] != []
        assert result["ready_to_implement"] is False

    def test_needs_human_tracked(self):
        provided = {s: {"status": "complete"} for s in spec_levels.LEVEL_SECTIONS[0]}
        provided["constraints"] = {"status": "needs_human", "note": "needs owner"}
        result = spec_levels.assess({"task_type": "QUICK"}, provided)
        assert "constraints" in result["needs_human"]


@pytest.mark.unit
class TestUnrecognisedSectionStatus:
    """F-013 (находка живой квалификации на niti): раздел заполнен, но статус вне словаря.

    Раньше такой раздел молча уезжал в missing, и блокер печатал «не заполнено: goal, scope…» —
    ложный след ценой лишней итерации: содержимое было, ошибкой было одно слово.
    """

    def _filled_with(self, status):
        provided = {s: {"status": "complete", "content": "x"} for s in spec_levels.LEVEL_SECTIONS[0]}
        provided["goal"] = {"status": status, "content": "цель описана подробно"}
        return spec_levels.assess({"task_type": "QUICK"}, provided)

    def test_error_names_allowed_statuses(self):
        cov = self._filled_with("filled")
        assert any("'filled'" in e and "complete" in e and "not_applicable" in e
                   for e in cov["form_errors"]), \
            "из сообщения не понять, что писать вместо 'filled', — придётся читать исходники"

    def test_filled_section_is_separated_from_empty_one(self):
        cov = self._filled_with("filled")
        bad = {b["id"]: b for b in cov["invalid_status"]}
        assert "goal" in bad, "раздел с нераспознанным статусом не отличён от пустого"
        assert bad["goal"]["given"] == "filled"
        assert bad["goal"]["has_content"] is True

    def test_still_fail_closed(self):
        """Отличать причину — не значит пропускать: спека с нераспознанным статусом не готова."""
        cov = self._filled_with("filled")
        assert cov["ready_to_implement"] is False
        assert "goal" in cov["blocking_missing"]

    def test_valid_statuses_produce_no_noise(self):
        cov = self._filled_with("not_applicable")
        assert cov["invalid_status"] == []
        assert cov["form_errors"] == []

    def test_created_spec_carries_the_vocabulary(self, tmp_path):
        """Словарь статусов должен быть в самом файле — его заполняет агент без исходников кита."""
        path, created, _ = spec_levels.create_spec(tmp_path, "wi-1", {"task_type": "QUICK"})
        assert created
        text = path.read_text(encoding="utf-8")
        for status in spec_levels.SECTION_STATUSES - {"missing"}:
            assert status in text, f"в шаблоне спеки нет статуса {status}"


@pytest.mark.unit
class TestRaisedLevelAddsSections:
    """F-029 (поле 2026-08-15, дочка ai-ops-cockpit; повтор находки другой дочки).

    `specify` с сигналами более высокого уровня говорил «заполнить нужно 9 разделов», а в
    features/<wid>/spec.yaml оставались 6 разделов L0 — заполнять было нечего, и `run` блокировался
    на разделах, которых шаблон не создавал. Инвариант: КАЖДЫЙ раздел, который кит называет
    незаполненным, обязан существовать в файле."""

    QUICK = {"task_type": "QUICK"}
    PRODUCT = {"task_type": "PRODUCT"}

    def _doc(self, path):
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_missing_sections_are_added_when_level_rises(self, tmp_path):
        path, created, _ = spec_levels.create_spec(tmp_path, "wi-1", self.QUICK)
        assert created and self._doc(path)["level"] == 0

        path2, created2, rep = spec_levels.create_spec(tmp_path, "wi-1", self.PRODUCT)
        assert path2 == path and created2 is False
        assert rep["error"] is None
        doc = self._doc(path)
        assert doc["level"] == 2 and doc["level_name"] == "L2 PRODUCT"
        for sid in spec_levels.required_sections(2):
            assert sid in doc["sections"], f"раздел {sid} уровня L2 не дописан"
        assert set(rep["added"]) == set(spec_levels.required_sections(2)) - set(
            spec_levels.required_sections(0))

    def test_every_blocking_section_exists_in_the_file(self, tmp_path):
        """Ровно то, что видел владелец: список «не заполнено» против содержимого файла."""
        spec_levels.create_spec(tmp_path, "wi-1", self.QUICK)
        path, _, _ = spec_levels.create_spec(tmp_path, "wi-1", self.PRODUCT)
        cov = spec_levels.assess_from_artifacts(self.PRODUCT, tmp_path, "wi-1")
        doc = self._doc(path)
        assert cov["blocking_missing"], "спека пуста — список незаполненного не должен быть пустым"
        for sid in cov["blocking_missing"]:
            assert sid in doc["sections"], (
                f"кит зовёт заполнить {sid}, а раздела в файле нет — заполнять нечего")

    def test_described_sections_are_never_touched(self, tmp_path):
        import yaml
        path, _, _ = spec_levels.create_spec(tmp_path, "wi-1", self.QUICK)
        doc = self._doc(path)
        doc["sections"]["goal"] = {"status": "complete", "content": "живой текст владельца",
                                   "note": None}
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

        spec_levels.create_spec(tmp_path, "wi-1", self.PRODUCT)
        goal = self._doc(path)["sections"]["goal"]
        assert goal["status"] == "complete" and goal["content"] == "живой текст владельца"

    def test_level_is_never_lowered_and_sections_stay(self, tmp_path):
        spec_levels.create_spec(tmp_path, "wi-1", self.PRODUCT)
        path, created, rep = spec_levels.create_spec(tmp_path, "wi-1", self.QUICK)
        doc = self._doc(path)
        assert created is False and rep["added"] == []
        assert doc["level"] == 2, "уровень нельзя понизить молча"
        assert "success_metrics" in doc["sections"], "разделы прошлого уровня не удаляются"

    def test_broken_spec_is_not_rewritten_and_says_so(self, tmp_path):
        path = tmp_path / "features" / "wi-1" / "spec.yaml"
        path.parent.mkdir(parents=True)
        path.write_text("это не спека, а обрывок текста\n", encoding="utf-8")

        _, created, rep = spec_levels.create_spec(tmp_path, "wi-1", self.PRODUCT)
        assert created is False and rep["added"] == []
        assert rep["error"], "молчаливый отказ дописать неотличим от успеха"
        assert path.read_text(encoding="utf-8") == "это не спека, а обрывок текста\n"


@pytest.mark.unit
class TestArtifactCoverage:
    """Перенос из test_spec_levels_selftest.py: покрытие из РЕАЛЬНОГО артефакта на диске.

    Real Spec-First (v2.110): create_spec кладёт файл нужной глубины, а assess_from_artifacts /
    validate_spec читают его с диска — «готов к реализации» доказывается содержимым файла, а не
    словами. Артефакт прогона (requirements.yaml) засчитывает свой раздел; отсутствие spec.yaml
    честно помечается, а не выдаётся за пустую-но-существующую спеку.
    """

    ENG = {"task_type": "ENGINEERING", "affected_areas": ["core"]}

    def _doc(self, path):
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_create_spec_engineering_makes_l1_with_missing_sections(self, tmp_path):
        sp, created, _rep = spec_levels.create_spec(tmp_path, "sf", self.ENG)
        assert created and sp.is_file()
        doc = self._doc(sp)
        assert doc["level"] == 1
        assert "requirements" in doc["sections"]
        assert doc["sections"]["goal"]["status"] == "missing"

    def test_empty_spec_is_not_ready_but_artifact_exists(self, tmp_path):
        spec_levels.create_spec(tmp_path, "sf", self.ENG)
        cov = spec_levels.assess_from_artifacts(self.ENG, tmp_path, "sf")
        assert cov["ready_to_implement"] is False
        assert cov["spec_artifact"] is True
        assert cov["blocking_missing"]

    def test_filled_spec_on_disk_is_ready(self, tmp_path):
        import yaml
        sp, _c, _r = spec_levels.create_spec(tmp_path, "sf", self.ENG)
        doc = self._doc(sp)
        for sid in doc["sections"]:
            doc["sections"][sid] = {"status": "complete", "content": "x"}
        sp.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

        cov = spec_levels.assess_from_artifacts(self.ENG, tmp_path, "sf")
        assert cov["ready_to_implement"] is True
        assert not cov["blocking_missing"]

    def test_run_artifact_credits_its_section(self, tmp_path):
        spec_levels.create_spec(tmp_path, "sf", self.ENG)
        work_root = tmp_path / "work"
        art_dir = work_root / ".ai" / "runplan" / "art"
        art_dir.mkdir(parents=True)
        (art_dir / "requirements.yaml").write_text("k: v\n", encoding="utf-8")

        prov = spec_levels.provided_from_artifacts(tmp_path, "art", work_root=work_root)
        assert prov.get("requirements", {}).get("status") == "complete"
        assert "requirements.yaml" in (prov["requirements"].get("note") or "")

    def test_validate_spec_without_artifact_is_honest(self, tmp_path):
        cov = spec_levels.validate_spec(tmp_path, "never", self.ENG)
        assert cov["spec_artifact"] is False
        assert "note" in cov
