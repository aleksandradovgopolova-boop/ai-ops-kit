# -*- coding: utf-8 -*-
"""Метрика и ратчет: поведенческие vs структурные тесты (validate_test_taxonomy).

Три обязательных теста на capability (AGENTS.md):
  * positive     — валидатор на РЕПОЗИТОРИИ печатает OK и выходит 0; классификатор верно относит
                   поведенческий фикстур-файл к behavioral, структурный — к structural;
  * fail-closed  — доля поведенческих, упавшая ниже baseline (поведенческий тест превращён в
                   структурный ИЛИ добавлены структурные сверх порога), ОТКЛОНЯЕТСЯ ратчетом;
  * side-effect  — baseline читается из реестра `packages/test-taxonomy-baseline.yaml`, а не вписан
                   числом: значение сверяется с самим замером кита.

Проба покраснения (требование issue #439): строится крохотное дерево тестов с одним «как бы
поведенческим» и одним структурным файлом, доля опускается ниже baseline — и ратчет это ловит.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ai_ops_kit.validation.validate_test_taxonomy import (
    BASELINE_FILE,
    check,
    classify_file,
    load_baseline,
    main,
    measure,
    measure_functions,
    render_function_advisory,
)

pytestmark = pytest.mark.unit


# Фикстуры-исходники: «поведенческий» импортирует продукт И зовёт его; «структурный» только читает
# файл по пути и утверждает на его содержимом. `import ai_ops_kit` распознаётся без опоры на
# пофайловое обнаружение шима — фикстура самодостаточна.
BEHAVIORAL_SRC = textwrap.dedent("""\
    import ai_ops_kit
    from ai_ops_kit.validation import validate_test_taxonomy as vtt

    def test_calls_product():
        result = vtt.measure()
        assert result["total_count"] >= 0
""")

STRUCTURAL_SRC = textwrap.dedent("""\
    from pathlib import Path

    def test_reads_a_file():
        text = Path("registry/agents.yaml").read_text(encoding="utf-8")
        assert "agents" in text
