"""Тесты стоячего ратчета молчаливых глушителей (validate_swallowed_exceptions).

Фиксируют: AST-детект считает `except ...: pass` (а не слово pass в комментарии/строке), tests/
исключены, baseline читается из реестра, ратчет краснеет при РОСТЕ и молчит при снижении, а на самом
ките он зелёный и baseline == факт.

Три обязательных теста на capability (AGENTS.md):
  * positive     — валидатор на РЕПОЗИТОРИИ печатает OK и выходит 0; baseline совпадает с замером;
  * fail-closed  — новый `except: pass` сверх baseline ОТКЛОНЯЕТСЯ (проба покраснения);
  * side-effect  — линия читается из packages/swallowed-exceptions-baseline.yaml, а не из assert.

Модуль проверки загружается ПОВЕДЕНЧЕСКИ (spec_from_file_location), а не импортом через sys.path:
это исключает зависимость от editable-установки и не пачкает корень worktree.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PKG = Path(__file__).resolve().parents[2]
_VALIDATOR = PKG / "ai_ops_kit" / "validation" / "validate_swallowed_exceptions.py"


def _load():
    """Загрузить модуль проверки из файла (без импорта через пакет/sys.path)."""
    spec = importlib.util.spec_from_file_location("validate_swallowed_exceptions_under_test",
                                                  _VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = _load()


def _make_pkg(tmp_path: Path, files: dict[str, str]) -> Path:
    """Собрать искусственный pkg_root: ai_ops_kit/<rel> с заданным исходником. -> pkg_root."""
    for rel, src in files.items():
        f = tmp_path / "ai_ops_kit" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(src, encoding="utf-8")
    return tmp_path


_SWALLOW = "try:\n    x = 1\nexcept Exception:\n    pass\n"
_HANDLED = "try:\n    x = 1\nexcept Exception:\n    x = 0\n"


# ─── measure_swallowers: AST-счёт, не регэксп ────────────────────────────────────────────────────

class TestMeasure:
    def test_counts_bare_and_typed_swallowers(self, tmp_path):
        src = ("try:\n    a()\nexcept ValueError:\n    pass\n"
               "try:\n    b()\nexcept:\n    pass\n")
        pkg = _make_pkg(tmp_path, {"m.py": src})
        assert V.total_of(V.measure_swallowers(pkg)) == 2

    def test_handled_except_is_not_a_swallower(self, tmp_path):
        pkg = _make_pkg(tmp_path, {"m.py": _HANDLED})
        assert V.total_of(V.measure_swallowers(pkg)) == 0

    def test_pass_in_comment_or_string_is_not_counted(self, tmp_path):
        """AST, а не регэксп: `pass` в комментарии/строке — не глушитель."""
        src = ('# except Exception: pass  тут просто текст\n'
               's = "except Exception: pass"\n'
               'def f():\n    pass\n')  # обычный pass в теле функции — тоже не глушитель
        pkg = _make_pkg(tmp_path, {"m.py": src})
        assert V.total_of(V.measure_swallowers(pkg)) == 0

    def test_except_with_body_beyond_pass_is_not_counted(self, tmp_path):
        """Тело должно быть РОВНО один pass: логирование перед pass — уже не молчаливо."""
        src = "try:\n    a()\nexcept Exception:\n    log()\n    pass\n"
        pkg = _make_pkg(tmp_path, {"m.py": src})
        assert V.total_of(V.measure_swallowers(pkg)) == 0

    def test_tests_are_excluded(self, tmp_path):
        """Пробы (test_*.py / внутри tests/) нарочно гасят ошибку — сторож их не считает."""
        pkg = _make_pkg(tmp_path, {"live.py": _SWALLOW,
                                   "test_probe.py": _SWALLOW,
                                   "tests/helper.py": _SWALLOW})
        assert V.total_of(V.measure_swallowers(pkg)) == 1


# ─── check: ратчет ───────────────────────────────────────────────────────────────────────────────

class TestCheck:
    def test_at_baseline_is_ok(self):
        assert V.check(57, {"baseline": 57}) == []

    def test_below_baseline_is_ok(self):
        """Снижение НЕ краснит прогон (усыхать можно свободно)."""
        assert V.check(40, {"baseline": 57}) == []

    def test_growth_reddens(self):
        errors = V.check(58, {"baseline": 57})
        assert len(errors) == 1
        assert "58" in errors[0] and "57" in errors[0]

    def test_missing_baseline_number_is_error(self):
        errors = V.check(57, {})
        assert errors and "не зафиксирована" in errors[0]

    def test_non_int_baseline_is_error(self):
        errors = V.check(57, {"baseline": "много"})
        assert errors and "не зафиксирована" in errors[0]


# ─── positive: валидатор на РЕПОЗИТОРИИ зелёный, baseline == факт ────────────────────────────────

class TestValidatorOnTheRepoIsGreen:
    def test_main_exits_zero_and_prints_ok(self, capsys):
        rc = V.main([])
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "SWALLOWED-EXCEPTIONS-OK" in out, out

    def test_baseline_matches_current_measurement(self):
        """Линия в baseline == фактическому числу глушителей; иначе устарела молча."""
        baseline = V.load_baseline(V.BASELINE_FILE)
        current = V.total_of(V.measure_swallowers())
        assert V.baseline_count(baseline) == current, (
            f"baseline {V.baseline_count(baseline)} != замер {current} — "
            f"пере-снимите: validate_swallowed_exceptions.py --baseline")


# ─── side-effect proof: линия живёт в реестре, а не в assert ─────────────────────────────────────

class TestTheBaselineHasOneHome:
    def test_baseline_file_is_where_the_validator_looks(self):
        assert V.BASELINE_FILE.name == "swallowed-exceptions-baseline.yaml"
        assert V.BASELINE_FILE.parent.name == "packages"

    def test_baseline_declares_an_integer_line(self):
        baseline = V.load_baseline(V.BASELINE_FILE)
        assert isinstance(V.baseline_count(baseline), int)


# ─── fail-closed: ПРОБА ПОКРАСНЕНИЯ на искусственном дереве ──────────────────────────────────────

class TestAGrowingSwallowerIsRefused:
    def test_new_swallower_over_baseline_is_flagged(self, tmp_path):
        """ПРОБА ПОКРАСНЕНИЯ: в живом коде появился новый `except: pass` сверх линии — валидатор ловит.

        baseline фиксирует линию на 1 глушителе; в дереве их 2 — рост обязан краснеть."""
        pkg = _make_pkg(tmp_path, {"a.py": _SWALLOW, "b.py": _SWALLOW})
        total = V.total_of(V.measure_swallowers(pkg))
        assert total == 2
        errors = V.check(total, {"baseline": 1})
        assert errors, "рост числа глушителей сверх линии не покраснел"
        assert "молчаливых глушителей стало 2" in errors[0]

    def test_report_lists_files_with_swallowers(self, tmp_path):
        pkg = _make_pkg(tmp_path, {"a.py": _SWALLOW, "clean.py": _HANDLED})
        report = V.render_report(V.measure_swallowers(pkg))
        assert "ai_ops_kit/a.py" in report
        assert "ai_ops_kit/clean.py" not in report
