"""Ночной обзор: точка отсчёта подтверждается человеком, а находки — не количества.

ПОВОД. Работа `night-review-v0-read-only` была объявлена закрытой 19.08, а в модуле стоял скелет:
дельта считалась ЗА СУТКИ (при обещании «с последнего ПОДТВЕРЖДЁННОГО обзора»), findings были
счётчиками коммитов и файлов, а `--selftest` печатал «пройдено», ничего не вызвав. Работа вернулась
в план по уликам.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ — три свойства, каждое стоило бы дорого без него:

1. **Точка отсчёта.** Сутки вместо подтверждения незаметны человеку: пропущенная ночь молча теряет
   изменения, разобранная дважды показывает одни и те же находки, и бриф правдоподобен в обоих
   случаях. Подтверждение — ДЕЙСТВИЕ (`--confirm`), а не факт отправки.
2. **Своя ошибка вызова — не находка.** Первая редакция звала все валидаторы путём к корню; пять
   из восьми ответили ошибкой использования, и обзор отчитался о них как о РАСХОЖДЕНИЯХ. Отправить
   человека чинить исправное хуже, чем не проверить.
3. **Третье состояние.** Валидатора нет в поставке, артефакта нет в репозитории — это «не
   проверено», а не «нарушений нет».
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.intelligence import nightly_review as nr  # noqa: E402


@pytest.fixture()
def repo(tmp_path):
    """Git-репозиторий с одним коммитом — минимум, на котором обзор осмыслен."""
    root = tmp_path / "product"
    root.mkdir()
    (root / "README.md").write_text("# p\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    for k, v in (("user.email", "t@t.t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(root), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    return root


@pytest.mark.unit
def test_without_a_confirmed_review_the_baseline_says_so(repo):
    b = nr.review_baseline(repo)
    assert b["kind"] == "fallback" and b["since"] is None
    assert "не было" in b["reason"], b["reason"]


@pytest.mark.unit
def test_confirming_moves_the_baseline_to_that_commit(repo):
    rec = nr.confirm_review(repo)
    assert rec["commit_sha"], rec
    b = nr.review_baseline(repo)
    assert b["kind"] == "confirmed" and b["since"] == rec["commit_sha"]


@pytest.mark.unit
def test_a_broken_confirmation_is_a_third_state_not_a_missing_one(repo):
    """Битая запись не равна отсутствию: иначе она молча сдвинула бы отсчёт на сутки."""
    p = repo / nr.CONFIRMED_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{это не json", encoding="utf-8")
    b = nr.review_baseline(repo)
    assert b["kind"] == "unreadable", b
    assert "НЕ подтверждена" in b["reason"], b["reason"]


@pytest.mark.unit
def test_a_confirmation_without_a_sha_is_not_trusted(repo):
    p = repo / nr.CONFIRMED_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"confirmed_at": "вчера"}), encoding="utf-8")
    assert nr.review_baseline(repo)["kind"] == "unreadable"


@pytest.mark.unit
def test_a_missing_validator_is_unknown_not_clean(repo):
    """Пустая дочка: валидаторов нет вовсе — обзор обязан сказать «не проверено»."""
    findings = nr.run_checks(repo)
    assert findings, "проверок не выполнено ни одной и об этом не сказано"
    assert all(f["ok"] is None for f in findings), [f for f in findings if f["ok"] is not None]
    assert all(f["detail"] for f in findings), "непроверенное без причины"


@pytest.mark.unit
def test_a_missing_artifact_is_unknown_not_a_finding(tmp_path):
    """Артефакта нет — проверять нечего. Это НЕ расхождение."""
    root = tmp_path / "kit"
    (root / "ai_ops_kit" / "validation").mkdir(parents=True)
    script = root / "ai_ops_kit" / "validation" / "validate_event_catalog.py"
    script.write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    f = next(x for x in nr.run_checks(root) if x["check"] == "события")
    assert f["ok"] is None and "нет" in f["detail"], f


@pytest.mark.unit
def test_a_wrong_invocation_is_not_reported_as_a_defect(tmp_path):
    """Валидатор ответил подсказкой по использованию — значит позвали не так, а не сломано."""
    root = tmp_path / "kit"
    (root / "ai_ops_kit" / "validation").mkdir(parents=True)
    (root / "ai_ops_kit" / "validation" / "validate_freshness.py").write_text(
        "import sys\nprint('использование: validate_freshness.py <файл>')\nsys.exit(2)\n",
        encoding="utf-8")
    f = next(x for x in nr.run_checks(root) if x["check"] == "документация")
    assert f["ok"] is None, f"своя ошибка вызова выдана за расхождение: {f}"
    assert "позвали неверно" in f["detail"], f


@pytest.mark.unit
def test_a_real_discrepancy_is_reported_as_one(tmp_path):
    """Обратная сторона: валидатор упал по существу — это находка, а не «не проверено»."""
    root = tmp_path / "kit"
    (root / "ai_ops_kit" / "validation").mkdir(parents=True)
    (root / "ai_ops_kit" / "validation" / "validate_references.py").write_text(
        "import sys\nprint('REFERENCES: 3 ссылки ведут в никуда')\nsys.exit(1)\n",
        encoding="utf-8")
    f = next(x for x in nr.run_checks(root) if x["check"] == "ссылки")
    assert f["ok"] is False, f
    assert "ведут в никуда" in f["detail"], f


@pytest.mark.unit
def test_the_brief_answers_the_five_questions(repo):
    brief = nr.format_brief(nr.collect_delta(repo), repo)
    for head in ("Что изменилось", "Что я проверила", "Чего я не стала делать и почему",
                 "Где нужно твоё решение", "Что важнее всего сегодня"):
        assert head in brief, f"в брифе нет раздела «{head}»:\n{brief[:500]}"


@pytest.mark.unit
def test_the_brief_says_read_only_is_a_boundary_not_an_omission(repo):
    brief = nr.format_brief(nr.collect_delta(repo), repo)
    assert "только на чтение" in brief and "граница выпуска" in brief, brief[:600]


@pytest.mark.unit
def test_an_unconfirmed_baseline_is_named_in_the_brief(repo):
    """Человек обязан видеть, что точка отсчёта не подтверждена — иначе бриф выглядит полным."""
    brief = nr.format_brief(nr.collect_delta(repo), repo)
    assert "не подтверждённая точка отсчёта" in brief, brief[:600]
    nr.confirm_review(repo)
    assert "не подтверждённая точка отсчёта" not in nr.format_brief(nr.collect_delta(repo), repo)
