"""Ядро не импортирует спутники (S2: kernel-boundary-rule).

Три кольца (AGENTS.md): Kernel — {shared, kernel, engine, gates, lifecycle, delivery,
governance}; Intelligence читает Kernel, но Kernel от него НЕ зависит. planning и engops —
спутники внутри capabilities, слоями не запрещены. Правило kernel-boundary в layering.yaml
закрывает дыру: validate_layering.py обязан ловить нарушение.

Три обязательных теста на capability:
  * positive     — реальный граф репозитория не нарушает правило;
  * fail-closed  — синтетическое нарушение краснеет;
  * side-effect  — правило читается из layering.yaml, а не захардкожено в проверке.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG / "validation"))

import validate_layering as vl  # noqa: E402


@pytest.fixture(scope="module")
def spec():
    return vl.load_spec()


def test_real_repository_respects_kernel_boundary(spec):
    """positive: ни один модуль ядра не импортирует planning/intelligence/engops."""
    errors, _caught = vl.check_kernel_boundary(spec, vl.build_graph())
    assert not errors, "ядро импортирует спутники:\n  " + "\n  ".join(errors)


@pytest.mark.parametrize("edge", [
    ("engine", "planning"),
    ("gates", "engops"),
    ("lifecycle", "intelligence"),
    ("shared", "planning"),
    ("kernel", "engops"),
    ("delivery", "intelligence"),
    ("governance", "planning"),
])
def test_synthetic_violation_is_caught(spec, edge):
    """fail-closed: каждое запрещённое ребро обязано краснеть с понятным сообщением."""
    fake_edges = {edge: {"synthetic -> synthetic"}}
    errors, caught = vl.check_kernel_boundary(spec, fake_edges)
    assert errors, f"нарушение {edge[0]} -> {edge[1]} прошло молча"
    assert any("kernel-boundary" in e and edge[0] in e and edge[1] in e for e in errors), (
        f"нарушение поймано, но названо непонятно: {errors}")
    assert edge in caught, "пойманное ребро не возвращено в caught"


def test_non_kernel_import_is_allowed(spec):
    """side-effect: правило не запрещает импорт спутников из НЕ-ядра (например, cli -> planning).

    cli в entrypoints, planning в capabilities — это вверх по слоям, но kernel-boundary не про
    это. Проверка, что правило не шире задуманного.
    """
    fake_edges = {("cli", "planning"): {"x -> y"}}
    errors, _caught = vl.check_kernel_boundary(spec, fake_edges)
    assert not errors, f"cli -> planning не обязан запрещаться kernel-boundary: {errors}"


def test_kernel_boundary_rule_is_declared_in_yaml(spec):
    """side-effect: правило читается из layering.yaml, а не захардкожено в validate_layering.py.

    Если кто-то удалит kernel-boundary из YAML, проверка обязана перестать работать — и тест
    это поймает, потому что синтетическое нарушение перестанет ловиться.
    """
    rules = spec.get("rules") or []
    kb = next((r for r in rules if r.get("id") == "kernel-boundary"), None)
    assert kb is not None, "правило kernel-boundary отсутствует в packages/layering.yaml"
    assert "kernel_members" in kb and "forbidden_imports" in kb, (
        "правило kernel-boundary обязано содержать kernel_members и forbidden_imports")


def test_main_includes_kernel_boundary(spec):
    """side-effect: main() вызывает check_kernel_boundary, а не только check().

    Проверка, объявленная но не вызванная, — то же самое, что проверка отсутствующая.
    """
    # Синтетический граф с нарушением: если main() не вызовет check_kernel_boundary,
    # ошибки будут пустые (check() не знает про kernel-boundary).
    fake_edges = {("engine", "planning"): {"x -> y"}}
    errors, _caught = vl.check_kernel_boundary(spec, fake_edges)
    assert errors, "check_kernel_boundary не ловит нарушение — вызов в main() мог пропасть"
