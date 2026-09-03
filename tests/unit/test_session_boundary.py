"""Гранулярные тесты session_boundary (мигрировано из test_session_boundary_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engops.session_boundary import (
    CLASSES,
    check,
    classify,
    to_relation,
)


@pytest.mark.unit
class TestClassify:
    def test_same_id_same_task(self):
        c, _ = classify(current_workitem="WI-143", new_workitem="WI-143", new_task="ещё правка")
        assert c == "same_task"

    def test_continuation_marker(self):
        c, _ = classify(current_workitem="WI-143", new_task="дожми canary для WI-143")
        assert c == "continuation"

    def test_adjacent_subtask(self):
        c, _ = classify(current_workitem="WI-143", new_task="добавить environment discovery", scope_overlap=True)
        assert c == "adjacent_subtask"

    def test_new_independent_task(self):
        c, _ = classify(current_workitem="WI-143", new_task="добавить совершенно другую фичу")
        assert c == "new_independent_task"

    def test_repo_changed_new_product(self):
        c, _ = classify(current_workitem="WI-143", new_task="что угодно", repo_changed=True)
        assert c == "new_product"

    def test_no_current_wi(self):
        c, _ = classify(current_workitem=None, new_task="первая задача")
        assert c == "new_independent_task"

    def test_continues_false_suppresses_marker(self):
        c, _ = classify(current_workitem="WI-1", new_task="продолжаем", continues=False)
        assert c == "new_independent_task"


@pytest.mark.unit
class TestValidation:
    def test_all_classes_valid(self):
        assert all(check(x) == [] for x in CLASSES)

    def test_to_relation_identity(self):
        assert to_relation("same_task") == "same_task"
