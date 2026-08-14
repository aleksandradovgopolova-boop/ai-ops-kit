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


def test_criteria_are_parsed_without_losing_items():
    """Разбор не теряет критерии: списки, чекбоксы, нумерация, проза — всё становится пунктами.

    Потерянный критерий = «выполнен по умолчанию»: молчание того же класса, что и ложный green.
    """
    assert [c["text"] for c in av.parse_criteria("- один\n* два\n1. три")] == ["один", "два", "три"]
    assert [c["text"] for c in av.parse_criteria("- [ ] чекбокс\n- [x] готов")] == ["чекбокс", "готов"]
    assert [c["id"] for c in av.parse_criteria("одна строка\nдругая строка")] == ["AC-1", "AC-2"]
    assert av.parse_criteria("Критерии:") == [], "заголовок пунктом не является"
    assert av.parse_criteria("") == [] and av.parse_criteria(None) == []


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
