"""Автономный запуск подсессий под потолком: отказы РАЗЛИЧИМЫ, и ни один из них не тратит.

Предмет проверки — не «функция вернула словарь», а два свойства, из-за которых автономию вообще
можно включать: (1) причина отказа названа своя, потому что лечение у них разное («объяви потолок»
≠ «кончились деньги» ≠ «не могу доказать расход»); (2) при отказе модель НЕ вызывается — иначе
«потолок» был бы отчётом о трате, а не её границей.

Мутационные проверки (каждая прогонялась и валит соответствующий тест):
  * убрать ветку `limit is None` -> test_no_ceiling_is_its_own_refusal падает (получается
    over_ceiling, то есть кит объясняет отказ ложной причиной);
  * снять проверку `cost_complete` -> test_unprovable_spend_refuses падает (кит утверждает «под
    потолком» по неполной сумме);
  * пустить `spawn` мимо `decide` -> test_refusal_spends_nothing падает (провайдер вызван);
  * убрать ветку «контекст не измерен» -> test_unknown_context_is_not_reported_as_cheap падает
    (кит называет неизмеренный контекст «ещё недорогим», то есть выдаёт «не знаю» за измерение).
    Первая версия этого теста проверяла только исход `continue_here` и мутацию ПРОПУСКАЛА: тот же
    исход даёт соседняя ветка. Тест переписан на проверку формулировки — это и есть предмет;
  * снять проверку подключённого учёта -> test_without_usage_accounting_it_refuses_instead_of_spending
    падает (трата, которую нельзя записать, обнулила бы следующий потолок);
  * переименовать AUTONOMOUS_ROLE только в записи -> test_spawn_is_charged_to_the_ledger падает
    (расход есть, а учёт его не видит: следующий потолок считался бы по нулю);
  * перестать считать пересечение потолка -> test_crossing_the_ceiling_is_named_not_hidden падает
    (перерасход происходит молча).

Все семь прогнаны сценарием `mutate-launcher.py`; ни одна мутация не прошла незамеченной.
"""
from __future__ import annotations

from ai_ops_kit.engops import session_launcher as sl
from ai_ops_kit.shared import usage_ledger

CEILING = {"max_autonomous_spend_usd": 1.0, "max_subsessions_per_session": 3}
HEAVY = {"session_id": "s1", "context_current": 500_000, "context_status": "measured"}


class Hooks:
    """Живой учёт расхода: те же `set_call_context`/`drain_call_stats`, что использует движок.

    Подменяется шов КОМПОЗИЦИИ (кто подключает учёт), а не сам учёт: буфер, нормализация записи и
    запись в ledger проходят продакшн-путём. Иначе тест доказывал бы работу стенда.
    """

    def __init__(self):
        from ai_ops_kit.providers import orchestrator_usage as ou
        self._ou = ou

    def set_context(self, **kw):
        self._ou.set_call_context(**kw)

    def drain(self):
        self._ou.clear_call_context()
        return self._ou.drain_call_stats()


def _snap(**over):
    return {**HEAVY, **over}


def _charge(root, cost, *, session="s1", n=1, cost_status="measured"):
    """Записать в ledger автономную трату так, как её пишет сам spawn (та же роль и run_id)."""
    rec = {"role": sl.AUTONOMOUS_ROLE, "provider": "claude-cli", "model": "claude-code-local",
           "input_tokens": 100, "output_tokens": 10, "usage_status": "measured",
           "cost": cost, "cost_status": cost_status, "trigger": "initial"}
    if cost_status == "unavailable":
        rec["cost"] = None
    usage_ledger.append(root, "w1", [rec], run_id=f"{sl.RUN_ID_PREFIX}:{session}:{n}")


def test_no_ceiling_is_its_own_refusal(tmp_path):
    """Потолок не объявлен — это «нельзя тратить вообще», а не «осталось ноль»."""
    d = sl.decide(str(tmp_path), _snap())
    assert d["action"] == "refuse"
    assert d["refusal"] == "no_ceiling"
    assert "не объявлен" in d["reason"]
    assert not sl.check(d)


