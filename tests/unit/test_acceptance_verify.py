"""Сверка критериев приёмки с результатом (B2-14, вторая половина).

ПОВОД — ЗАМЕР ЖИВОГО ПРОГОНА. BNBM 14.08.2026: draft PR со `sha_verified: True` и
`overall_status: delivered`, критерий приёмки «в README нет строк с `public/media`» НЕ выполнен
(строка осталась), `spec-coverage` — `acceptance_criteria: complete`. Первая половина правки
(#111) перестала выдавать непроверенное за проверенное; здесь проверяется САМА СВЕРКА.

Что именно защищается тестами:
  * positive — сверка выносит вердикт по каждому критерию и опирается на цитату из диффа;
  * реальный сценарий B2-14 — критерий про отсутствие строки, строка есть -> unmet НАЗВАН;
  * fail-closed × 5 — рубер-штамп (0 reads), выдуманная цитата, met без основания, неполный
    вердикт, отсутствие судьи: каждый исход даёт `verified=false` с НАЗВАННОЙ причиной;
  * side-effect proof — судья действительно гонялся под read-only: попытка write отклонена
    брокером, дерево не изменилось, и это доказано ПРЕЖДЕ проверки реакции на вердикт.

Мутационная проверка (`rules/core/field-lessons.yaml`): каждый fail-closed тест краснеет, если
соответствующую проверку в `acceptance_verify.verify` убрать — именно этим и проверялась их польза,
а не тем, что они зелёные.
"""
from __future__ import annotations

import json

import pytest

from ai_ops_kit.engine import acceptance_verify as av

CRITERIA = [{"id": "AC-1", "text": "в README нет строк с `public/media`"},
            {"id": "AC-2", "text": "описание структуры проекта соответствует репозиторию"}]

DIFF = """Изменённые файлы (git show --stat @ abc123456789):
 README.md | 4 +-

Unified-дифф ревизии:
--- a/README.md
+++ b/README.md
@@ -10,3 +10,3 @@
-public/media/ — медиафайлы проекта
+public/media/ — каталог медиа
+src/ — исходный код
"""


def _provider(replies):
    """Провайдер-судья по скрипту: n-й вызов -> n-я реплика. Лишние вызовы -> последняя реплика."""
    calls = {"n": 0}

    def provider(_prompt):
        i = min(calls["n"], len(replies) - 1)
        calls["n"] += 1
        return replies[i] if isinstance(replies[i], str) else json.dumps(replies[i])
    provider.calls = calls
    return provider


def _read(path="README.md"):
    return {"op": "read", "path": path}


def _verdict(items):
    return {"kind": "acceptance-result", "criteria": items}


@pytest.fixture()
def tree(tmp_path):
    (tmp_path / "README.md").write_text(
        "# Проект\n\npublic/media/ — каталог медиа\nsrc/ — исходный код\n", encoding="utf-8")
    return tmp_path


# ─── positive ──────────────────────────────────────────────────────────────────────────────────

def test_verdict_with_grounded_quotes_is_a_real_verification(tree):
    """positive: вердикт по каждому критерию + цитата, найденная в диффе -> сверка состоялась."""
    prov = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "met", "quote": "public/media/ — каталог медиа",
         "source": "README.md", "reason": "строка приведена к реальности"},
        {"id": "AC-2", "status": "met", "quote": "src/ — исходный код", "source": "README.md"},
    ])])

    rep = av.verify(tree, CRITERIA, prov, revision="abc123456789", change_context=DIFF)

    assert rep["verified"] is True, rep["reason"]
    assert rep["met_all"] is True
    assert rep["verifier"] and "abc123456789"[:12] in rep["verifier"]
    assert [c["grounded"] for c in rep["criteria"]] == [True, True]
    assert rep["reads"], "судья вынес вердикт, ничего не прочитав — это не сверка"


