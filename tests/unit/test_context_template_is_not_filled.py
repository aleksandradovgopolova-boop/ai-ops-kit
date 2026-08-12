"""F-027: заготовка контекста не считается заполненным документом.

НАХОДКА (внешнее ревью 12.08.2026). `check_completeness` спрашивал только `is_file()` — то есть
СУЩЕСТВОВАНИЕ файла принималось за ЗАПОЛНЕННОСТЬ. Собственные `ProductStatus.md` и `now.md` кита
лежали шаблонами с инструкцией-заглушкой «заполнить должен child», а валидатор печатал `[OK]` и
`CONTEXT-COMPLETE`.

Это ровно F-018, но в другой подсистеме: там то же самое нашлось у планирования, и детектор
заготовки для плана уже есть (`delivery_plan.is_template`). Один дефект, две подсистемы —
исправлена была одна. Цена выше обычной: `ai-session-start` читает эти документы ПЕРВЫМИ, то есть
сессия начинала работу с шаблона вместо состояния продукта.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
VALIDATOR = KIT / "ai_ops_kit" / "validation" / "validate_context_completeness.py"

TEMPLATE = """---
reviewed_at: '2026-08-11'
status: draft
---

# ProductStatus.md

Заполняется в child-репозитории. Формат — факт + где это работает:

| Область | Статус | Где живёт |
|---|---|---|
| Backend / API | (готово / частично / нет) | (деплой, URL) |
| Frontend | (…) | (что именно) |
| Хранилище | (…) | (СУБД) |
"""

FILLED = """---
reviewed_at: '2026-08-12'
status: actual
---

# ProductStatus.md

| Область | Статус | Чем подтверждено |
|---|---|---|
| Движок | **готово** | 119 модулей, 1915 тестов проходят |
| Провайдеры | **частично** | реализованы anthropic, openai, openai-compatible |
"""


def _child(tmp_path, product_text, now_text):
    d = tmp_path / ".ai" / "project" / "context" / "product"
    d.mkdir(parents=True)
    (d / "ProductStatus.md").write_text(product_text, encoding="utf-8")
    (d.parent / "now.md").write_text(now_text, encoding="utf-8")
    return tmp_path


def _run(root, *args):
    return subprocess.run([sys.executable, str(VALIDATOR), str(root), *args],
                          capture_output=True, text=True, timeout=120)


def _api():
    sys.path.insert(0, str(KIT / "ai_ops_kit" / "validation"))
    import validate_context_completeness as vcc
    return vcc


# ─── fail-closed: шаблон не «есть» ───────────────────────────────────────────────────────────────
@pytest.mark.unit
def test_template_is_not_counted_as_present(tmp_path):
    vcc = _api()
    root = _child(tmp_path, TEMPLATE, TEMPLATE)
    rep = vcc.check_completeness(root)
    assert rep["present"] == [], f"шаблон посчитан заполненным: {rep}"
    assert sorted(rep["template"]) == ["now.md", "product/ProductStatus.md"], rep
    assert rep["complete"] is False


@pytest.mark.unit
def test_output_names_the_template_and_says_why_it_matters(tmp_path):
    root = _child(tmp_path, TEMPLATE, TEMPLATE)
    out = _run(root).stdout
    assert "ЗАГОТОВКА" in out, out[-400:]
    assert "не «есть»" in out, "не сказано, что заготовка это не наличие"
    assert "прочитает их первыми" in out, "не названа цена: сессия начнёт работу с шаблона"


@pytest.mark.unit
def test_strict_fails_on_template(tmp_path):
    """`--strict` обязан краснеть: иначе гейт по контексту закрывается заготовкой."""
    root = _child(tmp_path, TEMPLATE, TEMPLATE)
    assert _run(root, "--strict").returncode == 1


@pytest.mark.unit
def test_detector_does_not_depend_on_line_wrapping():
    """Фраза-маркер, разбитая переносом строки, обязана ловиться.

    Замер: заполненный ProductStatus кита цитировал маркер, объясняя свою историю, и НЕ срабатывал
    только потому, что перенос разбил фразу пополам. Детектор, чей ответ зависит от переноса, —
    это удача, а не проверка.
    """
    vcc = _api()
    wrapped = "# doc\n\n> текст: «Заполняется в\n> child-репозитории».\n"
    assert vcc.is_template(wrapped) is True


# ─── positive: заполненный документ не объявляется заготовкой ────────────────────────────────────
@pytest.mark.unit
def test_filled_document_passes(tmp_path):
    vcc = _api()
    root = _child(tmp_path, FILLED, FILLED)
    rep = vcc.check_completeness(root)
    assert rep["template"] == [], rep
    assert rep["complete"] is True
    assert _run(root, "--strict").returncode == 0


@pytest.mark.unit
def test_missing_is_still_missing(tmp_path):
    """Прежнее поведение не сломано: отсутствующий документ по-прежнему MISSING, а не заготовка."""
    vcc = _api()
    (tmp_path / ".ai" / "project" / "context").mkdir(parents=True)
    rep = vcc.check_completeness(tmp_path)
    assert sorted(rep["missing"]) == ["now.md", "product/ProductStatus.md"], rep
    assert rep["template"] == []


# ─── свои документы: кит — свой лучший child ──────────────────────────────────────────────────────
@pytest.mark.unit
def test_the_kit_own_context_is_filled_not_a_template():
    """Own Medicine, проверяемый: если свои документы снова станут шаблоном — тест краснеет."""
    r = _run(KIT, "--strict")
    assert r.returncode == 0, r.stdout[-600:]
    assert "ЗАГОТОВКА" not in r.stdout, r.stdout[-400:]
