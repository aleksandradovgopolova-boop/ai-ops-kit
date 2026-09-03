"""Комментарии владельца в файле ответов ПЕРЕЖИВАЮТ повторный `ai-ops model` (F-020, niti 12.08).

НАХОДКА — потеря ОСНОВАНИЯ, а не значения. `write_question_file` пересобирает файл целиком:
значения переносятся через `read_answers`, комментарии — нет. В живом прогоне владелец вписал к
каждому ответу источник (`file:line`), и после следующего `ai-ops model` осталось 0 строк со
ссылками. Обход в прогоне — прятать ссылки ВНУТРЬ значений; это обход, а не решение.

ПОЧЕМУ ЭТО НЕ КОСМЕТИКА. Файл ответов — место, где факт становится `user_confirmed` и перестаёт
переспрашиваться. Утверждение без основания нечем проверить: подтверждённое и переписанное
выглядят одинаково. Инвариант «у каждого утверждения есть основание» держится ровно этими строками.

Три обязательных теста на capability (AGENTS.md): положительный, границы, доказательство отсутствия
побочного эффекта.
"""
from __future__ import annotations

import yaml

from ai_ops_kit.planning.repo_audit import answers_path, read_answers, write_question_file

ASK = {"questions": [
    {"id": "primary_user", "ask": "Кто основной пользователь продукта?"},
    {"id": "main_goal_now", "ask": "Какая главная цель продукта сейчас?",
     "proposal": {"value": "рост удержания"}},
]}

SOURCE_ABOVE = "# источник: docs/personas.md:3"
SOURCE_INLINE = "# выписано дословно из docs/product.md:14"


def _answer_with_comments(root):
    """Владелец отвечает и вписывает основания ДВУМЯ способами — над ответом и в хвосте строки."""
    f = answers_path(root)
    text = f.read_text(encoding="utf-8")
    text = text.replace('  primary_user: ""',
                        f'  {SOURCE_ABOVE}\n  primary_user: "исследователь"  {SOURCE_INLINE}')
    text = text.replace('  main_goal_now: ""', '  main_goal_now: "связность"')
    f.write_text(text, encoding="utf-8")
    return f


def test_owner_comments_survive_repeated_model_runs(tmp_path):
    """positive: оба вида комментария на месте после ДВУХ прогонов, ответы не пострадали."""
    write_question_file(tmp_path, ASK)
    f = _answer_with_comments(tmp_path)

    write_question_file(tmp_path, ASK)
    write_question_file(tmp_path, ASK)

    text = f.read_text(encoding="utf-8")
    assert SOURCE_ABOVE in text, "комментарий НАД ответом стёрт — основание потеряно"
    assert SOURCE_INLINE in text, "хвостовой комментарий стёрт — основание потеряно"
    assert read_answers(tmp_path)["primary_user"] == "исследователь", "ответ потерян"
    yaml.safe_load(text)                         # файл обязан остаться валидным


def test_kit_own_comments_are_not_adopted_as_owner_text(tmp_path):
    """границы: кит не принимает СВОИ строки за авторские и не копит их с каждым прогоном.

    Разбор отличает чужое от своего сравнением с тем, что кит пишет сам. Ошибись он в эту сторону —
    файл рос бы на копию всех вопросов при каждом `ai-ops model`, и владелец потерял бы свои
    строки в шуме. Это обратная цена той же правки, поэтому проверяется вместе с ней.
    """
    write_question_file(tmp_path, ASK)
    _answer_with_comments(tmp_path)
    write_question_file(tmp_path, ASK)
    write_question_file(tmp_path, ASK)

    text = answers_path(tmp_path).read_text(encoding="utf-8")
    assert text.count("Кто основной пользователь продукта?") == 1, "вопрос кита задвоился"
    assert text.count("по коду предполагаю: рост удержания") == 1, "предложение кита задвоилось"
    assert text.count(SOURCE_ABOVE) == 1, "авторская строка задвоилась"


def test_hash_inside_answer_is_not_mistaken_for_a_comment(tmp_path):
    """границы: `#` внутри ЗНАЧЕНИЯ — часть ответа, а не начало комментария.

    Резать строку по первому `#` было бы проще и неверно: ответ «рост #1 по выручке» превратился бы
    в «рост» плюс выдуманный комментарий. Значение пишется JSON-строкой, поэтому решётка считается
    комментарием только вне кавычек.
    """
    write_question_file(tmp_path, ASK)
    f = answers_path(tmp_path)
    f.write_text(f.read_text(encoding="utf-8").replace(
        '  main_goal_now: ""', '  main_goal_now: "рост #1 по выручке"  # цель года'),
        encoding="utf-8")

    write_question_file(tmp_path, ASK)

    assert read_answers(tmp_path)["main_goal_now"] == "рост #1 по выручке", "ответ обрезан по `#`"
    # ПРОВЕРЯЕТСЯ СТРОКА ЦЕЛИКОМ, а не вхождение «# цель года».
    #
    # Первая версия теста утверждала `"# цель года" in text` — и ПРОХОДИЛА на наивной резке по
    # первому `#`: та выдаёт комментарий `#1 по выручке"  # цель года`, внутри которого искомая
    # подстрока есть. Значение при этом тоже цело, потому что пишется из разобранного YAML, а не из
    # текста. То есть тест доказывал не то, ради чего написан; поймано мутацией, не чтением.
    line = next(ln for ln in f.read_text(encoding="utf-8").splitlines()
                if ln.lstrip().startswith("main_goal_now:"))
    assert line == '  main_goal_now: "рост #1 по выручке"  # цель года', (
        f"хвостовой комментарий искажён или потерян: {line!r}")


def test_unchanged_file_is_still_not_rewritten(tmp_path):
    """side-effect proof: правка не отняла «лишней записи не делаем».

    Файл с комментариями обязан быть ИДЕМПОТЕНТНЫМ: если бы перенос комментариев менял текст на
    каждом прогоне, `ai-ops model` показывал бы файл изменённым в `git status` чужого репозитория
    при каждом взгляде на состояние — ровно то поведение, которое здесь запрещено отдельно.
    """
    write_question_file(tmp_path, ASK)
    f = _answer_with_comments(tmp_path)
    write_question_file(tmp_path, ASK)          # первый прогон нормализует расположение

    before_text = f.read_text(encoding="utf-8")
    before_mtime = f.stat().st_mtime_ns
    write_question_file(tmp_path, ASK)

    assert f.read_text(encoding="utf-8") == before_text, "текст изменился на повторном прогоне"
    assert f.stat().st_mtime_ns == before_mtime, "файл перезаписан, хотя содержимое то же"