def test_the_bnbm_case_is_caught_unmet_criterion_is_named(tree):
    """Тот самый ложный green: критерий требует ОТСУТСТВИЯ строки, а строка в диффе есть.

    Это главный тест работы: до неё прогон печатал `delivered` и молчал. Здесь сверка состоялась
    (`verified=True`) и при этом сказала «не выполнено» — два разных факта, и оба нужны.
    """
    prov = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "unmet", "quote": "public/media/ — каталог медиа",
         "source": "README.md", "reason": "строка с public/media осталась в README"},
        {"id": "AC-2", "status": "met", "quote": "src/ — исходный код", "source": "README.md"},
    ])])

    rep = av.verify(tree, CRITERIA, prov, revision="abc123456789", change_context=DIFF)

    assert rep["verified"] is True, "сверка состоялась — вердикты вынесены и обоснованы"
    assert rep["met_all"] is False, "критерий не выполнен, а сверка сообщает об обратном"
    assert rep["unmet"] == ["AC-1"]
    assert "НЕ ВЫПОЛНЕНО" in rep["reason"]


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


def test_prose_after_a_truncated_diff_is_not_evidence(tmp_path):
    """Четвёртое ревью PR #118: инвариант «основанием может быть только тело ханка» должен держаться КОДОМ.

    Правка про `\\ No newline` убрала закрытие ханка на неизвестном префиксе — и проза после
    усечённого диффа снова становилась «содержимым». Сегодня оба сборщика контекста кладут дифф
    последним, поэтому дыра не эксплуатировалась; инвариант, который держится порядком рендеринга,
    а не проверкой, — это отложенный дефект.
    """
    ctx = ("diff --git a/f.txt b/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n"
           "-старое\n+новое\n"
           "... [дифф усечён на 14000 симв.]\n"
           "-это не дифф\n+и это не дифф\n")

    post, removed = av._post_state(ctx)

    assert "новое" in post and "старое" in removed, "тело ханка потеряно"
    assert "и это не дифф" not in post, f"проза после усечения стала содержимым: {post!r}"
    assert "это не дифф" not in removed, f"проза после усечения стала удалённой строкой: {removed!r}"


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


# ─── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_rubber_stamp_without_a_single_read_is_not_a_verification(tree):
    """fail-closed #1: вердикт без единого чтения. Тот же инвариант, что для блокирующих гейтов."""
    prov = _provider([_verdict([
        {"id": "AC-1", "status": "met", "quote": "public/media/ — каталог медиа", "source": "README.md"},
        {"id": "AC-2", "status": "met", "quote": "src/ — исходный код", "source": "README.md"},
    ])])

    rep = av.verify(tree, CRITERIA, prov, revision="abc", change_context=DIFF)

    assert rep["verified"] is False
    assert rep["met_all"] is None, "«выполнено» не объявляется там, где сверка не состоялась"
    assert "рубер-штамп" in rep["reason"] and "0 reads" in rep["reason"]


def test_invented_quote_does_not_close_a_criterion(tree):
    """fail-closed #2: цитаты нет ни в диффе, ни в файле -> вердикт не принимается.

    Единственная защита от красиво написанного вердикта, стоящего ни на чём. Симметрия: выдуманная
    цитата не закрывает критерий и не объявляет его провалённым — оба вердикта стояли бы на воздухе.
    """
    prov = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "met", "quote": "строк с public/media в README больше нет",
         "source": "README.md"},
        {"id": "AC-2", "status": "met", "quote": "src/ — исходный код", "source": "README.md"},
    ])])

    rep = av.verify(tree, CRITERIA, prov, revision="abc", change_context=DIFF)

    assert rep["verified"] is False
    assert rep["undetermined"] == ["AC-1"]
    ac1 = rep["criteria"][0]
    assert ac1["status"] == "undetermined" and ac1["grounded"] is False
    assert "основание не подтверждено" in ac1["reason"]


