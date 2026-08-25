"""Инвариант: каждый тест приписан к ярусу пирамиды — по каталогу, и это читается числом.

Ярус тестовой пирамиды задаётся РАСПОЛОЖЕНИЕМ файла (`tests/tier_map.DIR_TIER`):
tests/unit -> unit, tests/contracts -> contract, tests/integration -> integration.
`conftest.pytest_collection_modifyitems` проставляет маркер автоматически на сборке — поэтому
2686 функций не размечаются руками (git blame не топится), но пирамида видна `pytest -m unit`.

Здесь — охранный инвариант того, что авто-разметка ПОЛНА: ни один тест-файл не живёт вне каталога
с известным ярусом. Без него новый тест в новом каталоге выпал бы из пирамиды бесшумно (получил бы
ноль ярусных маркеров и не попал бы ни под один срез CI по ярусу).

Три обязательных теста на capability (AGENTS.md):
  * positive     — реальные файлы каждого яруса резолвятся в свой маркер;
  * fail-closed  — файл в НЕизвестном каталоге яруса не получает (ловится инвариантом);
  * side-effect  — соответствие живёт в едином источнике tier_map, а conftest читает ОТТУДА
                   (иначе маркер был бы второй правдой рядом с картой).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tier_map import DIR_TIER, TIER_MARKERS

TESTS_ROOT = Path(__file__).resolve().parents[1]


def _tier_dir(f: Path) -> str:
    """Непосредственный подкаталог tests/, в котором лежит файл (первый компонент относительного пути)."""
    rel = f.resolve().relative_to(TESTS_ROOT)
    return rel.parts[0] if len(rel.parts) > 1 else rel.parts[0]


# ── positive: каждый тест-файл — в каталоге с известным ярусом ──────────────────────────────────

@pytest.mark.contract
def test_every_test_file_lives_in_a_tiered_directory():
    orphans = []
    for f in sorted(TESTS_ROOT.rglob("test_*.py")):
        top = _tier_dir(f)
        if top not in DIR_TIER:
            orphans.append(str(f.relative_to(TESTS_ROOT)))
    assert not orphans, (
        "тест-файлы вне каталога с известным ярусом (добавь ярус в tier_map.DIR_TIER или перенеси "
        f"файл): {orphans}"
    )


@pytest.mark.contract
def test_known_tier_dirs_resolve_to_their_marker():
    # реальные каталоги пирамиды присутствуют и резолвятся в объявленный маркер
    for d, marker in DIR_TIER.items():
        assert (TESTS_ROOT / d).is_dir(), f"каталог яруса '{d}' не существует — карта устарела"
        assert marker in TIER_MARKERS, f"ярус '{marker}' не в TIER_MARKERS"


# ── fail-closed: незнакомый каталог яруса не получает ───────────────────────────────────────────

@pytest.mark.contract
def test_unknown_directory_gets_no_tier():
    # синтетический путь в несуществующем ярусе -> карта не выдаёт ярус, значит инвариант его поймает
    assert DIR_TIER.get("smoke_experiments") is None
    assert DIR_TIER.get("") is None


# ── side-effect: маркер берётся из единого источника, не дублируется в conftest ──────────────────

@pytest.mark.contract
def test_conftest_reads_the_map_not_a_copy():
    conftest = (TESTS_ROOT / "conftest.py").read_text(encoding="utf-8")
    assert "from tier_map import" in conftest, "conftest обязан читать ярусы из tier_map, а не хранить копию"
    assert "pytest_collection_modifyitems" in conftest, "нет хука авто-разметки по каталогу"
