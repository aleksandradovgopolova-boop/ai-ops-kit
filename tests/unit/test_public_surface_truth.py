"""Публичная поверхность утверждает то, что выпущено, — и это ПРОВЕРЯЕТСЯ, а не подразумевается.

ЧТО ПРОПУСТИЛ РЕЛИЗ 3.36.0. Коммит релиза прямо утверждал «публичная поверхность согласована», и
валидатор это подтвердил. При этом ROADMAP в шапке говорил «текущий канал — v3.34.0 stable», а README
писал «33 гейта» при claim'е 34. Проверка спрашивала «встречается ли строка версии где-нибудь в
файле» — а ROADMAP содержит ИСТОРИЮ всех релизов, поэтому подстрока `3.36.0` находилась в разделе
про 3.36 и подтверждала шапку про 3.34. Совпадение подстроки не является заявлением.

Три обязательных теста на capability:
  * positive     — настоящие README/ROADMAP объявляют текущую версию, и она равна VERSION;
  * fail-closed  — расхождение объявления с VERSION и числа в прозе с claim'ом краснеют;
                   ПРОПАЖА объявления краснеет тоже: ослепшая проверка хуже отсутствующей;
  * side-effect  — правило живёт в реестре (его можно распространить на новый документ), а не
                   зашито в код.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG / "ai_ops_kit" / "validation"))

import validate_release_claims as vrc  # noqa: E402


@pytest.fixture(scope="module")
def claims():
    return yaml.safe_load((PKG / "registry" / "release-claims.yaml").read_text(encoding="utf-8"))


# ── positive ──────────────────────────────────────────────────────────────────────────────────

def test_docs_declare_the_released_version(claims):
    assert vrc.authoritative_version_errors(claims, PKG) == []
    assert vrc.derived_number_errors(claims, PKG) == []


def test_rules_exist_for_both_public_documents(claims):
    """README и ROADMAP — те два файла, на которые смотрит человек, решая «что это за версия»."""
    files = {r["file"] for r in claims.get("authoritative_version") or []}
    assert {"README.md", "ROADMAP.md"} <= files, f"объявление версии проверяется не везде: {files}"


# ── fail-closed ───────────────────────────────────────────────────────────────────────────────

def _fake_pkg(tmp_path, readme, roadmap, version="9.9.9"):
    (tmp_path / "VERSION").write_text(version + "\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    (tmp_path / "ROADMAP.md").write_text(roadmap, encoding="utf-8")
    return tmp_path


def test_stale_channel_is_caught_even_when_the_new_version_appears_below(claims, tmp_path):
    """ТОЧНЫЙ СЛУЧАЙ 3.36.0: шапка говорит про старый канал, а ниже в истории есть новая версия."""
    pkg = _fake_pkg(
        tmp_path,
        readme="# п\n\n**v9.9.9 stable** — ок\n",
        roadmap=("совместимый в пределах 2.x; 3.x (текущий канал — **v3.34.0 stable**: старое)\n\n"
                 "- **v9.9.9 — новое** ✅ уже выпущено\n"))
    errs = vrc.authoritative_version_errors(claims, pkg)
    assert errs, "устаревшая шапка прошла, потому что новая версия нашлась подстрокой ниже"
    assert "3.34.0" in errs[0] and "9.9.9" in errs[0]


def test_missing_declaration_is_an_error_not_a_pass(claims, tmp_path):
    """Образец перестал совпадать -> проверка ослепла. Это ошибка, а не «замечаний нет»."""
    pkg = _fake_pkg(tmp_path, readme="# п\n\nверсия где-то там\n",
                    roadmap="3.x (текущий канал — **v9.9.9 stable**: ок)\n")
    errs = vrc.authoritative_version_errors(claims, pkg)
    assert errs and "ослепла" in errs[0], errs


def test_hand_typed_number_diverging_from_the_claim_is_caught(claims, tmp_path):
    """README писал «33 гейта» при claim'е 34 — и релиз прошёл."""
    pkg = tmp_path
    (pkg / "README.md").write_text(
        "| **Quality Gates** | 33 гейта объявлено; на конкретной задаче — её набор |\n",
        encoding="utf-8")
    errs = vrc.derived_number_errors(dict(claims, gates_count=34), pkg)
    assert errs and "33" in errs[0] and "34" in errs[0], errs


def test_number_matching_the_claim_passes(claims, tmp_path):
    """Положительный контроль: правило не краснеет всегда."""
    (tmp_path / "README.md").write_text(
        "| **Quality Gates** | 34 гейта объявлено; на конкретной задаче — её набор |\n",
        encoding="utf-8")
    assert vrc.derived_number_errors(dict(claims, gates_count=34), tmp_path) == []


# ── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_rules_are_data_not_code(claims):
    """Правило описывается в реестре: добавить документ можно, не трогая валидатор.

    Иначе следующий публичный файл снова окажется непроверенным — и узнаем мы об этом из релиза.
    """
    for rule in claims.get("authoritative_version") or []:
        assert {"file", "pattern"} <= set(rule), rule
    for rule in claims.get("derived_numbers_in_docs") or []:
        assert {"file", "pattern", "claim"} <= set(rule), rule
        assert rule["claim"] in claims, f"claim '{rule['claim']}' в реестре не объявлен"