""")


def _make_tree(root: Path, behavioral: int, structural: int) -> Path:
    """Собрать дерево tests/ из N поведенческих и M структурных файлов. -> путь дерева."""
    tests = root / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    for i in range(behavioral):
        (tests / f"test_beh_{i}.py").write_text(BEHAVIORAL_SRC, encoding="utf-8")
    for i in range(structural):
        (tests / f"test_str_{i}.py").write_text(STRUCTURAL_SRC, encoding="utf-8")
    return tests


# ─── positive: классификатор различает поведение и чтение ───────────────────────────────────────

class TestClassifierSeparatesBehaviorFromReading:
    def test_behavioral_file_is_behavioral(self, tmp_path):
        f = tmp_path / "test_beh.py"
        f.write_text(BEHAVIORAL_SRC, encoding="utf-8")
        assert classify_file(f) == "behavioral"

    def test_structural_file_is_structural(self, tmp_path):
        f = tmp_path / "test_str.py"
        f.write_text(STRUCTURAL_SRC, encoding="utf-8")
        assert classify_file(f) == "structural"

    def test_import_without_call_is_structural(self, tmp_path):
        """Импорт продукта БЕЗ вызова (только `callable(x)`/`x is not None`) — не поведение.

        Ровно класс `test_*_callable` из репозитория: символ импортирован, но не исполнен —
        проверяется поверхность модуля, а не его работа. Консервативно — это структурный тест."""
        f = tmp_path / "test_callable_only.py"
        f.write_text(textwrap.dedent("""\
            from ai_ops_kit.validation.validate_test_taxonomy import measure

            def test_measure_is_callable():
                assert callable(measure)
        """), encoding="utf-8")
        assert classify_file(f) == "structural"


# ─── positive: валидатор на РЕПОЗИТОРИИ зелёный ──────────────────────────────────────────────────

class TestValidatorOnTheRepoIsGreen:
    def test_main_exits_zero(self, capsys):
        rc = main([])
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "TEST-TAXONOMY-OK" in out, out

    def test_current_share_meets_baseline(self):
        """Замер кита не ниже baseline — иначе ратчет был бы красным на самом ките."""
        assert check(measure(), load_baseline()) == []


# ─── side-effect proof: baseline живёт в реестре, а не в assert ─────────────────────────────────

class TestTheBaselineHasOneHome:
    def test_baseline_file_exists_with_numbers(self):
        b = load_baseline()
        assert isinstance(b.get("behavioral_count"), int), b
        assert isinstance(b.get("total_count"), int) and b["total_count"] > 0, b

    def test_baseline_matches_the_measurement(self):
        """Числа в реестре обязаны совпасть с фактическим замером кита: иначе baseline устарел молча
        и защищает не ту границу."""
        b = load_baseline()
        cur = measure()
        assert b["behavioral_count"] == cur["behavioral_count"], (
            f"baseline behavioral {b['behavioral_count']} != замер {cur['behavioral_count']} — "
            f"пересчитайте: validate_test_taxonomy.py --baseline")
        assert b["total_count"] == cur["total_count"], (
            f"baseline total {b['total_count']} != замер {cur['total_count']}")


# ─── fail-closed: падение доли ниже baseline ОТКЛОНЯЕТСЯ ────────────────────────────────────────

class TestARaiseInStructuralityIsRefused:
    def test_share_drop_reddens(self, tmp_path):
        """ПРОБА ПОКРАСНЕНИЯ (issue #439): дерево с долей ниже baseline — ратчет краснеет.

        Baseline: 2 поведенческих из 2 (100%). Замер: 1 поведенческий + 1 структурный (50%).
        Доля упала — check обязан вернуть ошибку."""
        tree = _make_tree(tmp_path, behavioral=1, structural=1)
        cur = measure(tree)
        assert cur["behavioral_count"] == 1 and cur["structural_count"] == 1, cur
        baseline = {"behavioral_count": 2, "total_count": 2}
        errors = check(cur, baseline)
        assert errors, "падение доли поведенческих ниже baseline не покраснело"
        assert "упала ниже baseline" in errors[0], errors

    def test_behavioral_turned_structural_is_caught(self, tmp_path):
        """Именно дефект из issue: поведенческий тест превратили в структурный.

        Стартуем с дерева 2/2, снимаем baseline. Затем ОДИН файл превращаем в структурный (убираем
        вызов продукта) — доля падает с 100% до 50%, и ратчет ловит превращение."""
        tree = _make_tree(tmp_path, behavioral=2, structural=0)
        before = measure(tree)
        assert before["behavioral_count"] == 2, before
        baseline = {"behavioral_count": before["behavioral_count"],
                    "total_count": before["total_count"]}
        # регрессия: один поведенческий переписан как структурный
        (tree / "test_beh_1.py").write_text(STRUCTURAL_SRC, encoding="utf-8")
        after = measure(tree)
        assert after["behavioral_count"] == 1, after
        assert check(after, baseline), "превращение поведенческого в структурный не покраснело"

    def test_share_at_baseline_is_green(self, tmp_path):
        """Ратчет — ПОЛ, а не точное равенство: доля на уровне baseline (или выше) проходит."""
        tree = _make_tree(tmp_path, behavioral=2, structural=1)  # 66.7%
        cur = measure(tree)
        assert check(cur, {"behavioral_count": 1, "total_count": 2}) == []  # baseline 50%

    def test_adding_structural_files_can_breach(self, tmp_path):
        """Добавление структурных сверх порога тоже ловится — доля размывается вниз."""
        tree = _make_tree(tmp_path, behavioral=2, structural=3)  # 40%
        cur = measure(tree)
        assert check(cur, {"behavioral_count": 1, "total_count": 2}), cur  # baseline 50% -> breach

    def test_missing_baseline_numbers_are_refused(self):
        """Baseline без чисел — не порог: проверка обязана краснеть, а не молча пропускать."""
        assert check({"behavioral_count": 1, "total_count": 1,
                      "behavioral_share_pct": 100.0}, {})


# ─── advisory: функциональный счётчик виден, но НЕ энфорсится ────────────────────────────────────

# «Разбавленный» файл: поведенческий на уровне ФАЙЛА (импортирует и зовёт продукт), но одна из его
# тест-функций только читает файл — структурная. Файловая метрика этого не видит (файл = 1 единица,
# целиком behavioral); функциональный счётчик — видит (1 из 2 = 50%).
DILUTED_SRC = textwrap.dedent("""\
    from pathlib import Path

    from ai_ops_kit.validation import validate_test_taxonomy as vtt

    def test_calls_product():
        assert vtt.measure()["total_count"] >= 0

    def test_only_reads_a_file():
        assert Path("registry/agents.yaml").exists()
""")


class TestFunctionLevelAdvisoryIsVisibleButNotEnforced:
    def test_function_counter_sees_dilution_a_file_counter_misses(self, tmp_path):
        """Ядро P2: структурная тест-функция внутри поведенческого файла видна ФУНКЦИОНАЛЬНО.

        Файл целиком поведенческий (файловая доля 1/1 = 100%), но функциональный счётчик разбивает
        его на 1 поведенческую + 1 структурную функцию (50%) — именно «разбавление» и становится
        видимым."""
        tests = tmp_path / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        (tests / "test_diluted.py").write_text(DILUTED_SRC, encoding="utf-8")

        file_metric = measure(tests)
        assert file_metric["behavioral_count"] == 1 and file_metric["structural_count"] == 0

        fn_metric = measure_functions(tests)
        assert fn_metric["behavioral_fn_count"] == 1, fn_metric
        assert fn_metric["structural_fn_count"] == 1, fn_metric
        assert fn_metric["total_fn_count"] == 2, fn_metric
        assert fn_metric["behavioral_fn_share_pct"] == 50.0, fn_metric

    def test_function_counter_does_not_change_the_enforced_verdict(self, capsys):
        """Advisory-строка печатается, но энфорсимый вердикт и exit code — прежние.

        Гарантия жёсткой границы P2: функциональный счётчик ничего не краснит и не зеленит; он лишь
        добавляет строку вывода поверх неизменной файловой метрики."""
        rc = main([])
        out = capsys.readouterr().out
        assert rc == 0, out
        # энфорсимая метрика на месте и без изменений
        assert "TEST-TAXONOMY-OK" in out, out
        # advisory присутствует и честно помечена как не-энфорсимая
        assert "TEST-TAXONOMY-ADVISORY" in out, out
        assert "advisory, не энфорсится" in out, out

    def test_advisory_render_is_pure_and_marks_itself_advisory(self):
        """render_function_advisory — чистая печать над замером, помеченная advisory."""
        line = render_function_advisory(
            {"behavioral_fn_count": 3, "structural_fn_count": 1,
             "total_fn_count": 4, "behavioral_fn_share_pct": 75.0})
        assert "3/4" in line and "75.0%" in line
        assert "advisory, не энфорсится" in line

    def test_function_counter_never_feeds_check(self, tmp_path):
        """Ратчет `check` работает только на файловой метрике — функциональные числа его не касаются."""
        tests = tmp_path / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        (tests / "test_diluted.py").write_text(DILUTED_SRC, encoding="utf-8")
        file_metric = measure(tests)
        # baseline из файловой метрики: тот же замер проходит (пол, не потолок)
        assert check(file_metric, {"behavioral_count": file_metric["behavioral_count"],
                                   "total_count": file_metric["total_count"]}) == []


# ─── реестр совпадает с местом, где лежит baseline ──────────────────────────────────────────────

def test_baseline_file_is_where_the_validator_looks():
    assert BASELINE_FILE.name == "test-taxonomy-baseline.yaml"
    assert BASELINE_FILE.parent.name == "packages"
