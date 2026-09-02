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


@pytest.mark.unit
def test_a_document_of_another_kind_is_not_a_finding(tmp_path):
    """Ошибка вызова ВТОРОГО РОДА: файл есть, валидатор запускается — и проверяет не тот документ.

    ЗАМЕР 20.08.2026. Проверке «план» подали `planning/plan.yaml` (kind: delivery-plan), а
    `validate_plan_artifact` проверяет RunPlan ФИЧИ (kind: plan-artifact). Он честно ответил
    «kind должен быть plan-artifact» — а обзор выдал этот ответ за РАСХОЖДЕНИЕ и трижды сообщил
    владельцу о дефекте, которого нет.

    Первая защита ловила ответ «ты позвал не так» по тексту. Эта разновидность так не ловится:
    вызов синтаксически верен. Поэтому род документа сверяется ДО запуска — по его же полю `kind`.

    Урок шире самого случая: механизм закрывает тот класс, который ты понял, а не тот, который
    существует. Ради этого v0 обкатывается на ките, а не сразу в поле: у владельца такая находка
    отправила бы чинить исправный план, и доверие к утреннему брифу кончилось бы на первой неделе.
    """
    root = tmp_path / "kit"
    (root / "ai_ops_kit" / "validation").mkdir(parents=True)
    (root / "ai_ops_kit" / "validation" / "validate_plan_artifact.py").write_text(
        "import sys\nprint('kind должен быть plan-artifact')\nsys.exit(1)\n", encoding="utf-8")
    (root / "features" / "wi-1").mkdir(parents=True)
    (root / "features" / "wi-1" / "plan.yaml").write_text(
        "kind: delivery-plan\n", encoding="utf-8")     # НЕ тот род

    f = next(x for x in nr.run_checks(root) if x["check"] == "план работы")
    assert f["ok"] is None, f"документ другого рода выдан за расхождение: {f}"
    assert "рода" in f["detail"] and "plan-artifact" in f["detail"], f


@pytest.mark.unit
def test_the_right_kind_is_actually_checked(tmp_path):
    """Обратная сторона: род совпал — валидатор ЗАПУСКАЕТСЯ, и его вердикт идёт в бриф."""
    root = tmp_path / "kit"
    (root / "ai_ops_kit" / "validation").mkdir(parents=True)
    (root / "ai_ops_kit" / "validation" / "validate_plan_artifact.py").write_text(
        "import sys\nprint('PLAN-ARTIFACT: связей не хватает')\nsys.exit(1)\n", encoding="utf-8")
    (root / "features" / "wi-1").mkdir(parents=True)
    (root / "features" / "wi-1" / "plan.yaml").write_text(
        "kind: plan-artifact\n", encoding="utf-8")

    f = next(x for x in nr.run_checks(root) if x["check"] == "план работы")
    assert f["ok"] is False, f"совпавший род не дошёл до запуска: {f}"
    assert "связей не хватает" in f["detail"], f


@pytest.mark.unit
def test_a_usage_hint_below_the_first_line_is_still_a_wrong_call(tmp_path):
    """ЗАМЕР 20.08.2026 на ТРЁХ живых дочках: половина всех находок обзора была ложной.

    Настоящий отказ валидатора выглядит так (дословно, `validate_claims.py`, вызванный с каталогом):

        ОШИБКА: ожидался путь к файлу заявлений, получено '<каталог>' — это каталог.
        Использование: validate_claims.py [путь/к/claims.yaml] [--json]
        Без аргумента берётся knowledge/claims.yaml пакета.

    Маркер «Использование:» стоит во ВТОРОЙ строке, а защита искала его в `detail` — то есть в
    ПОСЛЕДНЕЙ. Обзор сообщал владельцу «расхождение: Без аргумента берётся knowledge/claims.yaml
    пакета» — предложение, из которого нельзя понять даже, о чём речь.

    Это второй раз за день, когда защита закрывает тот класс, который я поняла, а не тот, который
    существует: первый — документ другого рода. Оба нашлись только на настоящем прогоне.
    """
    root = tmp_path / "kit"
    (root / "ai_ops_kit" / "validation").mkdir(parents=True)
    (root / "ai_ops_kit" / "validation" / "validate_claims.py").write_text(
        "import sys\n"
        "print(\"ОШИБКА: ожидался путь к файлу заявлений, получено '.' — это каталог.\")\n"
        "print('Использование: validate_claims.py [путь/к/claims.yaml] [--json]')\n"
        "print('Без аргумента берётся knowledge/claims.yaml пакета.')\n"
        "sys.exit(1)\n", encoding="utf-8")
    f = next(x for x in nr.run_checks(root) if x["check"] == "заявления")
    assert f["ok"] is None, f"ошибка вызова снова выдана за расхождение: {f}"
    assert "ожидался путь" in f["detail"], f"показан хвост подсказки вместо сути жалобы: {f}"


