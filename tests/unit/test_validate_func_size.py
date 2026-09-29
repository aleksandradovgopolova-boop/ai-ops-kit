"""Тесты ратчета максимального размера функции (validate_func_size).

Фиксируют: AST-обход корректно считает размеры, baseline загружается,
ратчет краснеет при превышении и зеленеет в пределах потолка.
"""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from ai_ops_kit.validation.validate_func_size import (
    BASELINE_FILE,
    ENGINE_DIR,
    advise,
    advise_all,
    append_raises_text,
    check,
    check_all,
    iter_scopes,
    load_baseline,
    measure_functions,
    rebaseline,
    render_report,
    rewrite_scope_text,
    top_n,
    unrecorded_raises,
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

    def test_below_ceiling_is_not_an_error(self):
        """Максимум < потолок — НЕ отказ (#1128): сокращение функции не роняет посторонний PR."""
        funcs = [{"name": "f", "file": "a.py", "lineno": 1, "size": 50}]
        baseline = {"max_function_lines": 100}
        assert check(funcs, baseline) == []

    def test_below_ceiling_warns_to_lower_it(self):
        """…но предупреждение просит опустить потолок и называет команду."""
        funcs = [{"name": "f", "file": "a.py", "lineno": 1, "size": 50}]
        notes = advise(funcs, {"max_function_lines": 100})
        assert len(notes) == 1
        assert "опустить потолок" in notes[0]
        assert "--baseline" in notes[0]


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
                         "ai_ops_kit/providers/", "ai_ops_kit/validation/",
                         "ai_ops_kit/intelligence/"):
            assert expected in paths, f"{expected} не покрыт ратчетом"

    def test_every_package_directory_is_covered(self):
        """КАЖДЫЙ каталог пакета объявлен в ратчете, иначе функция в нём растёт свободно.

        #1119: `intelligence/` не был покрыт, и там выросла САМАЯ ДЛИННАЯ функция репозитория
        (`build_graph`, 275 строк: больше любого объявленного потолка). Список каталогов в baseline
        пополнялся вручную и отставал от кода; эта проверка ловит отставание сама, не дожидаясь
        следующего замера.
        """
        baseline = load_baseline(BASELINE_FILE)
        covered = {sc["path"].rstrip("/") for sc in iter_scopes(baseline)}
        uncovered = {}
        for directory in sorted((BASELINE_FILE.parents[1] / "ai_ops_kit").iterdir()):
            rel = f"ai_ops_kit/{directory.name}"
            if not directory.is_dir() or rel in covered:
                continue
            biggest = max((f["size"] for f in measure_functions(directory)), default=0)
            if biggest:
                uncovered[rel] = biggest
        assert not uncovered, (
            f"каталоги пакета вне ратчета: {uncovered}. Потолок заводится ПО ФАКТУ "
            f"(текущий максимум каталога) — он останавливает рост, а не требует рефакторинга")

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
        "ai_ops_kit/intelligence",
    ])
    def test_new_god_function_outside_engine_is_flagged(self, tmp_path, scope_rel):
        """Функция сверх потолка в НЕ-engine каталоге краснеет (раньше росла свободно)."""
        baseline = self._make_pkg(tmp_path, scope_rel, func_lines=250, ceiling=200)
        errors = check_all(baseline, pkg_root=tmp_path)
        assert len(errors) == 1
        assert scope_rel in errors[0]
        assert "превышает потолок" in errors[0]

    def test_god_function_in_a_nested_package_is_flagged(self, tmp_path):
        """Подпакет-сателлит внутри покрытого каталога тоже под присмотром.

        #1119: сторож охвата видел только верхний уровень, а измерение брало `glob("*.py")` без
        рекурсии — `checks/surface_extractors/` (18 файлов, 102 функции) не стерёг никто. Репозиторий
        активно плодит сателлиты, так что дыра росла бы сама.
        """
        scope_dir = tmp_path / "ai_ops_kit/checks"
        nested = scope_dir / "surface_extractors"
        nested.mkdir(parents=True)
        body = "\n".join(f"    x{i} = {i}" for i in range(249))
        (nested / "mod.py").write_text(f"def god():\n{body}\n", encoding="utf-8")
        baseline = {"scopes": [{"path": "ai_ops_kit/checks", "max_function_lines": 200}]}
        errors = check_all(baseline, pkg_root=tmp_path)
        assert len(errors) == 1, errors
        assert "превышает потолок" in errors[0]

    def test_nested_file_is_named_with_its_path(self, tmp_path):
        """И место названо так, чтобы его нашли: имя файла с путём внутри каталога."""
        scope_dir = tmp_path / "ai_ops_kit/checks"
        nested = scope_dir / "surface_extractors"
        nested.mkdir(parents=True)
        (nested / "ktor.py").write_text("def small():\n    return 1\n", encoding="utf-8")
        measured = measure_functions(scope_dir)
        assert [f["file"] for f in measured] == ["surface_extractors/ktor.py"], measured

    def test_within_ceiling_stays_green(self, tmp_path):
        """Функция ровно на потолке — зелено (ратчет не ложно-краснит)."""
        baseline = self._make_pkg(tmp_path, "ai_ops_kit/cli", func_lines=200, ceiling=200)
        assert check_all(baseline, pkg_root=tmp_path) == []

    def test_missing_scopes_section_is_itself_an_error(self):
        """Baseline без scopes — ратчет говорит «стеречь нечего», а не молча зеленеет."""
        errors = check_all({})
        assert len(errors) == 1
        assert "нет секции scopes" in errors[0]


