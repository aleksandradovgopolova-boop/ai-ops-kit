"""Красный, который нельзя погасить работой, — не проверка.

ЗАМЕР 20.08.2026, первый живой прогон ночного обзора на ТРЁХ подключённых репозиториях
(ii-sreda, bolshe-ne-budu-menshe, ai-ops-demo). В КАЖДОМ валидатор ссылок давал 33 «не резолвится»
подряд: `skills/`, `governance/`, `openspec/`, `decisions/`, `knowledge/`, `examples/`,
`installer/`. Все эти каталоги есть в ките и НЕ входят в `update_policy.managed_set` — то есть у
дочки их не будет никогда, и красный не гасится никакой работой.

Почему это дорого. Отчёт с вечными красными строками перестают читать построчно — его пролистывают
целиком, и вместе с ними пролистываются настоящие находки. Ложный красный не нейтрален: он тратит
внимание, которого потом не хватит на дефект. Из тех же 33 настоящих оказалось РОВНО ДВЕ.

Список доставки не дублируется в валидаторе константой: он уже записан в манифесте, и вторая копия
разошлась бы с первой на первом же изменении поставки. Тот же принцип, что «реестр — источник
истины»: спрашиваем у него, а не помним.

ПОПУТНОЕ НАБЛЮДЕНИЕ, НЕ ЗАКРЫТОЕ ЗДЕСЬ. Список префиксов, по которым токен вообще признаётся путём
(`_MANIFEST_PATH_PREFIXES`), не содержит `ai_ops_kit/` — а туда в v3.30 переехал весь движок. То
есть самые важные пути манифеста сегодня не проверяются вовсе. Здесь не чинится (другой предмет),
но названо, чтобы не потерялось.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.validation import validate_references as vr  # noqa: E402

MANIFEST = """schema_version: 1
child_install:
  example_install: "examples/child-install/"
  ci_template: "templates/ci/ai-ops-update.yml"
update_policy:
  managed_set:
    - "templates/**/*"
    - "registry/*.yaml"
"""


def _repo(tmp_path, *, kit: bool, name="r"):
    root = tmp_path / name
    (root / "manifest").mkdir(parents=True)
    (root / "manifest" / "ai-ops-manifest.yaml").write_text(MANIFEST, encoding="utf-8")
    (root / "templates" / "ci").mkdir(parents=True)
    (root / "templates" / "ci" / "ai-ops-update.yml").write_text("", encoding="utf-8")
    if kit:
        (root / "installer").mkdir()          # признак кита
        (root / "examples" / "child-install").mkdir(parents=True)
    return root


@pytest.mark.unit
def test_a_path_the_child_never_gets_is_not_red_there(tmp_path):
    """`examples/` не входит в managed_set — у дочки его нет по замыслу, и это не находка."""
    assert vr.manifest_path_findings(_repo(tmp_path, kit=False)) == []


@pytest.mark.unit
def test_the_same_path_is_still_checked_in_the_kit(tmp_path):
    """Проверка не отменяется, а переезжает туда, где осмысленна: в ките каталог обязан быть."""
    root = _repo(tmp_path, kit=True, name="kit")
    (root / "examples" / "child-install").rmdir()
    bad = vr.manifest_path_findings(root)
    assert any("examples/child-install/" in f["ref"] for f in bad), bad


@pytest.mark.unit
def test_a_delivered_path_is_still_red_in_a_child(tmp_path):
    """Глушится ТОЛЬКО недоставляемое: обещанный дочке путь обязан краснеть, если его нет.

    Это и есть граница правки. На живом замере после неё осталось две настоящие находки —
    `tools/bench_lite.py` и `tools/qual_run.py`: манифест обещает `tools/**/*.py`, а установщик
    их намеренно не кладёт. Обещание и поставка разошлись, и теперь это ВИДНО.
    """
    root = _repo(tmp_path, kit=False, name="child")
    (root / "templates" / "ci" / "ai-ops-update.yml").unlink()
    bad = vr.manifest_path_findings(root)
    assert any("ai-ops-update.yml" in f["ref"] for f in bad), bad


@pytest.mark.unit
def test_without_a_delivery_list_nothing_is_silenced(tmp_path):
    """Манифест без `managed_set` — проверять нечем, и тогда НЕ глушим ничего.

    Умолчание «раз списка нет, значит не доставляется» превратило бы повреждённый манифест в
    зелёный отчёт: ровно то, против чего стоит остальной кит.
    """
    root = _repo(tmp_path, kit=False, name="nolist")
    (root / "manifest" / "ai-ops-manifest.yaml").write_text(
        'schema_version: 1\nchild_install:\n  example_install: "examples/child-install/"\n',
        encoding="utf-8")
    bad = vr.manifest_path_findings(root)
    assert any("examples/child-install/" in f["ref"] for f in bad), bad