def test_a_one_letter_quote_grounds_in_anything_and_is_rejected(tree):
    """fail-closed #2b: слишком короткая цитата подтвердилась бы в ЛЮБОМ тексте.

    Без порога длины проверка основания превращалась бы в ритуал: `quote: "a"` находится всегда, и
    механическая проверка цитаты давала бы «подтверждено» на пустом месте.
    """
    prov = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "met", "quote": "—", "source": "README.md"},
        {"id": "AC-2", "status": "met", "quote": "src/ — исходный код", "source": "README.md"},
    ])])

    rep = av.verify(tree, CRITERIA, prov, revision="abc", change_context=DIFF)

    assert rep["verified"] is False
    assert rep["undetermined"] == ["AC-1"]
    assert "короче" in rep["criteria"][0]["reason"]


def test_met_cannot_stand_on_a_line_that_no_longer_exists(tmp_path):
    """fail-closed #2c: `met` с цитатой УДАЛЁННОЙ строки — это и есть форма B2-14.

    Судья цитировал прежнюю строку про `public/media` и ставил «выполнено». Проверка здесь — О
    ФОРМЕ, а не о смысле: «выполнено» не может опираться на текст, которого в результате нет.
    Критерий об ОТСУТСТВИИ этой проверкой не задет — у него `evidence="absent"` и своё
    доказательство (см. тест про доказуемое отсутствие ниже). Именно это разделение и позволило
    закрыть класс: три круга ревью до него проверка либо принимала прошлое за результат, либо
    отвергала честный вердикт об отсутствии.
    """
    (tmp_path / "README.md").write_text("# Проект\n\nмедиа в проекте нет\n", encoding="utf-8")
    diff = ("Unified-дифф ревизии:\n--- a/README.md\n+++ b/README.md\n@@ -1,3 +1,3 @@\n"
            "-public/media/ — медиафайлы проекта\n+медиа в проекте нет\n")
    crit = [{"id": "AC-1", "text": "в README нет строк с `public/media`"}]
    prov = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "met", "quote": "public/media/ — медиафайлы проекта",
         "source": "README.md"}])])

    rep = av.verify(tmp_path, crit, prov, revision="abc", change_context=diff)

    assert rep["verified"] is False
    assert rep["undetermined"] == ["AC-1"]
    assert "УДАЛЁННУЮ" in rep["criteria"][0]["reason"], rep["criteria"][0]["reason"]


def test_a_commit_message_is_not_evidence(tmp_path):
    """fail-closed #2d (второе ревью PR #118): судья цитировал СООБЩЕНИЕ КОММИТА писателя.

    Дыру создала правка про диапазон base..head: в контекст попал `git log --oneline`, а сообщение
    коммита — это `ai-ops: <текст задачи>`, то есть пересказ критерия. Цитата находилась, основание
    «подтверждалось», отчёт печатал «выполнены все». Содержимым считается только тело ханка —
    ни журнал коммитов, ни `--stat`, ни проза вокруг диффа.
    """
    (tmp_path / "README.md").write_text("# Проект\n\npublic/media/ — каталог медиа\n", encoding="utf-8")
    ctx = ("ИНТЕГРИРОВАННЫЙ дифф последовательности aaaaaaa..bbbbbbb:\ngit diff --stat:\n"
           " README.md | 2 +-\n\nКоммиты диапазона (по пакетам):\n"
           "bbbbbbb ai-ops: в README больше нет строк с public/media\n\n"
           "Combined unified-дифф base..head:\ndiff --git a/README.md b/README.md\n"
           "--- a/README.md\n+++ b/README.md\n@@ -1,3 +1,3 @@\n"
           "-public/media/ — медиафайлы проекта\n+public/media/ — каталог медиа\n")

    basis, why = av._ground_quote("в README больше нет строк с public/media", ctx, tmp_path,
                                  "README.md")
    assert basis is None, f"сообщение коммита принято за основание ({basis})"
    assert av._ground_quote(" README.md | 2 +-", ctx, tmp_path, "README.md")[0] is None, (
        "строка статистики диффа принята за содержимое")
    # а настоящее содержимое ханка по-прежнему заземляется
    assert av._ground_quote("public/media/ — каталог медиа", ctx, tmp_path,
                            "README.md")[0] in av.STRONG_BASIS, why


