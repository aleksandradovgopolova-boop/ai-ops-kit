"""Гранулярные тесты pipeline_evidence (мигрировано из test_pipeline_evidence_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engine.pipeline_evidence import (
    _author_with_retry,
    _cited_lines_confirmed,
    _gate_ev_from_verdict,
    _install_dependencies,
    _reevaluate_artifact_evidence,
    _review_cites_delivered_file,
    _review_security,
    _run_authoring,
    _run_reviews,
)


@pytest.mark.unit
class TestImports:
    def test_install_dependencies_callable(self):
        assert callable(_install_dependencies)

    def test_author_with_retry_callable(self):
        assert callable(_author_with_retry)

    def test_run_authoring_callable(self):
        assert callable(_run_authoring)

    def test_run_reviews_callable(self):
        assert callable(_run_reviews)

    def test_review_security_callable(self):
        assert callable(_review_security)

    def test_reevaluate_artifact_evidence_callable(self):
        assert callable(_reevaluate_artifact_evidence)


@pytest.mark.unit
class TestReviewGroundingReadsTheFile:
    """Заземление ревью поднято до уровня приёмки (Fix C, P0 04.09.2026): цитата ревьюера (`lines`)
    подтверждается ЧТЕНИЕМ доставленного файла, а не совпадением его ИМЕНИ."""

    def _write(self, tmp_path, rel, text):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_cited_lines_real_confirmed(self, tmp_path):
        self._write(tmp_path, "src/a.py", "l1\nl2\nl3\nl4\nl5\n")
        assert _cited_lines_confirmed(str(tmp_path), "src/a.py", "2-4") is True

    def test_cited_lines_fabricated_rejected(self, tmp_path):
        self._write(tmp_path, "src/a.py", "l1\n")           # файл в 1 строку
        assert _cited_lines_confirmed(str(tmp_path), "src/a.py", "500-520") is False

    def test_missing_lines_rejected(self, tmp_path):
        self._write(tmp_path, "src/a.py", "l1\nl2\n")
        assert _cited_lines_confirmed(str(tmp_path), "src/a.py", None) is False

    def test_unreadable_file_rejected(self, tmp_path):
        # файла на диске нет -> _read_source вернёт None -> цитата не подтверждена (fail-closed)
        assert _cited_lines_confirmed(str(tmp_path), "src/nope.py", "1") is False

    def test_cites_delivered_grounds_only_when_lines_real(self, tmp_path):
        self._write(tmp_path, "src/a.py", "l1\nl2\nl3\n")
        delivered = {"src/a.py"}
        real = {"checks": [{"id": "c", "status": "pass",
                            "evidence": [{"file": "src/a.py", "lines": "1-3"}]}]}
        fake = {"checks": [{"id": "c", "status": "pass",
                            "evidence": [{"file": "src/a.py", "lines": "800-900"}]}]}
        assert _review_cites_delivered_file(real, delivered, str(tmp_path)) is True
        # имя доставленного файла совпадает, но строки выдуманы -> НЕ заземлено
        assert _review_cites_delivered_file(fake, delivered, str(tmp_path)) is False

    def test_cites_off_change_file_not_grounded(self, tmp_path):
        self._write(tmp_path, "src/other.py", "l1\nl2\n")
        res = {"checks": [{"id": "c", "status": "pass",
                           "evidence": [{"file": "src/other.py", "lines": "1"}]}]}
        # файл реальный и строки реальны, но он НЕ в доставленной правке -> не заземляет
        assert _review_cites_delivered_file(res, {"src/delivered.py"}, str(tmp_path)) is False


@pytest.mark.unit
class TestProseVerdictClosesTheGate:
    """issue #614: прозаический вердикт (`Recommendation: …`, `prose_verdict=True`, checks пустые)
    ПОТРЕБЛЯЕТСЯ гейтом — раньше `vrr.check` отбрасывал его как «checks должен быть непустым» и
    валидный вердикт превращался в no-verdict. Заземление pass при этом НЕ ослаблено (Fix C держит)."""

    _GATE = {"id": "code_review", "blocking": True, "required_evidence": []}
    _VALID = {"code_review"}

    def _rv(self, status, *, reads=None, blockers=None):
        res = {"schema_version": 1, "kind": "reviewer-result", "gate": "code_review",
               "status": status, "checks": [], "prose_verdict": True}
        if blockers:
            res["blockers"] = blockers
        return {"result": res, "stopped": "verdict", "reads": reads or [], "denied": [],
                "source": None}

    def _consume(self, rv, tmp_path, delivered=None):
        return _gate_ev_from_verdict(
            "code_review", self._GATE, rv, revision="HEAD", delivered=delivered or set(),
            work_root=str(tmp_path), valid_ids=self._VALID, signals={},
            calibrated_enforcement=False, ui_evidence=None)

    def test_prose_needs_work_closes_as_fail_with_blockers(self, tmp_path):
        """Прозаический needs_work (warn) на блокирующем гейте -> gate fail с блокерами, не no-verdict."""
        rv = self._rv("warn", blockers=["не закрыта ветка обработки ошибки"])
        ev, entry = self._consume(rv, tmp_path)
        assert ev["status"] == "fail" and ev.get("blockers")
        assert entry["valid"] is True, "прозаический вердикт валиден (пустые checks — не порок формы)"

    def test_prose_pass_without_grounding_is_a_rubber_stamp_block(self, tmp_path):
        """★НЕ ложное зелёное★: прозаический pass при 0 чтений и без цитаты доставленного файла —
        рубер-штамп, блокирующий гейт не закрывает (Fix C не ослаблен упрощением элицитации)."""
        ev, entry = self._consume(self._rv("pass", reads=[]), tmp_path)
        assert ev["status"] == "fail", "ungrounded pass не закрывает блокирующий гейт"
        assert entry["closed_as"] == "blocked"

    def test_prose_pass_grounded_by_reads_closes_green(self, tmp_path):
        """Прозаический pass, ОПЁРТЫЙ на реальные чтения (reads непусты) -> pass закрывает гейт."""
        ev, entry = self._consume(self._rv("pass", reads=["src/a.py"]), tmp_path)
        assert ev["status"] == "pass"
        assert entry["valid"] is True
