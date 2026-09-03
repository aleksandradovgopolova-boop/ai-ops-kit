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
    check_all,
    iter_scopes,
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

    def test_baseline_declares_scopes(self):
        """Baseline объявляет секцию scopes — иначе ратчет ничего не стережёт."""
        baseline = load_baseline(BASELINE_FILE)
        scopes = iter_scopes(baseline)
        paths = {s["path"] for s in scopes}
        # engine/ — исторический scope; четыре дома god-функций — новое покрытие.
        assert "ai_ops_kit/engine/" in paths
        for expected in ("ai_ops_kit/cli/", "ai_ops_kit/planning/",
                         "ai_ops_kit/providers/", "ai_ops_kit/validation/"):
            assert expected in paths, f"{expected} не покрыт ратчетом"

    def test_all_scopes_within_ceiling(self):
        """Ни один объявленный scope НЕ превышает свой потолок (весь пакет, не только engine/).

        Если этот тест падает — кто-то добавил god-функцию сверх потолка в одном из
        покрытых каталогов. Либо разбить её, либо осознанно поднять потолок (с объяснением).
        """
        baseline = load_baseline(BASELINE_FILE)
        assert check_all(baseline) == []


# ---------------------------------------------------------------------------
# Регрессия: ратчет реально стережёт каталоги ВНЕ engine/
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestWiderScopeCatchesGodFunctions:
    """Новая god-функция в cli/planning/providers/validation ловится, а не растёт свободно.

    До расширения (func-size-ratchet-wider) ратчет мерил только engine/, и god-функция ВНЕ
    engine/ не краснела. Эти тесты редели бы на старом одно-каталожном ратчете.
    """

    @staticmethod
    def _make_pkg(tmp_path, scope_rel, func_lines, ceiling):
        """Собрать искусственный pkg_root: один scope с функцией на func_lines строк."""
        scope_dir = tmp_path / scope_rel
        scope_dir.mkdir(parents=True)
        body = "\n".join(f"    x{i} = {i}" for i in range(func_lines - 1))
        (scope_dir / "mod.py").write_text(f"def god():\n{body}\n", encoding="utf-8")
        baseline = {"scopes": [{"path": scope_rel, "max_function_lines": ceiling}]}
        return baseline

    @pytest.mark.parametrize("scope_rel", [
        "ai_ops_kit/cli",
        "ai_ops_kit/planning",
        "ai_ops_kit/providers",
        "ai_ops_kit/validation",
    ])
    def test_new_god_function_outside_engine_is_flagged(self, tmp_path, scope_rel):
        """Функция сверх потолка в НЕ-engine каталоге краснеет (раньше росла свободно)."""
        baseline = self._make_pkg(tmp_path, scope_rel, func_lines=250, ceiling=200)
        errors = check_all(baseline, pkg_root=tmp_path)
        assert len(errors) == 1
        assert scope_rel in errors[0]
        assert "превышает потолок" in errors[0]

    def test_within_ceiling_stays_green(self, tmp_path):
        """Функция ровно на потолке — зелено (ратчет не ложно-краснит)."""
        baseline = self._make_pkg(tmp_path, "ai_ops_kit/cli", func_lines=200, ceiling=200)
        assert check_all(baseline, pkg_root=tmp_path) == []

    def test_missing_scopes_section_is_itself_an_error(self):
        """Baseline без scopes — ратчет говорит «стеречь нечего», а не молча зеленеет."""
        errors = check_all({})
        assert len(errors) == 1
        assert "нет секции scopes" in errors[0]
