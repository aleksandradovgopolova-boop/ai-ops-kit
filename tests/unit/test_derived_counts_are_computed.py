"""Счёт валидаторов ВЫВОДИТСЯ из факта, а не держится числом, которое каждый PR синхронит.

Работа `derived-counts-are-computed-not-declared`, цель `checks-that-run`.

НАХОДКА (docs/parallel-execution-retro.md, класс derived-числа). `validators_count` и
`validators_externally_tested` в `release-claims.yaml` были общей точкой: каждая лента, добавив
валидатор, обязана была подвинуть число, а вливавшийся вторым — пересчитать. Число, набранное
руками, живёт своей жизнью ровно до первого расхождения.

РЕШЕНИЕ: число больше НЕ хранится. Оно выводится при проверке из факта
(`derived_verification_counts`: файлы `validation/validate_*.py` и те, чьё имя упомянуто в `tests/`)
и впрыскивается туда, где раньше стоял литерал. Двигать нечего — расхождение невозможно
by construction, а публичный текст по-прежнему сверяется с фактом.

Три обязательных теста на capability (AGENTS.md):
  * side-effect — в реестре БОЛЬШЕ НЕТ хранимого числа: PR физически нечего синхронить;
  * positive    — добавление валидатора НЕ требует правки реестра: число само следует за фактом;
  * fail-closed — публичный текст, разошедшийся с фактом, по-прежнему краснеет; и если лента всё же
                  впишет литерал и он разойдётся с фактом — это тоже ошибка (защита от повторного
                  «прибивания гвоздём»).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG / "ai_ops_kit" / "validation"))

import validate_release_claims as vrc  # noqa: E402

pytestmark = pytest.mark.unit

DERIVED_FIELDS = ("validators_count", "validators_externally_tested")


@pytest.fixture(scope="module")
def claims():
    return yaml.safe_load((PKG / "registry" / "release-claims.yaml").read_text(encoding="utf-8"))


# ── side-effect: в реестре нечего синхронить ────────────────────────────────────────────────────

def test_registry_no_longer_stores_the_number(claims):
    """Число не хранится — значит нет общей точки, которую двигали бы руками две ленты."""
    present = [f for f in DERIVED_FIELDS if f in claims]
    assert not present, (
        f"{present} снова захардкожены в release-claims — вернулась общая точка, "
        "которую каждый PR обязан синхронить; число должно ВЫВОДИТЬСЯ из факта")


def test_the_fact_is_the_single_home(claims):
    """Единственное место, где живёт число, — сам факт; проверка читает его оттуда."""
    vals = vrc.derived_field_values(PKG)
    assert set(vals) == set(DERIVED_FIELDS)
    vtotal, vtested = vrc.derived_verification_counts(PKG)
    assert vals == {"validators_count": vtotal, "validators_externally_tested": vtested}
    assert vtotal > 0, "факт пуст — считать нечего, проверка ослепла бы"


# ── positive: рост факта не требует правки реестра ──────────────────────────────────────────────

def test_adding_a_validator_needs_no_registry_edit(claims, monkeypatch):
    """Сердцевина работы: валидатор добавлен (факт вырос), а release-claims НЕ тронут — дрейфа нет.

    Раньше это давало красное «validators_count != валидаторов в validation/», пока PR не подвинет
    число в реестре. Теперь число следует за фактом само: реестр — названная точка слияния лент
    (docs/parallel-execution-retro.md) — его больше не держит.

    ГРАНИЦА: публичный текст (`ProductStatus.md` и т.п.) лежит вне write_scope этой работы и остаётся
    сверяемым с фактом через `derived_numbers_in_docs` — это отдельная поверхность честности, а не
    та общая точка, что сталкивала ленты. Поэтому проверяем именно ОТСУТСТВИЕ реестрового дрейфа."""
    vtotal, vtested = vrc.derived_verification_counts(PKG)
    monkeypatch.setattr(vrc, "derived_verification_counts",
                        lambda pkg=vrc.PKG: (vtotal + 1, vtested + 1))
    errors = vrc.check(dict(claims), PKG)
    registry_drift = [e for e in errors if "!= валидаторов в validation/" in e
                      or "фактически покрытых внешним тестом" in e]
    assert registry_drift == [], (
        f"рост факта потребовал правки release-claims — общая точка вернулась: {registry_drift}")


def test_real_registry_is_green(claims):
    """Реальный реестр без литералов проходит проверку целиком."""
    assert vrc.check(dict(claims), PKG) == []


# ── fail-closed: враньё в тексте и заново вписанный литерал по-прежнему ловятся ──────────────────

_DOC = {"file": "docs/STATUS.md", "pattern": r"(\d+)\s*<!-- claim:validators-total -->",
        "claim": "validators_count"}


def _pkg_with_status(tmp_path, number):
    """Синтетический pkg без каталога validation -> факт = 0 валидаторов; текст объявляет `number`."""
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "STATUS.md").write_text(
        f"{number} <!-- claim:validators-total -->\n", encoding="utf-8")
    return tmp_path


def test_public_text_out_of_step_with_the_fact_still_fails(tmp_path):
    """Публичный текст сверяется с ФАКТОМ, а не с пустотой: рассинхрон краснеет даже без литерала."""
    pkg = _pkg_with_status(tmp_path, 5)  # факт = 0, текст говорит 5
    errors = vrc.derived_number_errors({"derived_numbers_in_docs": [_DOC]}, pkg)
    assert any("validators_count" in e for e in errors), (
        f"расхождение публичного числа с фактом не поймано: {errors}")


def test_public_text_matching_the_fact_passes(tmp_path):
    """Обратная сторона: текст, равный факту, не краснеет — впрыснутый факт подставлен верно."""
    pkg = _pkg_with_status(tmp_path, 0)  # факт = 0, текст говорит 0
    assert vrc.derived_number_errors({"derived_numbers_in_docs": [_DOC]}, pkg) == []


def test_a_re_nailed_literal_that_disagrees_still_errors(claims):
    """Если лента снова впишет число и оно разойдётся с фактом — ошибка (защита от регресса)."""
    vtotal, _ = vrc.derived_verification_counts(PKG)
    errors = vrc.check(dict(claims, validators_count=vtotal + 999), PKG)
    assert any("validators_count" in e for e in errors), (
        "заново вписанный устаревший литерал прошёл молча")
