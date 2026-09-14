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

# Тесты собирают производные счётчики по реальному реестру релиз-claims (полный проход) — >10 c на
# CI, то есть slow по определению маркера (pytest.ini). Снят с шарда `fast` под `--dist loadfile` в
# slow-шарды selftests, где есть запас; на КАЖДОМ PR по-прежнему выполняется. Issue #465.
pytestmark = [pytest.mark.unit, pytest.mark.slow]

DERIVED_FIELDS = ("validators_count", "validators_externally_tested")
# gates_count/mvp_blocking_count тоже DERIVED (работа `gate-count-is-computed-not-declared`), но их
# литерал ПОКА хранится в release-claims.yaml — его уберёт отдельный bookkeeping-PR. Поэтому эти
# поля НЕ проверяются на отсутствие в реестре (см. секцию «gates» ниже), а вот из derived_field_values
# они обязаны выводиться уже сейчас, чтобы удаление литерала не уронило сверку.
GATE_FIELDS = ("gates_count", "mvp_blocking_count")


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
    assert set(vals) == set(DERIVED_FIELDS) | set(GATE_FIELDS)
    vtotal, vtested = vrc.derived_verification_counts(PKG)
    gates_total, mvp = vrc.derived_gate_counts(PKG)
    assert vals == {"validators_count": vtotal, "validators_externally_tested": vtested,
                    "gates_count": gates_total, "mvp_blocking_count": mvp}
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


# ── gates_count / mvp_blocking_count: тот же приём для числа ГЕЙТОВ ──────────────────────────────
# Работа `gate-count-is-computed-not-declared`. Добавление гейта в quality/gates.yaml — код;
# синхронный подъём gates_count в release-claims.yaml — правка КООРДИНАЦИОННОГО файла, которую
# parallel-safety --strict запрещает смешивать с кодом. Фичевый PR с новым гейтом упирался в этот
# запрет. Снимаем ту же коллизию тем же приёмом, что у validators_count: число выводится из факта
# (quality/gates.yaml), хранить литерал не обязательно.


def test_gate_counts_live_in_derived_field_values():
    """Оба числа гейтов выводятся из quality/gates.yaml и лежат в derived_field_values рядом с
    валидаторными — единый механизм «факт, а не литерал»."""
    vals = vrc.derived_field_values(PKG)
    gates_total, mvp = vrc.derived_gate_counts(PKG)
    assert vals["gates_count"] == gates_total > 0, "факт по гейтам пуст — проверка ослепла бы"
    assert vals["mvp_blocking_count"] == mvp


def test_check_derives_gate_counts_when_literal_absent(claims):
    """(а) Без литерала gates_count/mvp_blocking_count сверка ВЫВОДИТ число из quality/gates.yaml и
    проходит — это состояние ПОСЛЕ bookkeeping-PR, который уберёт литерал из release-claims.yaml.
    Код обязан переживать его уже сейчас, иначе удаление литерала уронит CI."""
    without = {k: v for k, v in dict(claims).items() if k not in GATE_FIELDS}
    assert vrc.check(without, PKG) == [], (
        "удаление литерала gates_count/mvp_blocking_count из реестра уронило сверку — "
        "число не деривируется из факта")


def test_adding_a_gate_needs_no_registry_edit(claims, monkeypatch):
    """(б) Гейт добавлен (факт вырос), release-claims без литерала НЕ тронут — реестрового дрейфа
    нет, и деривированное число растёт вместе с фактом. Раньше это давало красное
    «gates_count != гейтов в quality/gates.yaml», пока PR не подвинет число в координационном
    файле, — а именно эту правку запрещает смешивать с кодом parallel-safety."""
    gates_total, mvp = vrc.derived_gate_counts(PKG)
    monkeypatch.setattr(vrc, "derived_gate_counts", lambda pkg=vrc.PKG: (gates_total + 1, mvp + 1))
    assert vrc.derived_field_values(PKG)["gates_count"] == gates_total + 1, (
        "деривированное число не следует за фактом")
    without = {k: v for k, v in dict(claims).items() if k not in GATE_FIELDS}
    gate_drift = [e for e in vrc.check(without, PKG) if "гейтов в quality/gates.yaml" in e
                  or "mvp_blocking_gates в quality/gates.yaml" in e]
    assert gate_drift == [], (
        f"рост числа гейтов потребовал правки release-claims — общая точка вернулась: {gate_drift}")


def test_a_re_nailed_gate_literal_that_disagrees_still_errors(claims):
    """Fail-closed: если лента снова впишет gates_count и оно разойдётся с фактом — ошибка
    (защита от повторного «прибивания гвоздём»; проверка mvp_gates_are_blocking не ослаблена)."""
    gates_total, _ = vrc.derived_gate_counts(PKG)
    errors = vrc.check(dict(claims, gates_count=gates_total + 999), PKG)
    assert any("gates_count" in e for e in errors), "заново вписанный устаревший литерал прошёл молча"
