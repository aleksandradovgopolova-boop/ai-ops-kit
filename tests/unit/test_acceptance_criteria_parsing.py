"""Разбор критериев приёмки: `parse_criteria` и `criteria_from_spec` (B2-14; разрез test_acceptance_verify.py).

Отколото от test_acceptance_verify.py тем же механическим приёмом, что #438/#464 (разрез по темам без
изменения тел тестов). Здесь — разбор САМИХ критериев: маркеры списков, декоративные строки (`---`,
`* * *`), склейка многострочных пунктов и разметка `**bold**` (`parse_criteria`); и чтение раздела спеки
во всех формах — мэппинг, строка, список, `content:''`, `needs_human` (`criteria_from_spec`). Вердикт
`verify()` — в test_acceptance_verify.py, заземление цитат — в test_acceptance_verify_grounding.py.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engine import acceptance_verify as av


def test_a_bold_heading_does_not_eat_the_real_criteria():
    """Ревью PR #118: `**Заголовок**` считался пунктом, и настоящие критерии ИСЧЕЗАЛИ.

    Маркер списка без пробела делал пунктом любую строку на `*`/`-`. Непустой список отключал
    прозаический разбор — отчёт показывал `count: 1` по декоративной строке, а два реальных
    критерия не проверялись вовсе. Это тот же ложный green, только изнутри самого механизма.
    """
    got = [c["text"] for c in av.parse_criteria(
        "**Критерии приёмки**\nв README нет строк с public/media\nструктура описана верно")]

    assert got == ["в README нет строк с public/media", "структура описана верно"], got


def test_a_horizontal_rule_is_not_a_criterion():
    """Ревью PR #118: `---` становился пунктом `--` — неопровержимым, а значит вечно undetermined.

    Один разделитель в разделе навсегда превращал сверку в «неполную»: `verified` держится на
    отсутствии `undetermined`, и декоративная строка обнуляла бы работу механизма.
    """
    assert [c["text"] for c in av.parse_criteria("- крит один\n\n---\n\n- крит два")] == [
        "крит один", "крит два"]
    assert av.parse_criteria("# Заголовок\n***\n") == []


def test_mixed_markers_lose_nothing():
    """Второе ревью PR #118: `- один` + `*два` — и второй критерий ИСЧЕЗАЛ.

    Требование пробела после маркера (правка первого ревью) породило свой класс потерь: строка без
    пробела пунктом не считалась, а один найденный пункт выключал прозаический разбор. Отчёт
    показывал `count: 1` — «выполнен по умолчанию» через новую дверь.
    """
    got = [c["text"] for c in av.parse_criteria("- крит один\n*крит два\n-крит три")]

    assert got == ["крит один", "крит два", "крит три"], got


def test_a_multiline_list_item_keeps_its_tail():
    """Хвост многострочного пункта (`- |` в YAML) не теряется, а продолжает свой критерий."""
    got = [c["text"] for c in av.parse_criteria(
        "- в README нет строк с public/media\n  и структура описана верно\n- второй критерий")]

    assert got == ["в README нет строк с public/media и структура описана верно", "второй критерий"]


def test_spaced_horizontal_rules_are_not_criteria():
    """Второе ревью: `* * *` и `- - -` становились пунктами `* *` / `- -`.

    Неопровержимый псевдопункт -> честный `undetermined` -> `verified=False` навсегда: одна
    декоративная строка обнуляла сверку. Тот же дефект, что `---`, только в разнесённом варианте.
    """
    assert [c["text"] for c in av.parse_criteria("- крит один\n* * *\n- крит два")] == [
        "крит один", "крит два"]
    assert [c["text"] for c in av.parse_criteria("- крит\n- - -\n")] == ["крит"]


def test_an_unindented_line_after_a_bullet_is_its_own_criterion():
    """Третье ревью PR #118: правило продолжения СКЛЕИВАЛО два независимых критерия.

    Любая неразмеченная строка после пункта прилипала к нему, и судья выносил ОДИН вердикт на два
    требования — мог честно сказать `met`, когда выполнена лишь первая половина. Продолжением
    считается только строка с отступом: именно так размечается многострочный YAML-пункт.
    """
    got = [c["text"] for c in av.parse_criteria(
        "- в README нет public/media\nэндпоинт /health отвечает 200")]

    assert got == ["в README нет public/media", "эндпоинт /health отвечает 200"], got


def test_bold_markup_is_not_eaten_as_a_list_marker():
    """Третье ревью: `**AC-1**: …` терял первую звёздочку — критерий доезжал искажённым.

    Не потеря, но текст, который судья и владелец читают как критерий, обязан совпадать с тем, что
    написал человек: иначе вердикт выносится по подпорченной формулировке.
    """
    assert [c["text"] for c in av.parse_criteria("**AC-1**: нет public/media")] == [
        "**AC-1**: нет public/media"]
    # одиночная звёздочка — то же искажение, другое начертание (четвёртое ревью PR #118)
    assert [c["text"] for c in av.parse_criteria("*AC-1*: нет public/media")] == [
        "*AC-1*: нет public/media"]
    # а `*` как настоящий маркер списка по-прежнему работает
    assert [c["text"] for c in av.parse_criteria("*крит один\n*крит два")] == [
        "крит один", "крит два"]


def test_a_uniformly_indented_block_is_not_one_glued_criterion():
    """Четвёртое ревью PR #118: равномерный отступ склеивал все критерии в один.

    `_section_text` снимал отступ только у первой строки, поэтому соседние выглядели её
    продолжением — и судья выносил ОДИН вердикт на три требования. Общий отступ снимается со всего
    блока; настоящее продолжение (более глубокий отступ) по-прежнему приклеивается.
    """
    got = [c["text"] for c in av.parse_criteria(
        "    - AC-1: первое\n    AC-2: второе\n    AC-3: третье")]

    assert got == ["AC-1: первое", "AC-2: второе", "AC-3: третье"], got


def test_criteria_are_parsed_without_losing_items():
    """Разбор не теряет критерии: списки, чекбоксы, нумерация, проза — всё становится пунктами.

    Потерянный критерий = «выполнен по умолчанию»: молчание того же класса, что и ложный green.
    """
    assert [c["text"] for c in av.parse_criteria("- один\n* два\n1. три")] == ["один", "два", "три"]
    assert [c["text"] for c in av.parse_criteria("- [ ] чекбокс\n- [x] готов")] == ["чекбокс", "готов"]
    assert [c["id"] for c in av.parse_criteria("одна строка\nдругая строка")] == ["AC-1", "AC-2"]
    assert av.parse_criteria("Критерии:") == [], "заголовок пунктом не является"
    assert av.parse_criteria("") == [] and av.parse_criteria(None) == []


@pytest.mark.parametrize("section,expected", [
    ("acceptance_criteria:\n    status: complete\n    content: |\n      - нет public/media\n", 1),
    ("acceptance_criteria: нет строк с public/media\n", 1),                       # раздел СТРОКОЙ
    ("acceptance_criteria:\n  - нет public/media\n  - структура верна\n", 2),     # раздел СПИСКОМ
])
def test_every_shape_of_the_spec_section_is_read(tmp_path, section, expected):
    """Ревью PR #118: раздел спеки бывает мэппингом, строкой и списком — читались только мэппинги.

    На строке `.get('content')` бросал AttributeError, тот гасился, и функция отвечала «критериев
    нет». При этом `spec_levels` тот же файл считает заполненным. Итог был бы худшим из возможных:
    `spec-coverage: complete`, а прогон не печатает о критериях НИ СЛОВА — ровно B2-14, только
    воспроизведённый механизмом, который его чинит.
    """
    (tmp_path / "features" / "w").mkdir(parents=True)
    (tmp_path / "features" / "w" / "spec.yaml").write_text(
        f"schema_version: 1\nkind: FeatureSpec\nworkitem_id: w\nsections:\n  {section}",
        encoding="utf-8")

    text, items, problem = av.criteria_from_spec(tmp_path, "w")

    assert problem is None, problem
    assert len(items) == expected, f"разобрано {items} из раздела {section!r}"
    assert text


@pytest.mark.parametrize("section,expect_problem,expect_items", [
    # мэппинг без содержимого -> проблема НАЗВАНА (второе ревью)
    ("acceptance_criteria:\n    status: complete\n    note: нет строк с public/media\n", True, 0),
    # `content: ''` — ровно то, что пишет `spec_levels.create_spec`; молчание возвращалось (третье ревью)
    ("acceptance_criteria:\n    status: complete\n    content: ''\n    note: критерии тут\n", True, 0),
    # ключ без читаемого текста — потерянный критерий, назвать (третье ревью)
    ("acceptance_criteria:\n    AC-1: нет public/media\n    AC-2: []\n", True, 0),
    # намеренно не заполненные разделы: молчание честно
    ("acceptance_criteria:\n    status: missing\n", False, 0),
    # `needs_human` — долг, а не отказ: молчать нельзя, но и «не прочитано» неверно (четвёртое ревью)
    ("acceptance_criteria:\n    status: needs_human\n", True, 0),
    # мэппинг `AC-N: текст` — читаемая форма, в том числе рядом со `status` (третье ревью)
    ("acceptance_criteria:\n    AC-1: нет строк с public/media\n    AC-2: структура верна\n", False, 2),
    # ПЯТОЕ ревью отменило аддитивность четвёртого: содержимое есть -> оно и есть раздел, соседи —
    # метаданные. Иначе любой авторский ключ (`refs`, `verified_by`) становился фантомным критерием
    # либо давал ложное «критерии НЕ прочитаны» на разделе, прочитанном целиком.
    ("acceptance_criteria:\n    status: complete\n    content: '- нет public/media'\n"
     "    refs: []\n    verified_by: agent\n", False, 1),
    # все три ключа содержимого читаются, а не первый непустой (пятое ревью)
    ("acceptance_criteria:\n    content: '- AC-1 первый'\n    text: '- AC-2 второй'\n", False, 2),
    ("acceptance_criteria:\n    status: complete\n    AC-1: нет public/media\n    AC-2: верно\n",
     False, 2),
    ("acceptance_criteria:\n    AC-1:\n      text: вложенный критерий\n", False, 1),
])
def test_a_mapping_section_never_returns_to_silence(tmp_path, section, expect_problem, expect_items):
    """Второе и третье ревью PR #118: молчание возвращалось через каждую непредусмотренную форму.

    `spec_levels` считает такой раздел `complete`, а прогон не печатал НИ СЛОВА: та же связка
    «`spec-coverage: complete` + тишина», ради которой всё писалось. Теперь читаемая форма читается
    (в том числе рядом со `status` и с вложенным текстом), нечитаемая — НАЗЫВАЕТ проблему, а
    молчание оставлено ровно за разделом, не заполненным намеренно.
    """
    (tmp_path / "features" / "w").mkdir(parents=True)
    (tmp_path / "features" / "w" / "spec.yaml").write_text(
        f"schema_version: 1\nkind: FeatureSpec\nworkitem_id: w\nsections:\n  {section}",
        encoding="utf-8")

    text, items, problem = av.criteria_from_spec(tmp_path, "w")

    assert bool(problem) is expect_problem, f"problem={problem!r} при разборе {section!r}"
    assert len(items) == expect_items, items
    if not expect_problem and not expect_items:
        assert text == "", "намеренно не заполненный раздел не выдумывает критерии"


def test_a_section_awaiting_a_human_says_exactly_that(tmp_path):
    """`needs_human` — долг, а не отказ, и диагноз обязан быть верным (третье и четвёртое ревью).

    Третий круг сделал его молчаливым — вернулась связка «spec-coverage ready + прогон молчит»
    (`assess` на `needs_human` не блокирует, и список `needs_human` не читает никто). Четвёртый это
    поймал. Но и «критерии НЕ прочитаны, проверь вручную» — неверная причина: раздел не сломан, он
    ждёт человека. Проверяется именно ФОРМУЛИРОВКА: причина, отправляющая читающего не туда, — это
    та же цена, что причина отсутствующая.
    """
    (tmp_path / "features" / "w").mkdir(parents=True)
    (tmp_path / "features" / "w" / "spec.yaml").write_text(
        "sections:\n  acceptance_criteria:\n    status: needs_human\n", encoding="utf-8")

    _text, items, problem = av.criteria_from_spec(tmp_path, "w")

    assert items == []
    assert problem and "ждёт человека" in problem, problem
    assert "не прочитан" not in problem, f"неверный диагноз: {problem}"


def test_an_unreadable_spec_is_named_not_silently_empty(tmp_path):
    """Спека есть, но не разобрана -> «не знаю» С ПРИЧИНОЙ, а не «критериев нет».

    Третий исход не равен второму (тот же инвариант, что `unknown != not_changed` в контурах):
    молчание тут неотличимо от «критериев не объявляли», и владелец не узнаёт, что сверки не было.
    """
    (tmp_path / "features" / "w").mkdir(parents=True)
    (tmp_path / "features" / "w" / "spec.yaml").write_text("sections: [это, не, мэппинг]\n",
                                                           encoding="utf-8")

    text, items, problem = av.criteria_from_spec(tmp_path, "w")

    assert (text, items) == ("", [])
    assert problem and "мэппинг" in problem, problem


def test_no_spec_at_all_is_not_a_problem(tmp_path):
    """Границы: спеки нет — это «сверять нечего», а не поломка. Иначе предупреждение обесценится."""
    assert av.criteria_from_spec(tmp_path, "нет-такого") == ("", [], None)