def test_absence_is_provable_and_a_masked_removal_is_caught(tmp_path):
    """Критерий об ОТСУТСТВИИ доказуем — и доказательство сильнее прежнего (второе ревью PR #118).

    До этого при чистом удалении единственным дословным свидетельством была удалённая строка, а её
    заземление справедливо отвергает: критерий уходил в `undetermined`, и прогон печатал «критерии
    НЕ сверялись» при том что всё выполнено. `evidence=absent` проверяется чтением файла — и тот же
    механизм ловит ЗАМАСКИРОВАННОЕ удаление, на котором и родился B2-14.
    """
    (tmp_path / "README.md").write_text("# Проект\n\nмедиа в проекте нет\n", encoding="utf-8")
    ctx = ("diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1,3 +1,3 @@\n"
           "-public/media/ — медиафайлы проекта\n+медиа в проекте нет\n")
    crit = [{"id": "AC-1", "text": "в README больше нет строк с `public/media`"}]

    # (а) честное удаление: отсутствие подтверждено чтением файла
    prov = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "met", "evidence": "absent", "quote": "public/media",
         "source": "README.md"}])])
    rep = av.verify(tmp_path, crit, prov, revision="abc", change_context=ctx)
    assert rep["verified"] is True and rep["met_all"] is True, rep["reason"]

    # (б) замаскированное удаление: строка осталась в другом виде — основание ОПРОВЕРГНУТО чтением
    (tmp_path / "README.md").write_text("# Проект\n\npublic/media/ — каталог медиа\n", encoding="utf-8")
    prov2 = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "met", "evidence": "absent", "quote": "public/media",
         "source": "README.md"}])])
    rep2 = av.verify(tmp_path, crit, prov2, revision="abc", change_context=ctx)
    assert rep2["verified"] is False and rep2["undetermined"] == ["AC-1"]
    assert "В ФАЙЛЕ ЕСТЬ" in rep2["criteria"][0]["reason"], rep2["criteria"][0]["reason"]


def test_an_unproven_absence_claim_is_named_not_silently_accepted(tmp_path):
    """ГРАНИЦА МЕХАНИЗМА, названная прямо (четвёртое ревью PR #118).

    Третий круг требовал, чтобы `absent` подтверждался удалённой строкой, — и тем сделал выполненный
    критерий об отсутствии НЕДОКАЗУЕМЫМ: удаления могло не быть вовсе, дифф мог быть усечён, а
    промпт судьи прямо запрещал цитировать удалённое. Отвергать честный вердикт нельзя: сломанную
    проверку выключают.

    Поэтому недоказанное отсутствие вердикт НЕ отменяет, но и не выдаётся за проверенное: основание
    называется `judge-only`, критерий попадает в `judge_only`, `quote_verified` его не считает, и
    вывод прогона прямо просит владельца проверить эти критерии самому. Это ЧЕСТНАЯ, но более слабая
    гарантия, чем «код доказал», — и именно так она и записана.
    """
    (tmp_path / "README.md").write_text("# Проект\n", encoding="utf-8")
    ctx = "diff --git a/app.py b/app.py\n@@ -1 +1 @@\n-import os\n+import sys\n"
    crit = [{"id": "AC-1", "text": "эндпоинт /health отвечает 200"}]
    prov = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "met", "evidence": "absent",
         "quote": "эндпоинт /health отвечает 200", "source": "README.md"}])])

    rep = av.verify(tmp_path, crit, prov, revision="abc", change_context=ctx)

    assert rep["verified"] is True, "вердикт судьи отвергнут — механизм снова ломается на честной работе"
    assert rep["quote_verified"] == 0, "недоказанное отсутствие посчитано подтверждённым цитатой"
    assert rep["judge_only"] == ["AC-1"]
    assert rep["criteria"][0]["basis"] == "judge-only"
    assert rep["criteria"][0]["grounded"] is False
    assert "только суждением судьи" in rep["reason"], rep["reason"]