def test_unidentified_session_refuses(tmp_path):
    """Сессию не опознали — трату нельзя отнести к ней, значит нельзя доказать, что под потолком."""
    d = sl.decide(str(tmp_path), _snap(session_id="unlabelled"), ceiling=CEILING)
    assert d["refusal"] == "session_unidentified"


def test_unprovable_spend_refuses(tmp_path):
    """Есть вызов с неизвестной стоимостью -> сумма неполна -> «под потолком» недоказуемо."""
    _charge(str(tmp_path), None, cost_status="unavailable")
    d = sl.decide(str(tmp_path), _snap(), ceiling=CEILING)
    assert d["refusal"] == "spend_unprovable"
    assert d["numbers"]["spend_provable"] is False


def test_over_ceiling_refuses_with_numbers(tmp_path):
    """Потолок достигнут — отказ называет и трату, и потолок."""
    _charge(str(tmp_path), 1.25)
    d = sl.decide(str(tmp_path), _snap(), ceiling=CEILING)
    assert d["refusal"] == "over_ceiling"
    assert d["numbers"]["spent_usd"] == 1.25
    assert d["numbers"]["ceiling_usd"] == 1.0


def test_over_subsession_count_refuses(tmp_path):
    """Лимит числа подсессий исчерпан при остатке денег — отказ не путается с over_ceiling."""
    for i in range(3):
        _charge(str(tmp_path), 0.01, n=i + 1)
    d = sl.decide(str(tmp_path), _snap(), ceiling=CEILING)
    assert d["refusal"] == "over_count"


def test_unsafe_boundary_beats_money(tmp_path):
    """Небезопасную точку нельзя купить потолком: причина отказа — она, а не деньги."""
    d = sl.decide(str(tmp_path), _snap(), ceiling=CEILING, at_safe_boundary=False)
    assert d["refusal"] == "unsafe_boundary"


def test_unknown_context_is_not_reported_as_cheap(tmp_path):
    """Контекст не измерен -> продолжаем здесь, и причина названа ЧЕСТНО.

    Исход `continue_here` тут дают две разные ветки, поэтому проверять только его недостаточно:
    без ветки «не измерено» кит скажет «контекст ещё недорогой», то есть выдаст неизвестное за
    измеренную дешевизну. Тест закрепляет именно формулировку причины.
    """
    d = sl.decide(str(tmp_path), _snap(context_current=None, context_status="unavailable"),
                  ceiling=CEILING)
    assert d["action"] == "continue_here"
    assert d["numbers"]["context_state"] == "unknown"
    assert "не измерен" in d["reason"]
    assert "недорогой" not in d["reason"]


def test_same_work_continues_here(tmp_path):
    """Следующий шаг — та же работа: свежая сессия заставила бы исследовать заново."""
    d = sl.decide(str(tmp_path), _snap(), ceiling=CEILING, next_relation="same_task")
    assert d["action"] == "continue_here"


def test_warranted_case_spawns(tmp_path):
    """Дорогой измеренный контекст + другая работа впереди + потолок есть -> открываем подсессию."""
    d = sl.decide(str(tmp_path), _snap(), ceiling=CEILING)
    assert d["action"] == "spawn_subsession"
    assert not sl.check(d)


def test_refusal_spends_nothing(tmp_path):
    """ГЛАВНОЕ СВОЙСТВО: при отказе провайдер не вызывается ни разу."""
    calls = []
    res = sl.spawn(str(tmp_path), "бриф", _snap(), ceiling=CEILING,
                   provider=lambda p: calls.append(p) or "текст", usage_hooks=Hooks(),
                   decision=sl.decide(str(tmp_path), _snap()))     # без потолка -> отказ
    assert res["spawned"] is False
    assert calls == []
    assert res["spend_after"] is None


def test_without_usage_accounting_it_refuses_instead_of_spending(tmp_path):
    """Разрешение есть, а записать трату нечем -> не тратим.

    Незаписанная трата сделала бы следующий потолок недействительным (он считается по ledger),
    то есть потолок тихо перестал бы работать — ровно то, чего не должно случаться молча.
    """
    calls = []
    res = sl.spawn(str(tmp_path), "бриф", _snap(), ceiling=CEILING,
                   provider=lambda p: calls.append(p) or "текст")   # usage_hooks не передан
    assert res["spawned"] is False
    assert res["decision"]["refusal"] == "no_usage_accounting"
    assert calls == []


