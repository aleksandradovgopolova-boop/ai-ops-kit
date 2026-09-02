"""Тесты ратчета размера МОДУЛЯ (validate_module_size).

Фиксируют: обход считает строки файла, baseline загружается, ратчет краснеет при росте сверх
потолка И при появлении нового монолита без записи, а на самом ките он зелёный и baseline == факт.

Три обязательных теста на capability (AGENTS.md):
  * positive     — валидатор на РЕПОЗИТОРИИ печатает OK и выходит 0; baseline совпадает с замером;
  * fail-closed  — файл сверх потолка ИЛИ новый файл ≥ порога без записи ОТКЛОНЯЕТСЯ (проба покраснения);
  * side-effect  — потолки читаются из реестра packages/module-size-baseline.yaml, а не из assert.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_ops_kit.validation.validate_module_size import (
    BASELINE_FILE,
    THRESHOLD,
    ceilings_of,
    check,
    load_baseline,
    main,
    measure_modules,
    over_threshold,
    render_report,
)

pytestmark = pytest.mark.unit


def _make_pkg(tmp_path: Path, files: dict[str, int]) -> Path:
    """Собрать искусственный pkg_root: ai_ops_kit/<rel> с нужным числом строк каждый. -> pkg_root."""
    for rel, n in files.items():
        f = tmp_path / "ai_ops_kit" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(f"x = {i}" for i in range(n)) + "\n", encoding="utf-8")
    return tmp_path


# ─── measure_modules: подсчёт строк ─────────────────────────────────────────────────────────────

class TestMeasureModules:
    def test_counts_lines_of_each_file(self, tmp_path):
        pkg = _make_pkg(tmp_path, {"a.py": 10, "sub/b.py": 25})
        by_path = {m["path"]: m["lines"] for m in measure_modules(pkg)}
        assert by_path["ai_ops_kit/a.py"] == 10
        assert by_path["ai_ops_kit/sub/b.py"] == 25

    def test_path_is_relative_to_pkg_root(self, tmp_path):
        """Путь в замере — относительный posix, чтобы baseline не зависел от места дерева."""
        pkg = _make_pkg(tmp_path, {"cli/x.py": 5})
        assert measure_modules(pkg)[0]["path"] == "ai_ops_kit/cli/x.py"

    def test_line_count_independent_of_trailing_newline(self, tmp_path):
        """splitlines(): файл с финальным \\n и без него на одну строку не расходятся."""
        f = tmp_path / "ai_ops_kit" / "m.py"
        f.parent.mkdir(parents=True)
        f.write_text("a\nb\nc", encoding="utf-8")  # без финального перевода строки
        assert measure_modules(tmp_path)[0]["lines"] == 3


# ─── over_threshold: отбор и сортировка ─────────────────────────────────────────────────────────

class TestOverThreshold:
    def test_selects_at_or_above_threshold(self):
        mods = [{"path": "a", "lines": THRESHOLD - 1}, {"path": "b", "lines": THRESHOLD},
                {"path": "c", "lines": THRESHOLD + 100}]
        paths = [m["path"] for m in over_threshold(mods)]
        assert paths == ["c", "b"]  # порог включительно, по убыванию; ниже порога отброшен

    def test_below_threshold_is_unconstrained(self):
        mods = [{"path": "small", "lines": 100}]
        assert over_threshold(mods) == []


# ─── check: ратчет ──────────────────────────────────────────────────────────────────────────────

class TestCheck:
    def test_passes_when_at_ceiling(self):
        mods = [{"path": "ai_ops_kit/big.py", "lines": 900}]
        baseline = {"ceilings": {"ai_ops_kit/big.py": 900}}
        assert check(mods, baseline) == []

    def test_shrinking_is_allowed(self):
        """Файл усох ниже потолка — ратчет НЕ краснеет (потолок держит рост, не размер)."""
        mods = [{"path": "ai_ops_kit/big.py", "lines": 800}]
        baseline = {"ceilings": {"ai_ops_kit/big.py": 900}}
        assert check(mods, baseline) == []

    def test_growth_past_ceiling_reddens(self):
        mods = [{"path": "ai_ops_kit/big.py", "lines": 950}]
        baseline = {"ceilings": {"ai_ops_kit/big.py": 900}}
        errors = check(mods, baseline)
        assert len(errors) == 1
        assert "превышает потолок" in errors[0]
        assert "ai_ops_kit/big.py" in errors[0]

    def test_new_monolith_without_baseline_entry_reddens(self):
        """Файл ≥ порога, которого нет в baseline — новый монолит, обязан краснеть."""
        mods = [{"path": "ai_ops_kit/newbig.py", "lines": THRESHOLD + 5}]
        baseline = {"ceilings": {}}
        errors = check(mods, baseline)
        assert len(errors) == 1
        assert "НЕ в baseline" in errors[0]
        assert "ai_ops_kit/newbig.py" in errors[0]

    def test_missing_ceilings_section_is_error_only_when_something_is_big(self):
        mods = [{"path": "ai_ops_kit/big.py", "lines": THRESHOLD}]
        errors = check(mods, {})
        assert errors and "нет секции ceilings" in errors[0]

    def test_no_big_files_no_baseline_is_fine(self):
        """Ни один файл не достиг порога — стеречь нечего, пустой baseline не криминал."""
        assert check([{"path": "ai_ops_kit/tiny.py", "lines": 10}], {}) == []

    def test_non_int_ceiling_is_refused(self):
        mods = [{"path": "ai_ops_kit/big.py", "lines": 900}]
        baseline = {"ceilings": {"ai_ops_kit/big.py": "много"}}
        errors = check(mods, baseline)
        assert errors and "не число" in errors[0]


# ─── render_report ──────────────────────────────────────────────────────────────────────────────

class TestRenderReport:
    def test_lists_over_threshold_files(self):
        mods = [{"path": "ai_ops_kit/big.py", "lines": 900},
                {"path": "ai_ops_kit/small.py", "lines": 100}]
        report = render_report(mods)
        assert "ai_ops_kit/big.py" in report
        assert "ai_ops_kit/small.py" not in report


# ─── positive: валидатор на РЕПОЗИТОРИИ зелёный, baseline == факт ────────────────────────────────

class TestValidatorOnTheRepoIsGreen:
    def test_main_exits_zero_and_prints_ok(self, capsys):
        rc = main([])
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "MODULE-SIZE-OK" in out, out

    def test_baseline_matches_current_measurement(self):
        """Каждый файл сверх порога записан в baseline с потолком == текущему размеру.

        Иначе baseline устарел молча и защищает не ту границу — как контракт func-size."""
        baseline = load_baseline(BASELINE_FILE)
        ceilings = ceilings_of(baseline)
        current = {m["path"]: m["lines"] for m in over_threshold(measure_modules())}
        assert set(ceilings) == set(current), (
            f"состав файлов сверх порога разошёлся с baseline: "
            f"только в замере {set(current) - set(ceilings)}, "
            f"только в baseline {set(ceilings) - set(current)} — "
            f"пере-снимите: validate_module_size.py --baseline")
        for path, lines in current.items():
            assert ceilings[path] == lines, (
                f"{path}: потолок {ceilings[path]} != замер {lines} — "
                f"пере-снимите baseline: validate_module_size.py --baseline")


# ─── side-effect proof: потолки живут в реестре, а не в assert ──────────────────────────────────

class TestTheBaselineHasOneHome:
    def test_baseline_file_is_where_the_validator_looks(self):
        assert BASELINE_FILE.name == "module-size-baseline.yaml"
        assert BASELINE_FILE.parent.name == "packages"

    def test_baseline_declares_ceilings_with_numbers(self):
        baseline = load_baseline(BASELINE_FILE)
        ceilings = ceilings_of(baseline)
        assert ceilings, "baseline не объявляет ни одного потолка"
        assert all(isinstance(v, int) for v in ceilings.values()), ceilings


# ─── fail-closed: ПРОБА ПОКРАСНЕНИЯ на искусственном дереве ──────────────────────────────────────

class TestAGrowingMonolithIsRefused:
    def test_file_over_its_ceiling_is_flagged(self, tmp_path):
        """ПРОБА ПОКРАСНЕНИЯ: файл вырос сверх замороженного потолка — валидатор ловит.

        baseline фиксирует big.py на THRESHOLD строк; в дереве он на THRESHOLD+50 — рост обязан
        краснеть."""
        pkg = _make_pkg(tmp_path, {"big.py": THRESHOLD + 50})
        baseline = {"ceilings": {"ai_ops_kit/big.py": THRESHOLD}}
        errors = check(measure_modules(pkg), baseline)
        assert errors, "рост монолита сверх потолка не покраснел"
        assert "превышает потолок" in errors[0]

    def test_new_over_threshold_file_lacking_entry_is_flagged(self, tmp_path):
        """ПРОБА ПОКРАСНЕНИЯ (вторая форма): новый файл ≥ порога без записи в baseline — ловится."""
        pkg = _make_pkg(tmp_path, {"listed.py": THRESHOLD, "sneaked.py": THRESHOLD + 1})
        baseline = {"ceilings": {"ai_ops_kit/listed.py": THRESHOLD}}
        errors = check(measure_modules(pkg), baseline)
        assert errors, "новый монолит без записи не покраснел"
        assert any("НЕ в baseline" in e and "sneaked.py" in e for e in errors), errors

    def test_shrunk_file_stays_green(self, tmp_path):
        """Файл усох ниже потолка — зелено (усыхать можно свободно, ратчет не ложно-краснит)."""
        pkg = _make_pkg(tmp_path, {"big.py": THRESHOLD})
        baseline = {"ceilings": {"ai_ops_kit/big.py": THRESHOLD + 300}}
        assert check(measure_modules(pkg), baseline) == []