# ---------------------------------------------------------------------------
# #1128: снижение и координаты — предупреждение; --baseline правит текстом и не ходит вверх
# ---------------------------------------------------------------------------

def _func_src(name: str, lines: int) -> str:
    body = "\n".join(f"    x{i} = {i}" for i in range(lines - 1))
    return f"def {name}():\n{body}\n"


# Baseline с комментариями во всех местах, где они живут в настоящем файле: шапка, перед scope,
# между scope'ами и хвостовой комментарий строки. После --baseline каждый из них обязан уцелеть.
_BASELINE_TEXT = textwrap.dedent("""\
    # Шапка: история потолка и обоснование.
    schema_version: 2
    kind: func-size-ratchet

    scopes:
      # alpha/ — опускали 300 -> 200 (#1). Этот комментарий обязан пережить --baseline.
      - path: pkg/alpha/
        max_function_lines: 200   # хвостовой комментарий
        max_function: old_name
        max_function_file: old.py
        max_function_lineno: 999

      # beta/ — второй scope.
      - path: pkg/beta/
        max_function_lines: 50
        max_function: beta_fn
        max_function_file: b.py
        max_function_lineno: 1
    """)

_FIELD_LINE = ("max_function_lines:", "max_function:", "max_function_file:", "max_function_lineno:")


def _make_repo(tmp_path, alpha_lines: int, beta_lines: int = 50):
    """pkg_root с двумя scope'ами и baseline-файлом с комментариями."""
    for rel, name, size, fname in (("pkg/alpha", "new_name", alpha_lines, "new.py"),
                                   ("pkg/beta", "beta_fn", beta_lines, "b.py")):
        d = tmp_path / rel
        d.mkdir(parents=True)
        (d / fname).write_text(_func_src(name, size), encoding="utf-8")
    bl = tmp_path / "baseline.yaml"
    bl.write_text(_BASELINE_TEXT, encoding="utf-8")
    return bl