def test_a_removed_line_from_another_file_does_not_prove_absence(tmp_path):
    """Обход, отодвинутый третьим кругом: удалённая строка ИЗ ДРУГОГО файла (четвёртое ревью).

    `removed` был объединением всех удалённых строк диффа, поэтому отсутствие в README
    «доказывалось» строкой, удалённой из `app.py`. Доказательство теперь пофайловое: сильным
    основанием считается только удаление ИЗ ТОГО ЖЕ файла, о котором говорит вердикт.
    """
    (tmp_path / "README.md").write_text("# Проект\nсм. public/media/logo.png\n", encoding="utf-8")
    ctx = "diff --git a/app.py b/app.py\n@@ -1 +1 @@\n-import os\n+import sys\n"

    basis, why = av._ground_quote("import os", ctx, tmp_path, "README.md", "absent")

    assert basis not in av.STRONG_BASIS, f"чужое удаление принято за доказательство ({basis})"
    assert basis == "judge-only" and "не удалялась" in why, why


def test_absence_without_a_source_is_not_proof(tmp_path):
    """`absent` без файла — «нигде не нашёл», а это не доказательство. Контракт такое не пропускает."""
    crit = [{"id": "AC-1", "text": "в README нет строк с public/media"}]
    prov = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "met", "evidence": "absent", "quote": "public/media"}])])

    rep = av.verify(tmp_path, crit, prov, revision="abc", change_context="@@ -1 +1 @@\n+текст\n")

    assert rep["verified"] is False
    assert "evidence=absent требует quote и source" in rep["reason"], rep["reason"]


def test_a_no_newline_marker_does_not_hide_the_added_line(tmp_path):
    """Третье ревью PR #118: `\\ No newline at end of file` обрывал ханк.

    Git ставит эту строку МЕЖДУ удалённым и добавленным вариантом последней строки файла. Прежний
    разбор считал неизвестный префикс концом ханка — и добавленная строка становилась невидимой для
    заземления: судья лишался основного пути подтверждения, а сверка объявлялась неполной на
    работе, которая сделана.
    """
    ctx = ("diff --git a/f.txt b/f.txt\n--- a/f.txt\n+++ b/f.txt\n@@ -1,2 +1,2 @@\n"
           " оставили\n-старый хвост\n\\ No newline at end of file\n+новый хвост здесь\n")

    post, removed = av._post_state(ctx)

    assert "новый хвост здесь" in post, f"добавленная строка потеряна: {post!r}"
    assert "старый хвост" in removed


def test_diff_content_that_looks_like_a_file_header_survives(tmp_path):
    """Третье ревью: удалённая строка `-- комментарий` рендерится как `--- …` и убивала ханк.

    Отсекать заголовки по префиксу можно только ВНЕ ханка: внутри ханка `--- ` — это удалённая
    строка, чей текст начинается с `-- ` (например SQL-комментарий). Прежняя проверка выбрасывала
    её вместе с остатком ханка, то есть теряла и добавленные строки.
    """
    ctx = ("diff --git a/q.sql b/q.sql\n--- a/q.sql\n+++ b/q.sql\n@@ -1,2 +1,2 @@\n"
           " select 1\n--- old sql comment\n+select 2\n+public/media added here\n")

    post, removed = av._post_state(ctx)

    assert "select 2" in post and "public/media added here" in post, f"тело ханка потеряно: {post!r}"
    assert "- old sql comment" in removed


def test_an_added_line_starting_with_pluses_is_not_a_file_header(tmp_path):
    """Пятое ревью PR #118: зеркало регрессии `--- ` — добавленная строка на `++ `.

    Она рендерится как `+++ …`, читалась заголовком файла, убивала остаток ханка И сама исчезала из
    результата. Судья, цитирующий её, получал «цитата выдумана» -> `undetermined` -> «критерии НЕ
    сверялись» на выполненной работе. В коде рядом стоял комментарий, прямо запрещающий такую
    проверку внутри ханка, — и я повторил её для `+`.
    """
    ctx = ("diff --git a/f.md b/f.md\n--- a/f.md\n+++ b/f.md\n@@ -1 +1,3 @@\n"
           " было\n++ note\n+важная строка критерия\n")

    by_file = av._diff_by_file(ctx)

    assert set(by_file) == {"f.md"}, f"выдуманный путь из тела ханка: {sorted(by_file)}"
    assert "важная строка критерия" in by_file["f.md"][0], f"строка критерия потеряна: {by_file}"
    assert "+ note" in by_file["f.md"][0]


