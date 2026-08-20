"""Тесты Drift между артефактами (PR-22) на фикстурах.

Граница: висячая ссылка документации на код — дрейф с НАЗВАННОЙ находкой; отсутствие стороны
пары — UNKNOWN, а НЕ «расхождений нет».
"""
from __future__ import annotations

from ai_ops_kit.intelligence import drift_artifacts as da


def _code(root, rel):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x = 1\n", encoding="utf-8")


def _doc(root, name, text):
    (root / name).write_text(text, encoding="utf-8")


# ── документация↔код ──

def test_docs_referencing_missing_code_is_drift(tmp_path):
    _code(tmp_path, "ai_ops_kit/real.py")
    _doc(tmp_path, "README.md", "Смотри `ai_ops_kit/real.py` и `ai_ops_kit/ghost.py`.\n")
    r = da.docs_vs_code(tmp_path)
    assert r.status == da.DRIFT
    assert len(r.findings) == 1
    assert "ghost.py" in r.findings[0]


def test_docs_referencing_only_existing_code_is_clean(tmp_path):
    _code(tmp_path, "ai_ops_kit/real.py")
    _doc(tmp_path, "README.md", "Модуль `ai_ops_kit/real.py` делает всё.\n")
    r = da.docs_vs_code(tmp_path)
    assert r.status == da.CLEAN


def test_no_docs_is_unknown_not_clean(tmp_path):
    _code(tmp_path, "ai_ops_kit/real.py")
    r = da.docs_vs_code(tmp_path)
    assert r.status == da.UNKNOWN


def test_only_backtick_refs_counted_not_prose(tmp_path):
    # «ghost.py» без кавычек и не код-путь — не должно считаться ссылкой
    _doc(tmp_path, "README.md", "Файла ghost.py тут нет как ссылки, только в прозе.\n")
    r = da.docs_vs_code(tmp_path)
    assert r.status == da.CLEAN


def test_docs_dir_is_scanned(tmp_path):
    (tmp_path / "docs").mkdir()
    _doc(tmp_path, "docs/guide.md", "Открой `src/missing.py`.\n")
    r = da.docs_vs_code(tmp_path)
    assert r.status == da.DRIFT
    assert "docs/guide.md" in r.findings[0]


def test_reference_by_basename_not_flagged(tmp_path):
    # документ ссылается на модуль по имени, а он живёт в подкаталоге — это не дрейф
    _code(tmp_path, "ai_ops_kit/validation/validate_x.py")
    _doc(tmp_path, "README.md", "Проверку делает `validate_x.py`.\n")
    assert da.docs_vs_code(tmp_path).status == da.CLEAN


def test_historical_docs_excluded(tmp_path):
    # changelog законно ссылается на старые/примерные пути — из сверки исключён
    (tmp_path / "docs" / "changelog").mkdir(parents=True)
    _doc(tmp_path, "docs/changelog/v1.md", "Раньше был `old/gone.py`.\n")
    assert da.docs_vs_code(tmp_path).status == da.UNKNOWN  # реальных документов не осталось


# ── пары, ждущие соседние ленты ──

def test_pending_pairs_are_unknown_with_named_lane(tmp_path):
    assert da.backlog_vs_delivery(tmp_path).status == da.UNKNOWN
    assert da.passport_vs_reality(tmp_path).status == da.UNKNOWN
    assert da.roadmap_vs_backlog(tmp_path).status == da.UNKNOWN
    # причина называет ленту-поставщика
    assert "лента 3" in da.backlog_vs_delivery(tmp_path).reason


def test_present_side_still_unknown_until_comparator(tmp_path):
    # Passport появился (лента 2), но компаратор с фактом не построен -> честный unknown, не clean
    (tmp_path / ".ai-ops").mkdir()
    (tmp_path / da.PASSPORT_REL).write_text("# Passport\n", encoding="utf-8")
    r = da.passport_vs_reality(tmp_path)
    assert r.status == da.UNKNOWN
    assert "ещё не реализована" in r.reason


# ── сводный отчёт ──

def test_report_flags_incomplete_when_pairs_unknown(tmp_path):
    _code(tmp_path, "ai_ops_kit/real.py")
    _doc(tmp_path, "README.md", "`ai_ops_kit/real.py`\n")
    rep = da.drift_report(tmp_path)
    assert rep["has_drift"] is False           # docs↔code чисто
    assert rep["complete"] is False            # три пары unknown
    assert set(rep["unverified"]) == {"roadmap↔backlog", "backlog↔delivery", "Passport↔факт"}


def test_report_has_drift_when_docs_dangle(tmp_path):
    _doc(tmp_path, "README.md", "`ai_ops_kit/ghost.py`\n")
    rep = da.drift_report(tmp_path)
    assert rep["has_drift"] is True


def test_result_without_reason_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        da.DriftResult("p", da.CLEAN, "")


def test_result_with_bad_status_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        da.DriftResult("p", "maybe", "причина")
