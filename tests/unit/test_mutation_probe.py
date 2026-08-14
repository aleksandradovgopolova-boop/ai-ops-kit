"""Мутационные пробы: контур ловит класс «объявлено — не исполняется» (2026-08-14).

ПОВОД — ЗАМЕР, а не дисциплина ради дисциплины. PR #118 прошёл пять кругов свежего ревью: 36
находок, шесть уровня HIGH, и НИ ОДНУ не поймали 11 обязательных джоб CI. Восемь правок того дня
были «покрыты тестами» и не проверялись ничем — снятие проверки оставляло тесты зелёными. Правило
«мутируй исправление» жило в `rules/core/field-lessons.yaml` как ПРОЗА и исполнялось ровно настолько,
насколько исполнитель о нём помнил.

Три обязательных теста на capability:
  * positive     — реестр проб кита прогоняется, и КАЖДЫЙ мутант умирает (это и есть контур);
  * fail-closed  — выживший мутант, красная база, неоднозначный и отсутствующий образец: каждый
                   исход называется, и ни один не выдаётся за успех;
  * side-effect  — прогон НЕ портит дерево, которое проверяет (мутация живёт только в копии).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.devtools import mutation_probe as mp
from ai_ops_kit.validation import validate_mutation_probes as vmp

PKG_ROOT = Path(__file__).resolve().parents[2]

GUARDED = '''def keep(value):
    if value is None:
        return "отказ"
    return "ок"
'''
TEST_SRC = '''from guarded import keep

def test_none_is_refused():
    assert keep(None) == "отказ"
'''


def _mini_repo(tmp_path, guard_body=GUARDED, test_body=TEST_SRC):
    """Крошечное дерево с одной охраной и одним тестом — прогон проб на нём быстрый и настоящий."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "VERSION").write_text("0.0.1\n", encoding="utf-8")
    (tmp_path / "guarded.py").write_text(guard_body, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_guarded.py").write_text(test_body, encoding="utf-8")
    return tmp_path


def _probes(tmp_path, **over):
    probe = {"id": "guard-refuses-none", "file": "guarded.py",
             "find": "    if value is None:", "replace_with": "    if False:",
             "tests": ["tests/test_guarded.py"], "why": "охрана отказа — смысл функции"}
    probe.update(over)
    (tmp_path / "quality").mkdir(exist_ok=True)
    (tmp_path / "quality" / "mutation-probes.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "kind": "mutation-probes", "probes": [probe]},
                       allow_unicode=True, sort_keys=False), encoding="utf-8")
    return tmp_path


# ─── positive ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.slow
def test_every_declared_probe_of_the_kit_kills_its_mutant():
    """ГЛАВНЫЙ тест этой работы: охрана каждого механизма кита действительно чем-то проверяется.

    Это не про аккуратность автора: выживший мутант означает, что механизм держится на честном слове
    и его можно молча снести, оставив контур зелёным. Ровно тот класс, который 11 джоб CI не видят.
    """
    rep = mp.run(PKG_ROOT)

    assert rep["checked"] > 0, "реестр проб пуст — контур ничего не охраняет"
    assert rep["survived"] == [], (
        f"мутанты ВЫЖИЛИ (охрана не проверяется ничем): {rep['survived']}")
    assert rep["not_verified"] == [], (
        f"пробы не проверены — неизвестность не считается успехом: {rep['not_verified']}")


def test_a_killed_mutant_is_reported_as_killed(tmp_path):
    """Механизм отличает убитого мутанта от выжившего на настоящем прогоне, а не по обещанию."""
    root = _probes(_mini_repo(tmp_path))

    rep = mp.run(root, python=sys.executable)

    assert [p["outcome"] for p in rep["probes"]] == ["killed"], rep["probes"]
    assert rep["survived"] == [] and rep["not_verified"] == []


# ─── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_a_surviving_mutant_is_named_not_swallowed(tmp_path):
    """Тест, не проверяющий охрану, ловится: мутант выжил -> это ДЕФЕКТ, а не «всё зелено».

    Здесь тест проверяет ровно то, что мутация не меняет («ок» при непустом значении), — так и
    выглядят восемь правок дня, которые «были покрыты тестами».
    """
    weak_test = 'from guarded import keep\n\ndef test_ok_path():\n    assert keep(1) == "ок"\n'
    root = _probes(_mini_repo(tmp_path, test_body=weak_test))

    rep = mp.run(root, python=sys.executable)

    assert rep["survived"] == ["guard-refuses-none"], rep["probes"]
    assert "не проверяется" in rep["probes"][0]["reason"]