@pytest.mark.unit
class TestAdviseCoordinates:
    """Координаты максимума справочные: расхождение — предупреждение, а не отказ."""

    STALE = {"max_function_lines": 100, "max_function": "f",
             "max_function_file": "a.py", "max_function_lineno": 7}
    FUNCS = [{"name": "f", "file": "a.py", "lineno": 10, "size": 100}]

    def test_stale_coordinates_warn(self):
        notes = advise(self.FUNCS, self.STALE)
        assert len(notes) == 1
        assert "координаты максимума устарели" in notes[0]
        assert "a.py:7" in notes[0] and "a.py:10" in notes[0]

    def test_stale_coordinates_do_not_fail(self):
        assert check(self.FUNCS, self.STALE) == []

    def test_matching_coordinates_are_silent(self):
        spec = dict(self.STALE, max_function_lineno=10)
        assert advise(self.FUNCS, spec) == []

    def test_tie_accepts_any_leader(self):
        """Две функции одного максимального размера — записанная любая из них не устарела."""
        funcs = [{"name": "a", "file": "a.py", "lineno": 1, "size": 100},
                 {"name": "b", "file": "b.py", "lineno": 5, "size": 100}]
        spec = {"max_function_lines": 100, "max_function": "b",
                "max_function_file": "b.py", "max_function_lineno": 5}
        assert advise(funcs, spec) == []

    def test_growth_is_error_not_advice(self):
        """Рост — ошибка check; advise его не дублирует."""
        funcs = [{"name": "g", "file": "a.py", "lineno": 1, "size": 150}]
        spec = {"max_function_lines": 100}
        assert advise(funcs, spec) == []
        assert len(check(funcs, spec)) == 1

    # Сверки «координаты настоящего baseline совпадают с фактом» здесь НАМЕРЕННО нет: она
    # краснела бы любой PR, сдвинувший строку выше максимума, — ровно тот шум, от которого #1128
    # уводит координаты в предупреждения. Их сводит `--baseline`.

    def test_advise_all_prefixes_scope(self, tmp_path):
        """advise_all называет scope, к которому относится предупреждение."""
        d = tmp_path / "pkg/alpha"
        d.mkdir(parents=True)
        (d / "m.py").write_text(_func_src("f", 10), encoding="utf-8")
        notes = advise_all({"scopes": [{"path": "pkg/alpha/", "max_function_lines": 20}]},
                           pkg_root=tmp_path)
        assert len(notes) == 1
        assert notes[0].startswith("[pkg/alpha/]")


@pytest.mark.unit
class TestRewriteScopeText:
    """Правка значения поля текстом: меняется значение, всё остальное — байт в байт."""

    def test_replaces_only_the_value(self):
        new = rewrite_scope_text(_BASELINE_TEXT, "pkg/alpha/", {"max_function_lines": 150})
        assert "    max_function_lines: 150   # хвостовой комментарий\n" in new
        assert new.replace("150   #", "200   #", 1) == _BASELINE_TEXT

    def test_touches_only_its_own_scope(self):
        new = rewrite_scope_text(_BASELINE_TEXT, "pkg/beta/", {"max_function_lines": 40})
        parsed = yaml.safe_load(new)
        assert parsed["scopes"][0]["max_function_lines"] == 200
        assert parsed["scopes"][1]["max_function_lines"] == 40

    def test_unknown_scope_is_refused(self):
        with pytest.raises(ValueError, match="найден в baseline 0"):
            rewrite_scope_text(_BASELINE_TEXT, "pkg/gamma/", {"max_function_lines": 1})

    def test_missing_field_is_refused(self):
        text = _BASELINE_TEXT.replace("    max_function_lineno: 999\n", "")
        with pytest.raises(ValueError, match="max_function_lineno встречается 0"):
            rewrite_scope_text(text, "pkg/alpha/", {"max_function_lineno": 5})

    def test_odd_name_is_quoted(self):
        new = rewrite_scope_text(_BASELINE_TEXT, "pkg/alpha/", {"max_function": "a: b #c"})
        assert yaml.safe_load(new)["scopes"][0]["max_function"] == "a: b #c"


