"""Ответы онбординга ВЫЖИВАЮТ повторный `ai-ops model` (F-023, живой прогон niti 2026-08-12).

НАХОДКА — потеря данных на главном шаге онбординга, молча.

`write_question_file` писал значение через `yaml.safe_dump(val, default_flow_style=True).strip()`,
и это ломало файл ДВАЖДЫ:

  1. для голого скаляра PyYAML дописывает маркер конца документа: `safe_dump("текст")` даёт
     `'текст\\n...\\n'`. `.strip()` убирает только пробелы — в файл попадала строка `...`, которая
     начинает НОВЫЙ YAML-документ, и всё после неё перестаёт быть частью `answers`;
  2. дефолт `width=80` переносил длинное значение на следующую строку, а префикс `  <ключ>: `
     добавлялся лишь к первой — продолжение оказывалось на отступе соседних ключей.

Дальше срабатывал второй дефект: `read_answers` глотал `yaml.YAMLError` и возвращал `{}`. Кит
получал «ответов нет», переспрашивал ВСЁ заново и перезаписывал файл пустым. Ответы владельца
исчезали без единого сообщения.

Ломалось ровно на СОДЕРЖАТЕЛЬНЫХ ответах: короткие («да», «product») выживали, а ответ на «кто ваш
пользователь» — нет. В живом прогоне niti так и вышло: 11 вопросов -> 5 -> снова 11.

Три обязательных теста на capability (AGENTS.md).
"""
from __future__ import annotations

import pytest
import yaml

from repo_audit import AnswersCorrupt, answers_path, read_answers, write_question_file

ASK = {"questions": [{"id": "primary_user", "ask": "Кто основной пользователь продукта?"},
                     {"id": "main_goal_now", "ask": "Какая главная цель продукта сейчас?"}]}

# НАСТОЯЩИЙ ответ из живого прогона niti — именно на нём файл и сломался.
#
# Строка выбрана не «подлиннее», а по МЕХАНИЗМУ дефекта, замеренному отдельно: PyYAML пишет
# скаляр PLAIN (без кавычек), если в нём нет символов, требующих квотирования. Тогда при
# `width=80` он переносит значение и добавляет маркер `...` — файл невалиден. А строка с «ёлочками»
# или двоеточием квотируется, переносится внутри кавычек и остаётся валидной. Первая версия этого
# теста как раз брала строку с кавычками — и проходила на СЛОМАННОМ коде. Мутационная проверка это
# и показала: тест обязан ловить механизм, а не длину.
LONG = ('Заметки, цитаты и фрагменты накапливаются, но смысл между ними теряется. Продукт не '
        'просто хранит их, а помогает находить смысловые связи, объяснять эти связи и показывать '
        'их в графе.')


def _fill(root, key, value):
    f = answers_path(root)
    doc = yaml.safe_load(f.read_text(encoding="utf-8"))
    doc["answers"][key] = value
    f.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=10 ** 6),
                 encoding="utf-8")


def test_long_answer_survives_repeated_model_runs(tmp_path):
    """positive: содержательный ответ жив после ДВУХ повторных прогонов, файл остаётся валидным."""
    write_question_file(tmp_path, ASK)
    _fill(tmp_path, "primary_user", LONG)

    write_question_file(tmp_path, ASK)
    write_question_file(tmp_path, ASK)

    back = read_answers(tmp_path)
    assert back.get("primary_user") == LONG, (
        f"ответ владельца потерян или обрезан: {back.get('primary_user')!r}")

    text = answers_path(tmp_path).read_text(encoding="utf-8")
    yaml.safe_load(text)                     # не должно бросать
    assert "\n...\n" not in text and not text.rstrip().endswith("..."), (
        "в файле маркер конца документа — всё после него выпадет из `answers`")


def test_corrupt_answers_file_is_not_reported_as_no_answers(tmp_path):
    """fail-closed: битый файл — это НЕ «ответов нет», и переписывать его нельзя.

    Прежде `read_answers` возвращал `{}`, и следующий прогон затирал ответы. Теперь ошибка доходит
    до человека словами «починить, а не отвечать заново».
    """
    write_question_file(tmp_path, ASK)
    _fill(tmp_path, "primary_user", LONG)
    f = answers_path(tmp_path)
    f.write_text(f.read_text(encoding="utf-8") + "\n...\nэто уже другой документ: да\n",
                 encoding="utf-8")

    with pytest.raises(AnswersCorrupt) as e:
        read_answers(tmp_path)
    assert "починить" in str(e.value), "ошибка не говорит, что делать"

    with pytest.raises(AnswersCorrupt):
        write_question_file(tmp_path, ASK)   # запись обязана отказаться, а не обнулить
    assert LONG in f.read_text(encoding="utf-8"), "битый файл перезаписан — ответ уничтожен"


def test_unanswered_and_short_answers_are_preserved(tmp_path):
    """side-effect proof: правка не сломала обычные случаи.

    Без этого «починку» можно было бы получить, начав квотировать всё подряд и потеряв пустые
    значения — а пустое значение это «ещё не ответил», отдельный смысл.
    """
    write_question_file(tmp_path, ASK)
    _fill(tmp_path, "main_goal_now", "product")

    write_question_file(tmp_path, ASK)
    back = read_answers(tmp_path)

    assert back == {"main_goal_now": "product"}, (
        f"пустой ответ перестал значить «ещё не ответил» либо короткий потерян: {back}")
    text = answers_path(tmp_path).read_text(encoding="utf-8")
    assert 'primary_user: ""' in text, "неотвеченный вопрос исчез из файла — его больше не задать"

def test_answer_survives_when_question_is_no_longer_asked(tmp_path):
    """Ответ выживает, когда вопрос БОЛЬШЕ НЕ ЗАДАЮТ — это отдельная ветка записи (F-021, ч.2).

    В `write_question_file` два места, где пишется значение: для вопросов из текущего `ask` и для
    «ответов на вопросы, которых больше не задают». Первая правка закрыла только первое — а
    отвеченные вопросы идут ИМЕННО во второе. Дефект остался ровно там, где живут данные: на
    живом продукте ответы гибли и после «исправления».

    Поймано повторным прогоном на niti, не чтением кода: тест выше проходил, потому что держал
    оба ключа в `ask`.
    """
    write_question_file(tmp_path, ASK)
    _fill(tmp_path, "primary_user", LONG)

    # Вопрос ушёл из списка — путь «больше не спрашиваем».
    shrunk = {"questions": [{"id": "main_goal_now", "ask": "Какая главная цель продукта сейчас?"}]}
    write_question_file(tmp_path, shrunk)
    write_question_file(tmp_path, shrunk)

    back = read_answers(tmp_path)
    assert back.get("primary_user") == LONG, (
        f"ответ на уже не задаваемый вопрос потерян: {back}")
    yaml.safe_load(answers_path(tmp_path).read_text(encoding="utf-8"))