def test_a_refuted_absence_claim_confirms_unmet_instead_of_erasing_it(tmp_path):
    """Пятое ревью PR #118: опровергнутое отсутствие обнуляло ВЕРНЫЙ `unmet`.

    Судья говорит «строки public/media в README нет», код читает файл и видит её — то есть критерий
    НЕ ВЫПОЛНЕН, и это ровно поимка B2-14. Прежний код считал такую цитату выдуманной и печатал
    «критерии НЕ сверялись» вместо «НЕ ВЫПОЛНЕНО 1 из 1»: сверка, поймавшая дефект, отчитывалась
    как несостоявшаяся. Цитата настоящая — опровергнуто ЗАЯВЛЕНИЕ, а не она.
    """
    (tmp_path / "README.md").write_text("# Проект\npublic/media/ — каталог медиа\n", encoding="utf-8")
    ctx = ("diff --git a/README.md b/README.md\n@@ -1,2 +1,2 @@\n"
           "-public/media/ — медиафайлы проекта\n+public/media/ — каталог медиа\n")
    crit = [{"id": "AC-1", "text": "в README нет строк с `public/media`"}]

    prov = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "unmet", "evidence": "absent", "quote": "public/media",
         "source": "README.md", "reason": "строка осталась"}])])
    rep = av.verify(tmp_path, crit, prov, revision="abc", change_context=ctx)

    assert rep["verified"] is True, f"сверка объявлена несостоявшейся: {rep['reason']}"
    assert rep["met_all"] is False and rep["unmet"] == ["AC-1"]
    assert rep["criteria"][0]["grounded"] is True, "опровергнутое отсутствие — сильное основание"

    # а `met` против прочитанного файла — это и есть B2-14, и он по-прежнему не принимается
    prov2 = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "met", "evidence": "absent", "quote": "public/media",
         "source": "README.md"}])])
    rep2 = av.verify(tmp_path, crit, prov2, revision="abc", change_context=ctx)
    assert rep2["verified"] is False and rep2["undetermined"] == ["AC-1"]
    assert "В ФАЙЛЕ ЕСТЬ" in rep2["criteria"][0]["reason"]


def test_a_source_path_variant_does_not_lose_the_proof(tmp_path):
    """Пятое ревью: `./README.md` терял `absence-proof` и получал НЕВЕРНУЮ причину.

    Причина говорила «эта строка не удалялась в этом изменении», хотя она удалялась. Неверная
    причина хуже отсутствующей: владелец идёт проверять не туда.
    """
    (tmp_path / "README.md").write_text("# Проект\n", encoding="utf-8")
    ctx = ("diff --git a/README.md b/README.md\n@@ -1,2 +1 @@\n"
           "-public/media/ — медиафайлы проекта\n+# Проект\n")

    for src in ("README.md", "./README.md", "b/README.md"):
        basis, why = av._ground_quote("public/media", ctx, tmp_path, src, "absent")
        assert basis == "absence-proof", f"{src}: основание потеряно ({basis}, {why})"