@pytest.mark.unit
class TestRebaseline:
    """--baseline: опускает текстом, сохраняет комментарии, подъём — только с обоснованием."""

    def test_lowering_writes_new_numbers(self, tmp_path):
        bl = _make_repo(tmp_path, alpha_lines=120)
        code, _ = rebaseline(bl, pkg_root=tmp_path)
        assert code == 0
        spec = load_baseline(bl)["scopes"][0]
        assert spec["max_function_lines"] == 120
        coords = (spec["max_function"], spec["max_function_file"], spec["max_function_lineno"])
        assert coords == ("new_name", "new.py", 1)

    def test_comments_survive_byte_for_byte(self, tmp_path):
        """Side-effect proof: вне значений полей файл совпадает с прежним байт в байт."""
        bl = _make_repo(tmp_path, alpha_lines=120)
        assert rebaseline(bl, pkg_root=tmp_path)[0] == 0
        before = _BASELINE_TEXT.splitlines(keepends=True)
        after = bl.read_text(encoding="utf-8").splitlines(keepends=True)
        assert len(before) == len(after)
        changed = 0
        for old, new in zip(before, after):
            if old.lstrip().startswith(_FIELD_LINE):
                assert old.split(":", 1)[0] == new.split(":", 1)[0]
                old_tail = old[old.index("#"):] if "#" in old else ""
                new_tail = new[new.index("#"):] if "#" in new else ""
                assert old_tail == new_tail
                changed += old != new
            else:
                assert old == new
        assert changed == 4          # alpha: потолок + три координаты; beta не менялся

    def test_raise_without_reason_is_refused(self, tmp_path):
        """Fail-closed: подъём без --allow-raise — отказ, и файл не тронут НИ В ОДНОМ scope."""
        bl = _make_repo(tmp_path, alpha_lines=250, beta_lines=10)
        code, msgs = rebaseline(bl, pkg_root=tmp_path)
        assert code == 1
        assert any("200 -> 250" in m and "ПОДНЯЛСЯ" in m for m in msgs)
        assert bl.read_text(encoding="utf-8") == _BASELINE_TEXT

    def test_blank_reason_is_refused(self, tmp_path):
        bl = _make_repo(tmp_path, alpha_lines=250)
        code, _ = rebaseline(bl, pkg_root=tmp_path, allow_raise="   ")
        assert code == 1
        assert bl.read_text(encoding="utf-8") == _BASELINE_TEXT

    def test_raise_with_reason_is_recorded(self, tmp_path):
        bl = _make_repo(tmp_path, alpha_lines=250)
        code, _ = rebaseline(bl, pkg_root=tmp_path, allow_raise="разрез отдельной работой",
                             today="2026-09-28")
        assert code == 0
        data = load_baseline(bl)
        assert data["scopes"][0]["max_function_lines"] == 250
        assert data["raises"] == [{"at": "2026-09-28", "path": "pkg/alpha/", "from": 200,
                                   "to": 250, "why": "разрез отдельной работой"}]
        assert bl.read_text(encoding="utf-8").startswith(_BASELINE_TEXT.replace(
            "200   #", "250   #").replace("old_name", "new_name").replace(
            "old.py", "new.py").replace("999", "1"))

    def test_second_raise_appends_to_ledger(self, tmp_path):
        bl = _make_repo(tmp_path, alpha_lines=250)
        assert rebaseline(bl, pkg_root=tmp_path, allow_raise="первый", today="2026-09-01")[0] == 0
        (tmp_path / "pkg/alpha/new.py").write_text(_func_src("new_name", 260), encoding="utf-8")
        assert rebaseline(bl, pkg_root=tmp_path, allow_raise="второй", today="2026-09-02")[0] == 0
        raises = load_baseline(bl)["raises"]
        assert [(r["from"], r["to"], r["why"]) for r in raises] == [(200, 250, "первый"),
                                                                     (250, 260, "второй")]

    def test_crlf_line_endings_are_preserved(self, tmp_path):
        """CRLF-файл остаётся CRLF: правка чисел не переписывает концы строк."""
        bl = _make_repo(tmp_path, alpha_lines=120)
        crlf = _BASELINE_TEXT.replace("\n", "\r\n").encode("utf-8")
        bl.write_bytes(crlf)
        assert rebaseline(bl, pkg_root=tmp_path)[0] == 0
        after = bl.read_bytes()
        assert after.count(b"\r\n") == crlf.count(b"\r\n")
        assert b"\n" not in after.replace(b"\r\n", b"")
        assert load_baseline(bl)["scopes"][0]["max_function_lines"] == 120

    def test_missing_baseline_is_a_clean_refusal(self, tmp_path):
        """Нет файла — понятный отказ с кодом 1, а не трассировка; файл не создаётся."""
        bl = tmp_path / "nope.yaml"
        code, msgs = rebaseline(bl, pkg_root=tmp_path)
        assert code == 1
        assert "baseline-файла нет" in msgs[0]
        assert not bl.exists()

    def test_rerun_on_fact_is_a_noop(self, tmp_path):
        """Повторный прогон на неизменном коде не меняет ни байта."""
        bl = _make_repo(tmp_path, alpha_lines=120)
        rebaseline(bl, pkg_root=tmp_path)
        once = bl.read_text(encoding="utf-8")
        rebaseline(bl, pkg_root=tmp_path)
        assert bl.read_text(encoding="utf-8") == once


