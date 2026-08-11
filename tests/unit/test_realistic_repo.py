"""Кит на РЕАЛИСТИЧНОМ репозитории: то, что раньше находилось только в поле.

Пять ревью и три обкатки дали около тридцати дефектов, и ни одного не поймали синтетические тесты:
`tmp_path`-репозиторий собирает автор под ожидаемый ответ, а живой продукт так не устроен. Здесь
каждый класс, стоивший обкатки, закреплён на дереве, которое устроено как настоящее монорепо —
`tests/realistic.py` объясняет состав и причину каждой его части.

Тесты намеренно проверяют СВЯЗКИ (детект -> вердикт -> перевод человеку), а не отдельные функции:
17 из 44 выживших мутантов жили именно в швах.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from realistic import (  # noqa: E402
    CYRILLIC_DOC, assert_not_first_by_accident, build_realistic_repo, declare_repo_layout)

from ai_ops_kit.planning import contours as C  # noqa: E402
from ai_ops_kit.planning import repo_audit as A  # noqa: E402

MODEL = C.load_model()


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    """Одно дерево на модуль: сборка ~700 файлов, пересобирать на каждый тест незачем."""
    return build_realistic_repo(tmp_path_factory.mktemp("mono") / "repo")


# ── Детект не путает продукт с вендором и с самим китом ───────────────────────────────────────

def test_vendor_and_kit_internals_are_not_the_product(repo):
    """`node_modules` в каждом пакете, `.next`, `dist`, бэкап managed-слоя кита и рабочая копия
    агента — всё это НЕ продукт. Прежде каждый из этих каталогов давал ложный ответ."""
    ev = A.discover(repo)
    # Код продукта посчитан, вендор — нет: 12 страниц + 4 FSD + 3 слоя + 8 хендлеров + 1 пакет
    # + 2 теста + 2 миграции(sql) — вендорных `dep*.js` там 160, и они не должны попасть.
    assert 25 <= ev["source_files"] <= 45, f"похоже, посчитан вендор: {ev['source_files']}"
    assert ev["migrations"], "настоящие миграции обязаны быть найдены"
    assert all(".ai/" not in m and "node_modules" not in m for m in ev["migrations"])


def test_kit_backup_dockerfile_is_not_evidence_about_the_product(repo):
    """Обкатка wow-repo: Dockerfile в бэкапе managed-слоя кита делал контур архитектуры
    `not_changed` там, где честный ответ `unknown`. Продуктового Dockerfile здесь нет."""
    der = C.derive_affects(repo, ["apps/web/src/pages/p0.tsx"], MODEL, overrides={})
    assert der["system_architecture"]["state"] == C.UNKNOWN, (
        "кит принял свой бэкап за факт о продукте: " + der["system_architecture"]["reason"])


def test_fsd_entities_layer_is_not_the_data_model(repo):
    """Обкатка niti: `src/entities/` в FSD — слой интерфейса; 6 ложных находок из 9."""
    der = C.derive_affects(repo, ["apps/web/src/entities/concept/ui/Card.tsx"], MODEL, overrides={})
    assert der["data_contracts"]["state"] != C.CHANGED


def test_real_migration_does_change_the_data_contour(repo):
    """Положительный контроль к предыдущему: сигнал не выключен целиком, он сузился."""
    der = C.derive_affects(repo, ["apps/api/supabase/migrations/0002_add_col.sql"], MODEL,
                           overrides={})
    assert der["data_contracts"]["state"] == C.CHANGED


# ── Пути из настоящего git, а не из строкового литерала ───────────────────────────────────────

def test_paths_come_from_git_and_survive_cyrillic(repo):
    """Обкатка не нашла бы этого: кит русскоязычный, а `core.quotePath` включён по умолчанию.
    Берём путь ИЗ GIT, как его берёт конвейер, а не пишем строку руками."""
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "e"], check=True)
    (repo / CYRILLIC_DOC).write_text("# обзор 2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "правка обзора"], check=True)

    from ai_ops_kit.engine.pipeline_git import _committed_changed_files
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True).stdout.strip()
    changed = _committed_changed_files(repo, sha)
    assert any("Обзор.md" in f for f in changed), f"путь с кириллицей потерян: {changed}"
    der = C.derive_affects(repo, changed, MODEL, overrides={})
    assert der["product_strategy"]["state"] == C.CHANGED


# ── Производительность: обход подрезается, а не обходит вендор ────────────────────────────────

@pytest.mark.slow
def test_signal_search_is_fast_on_a_monorepo(repo):
    """Обкатка niti: 12 секунд на вызов гейта, а гейт зовут на каждом прогоне. Порог с большим
    запасом: важно не точное время, а что стоимость не линейна по размеру вендора."""
    t0 = time.time()
    for _ in range(3):
        C.derive_affects(repo, ["apps/web/src/pages/p1.tsx"], MODEL, overrides={})
    dt = (time.time() - t0) / 3
    assert dt < 1.0, f"обход не подрезается: {dt:.2f} c на вызов"


# ── Объявление владельца доезжает во ВСЕ потребители, а не в один ─────────────────────────────

def test_declared_layout_reaches_every_consumer(repo, tmp_path):
    """Техническое ревью: `contours.sot_for` объявление читал, а `repo_audit._contour_state` — нет,
    и `ai-ops model` (единственное, что видит человек) давал ПРОТИВОПОЛОЖНЫЙ ответ об одном контуре.
    Проверяем оба потребителя на одном дереве."""
    import shutil
    work = tmp_path / "declared"
    shutil.copytree(repo, work)
    declare_repo_layout(work)

    st = C.sot_state(work, MODEL)["research_decisions"]
    assert st["ok"], "contours не увидел объявленный источник истины"

    row = next(r for r in A.audit(work, A.discover(work), MODEL)["contours"]
               if r["contour"] == "research_decisions")
    assert row["state"] != A.MISSING, (
        "repo_audit игнорирует объявление владельца — `ai-ops model` соврёт человеку")


def test_gate_finds_description_behind_code_on_a_real_layout(repo, tmp_path):
    """Целевой дефект модели на реалистичном дереве: схема сменилась, openapi — нет."""
    import shutil
    work = tmp_path / "behind"
    shutil.copytree(repo, work)
    declare_repo_layout(work)

    rep = C.reconcile(work, {}, ["apps/api/supabase/migrations/0003_new.sql"], MODEL)
    behind = [f for f in rep["findings"] if f["id"] == "source_of_truth_behind"]
    assert behind and behind[0]["contour"] == "data_contracts"
    assert rep["verdict"] == "inconsistent"

    # А когда описание обновлено вместе со схемой — согласовано.
    rep2 = C.reconcile(work, {}, ["apps/api/supabase/migrations/0003_new.sql",
                                  "docs/project/openapi.yaml"], MODEL)
    assert not [f for f in rep2["findings"] if f["id"] == "source_of_truth_behind"]


# ── Правило самой фикстуры ────────────────────────────────────────────────────────────────────

def test_fixture_rule_catches_accidentally_satisfied_tests():
    """`assert_not_first_by_accident` — проверка КАЧЕСТВА теста, и она обязана работать.

    Мутационное ревью показало цену её отсутствия: три теста «про ранжирование» проходили при
    сортировке по id, потому что ожидаемый победитель всегда был первым по алфавиту.
    """
    assert_not_first_by_accident("zzz-01", ["aaa-01", "mmm-01", "zzz-01"])
    with pytest.raises(AssertionError, match="алфавит"):
        assert_not_first_by_accident("aaa-01", ["aaa-01", "zzz-01"])
    with pytest.raises(AssertionError, match="порядком строк"):
        assert_not_first_by_accident("mmm-01", ["mmm-01", "aaa-01"])
