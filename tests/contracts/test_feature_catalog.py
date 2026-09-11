"""Каталог фич СГЕНЕРИРОВАН, а не написан руками — и честно рендерит реестр (W4b).

Цель всей фичи feature-registry-coverage — чтобы аналитик за час разобрался во ВСЕХ фичах продукта
из ОДНОГО места. Человеческую сторону даёт каталог `docs/feature-catalog.md`, собранный из реестра
фич чистым рендером `ai_ops_kit/checks/feature_catalog.render_catalog`. Эти тесты держат его честным:

  * страница `docs/feature-catalog.md` == вывод генератора из образца-реестра (committed == render),
    иначе она молча разойдётся с реестром — тот же класс защиты, что у docs/capability-map.md;
  * рендер идемпотентен (повторный сбор той же страницы даёт тот же текст);
  * пустой/отсутствующий реестр -> честная заглушка, а не падение;
  * каждая фича реестра ПРИСУТСТВУЕТ в каталоге (аналитик видит их все, не подмножество).

Все тесты ПОВЕДЕНЧЕСКИЕ: импортируют рендер и CLI-обёртку и ЗОВУТ их, а не читают их исходники.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ai_ops_kit.checks import feature_catalog
from ai_ops_kit.devtools import feature_catalog_cli as cli

PKG_ROOT = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.contract]


def _example_registry() -> dict:
    return yaml.safe_load(cli.DEFAULT_REGISTRY.read_text(encoding="utf-8")) or {}


def test_committed_page_is_generated_not_hand_written():
    """`docs/feature-catalog.md` == рендер из образца-реестра. Правлено рукой или устарело — красное."""
    page = PKG_ROOT / cli.PAGE_REL
    assert page.is_file(), (
        f"{cli.PAGE_REL} нет — сгенерируйте: "
        "python3 -m ai_ops_kit.devtools.feature_catalog_cli --write")
    assert page.read_text(encoding="utf-8") == feature_catalog.render_catalog(_example_registry()), (
        f"{cli.PAGE_REL} устарел или правлен рукой — перегенерируйте: "
        "python3 -m ai_ops_kit.devtools.feature_catalog_cli --write")


def test_render_is_idempotent():
    """Повторный сбор той же страницы даёт тот же текст — генератор детерминирован по реестру."""
    reg = _example_registry()
    assert feature_catalog.render_catalog(reg) == feature_catalog.render_catalog(reg)


def test_cli_check_agrees_with_committed_page():
    """Процессный вход --check зелёный на committed-доке — обёртка и committed согласованы."""
    assert cli.main(["--check"]) == 0


def test_empty_registry_renders_an_honest_stub_not_a_crash():
    """Пустой реестр — не ошибка: заглушка «фичи ещё не заведены», а не исключение."""
    out = feature_catalog.render_catalog({"features": []})
    assert "Фичи ещё не заведены" in out
    # заглушка всё равно несёт маркер «не править руками» — её тоже стережёт committed-сверка
    assert "РУКАМИ НЕ ПРАВИТЬ" in out


def test_missing_registry_is_treated_as_empty():
    """Отсутствующий файл реестра -> пустой реестр -> заглушка (загрузчик не падает)."""
    reg = cli.load_registry(Path("/no/such/feature-registry.yaml"))
    assert reg == {}
    assert "Фичи ещё не заведены" in feature_catalog.render_catalog(reg)


def test_every_feature_in_the_registry_appears_in_the_catalog():
    """Каждая фича образца ПРИСУТСТВУЕТ в каталоге — аналитик видит их все, не подмножество."""
    reg = _example_registry()
    out = feature_catalog.render_catalog(reg)
    missing = [f["id"] for f in reg["features"] if f["id"] not in out]
    assert not missing, f"фичи реестра пропали из каталога: {missing}"


def test_catalog_shows_what_who_verify_for_the_analyst():
    """По фиче видно ЧТО/ДЛЯ КОГО/КАК ПРОВЕРИТЬ — иначе аналитику каталог бесполезен."""
    reg = _example_registry()
    out = feature_catalog.render_catalog(reg)
    assert "Что делает:" in out and "Для кого:" in out and "Как проверить:" in out
    a_feature = reg["features"][0]["description"]
    assert a_feature["what"] in out and a_feature["who"] in out and a_feature["verify"] in out


def test_summary_counts_are_derived_from_the_registry_not_hardcoded():
    """Числа сводки взяты из реестра: всего фич и разбивка по статусам совпадают с реестром."""
    reg = _example_registry()
    summ = feature_catalog.summarize(reg)
    assert summ["total"] == len(reg["features"])
    expected: dict[str, int] = {}
    for f in reg["features"]:
        expected[f["status"]] = expected.get(f["status"], 0) + 1
    assert summ["by_status"] == expected


def test_surface_confidence_is_shown_so_strength_stays_honest():
    """Поверхность несёт confidence в каталоге — честность силы = честность уверенности (как в W3)."""
    out = feature_catalog.render_catalog(_example_registry())
    assert "Уверенность" in out and "inferred" in out
