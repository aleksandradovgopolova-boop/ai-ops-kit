"""Устойчивость к мусору от модели — вход, который кит не контролирует.

Writer недетерминирован по определению: живая модель возвращает обрезанный JSON, чужую схему,
пустоту, гигантский ответ, текст вместо действия. До сих пор проверялся ровно один случай
(«нет json -> error»), хотя именно этот вход единственный, где кит не может ничего гарантировать
о форме данных.

Три обязательных теста на capability (AGENTS.md):
  * positive     — валидное действие распознаётся, в том числе в текстовом обрамлении;
  * fail-closed  — любой мусор даёт ЯВНУЮ ошибку разбора, а не частично разобранное действие и не
                   исключение наружу; неизвестная операция отвергается брокером;
  * side-effect  — мусор не приводит к записи на диск: ни один файл не создан.
"""
from __future__ import annotations

import json

import pytest

from ai_ops_kit.engine import tool_broker
from ai_ops_kit.engine import tool_loop


# ---------------------------------------------------------------- positive ---

@pytest.mark.unit
class TestValidActionsAreParsed:

    def test_bare_json(self):
        assert tool_loop.parse_action('{"op":"read","path":"a.py"}') == {"op": "read", "path": "a.py"}

    def test_json_wrapped_in_prose(self):
        """Модели любят пояснять. Действие обязано находиться внутри текста."""
        text = 'Сейчас прочитаю файл.\n```json\n{"op":"read","path":"a.py"}\n```\nГотово.'
        assert tool_loop.parse_action(text)["op"] == "read"

    def test_dict_passes_through(self):
        assert tool_loop.parse_action({"done": True}) == {"done": True}


# ------------------------------------------------------------- fail-closed ---

@pytest.mark.unit
class TestGarbageIsRefusedExplicitly:

    @pytest.mark.parametrize("payload,label", [
        ("", "пустой ответ"),
        ("   \n\t ", "только пробелы"),
        (None, "None вместо строки"),
        ("просто текст без всякого json", "проза без JSON"),
        ('{"op":"write","path":"a.py"', "обрезанный JSON"),
        ('{"op": "write", "path": }', "синтаксически битый JSON"),
        ("{}", "пустой объект"),
        ('{"нечто":"чужая схема"}', "чужая схема"),
        ('{"op":"write"}', "write без path"),
        ("[1, 2, 3]", "массив вместо объекта"),
        ('{"op":"' + "x" * 100000 + '"}', "гигантский ответ"),
    ])
    def test_never_raises_and_never_half_parses(self, payload, label):
        """Разбор обязан вернуть либо действие, либо явную ошибку — и никогда не бросить."""
        try:
            action = tool_loop.parse_action(payload)
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"{label}: parse_action бросил {type(e).__name__} — цикл упадёт наружу")
        assert isinstance(action, dict), f"{label}: результат не словарь"
        if "error" not in action:
            # разобралось — значит это ДОЛЖНО быть предложением: действие цикла (op/done)
            # или вердикт ревьюера (kind/status), а не огрызок
            assert action.get("op") or action.get("done") or action.get("kind") or action.get("status"), \
                f"{label}: разобрано в {action!r} — не действие и не вердикт, полудействие"

    def test_truncated_json_is_named_bad_json(self):
        assert tool_loop.parse_action('{"op":"write","path":"a.py"')["error"] == "bad-json"

    def test_prose_is_named_no_json(self):
        assert tool_loop.parse_action("я подумаю над этим")["error"] == "no-json"

    @pytest.mark.parametrize("action", [
        {"op": "выдуманная-операция", "path": "a.py"},
        {"op": "", "path": "a.py"},
        {"op": "write"},
        {"op": "write", "path": ""},
    ])
    def test_broker_refuses_malformed_actions(self, action, tmp_path):
        """Даже если разбор что-то вернул, брокер не обязан это исполнять."""
        policy = tool_broker.Policy(level="controlled-write", write_scope=["src"],
                                    child_root=str(tmp_path))
        assert policy.decide(action)["allow"] is False


# -------------------------------------------------------- side-effect proof ---

@pytest.mark.unit
def test_garbage_stream_writes_nothing_to_disk(tmp_path):
    """Модель выдаёт только мусор: цикл обязан остановиться, не создав ни одного файла."""
    (tmp_path / "src").mkdir()
    policy = tool_broker.Policy(level="controlled-write", write_scope=["src"],
                                child_root=str(tmp_path))
    garbage = iter(["", "просто текст", '{"op":"write","path":"src/a.py"',
                    '{"чужая":"схема"}', "[1,2,3]"] * 5)

    report = tool_loop.run_loop(lambda ctx: next(garbage), tmp_path, policy, max_steps=10)

    assert report["stopped"].startswith("bad-proposal"), report["stopped"]
    assert not list((tmp_path / "src").iterdir()), "мусор от модели привёл к записи на диск"
    assert not report["executed"], "исполнено действие, собранное из мусора"


@pytest.mark.unit
def test_huge_payload_is_parsed_whole_and_does_not_hang(tmp_path):
    """Гигантский ответ не зависает при разборе и НЕ обрезается молча.

    ЗАЯВЛЕНИЕ ПРИВЕДЕНО К СОДЕРЖАНИЮ (ревизия 2026-08-11). Докстрока обещала ещё и «не проходить
    как действие», но проверялось ровно обратное: `action["op"] == "write"` и полная длина
    содержимого. Следом выпавшей половины была неиспользуемая `policy` — её собирали, чтобы
    прогнать действие через брокер. Потолка на РАЗМЕР ЗАПИСИ в брокере нет (есть `_READ_MAX`
    только на чтение), поэтому 2 МБ — законная запись в пределах scope, и утверждать обратное
    значило бы выдумать политику, которой нет. Молчаливое обрезание — вот настоящий риск: правка
    уехала бы неполной.
    """
    huge = json.dumps({"op": "write", "path": "src/a.py", "content": "x" * 2_000_000})

    action = tool_loop.parse_action(huge)

    assert action["op"] == "write"
    assert len(action["content"]) == 2_000_000, "содержимое молча обрезано — правка была бы неполной"
