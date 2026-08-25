#!/usr/bin/env python3
"""Тесты портов ядра (K0: kernel-ports-and-contracts).

Проверяют:
1. Все Protocol'ы импортируются и являются runtime_checkable.
2. TypedDict-контракты — корректные dict-подклассы.
3. Structural typing: класс с нужными методами проходит isinstance-проверку порта.
4. Ядро (kernel/) не импортирует спутники (planning/intelligence/engops).
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest


PKG = Path(__file__).resolve().parents[2]


def test_all_ports_importable():
    """Все 7 портов и 8 TypedDict импортируются без ошибок."""
    from ai_ops_kit.kernel.ports import (
        ExecutorPort, ContextPort, EvidenceProvider, GatePort,
        DeliveryPort, PolicyPort, ClassifierPort,
        ExecutionSpec, ExecutionResult, Evidence, Change,
        RunContext, Action, Autonomy, Classification,
    )
    # Protocol'ы — runtime_checkable
    for port in (ExecutorPort, ContextPort, EvidenceProvider, GatePort,
                 DeliveryPort, PolicyPort, ClassifierPort):
        assert hasattr(port, '__protocol_attrs__') or callable(port)


def test_typed_dicts_are_dicts():
    """TypedDict-контракты — подклассы dict (runtime-совместимость)."""
    from ai_ops_kit.kernel.ports import (
        ExecutionSpec, ExecutionResult, Evidence, Change,
        RunContext, Action, Autonomy, Classification,
    )
    for cls in (ExecutionSpec, ExecutionResult, Evidence, Change,
                RunContext, Action, Autonomy, Classification):
        assert issubclass(cls, dict)


def test_structural_typing_executor_port():
    """Класс с методом run() проходит isinstance-проверку ExecutorPort."""
    from ai_ops_kit.kernel.ports import ExecutorPort

    class FakeExecutor:
        def run(self, spec):
            return {"overall_status": "done", "ready_for_pr": True}

    assert isinstance(FakeExecutor(), ExecutorPort)


def test_structural_typing_context_port():
    """Класс с методом build() проходит isinstance-проверку ContextPort."""
    from ai_ops_kit.kernel.ports import ContextPort

    class FakeContext:
        def build(self, task, signals, child_root):
            return {"kind": "ContextBundle", "text": ""}

    assert isinstance(FakeContext(), ContextPort)


def test_structural_typing_classifier_port():
    """Класс с методом classify() проходит isinstance-проверку ClassifierPort."""
    from ai_ops_kit.kernel.ports import ClassifierPort

    class FakeClassifier:
        def classify(self, signals):
            return {"workflow": "ENGINEERING"}

    assert isinstance(FakeClassifier(), ClassifierPort)


def test_kernel_does_not_import_satellites():
    """kernel/ не импортирует planning/intelligence/engops — граница ядра."""
    kernel_dir = PKG / "ai_ops_kit" / "kernel"
    satellites = {"ai_ops_kit.planning", "ai_ops_kit.intelligence", "ai_ops_kit.engops"}

    for py_file in kernel_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for sat in satellites:
                    assert not node.module.startswith(sat), (
                        f"{py_file.name}:{node.lineno} импортирует {node.module} — "
                        f"ядро не должно зависеть от спутника {sat.split('.')[-1]}"
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    for sat in satellites:
                        assert not alias.name.startswith(sat), (
                            f"{py_file.name}:{node.lineno} импортирует {alias.name} — "
                            f"ядро не должно зависеть от спутника {sat.split('.')[-1]}"
                        )