def test_spawn_is_charged_to_the_ledger(tmp_path):
    """Расход подсессии попадает в учёт: иначе следующий потолок считался бы по нулю."""
    def provider(prompt):
        from ai_ops_kit.providers import orchestrator_usage as ou
        ou._record_call("claude-code-local", 120, 30, 0.5, provider="claude-cli", cost=0.42)
        return "предложение"

    res = sl.spawn(str(tmp_path), "бриф", _snap(), ceiling=CEILING, provider=provider,
                   usage_hooks=Hooks(), workitem_id="w1")
    assert res["spawned"] is True
    assert res["records_written"] == 1
    assert res["spend_before"]["cost"] == 0.0
    assert res["spend_after"]["cost"] == 0.42
    assert res["ceiling_crossed_by"] is None
    # и следующий вызов видит эту трату
    assert sl.autonomous_spend(str(tmp_path), "s1")["cost"] == 0.42


def test_crossing_the_ceiling_is_named_not_hidden(tmp_path):
    """Потраченное не отменить — честная половина решения в том, чтобы назвать пересечение."""
    def provider(prompt):
        from ai_ops_kit.providers import orchestrator_usage as ou
        ou._record_call("claude-code-local", 120, 30, 0.5, provider="claude-cli", cost=1.5)
        return "предложение"

    res = sl.spawn(str(tmp_path), "бриф", _snap(), ceiling=CEILING, provider=provider,
                   usage_hooks=Hooks(), workitem_id="w1")
    assert res["ceiling_crossed_by"] == 0.5
    # и следующее решение отказывает по названной причине
    assert sl.decide(str(tmp_path), _snap(), ceiling=CEILING)["refusal"] == "over_ceiling"


def test_brief_carries_repo_facts_not_parent_history(tmp_path):
    """Бриф собран из фактов репозитория и ограничен: иначе свежая сессия унесёт тот же контекст."""
    brief = sl.build_brief(workitem_id="w1", title="починить импорт", repo_path=str(tmp_path),
                           facts=["стек: python", "тесты: pytest"], safe_step="прогнать тесты")
    assert "w1" in brief and "стек: python" in brief
    assert len(brief) < 4000
    assert "не пиши файлы" in brief


def test_truncated_brief_says_so(tmp_path):
    """Урезанный охват называется: молчаливое усечение читалось бы как «в брифе всё»."""
    brief = sl.build_brief(facts=["ф" * 100 for _ in range(50)], max_chars=300)
    assert "усечён" in brief


def test_unreadable_config_does_not_grant_permission(tmp_path):
    """Битый .ai-ops.yaml не означает «потолка нет, трать свободно» — дефолт fail-closed."""
    (tmp_path / ".ai-ops.yaml").write_text("session_economy: [это: не: словарь\n", encoding="utf-8")
    assert sl.load_ceiling(str(tmp_path))["max_autonomous_spend_usd"] is None
    assert sl.decide(str(tmp_path), _snap())["refusal"] == "no_ceiling"


def test_ceiling_read_from_config(tmp_path):
    """Потолок объявляется владельцем в .ai-ops.yaml и читается оттуда."""
    (tmp_path / ".ai-ops.yaml").write_text(
        "session_economy:\n  max_autonomous_spend_usd: 2.5\n  max_subsessions_per_session: 4\n",
        encoding="utf-8")
    c = sl.load_ceiling(str(tmp_path))
    assert c["max_autonomous_spend_usd"] == 2.5
    assert c["max_subsessions_per_session"] == 4
    assert sl.decide(str(tmp_path), _snap())["action"] == "spawn_subsession"


def test_decision_check_rejects_refusal_without_code():
    """Валидатор решения не пропускает отказ без кода причины."""
    bad = {"kind": "SubsessionDecision", "action": "refuse", "refusal": None, "reason": "просто нет"}
    assert sl.check(bad)
