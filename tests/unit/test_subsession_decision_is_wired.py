"""Решение об автономии доходит до человека, и отказы звучат по-разному.

ЗАЧЕМ ЭТОТ ФАЙЛ. В этом репозитории уже был случай, когда переводчик `from_doctor` был написан,
покрыт тестами и НЕ ВЫЗЫВАЛСЯ НИОТКУДА — то есть проверялось представление автора, а не поведение
продукта. Здесь проверяется ровно разводка: `_session_guard_before_start` обязан спросить
`session_launcher.decide` и отдать ответ наружу через `_say`, а не печатать сам.

Второе свойство — слова. Семь отказов лечатся по-разному («назначь сумму» ≠ «сумма израсходована» ≠
«не могу доказать расход»), поэтому сведение их в одну фразу «нельзя» было бы потерей информации
ровно там, где человек принимает решение.

Мутации (прогнаны, каждая валит свой тест):
  * убрать вызов `decide` из стража -> test_guard_asks_the_launcher падает;
  * заменить `_say` на `print` -> test_guard_speaks_through_the_presenter падает;
  * вернуть один общий текст на все отказы -> test_refusals_do_not_collapse_into_one_word падает;
  * пустить решение наружу при любом исходе -> test_it_speaks_only_when_session_change_is_advised
    падает (строка стала бы шумом на каждом прогоне).
"""
from __future__ import annotations

import ast
from pathlib import Path

from ai_ops_kit.ui import presenter

CLI = Path(__file__).resolve().parents[2] / "ai_ops_kit" / "cli" / "ai_ops_cli.py"


def _guard_source():
    tree = ast.parse(CLI.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_session_guard_before_start")
    return fn


def test_guard_asks_the_launcher():
    """Страж перед стартом обязан спросить решение об автономии, а не только совет по гигиене."""
    src = ast.dump(_guard_source())
    assert "session_launcher" in src, "страж не зовёт session_launcher — решение об автономии мёртво"
    assert "decide" in src


def test_guard_speaks_through_the_presenter():
    """Наружу — только через `_say`: единственный путь к человеку в этом репозитории."""
    fn = _guard_source()
    said = [n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_say"
            and len(n.args) >= 2 and getattr(n.args[1], "value", None) == "from_subsession_decision"]
    assert said, "решение об автономии печатается мимо presenter"


def test_it_speaks_only_when_session_change_is_advised():
    """Условие есть И оно СОДЕРЖАТЕЛЬНО: иначе строка про автономию — шум на каждом прогоне.

    Проверять «есть ли `if`» недостаточно: `if True:` — тоже `if`, и первая версия этого теста
    мутацию `if True:` ПРОПУСТИЛА. Предмет — что вывод привязан к исходу рекомендации.
    """
    fn = _guard_source()
    ifs = [n for n in ast.walk(fn) if isinstance(n, ast.If)
           and any(isinstance(c, ast.Call) and getattr(c.func, "attr", None) == "decide"
                   for c in ast.walk(n))]
    assert ifs, "решение об автономии выводится без условия — шум на каждом прогоне"
    cond = ast.dump(ifs[0].test)
    assert not isinstance(ifs[0].test, ast.Constant), "условие константное — то есть условия нет"
    assert "outcome" in cond, "вывод не привязан к исходу рекомендации по смене сессии"


def _render(decision):
    return presenter.render(presenter.from_subsession_decision(decision), audience="product")


def _dec(action, refusal=None, **numbers):
    return {"kind": "SubsessionDecision", "action": action, "refusal": refusal,
            "reason": "причина", "numbers": numbers}


def test_refusals_do_not_collapse_into_one_word():
    """Разное лечение — разные слова. Тексты трёх отказов обязаны различаться."""
    no_ceiling = _render(_dec("refuse", "no_ceiling", ceiling_usd=None))
    over = _render(_dec("refuse", "over_ceiling", ceiling_usd=1.0, spent_usd=1.25))
    unprovable = _render(_dec("refuse", "spend_unprovable", ceiling_usd=1.0))
    assert len({no_ceiling, over, unprovable}) == 3
    assert "не назначена" in no_ceiling or "никто не называл" in no_ceiling
    assert "израсходована" in over
    assert "доказать" in unprovable


def test_owner_text_carries_no_internal_names():
    """Читателю — человеческий язык: ни имён полей конфига, ни кодов отказов в самом тексте."""
    out = _render(_dec("refuse", "no_ceiling", ceiling_usd=None))
    for internal in ("max_autonomous_spend_usd", "session_economy", "no_ceiling", "SubsessionDecision",
                     "WorkItem", "usage_hooks"):
        assert internal not in out, f"внутреннее имя «{internal}» ушло наружу"


def test_internal_details_are_kept_not_dropped():
    """Детали не выбрасываются: без них кит непроверяем. Они в technical, не в тексте."""
    msg = presenter.from_subsession_decision(_dec("refuse", "no_ceiling", ceiling_usd=None,
                                                  session_id="s1"))
    payload = msg["technical_details"]["payload"]
    assert msg["technical_details"]["available"] is True
    assert payload["код отказа"] == "no_ceiling"
    assert payload["потолок $"] == "не объявлен"


def test_taking_the_work_reads_as_a_promise_not_a_question():
    """Когда кит берёт работу сам — это утверждение, а не вопрос владельцу."""
    out = _render(_dec("spawn_subsession", None, ceiling_usd=2.0, spent_usd=0.5))
    assert "возьму" in out
    assert "ничего не нужно" in out
