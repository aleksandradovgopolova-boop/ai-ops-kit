"""Реконсиляция статья↔гейт Архитектурной конституции честна и свежа (#824).

ПОВЕДЕНЧЕСКИЙ: импортирует продуктовый модуль `arch_gate_reconciliation` и ЗОВЁТ его — сверка идёт
через реальную доставку (`installer.RUNTIME_VALIDATORS`/`is_runtime_asset`), а не через чтение
файла глазами. Держим три вещи: каждый цитируемый гейт разрешается в реальный backing; колонка
«в дочке?» согласована с доставкой (обещание = реальность); сгенерированная таблица в синхроне.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_ops_kit.devtools import arch_gate_reconciliation as recon

OUT_MD = Path(recon.OUT_MD)


@pytest.mark.unit
def test_every_cited_gate_resolves_to_real_backing():
    """Гейт статьи (кроме none/meta) обязан указывать на существующую проверку — иначе мёртвая ссылка."""
    unresolved = [r["id"] for r in recon.reconcile() if r["kind"] == "unresolved"]
    assert unresolved == [], f"статьи цитируют несуществующий гейт (мёртвая ссылка): {unresolved}"


@pytest.mark.unit
def test_declared_enforcement_matches_real_delivery():
    """ЧЕСТНОСТЬ: enforced_in каждой статьи согласован с реальной доставкой backing'а в дочку.

    child/both -> backing реально доходит до дочки; parent -> гейт есть, но в дочку НЕ едет;
    none -> гейта нет; meta -> само-правило. Расхождение = ложная зрелость (HON-003)."""
    bad = recon.dishonest_rows()
    detail = [(r["id"], r["enforced_in"], r["kind"], r["reaches_child"]) for r in bad]
    assert bad == [], f"обещание Исполнения разошлось с реальной доставкой: {detail}"


@pytest.mark.unit
def test_column_is_meaningful_parent_only_gates_exist():
    """Колонка «в дочке?» не декоративна: есть и parent-only-гейты, и доходящие до дочки."""
    rows = recon.reconcile()
    real = [r for r in rows if r["gate"] not in ("none", "meta")]
    assert any(not r["reaches_child"] for r in real), "нет ни одного parent-only гейта — колонка бессмысленна"
    assert any(r["reaches_child"] for r in real), "ни один гейт не доходит до дочки — доставка не отражена"


@pytest.mark.unit
def test_generated_table_is_fresh():
    """СВЕЖЕСТЬ: закоммиченная gate-reconciliation.md == пересборке (генерат не правят руками)."""
    assert OUT_MD.is_file(), "нет standards/architecture/gate-reconciliation.md — сгенерируйте --write"
    assert OUT_MD.read_text(encoding="utf-8") == recon.render_markdown(), (
        "gate-reconciliation.md разошлась — пересоберите: "
        "python -m ai_ops_kit.devtools.arch_gate_reconciliation --write")


@pytest.mark.unit
def test_main_exit_code_reflects_honesty():
    """Точка входа падает, если появилась нечестная строка (для CI/ручного прогона)."""
    assert recon.main(["--write"]) == 0, "реконсиляция сообщает о нечестных строках на текущем дереве"