def test_owner_check_required_is_in_the_report_not_only_in_stdout(tmp_path):
    """Пятое ревью: «выполнены все» при нуле подтверждённых оснований жило только в терминале.

    Любая другая поверхность — PR, расписка о доставке, наблюдаемость — читала такой отчёт как
    проверенный. Факт «это надо посмотреть самому» обязан быть В ДАННЫХ, иначе он не доедет.
    """
    (tmp_path / "README.md").write_text("# Проект\n", encoding="utf-8")
    ctx = "diff --git a/app.py b/app.py\n@@ -1 +1 @@\n-import os\n+import sys\n"
    crit = [{"id": "AC-1", "text": "эндпоинт /health отвечает 200"}]
    prov = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "met", "evidence": "absent",
         "quote": "сервис не отвечает на /health", "source": "README.md"}])])

    rep = av.verify(tmp_path, crit, prov, revision="abc", change_context=ctx)

    assert rep["met_all"] is True and rep["quote_verified"] == 0
    assert rep["owner_check_required"] is True, "слабое «выполнено» не помечено в отчёте"


def test_a_removed_line_starting_with_dashes_is_still_recognised(tmp_path):
    """Второе ревью, низкий приоритет: удалённая строка на `--` считалась заголовком диффа.

    Она не попадала ни в результат, ни в удалённые — и информативная причина «цитата только в
    УДАЛЁННОЙ строке» деградировала до общей «не найдена». Причина, потерявшая конкретику,
    отправляет читающего искать не там.
    """
    (tmp_path / "README.md").write_text("# Проект\n", encoding="utf-8")
    ctx = ("diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1,2 +1 @@\n"
           "---старый разделитель\n+# Проект\n")

    basis, why = av._ground_quote("--старый разделитель", ctx, tmp_path, "README.md")

    assert basis == "removed-line", f"удалённая строка не распознана: {basis} ({why})"
    assert basis not in av.STRONG_BASIS, "основание о состоянии ДО правки не может быть сильным"
    assert "ДО" in why, why


def test_a_moved_line_is_still_grounded_if_it_lives_in_the_file(tmp_path):
    """Границы того же правила: перенесённая строка выглядит удалённой, но живёт в файле.

    Отвергать её значило бы краснеть на честной цитате — проверка основания должна отделять
    «этого больше нет» от «это переехало», иначе её научатся обходить как шумную.
    """
    (tmp_path / "README.md").write_text("# Проект\n\nsrc/ — исходный код\n", encoding="utf-8")
    diff = ("--- a/README.md\n+++ b/README.md\n@@ -1,3 +1,3 @@\n"
            "-src/ — исходный код\n+## Структура\n")
    crit = [{"id": "AC-1", "text": "структура описана"}]
    prov = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "met", "quote": "src/ — исходный код", "source": "README.md"}])])

    rep = av.verify(tmp_path, crit, prov, revision="abc", change_context=diff)

    assert rep["verified"] is True and rep["met_all"] is True, rep["reason"]


def test_met_without_a_quote_breaks_the_contract(tree):
    """fail-closed #3: «выполнено» без цитаты неопровержимо — контракт такое не пропускает."""
    prov = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "met", "reason": "выглядит нормально"},
        {"id": "AC-2", "status": "met", "quote": "src/ — исходный код", "source": "README.md"},
    ])])

    rep = av.verify(tree, CRITERIA, prov, revision="abc", change_context=DIFF)

    assert rep["verified"] is False
    assert "контракту" in rep["reason"] and "AC-1" in rep["reason"]


def test_a_missing_criterion_verdict_makes_the_check_incomplete(tree):
    """fail-closed #4: вердикт не по всем критериям. Пропуск ≠ «выполнен по умолчанию»."""
    prov = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "met", "quote": "public/media/ — каталог медиа", "source": "README.md"},
    ])])

    rep = av.verify(tree, CRITERIA, prov, revision="abc", change_context=DIFF)

    assert rep["verified"] is False
    assert "AC-2" in rep["reason"] and "сверка неполна" in rep["reason"]


def test_no_judge_means_not_verified_not_verified_ok(tree):
    """fail-closed #5: судьи нет (offline / без провайдера) -> «не сверялись» с причиной."""
    rep = av.verify(tree, CRITERIA, None, revision="abc", change_context=DIFF)

    assert rep["verified"] is False and rep["met_all"] is None
    assert "ревьюер недоступен" in rep["reason"]
    assert rep["count"] == 2 and rep["declared"] is True
    assert all(c["status"] == "undetermined" for c in rep["criteria"])