@pytest.mark.unit
def test_a_real_verdict_is_still_taken_from_the_last_line(tmp_path):
    """Обратная сторона: у НАСТОЯЩЕЙ находки вердикт стоит последним, и его нельзя потерять."""
    root = tmp_path / "kit"
    (root / "ai_ops_kit" / "validation").mkdir(parents=True)
    (root / "ai_ops_kit" / "validation" / "validate_references.py").write_text(
        "import sys\nprint('сканирую…')\nprint('REFERENCES: 3 ссылки ведут в никуда')\n"
        "sys.exit(1)\n", encoding="utf-8")
    f = next(x for x in nr.run_checks(root) if x["check"] == "ссылки")
    assert f["ok"] is False and "ведут в никуда" in f["detail"], f


# ─── РАСПИСАНИЕ: обзор идёт ночью, а не по случаю ──────────────────────────────────────────────
# `delta_review_runs_nightly_and_briefs_the_owner`. Кит НЕ крутит демон — «идёт ночью» значит,
# что существует РЕАЛЬНЫЙ триггер (CI-workflow с `schedule: cron`, зовущий обзор), а не обещание
# в конфиге. Честность та же, что у EnvironmentMap: объявлено ≠ видно в репозитории.


@pytest.mark.unit
def test_no_schedule_is_absent_not_pretend_nightly(repo):
    """Пустая дочка: ночного триггера нет — так и сказать, а не выдать обещание за расписание."""
    st = nr.schedule_status(repo)
    assert st["state"] == "absent", st


@pytest.mark.unit
def test_config_asking_for_nightly_without_a_trigger_is_declared_not_detected(repo):
    """Конфиг просит ночной обзор, но CI-триггера нет: расписание объявлено, но НЕ сработает."""
    (repo / ".ai-ops.yaml").write_text("nightly:\n  enabled: true\n", encoding="utf-8")
    st = nr.schedule_status(repo)
    assert st["state"] == "declared_not_detected", st
    assert "не сработает" in st["reason"] or "триггер" in st["reason"], st


@pytest.mark.unit
def test_installing_a_schedule_creates_a_real_nightly_trigger(repo):
    """install_schedule кладёт workflow с `schedule: cron`, зовущий обзор -> статус detected."""
    res = nr.install_schedule(repo, cron="0 3 * * *")
    assert res["status"] in ("created", "updated"), res
    wf = repo / res["workflow"]
    assert wf.is_file(), res
    text = wf.read_text(encoding="utf-8")
    assert "schedule:" in text and "cron:" in text and "nightly_review" in text, text
    st = nr.schedule_status(repo)
    assert st["state"] == "detected", st
    assert st["cron"] == "0 3 * * *", st


@pytest.mark.unit
def test_installing_a_schedule_is_idempotent(repo):
    """Второй install не плодит второй workflow и не роняет — обновляет тот же файл."""
    nr.install_schedule(repo, cron="0 3 * * *")
    res = nr.install_schedule(repo, cron="30 2 * * *")
    assert res["status"] == "updated", res
    assert nr.schedule_status(repo)["cron"] == "30 2 * * *"


# ─── БРИФ ДОХОДИТ ДО ВЛАДЕЛЬЦА: произведён ≠ доставлен ─────────────────────────────────────────


@pytest.mark.unit
def test_delivering_a_brief_writes_a_durable_inbox_and_receipt(repo):
    """Бриф в stdout владельца не достигает. Доставка — инбокс + указатель latest + receipt."""
    rec = nr.deliver_brief(repo, "# Утренний обзор\nтело брифа", date="2026-09-02")
    assert rec["kind"] == "NightlyBriefReceipt", rec
    dated = repo / rec["path"]
    latest = repo / rec["latest"]
    assert dated.is_file() and latest.is_file(), rec
    assert "тело брифа" in dated.read_text(encoding="utf-8")
    assert latest.read_text(encoding="utf-8") == dated.read_text(encoding="utf-8")


@pytest.mark.unit
def test_run_nightly_produces_a_brief_and_delivers_it_to_the_owner(repo):
    """Точка входа расписания: собрать дельту -> бриф -> доставить владельцу, вернуть receipt."""
    out = nr.run_nightly(repo, date="2026-09-02")
    assert out["brief"] and "Утренний обзор" in out["brief"], out
    assert out["receipt"] and out["receipt"]["kind"] == "NightlyBriefReceipt", out
    assert (repo / out["receipt"]["latest"]).is_file()


@pytest.mark.unit
def test_run_nightly_can_skip_delivery_when_asked(repo):
    """`deliver=False` — бриф собран, но в инбокс не положен (для dry-прогонов и тестов)."""
    out = nr.run_nightly(repo, deliver=False)
    assert out["brief"] and out["receipt"] is None, out