@pytest.mark.unit
class TestAllowRaiseArg:
    """Флаг --allow-raise: обоснование берётся из аргумента; флаг без него — пустая строка."""

    @pytest.mark.parametrize("argv, expected", [
        (["--baseline"], None),
        (["--baseline", "--allow-raise", "почему"], "почему"),
        (["--baseline", "--allow-raise=почему"], "почему"),
        (["--allow-raise", "--baseline"], ""),
        (["--baseline", "--allow-raise"], ""),
    ])
    def test_parses(self, argv, expected):
        from ai_ops_kit.validation.validate_func_size import _allow_raise_arg
        assert _allow_raise_arg(argv) == expected


@pytest.mark.unit
class TestAppendRaisesText:
    """Лента raises дописывается только в конец файла."""

    def test_ledger_in_the_middle_is_refused(self):
        text = "raises:\n  - at: '1'\nscopes: []\n"
        entry = {"at": "x", "path": "p/", "from": 1, "to": 2, "why": "w"}
        with pytest.raises(ValueError, match="не последний"):
            append_raises_text(text, [entry])


@pytest.mark.unit
class TestUnrecordedRaises:
    """Потолок не вырос относительно прежней версии baseline без записи в raises."""

    OLD = {"scopes": [{"path": "a/", "max_function_lines": 100}]}

    def test_raise_without_record_is_flagged(self):
        new = {"scopes": [{"path": "a/", "max_function_lines": 120}]}
        problems = unrecorded_raises(self.OLD, new)
        assert len(problems) == 1
        assert "100 -> 120" in problems[0]

    def test_recorded_raise_passes(self):
        new = {"scopes": [{"path": "a/", "max_function_lines": 120}],
               "raises": [{"path": "a/", "from": 100, "to": 120, "why": "осознанно"}]}
        assert unrecorded_raises(self.OLD, new) == []

    def test_record_without_why_does_not_count(self):
        new = {"scopes": [{"path": "a/", "max_function_lines": 120}],
               "raises": [{"path": "a/", "from": 100, "to": 120, "why": ""}]}
        assert len(unrecorded_raises(self.OLD, new)) == 1

    def test_lowering_and_new_scope_pass(self):
        new = {"scopes": [{"path": "a/", "max_function_lines": 90},
                          {"path": "b/", "max_function_lines": 500}]}
        assert unrecorded_raises(self.OLD, new) == []

    def test_real_baseline_did_not_grow_against_origin_main(self):
        """Контракт: ни один потолок настоящего baseline не вырос против origin/main без записи."""
        root = BASELINE_FILE.parents[1]
        rel = BASELINE_FILE.relative_to(root).as_posix()
        proc = subprocess.run(["git", "show", f"origin/main:{rel}"], cwd=root,
                              capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            pytest.skip("СВЕРКА ПОТОЛКОВ С origin/main ВЫКЛЮЧЕНА: ветки нет в клоне (нужен fetch "
                        f"origin/main, в CI — fetch-depth: 0): {proc.stderr.strip()[:120]}")
        old = yaml.safe_load(proc.stdout) or {}
        new = load_baseline(BASELINE_FILE)
        measured = {sc["path"]: max((f["size"] for f in measure_functions(sc["dir"])), default=0)
                    for sc in iter_scopes(new)}
        assert unrecorded_raises(old, new, measured) == []

    def test_chain_of_raises_counts_as_recorded(self):
        """Два --allow-raise подряд (4->11, 11->21) против origin/main (4) — подъём записан."""
        old = {"scopes": [{"path": "k/", "max_function_lines": 4}]}
        new = {"scopes": [{"path": "k/", "max_function_lines": 21}],
               "raises": [{"path": "k/", "from": 4, "to": 11, "why": "раз"},
                          {"path": "k/", "from": 11, "to": 21, "why": "два"}]}
        assert unrecorded_raises(old, new) == []

    def test_broken_chain_is_flagged(self):
        """Цепочка с дырой (4->11, 15->21) подъём 4->21 не покрывает."""
        old = {"scopes": [{"path": "k/", "max_function_lines": 4}]}
        new = {"scopes": [{"path": "k/", "max_function_lines": 21}],
               "raises": [{"path": "k/", "from": 4, "to": 11, "why": "раз"},
                          {"path": "k/", "from": 15, "to": 21, "why": "два"}]}
        assert len(unrecorded_raises(old, new)) == 1

    def test_two_step_rebaseline_passes_the_contract(self, tmp_path):
        """Сквозь настоящий rebaseline: два подъёма подряд не дают ложно-красной сверки."""
        bl = _make_repo(tmp_path, alpha_lines=250)
        old = load_baseline(bl)
        assert rebaseline(bl, pkg_root=tmp_path, allow_raise="раз", today="2026-09-01")[0] == 0
        (tmp_path / "pkg/alpha/new.py").write_text(_func_src("new_name", 260), encoding="utf-8")
        assert rebaseline(bl, pkg_root=tmp_path, allow_raise="два", today="2026-09-02")[0] == 0
        assert unrecorded_raises(old, load_baseline(bl)) == []

    @pytest.mark.parametrize("renamed", ["ai_ops_kit/kernel", "./ai_ops_kit/kernel/",
                                         "ai_ops_kit//kernel/"])
    def test_renamed_path_does_not_hide_a_raise(self, renamed):
        """Переименование `kernel/` -> `kernel` не делает каталог «новым»: подъём 4->51 пойман."""
        old = {"scopes": [{"path": "ai_ops_kit/kernel/", "max_function_lines": 4}]}
        new = {"scopes": [{"path": renamed, "max_function_lines": 51}]}
        problems = unrecorded_raises(old, new)
        assert len(problems) == 1
        assert "4 -> 51" in problems[0]

    def test_new_scope_above_fact_is_flagged(self):
        """Новый каталог заводится ПО ФАКТУ: потолок выше текущего максимума — нарушение."""
        new = {"scopes": [{"path": "b/", "max_function_lines": 500}]}
        problems = unrecorded_raises({"scopes": []}, new, measured={"b/": 30})
        assert len(problems) == 1
        assert "новый каталог" in problems[0]

    def test_new_scope_at_fact_passes(self):
        new = {"scopes": [{"path": "b/", "max_function_lines": 30}]}
        assert unrecorded_raises({"scopes": []}, new, measured={"b": 30}) == []
