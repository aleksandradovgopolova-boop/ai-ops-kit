"""Ратчет структурного дублирования функций — статья CODE-003 конституции (#827).

ПОВЕДЕНЧЕСКИЙ: импортирует `ai_ops_kit.devtools.code_duplication` и ЗОВЁТ его над живым деревом.
Долг CODE-003 (DRY) закрыт РЕАЛЬНЫМ гейтом-ратчетом: существующие структурные дубли заморожены в
`packages/code-duplication-baseline.yaml`, НОВАЯ группа краснит этот тест. Как func-size/module-size:
потолок ходит вниз, новый дубль наверх — нельзя.

Три проверки capability: no-new (ратчет держит), fail-closed (страж ловит синтетический дубль),
ратчет-вниз (устаревшая запись baseline видна). Плюс форма: baseline непуст и версионно-стабилен.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ai_ops_kit.devtools import code_duplication as cd


@pytest.mark.contract
def test_no_new_structural_duplicates():
    """РАТЧЕТ: сверх замороженного baseline новых структурных дублей нет."""
    new = cd.new_groups()
    detail = [g["members"] for g in new]
    assert new == [], f"новый структурный дубль функций (нарушение CODE-003): {detail}"


@pytest.mark.contract
def test_baseline_is_frozen_and_nonempty():
    """Baseline существует и заморозил известный долг (иначе ратчет бессмыслен)."""
    base = cd.load_baseline()
    assert base, "baseline дублей пуст — заморозьте существующие группы (--write-baseline)"
    assert len(base) == len(cd.duplicate_groups()), "baseline разошёлся с живым замером"


@pytest.mark.contract
def test_ratchet_is_down_only_no_stale_entries():
    """Ратчет вниз: запись baseline, которой больше нет в коде, обязана быть удалена."""
    stale = cd.stale_baseline_keys()
    assert stale == set(), (
        f"устаревшие записи baseline (дубль убрали — удалите группу): {sorted(stale)}; "
        f"пересоберите: python -m ai_ops_kit.devtools.code_duplication --write-baseline")


@pytest.mark.contract
def test_detector_catches_a_synthetic_duplicate(tmp_path):
    """FAIL-CLOSED: на дереве с двумя структурно-одинаковыми функциями детектор находит группу."""
    body = (
        "def alpha(x):\n"
        "    total = 0\n"
        "    count = 0\n"
        "    acc = 1\n"
        "    for i in range(x):\n"
        "        if i % 2 == 0:\n"
        "            total += i\n"
        "        else:\n"
        "            total -= i\n"
        "        count += 1\n"
        "        acc *= 2\n"
        "    y = total * 2\n"
        "    z = y + count\n"
        "    w = z + acc\n"
        "    return w\n"
    )
    twin = body.replace("alpha", "beta")            # то же строение, другое имя -> дубль
    (tmp_path / "m.py").write_text(body + "\n" + twin, encoding="utf-8")
    groups = cd.duplicate_groups(tmp_path)
    assert any(len(g["members"]) == 2 for g in groups), "детектор не увидел синтетический дубль — страж слеп"


@pytest.mark.contract
def test_signature_is_version_stable_shape():
    """Подпись — кортеж имён типов узлов (строки): не зависит от версии Python (в отличие от ast.dump)."""
    fn = ast.parse("def f(a):\n    b = a + 1\n    return b\n").body[0]
    sig = cd._signature(fn)
    assert isinstance(sig, tuple) and all(isinstance(s, str) for s in sig), "подпись не версионно-стабильна"
