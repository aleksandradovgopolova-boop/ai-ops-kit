"""`ai-ops subsession`: команда существует, разведена и НЕ тратит без явной просьбы.

ПРЕДМЕТ. Команда, которая тратит деньги от одного слова, — не инструмент, а ловушка. Поэтому
проверяется не «функция есть», а три свойства: она вызывается из диспетчера (иначе мёртвый код),
по умолчанию сухая (трата только с `--spawn`), и учёт расхода подключён в момент траты (без него
следующий потолок считался бы по неполной сумме, то есть потолок тихо перестал бы работать).

Проверка идёт разбором AST установщика, а не запуском с настоящей моделью: тест не должен тратить
деньги. Живой прогон — отдельно, он записан в `qualification/FIELD-RUN-AUTONOMY-2026-08-13.md`.

Мутации (прогнаны, каждая валит свой тест):
  * убрать ветку диспетчера -> test_command_is_dispatched;
  * снять условие `--spawn` -> test_it_does_not_spend_without_being_asked;
  * не передавать usage_hooks в spawn -> test_spend_is_accounted_at_the_moment_it_happens;
  * не печатать пересечение потолка -> test_overspend_is_named_not_hidden.
"""
from __future__ import annotations

import ast
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[2] / "installer" / "ai_ops.py"


def _tree():
    return ast.parse(INSTALLER.read_text(encoding="utf-8"))


def _func(name):
    return next((n for n in ast.walk(_tree())
                 if isinstance(n, ast.FunctionDef) and n.name == name), None)


def test_command_exists():
    assert _func("cmd_subsession") is not None, "команды нет"


def test_command_is_dispatched():
    """Разводка: без ветки в диспетчере команда недоступна человеку — то есть мёртвый код."""
    src = INSTALLER.read_text(encoding="utf-8")
    assert 'cmd == "subsession"' in src, "команда не разведена в диспетчере"
    assert "return cmd_subsession(argv)" in src


def test_it_is_listed_for_the_human():
    """Команда, которой нет в списке команд, не существует для владельца."""
    src = INSTALLER.read_text(encoding="utf-8")
    head = src[:src.index("import ", 200)] if "import " in src else src[:4000]
    assert "subsession" in head, "команда не названа в списке команд"


def test_it_does_not_spend_without_being_asked():
    """Сухо по умолчанию: вызов модели обязан быть за условием `--spawn`."""
    fn = _func("cmd_subsession")
    spawn_calls = [n for n in ast.walk(fn)
                   if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "spawn"]
    assert spawn_calls, "трата вообще не вызывается — команда бесполезна"
    # ast.dump печатает строковые константы в одинарных кавычках — ищем сам литерал, не его запись
    guards = [n for n in ast.walk(fn) if isinstance(n, ast.If)
              and "--spawn" in ast.dump(n.test)]
    assert guards, "трата не защищена явной просьбой `--spawn`"
    # ранний выход до траты, а не «продолжим и посмотрим»
    assert any(isinstance(b, ast.Return) for g in guards for b in g.body), \
        "условие есть, но не прерывает путь до траты"


def test_spend_is_accounted_at_the_moment_it_happens():
    """В `spawn` передаётся и исполнитель, и учёт расхода — иначе потолок перестаёт работать."""
    fn = _func("cmd_subsession")
    call = next(n for n in ast.walk(fn)
                if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "spawn")
    kwargs = {k.arg for k in call.keywords}
    assert "provider" in kwargs, "исполнитель не передан"
    assert "usage_hooks" in kwargs, "учёт расхода не подключён в момент траты"


def test_overspend_is_named_not_hidden():
    """Потраченного не вернуть; честная половина — сказать о перерасходе.

    Проверяется СТРУКТУРА, а не наличие имени: первая версия теста искала подстроку
    `ceiling_crossed_by` где угодно в функции и мутацию `if False:` ПРОПУСКАЛА — имя оставалось в
    тексте сообщения, которое больше не печаталось. Тест на присутствие слова доказывает, что слово
    написано, а не что оно срабатывает.
    """
    fn = _func("cmd_subsession")
    guards = [n for n in ast.walk(fn) if isinstance(n, ast.If)
              and "ceiling_crossed_by" in ast.dump(n.test)
              and not isinstance(n.test, ast.Constant)]
    assert guards, "перерасход не проверяется живым условием"
    assert any(isinstance(b, ast.Expr) and isinstance(b.value, ast.Call)
               and getattr(b.value.func, "id", None) == "print"
               for g in guards for b in g.body), "перерасход проверяется, но человеку не называется"


def test_hooks_drain_and_clear_context():
    """Дренаж обязателен: `_record_call` копит в памяти, и без дренажа расход не попадёт в ledger."""
    fn = _func("cmd_subsession")
    src = ast.dump(fn)
    assert "drain_call_stats" in src
    assert "set_call_context" in src
    assert "clear_call_context" in src