def test_no_verdict_at_all_is_not_silence(tree):
    """Судья не заключил ничего: причина названа, «сверено» не объявлено."""
    prov = _provider(["не могу разобрать задачу"])

    rep = av.verify(tree, CRITERIA, prov, revision="abc", change_context=DIFF)

    assert rep["verified"] is False
    assert "не вынес вердикт" in rep["reason"]


def test_absent_criteria_are_a_separate_state(tree):
    """Критериев не объявляли — это не провал сверки, а «сверять нечего»."""
    rep = av.verify(tree, [], _provider([_verdict([])]), revision="abc", change_context=DIFF)

    assert rep["declared"] is False and rep["verified"] is False
    assert "не объявлены" in rep["reason"]


# ─── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_judge_runs_read_only_and_cannot_touch_the_tree(tree):
    """side-effect proof: судья ДЕЙСТВИТЕЛЬНО гонялся под read-only Policy.

    Сперва доказываем сам факт работы судьи (чтение состоялось, попытка записи отклонена брокером,
    файл на диске не изменился) — и только потом смотрим на вердикт. Иначе тест на реакцию гейта
    прошёл бы и на судье, которого никто не вызывал.
    """
    before = (tree / "README.md").read_text(encoding="utf-8")
    prov = _provider([
        {"op": "write", "path": "README.md", "content": "перепишу сам"},
        _read(),
        _verdict([
            {"id": "AC-1", "status": "unmet", "quote": "public/media/ — каталог медиа",
             "source": "README.md", "reason": "строка осталась"},
            {"id": "AC-2", "status": "met", "quote": "src/ — исходный код", "source": "README.md"},
        ]),
    ])

    rep = av.verify(tree, CRITERIA, prov, revision="abc", change_context=DIFF)

    assert rep["reads"], "судья ничего не прочитал — доказывать реакцию на его вердикт нечего"
    assert rep["denied"], "попытка записи не отклонена — судья не был read-only"
    assert any((d.get("op") == "write") for d in rep["denied"])
    assert (tree / "README.md").read_text(encoding="utf-8") == before, "дерево изменено ревьюером"
    assert sorted(p.name for p in tree.iterdir()) == ["README.md"], "судья создал файлы"
    # и только теперь — реакция на вердикт
    assert rep["verified"] is True and rep["unmet"] == ["AC-1"]


def test_the_denial_nudge_asks_for_the_right_kind_of_verdict(tree):
    """Ревью PR #118: отказ брокера советовал судье приёмки вернуть ЧУЖОЙ вид вердикта.

    Четыре нуджа петли параметризованы, а этот остался с зашитым `reviewer-result`. Судья, честно
    послушавшийся подсказки, вернул бы вердикт без `criteria` — терминальную проверку он не
    проходит, шаги сгорают, исход «ревьюер не вынес вердикт». Подсказка неверна ровно там, куда
    судья попадает при попытке записи, — то есть в ветке отказа, как B2-10/B2-11.
    """
    seen = []

    def watching_provider(prompt):
        seen.append(prompt)
        if len(seen) == 1:
            return json.dumps({"op": "write", "path": "README.md", "content": "правлю сам"})
        if len(seen) == 2:
            return json.dumps(_read())
        return json.dumps(_verdict([
            {"id": "AC-1", "status": "met", "quote": "public/media/ — каталог медиа",
             "source": "README.md"},
            {"id": "AC-2", "status": "met", "quote": "src/ — исходный код", "source": "README.md"}]))

    av.verify(tree, CRITERIA, watching_provider, revision="abc", change_context=DIFF)

    after_denial = seen[1]
    assert "ОТКЛОНЕНО" in after_denial, "тест смотрит не на тот шаг — отказа в контексте нет"
    assert "acceptance-result" in after_denial.split("ОТКЛОНЕНО", 1)[1], (
        "после отказа судью просят вернуть вердикт чужой формы")