def test_a_red_baseline_is_not_a_killed_mutant(tmp_path):
    """Красная база — «не проверено», а не «мутант убит»: тест падал бы и без мутации.

    Без этого различения механизм давал бы самый вредный вид зелёного: чем хуже тесты, тем «лучше»
    результат проб. Тот же инвариант, что `unavailable != 0`.
    """
    broken = 'from guarded import keep\n\ndef test_broken():\n    assert keep(1) == "не то"\n'
    root = _probes(_mini_repo(tmp_path, test_body=broken))

    rep = mp.run(root, python=sys.executable)

    assert rep["not_verified"] == ["guard-refuses-none"], rep["probes"]
    assert "базовый прогон КРАСНЫЙ" in rep["probes"][0]["reason"]


def test_an_ambiguous_or_missing_pattern_is_not_verified(tmp_path):
    """Образец, встречающийся дважды или ноль раз, — неоднозначная мутация, а не успех."""
    twice = GUARDED + '\ndef also(value):\n    if value is None:\n        return "отказ"\n'
    root = _probes(_mini_repo(tmp_path, guard_body=twice))
    rep = mp.run(root, python=sys.executable)
    assert rep["not_verified"] == ["guard-refuses-none"]
    assert "встречается 2" in rep["probes"][0]["reason"]

    gone = _probes(_mini_repo(tmp_path / "b", guard_body='def keep(v):\n    return "ок"\n'))
    rep2 = mp.run(gone, python=sys.executable)
    assert rep2["not_verified"] == ["guard-refuses-none"], rep2["probes"]


def test_the_registry_catches_a_pattern_that_drifted_from_the_code():
    """Быстрая половина контура: реестр не может молча отстать от кода.

    Проба, чей образец больше не встречается, ничего не проверяет — и это ровно тот способ, которым
    механизм проверок умирает незаметно. Валидатор обязан назвать это ошибкой.
    """
    drifted = {"schema_version": 1, "kind": "mutation-probes", "probes": [
        {"id": "p", "file": "VERSION", "find": "такой строки в файле нет",
         "replace_with": "x", "tests": ["tests/unit/test_mutation_probe.py"], "why": "почему"}]}

    errors = vmp.check(drifted, root=PKG_ROOT)

    assert any("НЕ НАЙДЕН" in e for e in errors), errors


def test_a_probe_without_a_reason_is_rejected():
    """Проба без `why` через месяц станет обрядом, который снимут первым."""
    errors = vmp.check({"schema_version": 1, "kind": "mutation-probes", "probes": [
        {"id": "p", "file": "VERSION", "find": "0", "replace_with": "1", "tests": []}]})

    assert any("why" in e for e in errors), errors


def test_a_mutation_that_changes_nothing_is_rejected():
    """`replace_with` == `find`: такой мутант «убит» всегда, и проба лжёт о защите."""
    errors = vmp.check({"schema_version": 1, "kind": "mutation-probes", "probes": [
        {"id": "p", "file": "VERSION", "find": "0", "replace_with": "0",
         "tests": ["t"], "why": "почему"}]})

    assert any("ничего не меняет" in e for e in errors), errors


# ─── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_the_run_does_not_touch_the_tree_it_checks(tmp_path):
    """Прогон, который может испортить проверяемое дерево, в контур не годится.

    Замер: за 14.08.2026 правка «на месте» дважды оставляла мутацию в рабочем дереве после
    исключения, и один раз это заметилось только сверкой с бэкапом. Поэтому мутация живёт в копии,
    и это проверяется побайтово — ПРЕЖДЕ, чем смотреть на вердикт прогона.
    """
    root = _probes(_mini_repo(tmp_path))
    before = {p.relative_to(root): p.read_bytes()
              for p in root.rglob("*") if p.is_file()}

    rep = mp.run(root, python=sys.executable)

    after = {p.relative_to(root): p.read_bytes()
             for p in root.rglob("*") if p.is_file() and "__pycache__" not in str(p)}
    for rel, data in before.items():
        assert after.get(rel) == data, f"прогон изменил {rel} в проверяемом дереве"
    assert rep["probes"], "нечего проверять — тест смотрит не на тот прогон"


def test_only_selected_probes_run_when_asked(tmp_path):
    """`--only` сужает прогон: иначе локальная проверка одной охраны стоила бы всего реестра."""
    root = _probes(_mini_repo(tmp_path))

    rep = mp.run(root, only=["takoj-proby-net"], python=sys.executable)

    assert rep["checked"] == 0 and rep["survived"] == []
