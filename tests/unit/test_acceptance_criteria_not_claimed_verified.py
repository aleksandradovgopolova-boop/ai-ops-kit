"""«Доставлено» не читается как «критерии выполнены» (B2-14, живой прогон 14.08.2026).

ЗАМЕР, А НЕ ОПАСЕНИЕ. Прогон на реальном продукте с живыми деньгами отдал владельцу draft PR со
`sha_verified: True` и `overall_status: delivered`. Критерий приёмки требовал дословно «в README нет
строк с `public/media`» — в доставленном тексте эта строка ОСТАЛАСЬ, только описание стало
расплывчатым: ложное утверждение о проекте (каталога не существует) не ушло, а замаскировалось.
`spec-coverage` при этом сообщал `acceptance_criteria: complete`.

РАЗНИЦА В ОДНОМ СЛОВЕ: `complete` означает «раздел заполнен», а не «критерий выполнен». Цена —
ложный green на последнем шаге: приёмка перекладывается на человека без предупреждения, под ярлыком
проверенного.

ЧЕГО ЭТА ПРАВКА НЕ ДЕЛАЕТ: она НЕ сверяет критерии — для этого нужен независимый ревьюер, читающий
дифф против каждого критерия (объявлено работой `acceptance-criteria-verified-by-reviewer`). Она
перестаёт выдавать непроверенное за проверенное. Тот же инвариант, что `unavailable != 0`.
"""
from __future__ import annotations

from ai_ops_kit.engine.ai_ops_run import _print_pipeline

BASE = {
    "workitem_id": "demo", "status": "READY_FOR_PR", "base_workflow": "QUICK",
    "provider": "claude-cli", "profile": {"display": ["node (npm)"]},
    "tool_loop": {"status": "done", "steps": 4}, "commit": {},
    "gates": {"evaluated": ["intake_completeness"], "unmet": [], "blocked": False},
}


def _out(capsys, report):
    _print_pipeline({**BASE, **report})
    return capsys.readouterr().out


def test_unverified_criteria_are_named_in_the_same_output_as_ready(capsys):
    """positive: предупреждение стоит там же, где «готово», а не только в JSON-отчёте.

    Владелец читает вывод прогона, а не файл отчёта. Признание, доехавшее только до JSON, — это
    признание, которого он не увидит; ровно так и вышло в живом прогоне.
    """
    out = _out(capsys, {"acceptance_criteria": {
        "declared": True, "verified": False,
        "reason": "критерии объявлены, но с результатом НЕ сверялись: механизма сверки нет"}})

    assert "критерии приёмки НЕ сверялись" in out, (
        f"в выводе нет признания о критериях:\n{out}")
    assert "механизма сверки нет" in out, "причина не названа — «не сверялись» без причины бесполезно"


def test_absent_criteria_do_not_produce_a_scary_warning(capsys):
    """границы: если критериев не объявляли, сверять нечего — и пугать нечем.

    Иначе предупреждение появлялось бы всегда и обесценилось: гейт, срабатывающий на всё, учат
    обходить. Отсутствие критериев — отдельное состояние, а не провал сверки.
    """
    out = _out(capsys, {"acceptance_criteria": {
        "declared": False, "verified": False, "reason": "критерии приёмки не объявлены"}})

    assert "критерии приёмки НЕ сверялись" not in out, (
        f"предупреждение сработало там, где сверять нечего:\n{out}")


def test_verified_flag_cannot_be_faked_by_absence(capsys):
    """side-effect proof: молчание = НЕ подтверждение.

    Главный риск этой правки — что её же и обойдут: достаточно не положить поле в отчёт, и
    предупреждение исчезнет, а «доставлено» останется. Проверяется, что отсутствие поля не создаёт
    впечатления проверенного: в выводе нет ни слова о том, что критерии выполнены.
    """
    out = _out(capsys, {})

    assert "критерии приёмки выполнены" not in out
    assert "критерии сверены" not in out
