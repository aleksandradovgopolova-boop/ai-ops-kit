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

# ─── positive ─────────────────────────────────────────────────────────────────────────────────

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

# ─── fail-closed ──────────────────────────────────────────────────────────────────────────────

def test_a_verdict_grounded_only_on_the_diff_with_no_read_is_a_rubber_stamp(tmp_path):
    """fail-closed #1 (Fix C, 31.08.2026): met без чтения СУДЬЁЙ и без сверки по доставленному файлу.

    Прежде рубер-штампом было «0 read судьи». Шесть живых замеров показали: судья claude-cli read-op
    детерминированно НЕ эмитит, а цитату сверяет сам кит по доставленному файлу — поэтому
    вовлечённость определяется сверкой с ЭТАЛОНОМ, а не ceremonial read. Здесь met опирается ТОЛЬКО
    на дифф (post-state), а доставленный файл цитаты НЕ содержит (устаревший/частичный дифф): с
    эталоном не сверились ничем — рубер-штамп. Мутация: убери страж FILE_CONFIRMED_BASES из verify —
    вердикт «пройдёт» на одном диффе, и тест краснеет.
    """
    (tmp_path / "README.md").write_text("# Проект\n", encoding="utf-8")   # доставленный файл БЕЗ строки
    ctx = ("diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1,2 @@\n"
           " # Проект\n+public/media/ — каталог медиа\n")   # дифф ДОБАВЛЯЕТ строку, но в файле её нет
    crit = [{"id": "AC-1", "text": "в README есть строка про public/media"}]
    prov = _provider([_verdict([
        {"id": "AC-1", "status": "met", "evidence": "present",
         "quote": "public/media/ — каталог медиа", "source": "README.md"}])])

    rep = av.verify(tmp_path, crit, prov, revision="abc", change_context=ctx)

    assert rep["verified"] is False
    assert rep["met_all"] is None, "«выполнено» не объявляется там, где сверка не состоялась"
    assert "рубер-штамп" in rep["reason"] and "0 reads" in rep["reason"]
    assert not (rep.get("reads") or [])


def test_a_met_confirmed_against_the_delivered_file_stands_without_a_judge_read(tmp_path):
    """positive (Fix C, 31.08.2026): met стоит без read-op СУДЬИ, если КИТ сверил цитату по файлу.

    Ровно поведение живого судьи claude-cli: корректный met выносится сразу, read-op не эмитится
    (шесть замеров). Прежний страж «0 reads» такой вердикт обнулял, и чистая приёмка авто-судьёй
    была недостижима НА ПРАКТИКЕ. Теперь авторитетное чтение доставленного файла делает КИТ: цитата
    есть в доставленном confirm.py -> basis `file` -> сверка состоялась. writer≠judge цел: смысловой
    вердикт вынес независимый судья, а кит лишь подтвердил цитату по эталону. Мутация: верни страж к
    `if not reads` ДО грунтовки — met снова обнуляется, и тест краснеет.
    """
    (tmp_path / "confirm.py").write_text(
        "def should_confirm(proc):\n    if proc.get('under_tmux'):\n        return False\n"
        "    return True\n", encoding="utf-8")
    ctx = ("diff --git a/confirm.py b/confirm.py\n--- /dev/null\n+++ b/confirm.py\n@@ -0,0 +1,4 @@\n"
           "+def should_confirm(proc):\n+    if proc.get('under_tmux'):\n+        return False\n"
           "+    return True\n")
    crit = [{"id": "AC-1", "text": "есть функция should_confirm(proc)"}]
    prov = _provider([_verdict([
        {"id": "AC-1", "status": "met", "evidence": "present",
         "quote": "def should_confirm(proc):", "source": "confirm.py"}])])   # НИ ОДНОГО read

    rep = av.verify(tmp_path, crit, prov, revision="abc", change_context=ctx)

    assert not (rep.get("reads") or []), "судья не читал — читал КИТ при грунтовке"
    assert rep["verified"] is True and rep["met_all"] is True, rep["reason"]
    assert rep["criteria"][0]["basis"] == "file", "met не сверен по доставленному файлу"
    assert rep["quote_verified"] == 1


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


def test_absence_without_a_source_is_not_proof(tmp_path):
    """`absent` без файла — «нигде не нашёл», а это не доказательство. Контракт такое не пропускает."""
    crit = [{"id": "AC-1", "text": "в README нет строк с public/media"}]
    prov = _provider([_read(), _verdict([
        {"id": "AC-1", "status": "met", "evidence": "absent", "quote": "public/media"}])])

    rep = av.verify(tmp_path, crit, prov, revision="abc", change_context="@@ -1 +1 @@\n+текст\n")

    assert rep["verified"] is False
    assert "evidence=absent требует quote и source" in rep["reason"], rep["reason"]


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

# ─── side-effect proof ────────────────────────────────────────────────────────────────────────

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
