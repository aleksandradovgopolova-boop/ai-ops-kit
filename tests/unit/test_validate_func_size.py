"""Тесты ратчета максимального размера функции (validate_func_size).

Фиксируют: AST-обход корректно считает размеры, baseline загружается,
ратчет краснеет при превышении и зеленеет в пределах потолка.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_ops_kit.validation.validate_func_size import (
    BASELINE_FILE,
    ENGINE_DIR,
    check,
    load_baseline,
    measure_functions,
    render_report,
    top_n,
)


# ---------------------------------------------------------------------------
# measure_functions: AST-обход
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMeasureFunctions:
    """AST-обход считает размеры функций."""

    def test_counts_regular_function(self, tmp_path):
        """Обычная def — размер = end_lineno - lineno + 1."""
        src = textwrap.dedent("""\
            def foo():
                x = 1
                y = 2
                return x + y
        """)
        (tmp_path / "mod.py").write_text(src, encoding="utf-8")
        funcs = measure_functions(tmp_path)
        assert len(funcs) == 1
        assert funcs[0]["name"] == "foo"
        assert funcs[0]["size"] == 4

    def test_counts_async_function(self, tmp_path):
        """async def тоже считается."""
        src = textwrap.dedent("""\
            async def bar():
                await something()
                return 42
        """)
        (tmp_path / "mod.py").write_text(src, encoding="utf-8")
        funcs = measure_functions(tmp_path)
        assert len(funcs) == 1
        assert funcs[0]["name"] == "bar"
        assert funcs[0]["size"] == 3

    def test_nested_functions_counted_separately(self, tmp_path):
        """Вложенные функции считаются каждая отдельно (не как одна большая)."""
        src = textwrap.dedent("""\
            def outer():
                def inner():
                    pass
                inner()
        """)
        (tmp_path / "mod.py").write_text(src, encoding="utf-8")
        funcs = measure_functions(tmp_path)
        names = {f["name"] for f in funcs}
        assert "outer" in names
        assert "inner" in names

    def test_syntax_error_skipped(self, tmp_path):
        """Файл с SyntaxError пропускается, не роняет обход."""
        (tmp_path / "bad.py").write_text("def foo(:\n", encoding="utf-8")
        (tmp_path / "good.py").write_text("def bar():\n    pass\n", encoding="utf-8")
        funcs = measure_functions(tmp_path)
        assert len(funcs) == 1
        assert funcs[0]["name"] == "bar"

    def test_records_file_and_lineno(self, tmp_path):
        """Каждая запись содержит имя файла и номер строки."""
        src = textwrap.dedent("""\
            def alpha():
                pass

            def beta():
                x = 1
                return x
        """)
        (tmp_path / "sample.py").write_text(src, encoding="utf-8")
        funcs = measure_functions(tmp_path)
        by_name = {f["name"]: f for f in funcs}
        assert by_name["alpha"]["file"] == "sample.py"
        assert by_name["alpha"]["lineno"] == 1
        assert by_name["beta"]["lineno"] == 4


# ---------------------------------------------------------------------------
# top_n: сортировка
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTopN:
    """Топ-N крупнейших функций."""

    def test_returns_sorted_descending(self):
        funcs = [
            {"name": "small", "file": "a.py", "lineno": 1, "size": 10},
            {"name": "big", "file": "b.py", "lineno": 1, "size": 100},
            {"name": "medium", "file": "c.py", "lineno": 1, "size": 50},
        ]
        result = top_n(funcs, n=2)
        assert len(result) == 2
        assert result[0]["name"] == "big"
        assert result[1]["name"] == "medium"

    def test_n_larger_than_list(self):
        funcs = [{"name": "only", "file": "a.py", "lineno": 1, "size": 5}]
        assert len(top_n(funcs, n=10)) == 1


# ---------------------------------------------------------------------------
# check: ратчет
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCheck:
    """Ратчет: сравнение с baseline."""

    def test_passes_when_at_ceiling(self):
        """Максимум = потолок — ОК (ратчет не краснеет)."""
        funcs = [{"name": "f", "file": "a.py", "lineno": 1, "size": 100}]
        baseline = {"max_function_lines": 100}
        assert check(funcs, baseline) == []

    def test_fails_when_exceeds_ceiling(self):
        """Максимум > потолок — FAIL."""
        funcs = [{"name": "god", "file": "a.py", "lineno": 1, "size": 200}]
        baseline = {"max_function_lines": 100}
        errors = check(funcs, baseline)
        assert len(errors) == 1
        assert "превышает потолок" in errors[0]
        assert "god" in errors[0]

    def test_fails_when_baseline_missing(self):
        """Нет baseline — ратчет не может проверять."""
        funcs = [{"name": "f", "file": "a.py", "lineno": 1, "size": 10}]
        errors = check(funcs, {})
        assert len(errors) == 1
        assert "нет числа" in errors[0]

    def test_reports_when_below_ceiling(self):
        """Максимум < потолок — ратчет говорит «опусти потолок»."""
        funcs = [{"name": "f", "file": "a.py", "lineno": 1, "size": 50}]
        baseline = {"max_function_lines": 100}
        errors = check(funcs, baseline)
        assert len(errors) == 1
        assert "опустить" in errors[0]


# ---------------------------------------------------------------------------
# load_baseline
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLoadBaseline:
    """Загрузка baseline из YAML."""

    def test_loads_existing_baseline(self, tmp_path):
        bl = tmp_path / "bl.yaml"
        bl.write_text("max_function_lines: 500\n", encoding="utf-8")
        result = load_baseline(bl)
        assert result["max_function_lines"] == 500

    def test_returns_empty_for_missing_file(self, tmp_path):
        result = load_baseline(tmp_path / "nonexistent.yaml")
        assert result == {}


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRenderReport:
    """Человекочитаемый отчёт."""

    def test_contains_total_count(self):
        funcs = [{"name": "a", "file": "x.py", "lineno": 1, "size": 10}]
        report = render_report(funcs)
        assert "Всего функций: 1" in report

    def test_lists_largest_first(self):
        funcs = [
            {"name": "small", "file": "a.py", "lineno": 1, "size": 5},
            {"name": "big", "file": "b.py", "lineno": 1, "size": 500},
        ]
        report = render_report(funcs)
        # big должна идти первой (500 > 5)
        big_pos = report.index("big")
        small_pos = report.index("small")
        assert big_pos < small_pos


# ---------------------------------------------------------------------------
# Инвариант: реальный baseline соответствует текущему коду
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRealBaselineConsistency:
    """Baseline-файл и реальный код согласованы."""

    def test_baseline_file_exists(self):
        """Baseline-файл существует (ратчет не может работать без него)."""
        assert BASELINE_FILE.is_file()

    def test_current_max_does_not_exceed_baseline(self):
        """Текущий максимум в engine/ НЕ превышает объявленный потолок.

        Если этот тест падает — кто-то добавил god-функцию сверх потолка.
        Либо разбить её, либо осознанно поднять потолок (с объяснением).
        """
        funcs = measure_functions(ENGINE_DIR)
        baseline = load_baseline(BASELINE_FILE)
        ceiling = baseline.get("max_function_lines", 0)
        actual_max = max((f["size"] for f in funcs), default=0)
        assert actual_max <= ceiling, (
            f"Текущий max {actual_max} строк превышает потолок {ceiling}. "
            f"Разбей god-функцию или обнови baseline."
        )
