"""Четыре P1 пере-прогона BNBM: путь владельца перекрыт в четырёх местах (14.08.2026, вечер).

Все четыре нашлись В ПОЛЕ, на живом продукте, и ни одну не поймали 11 джоб CI — потому что они
живут не в коде продукта, а на пути человека: в обёртке, в диагностике, в выводе и в продолжении
работы.

  B2-15 — `--execute` недостижим через `./ai-ops`: путь дописывался ПОСЛЕДНИМ, и любая опция ломала
          разбор. Главный путь продукта («поставил задачу → кит её сделал») в дочке был закрыт;
  B2-16 — `doctor` блокировал работу, когда СОСЕДНЯЯ копия кита СТАРШЕ установленной; выполнение
          совета понизило бы дочку, а где нашлась «соседняя» — не говорилось;
  B2-18 — при нуле объявленных критериев вывод молчал о них совсем, и `delivered` читалось как
          «проверено»;
  B2-20 — `resume` завершённой-но-недоставленной работы хоронил готовый результат в `blocked`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
WRAPPER = PKG / "templates" / "runtime" / "ai-ops-entry.sh"
INSTALLER = PKG / "installer" / "ai_ops.py"


# ─── B2-15 ─────────────────────────────────────────────────────────────────────────────────────

def test_wrapper_puts_the_repo_path_before_the_flags():
    """Путь репозитория идёт СРАЗУ ЗА ИНТЕНТОМ, а не в конец команды.

    argparse набирает позиционные `intent` + `rest` одной непрерывной группой: аргумент после флагов
    в неё уже не попадает. Пока путь дописывался последним, `./ai-ops run "текст" --execute` падал с
    `unrecognized arguments` и кодом 2 — то есть исполнить задачу через обёртку было НЕЛЬЗЯ, работал
    только сухой прогон.
    """
    text = WRAPPER.read_text(encoding="utf-8")
    exec_lines = [ln.strip() for ln in text.splitlines()
                  if "ai_ops_cli.py" in ln and ln.strip().startswith("exec")]

    assert exec_lines, "в обёртке нет вызова интент-CLI — тест смотрит не туда"
    for ln in exec_lines:
        assert not re.search(r'"\$@"\s+"\$here"', ln), (
            f"путь дописан ПОСЛЕ флагов — `run \"текст\" --execute` снова сломается: {ln}")
    assert any('"$intent" "$here" "$@"' in ln for ln in exec_lines), (
        f"нет вызова с путём сразу за интентом: {exec_lines}")


def test_wrapper_shifts_the_intent_before_passing_the_rest():
    """`shift` обязателен: без него интент уедет в аргументы дважды."""
    text = WRAPPER.read_text(encoding="utf-8")

    assert re.search(r'intent="\$1";\s*shift', text), "интент не снят со списка аргументов"


# ─── B2-16 ─────────────────────────────────────────────────────────────────────────────────────

def test_an_older_neighbour_copy_does_not_block_the_child():
    """Соседняя копия СТАРШЕ установленной — не повод для update: понижение обновлением не является.

    На машине разработчика `$HOME/ai-ops-kit` — рабочее дерево, оно легко стоит на слитой ветке.
    Дочка с 3.36.10 получала блокирующее «нужен update» против 3.36.8, и выполнение совета понизило
    бы её. Сравнение стало версионным, а не «!=».
    """
    src = INSTALLER.read_text(encoding="utf-8")

    assert 'parse_version(inst or "0") < parse_version(avail)' in src, (
        "сравнение версий в doctor снова строгое неравенство — понижение будет считаться апдейтом")
    assert "понижение версии обновлением не является" in src


def test_the_doctor_message_names_where_it_found_the_other_version():
    """«Рядом лежит» без адреса не позволяет понять, о какой копии речь."""
    src = INSTALLER.read_text(encoding="utf-8")

    assert "в источнике {PKG} лежит" in src, "путь источника не назван в блокирующем сообщении"


# ─── B2-18 ─────────────────────────────────────────────────────────────────────────────────────

def test_absence_of_criteria_is_said_out_loud_when_the_run_is_ready(capsys):
    """При нуле объявленных критериев вывод обязан это НАЗВАТЬ, а не молчать.

    Урок B2-14 («доставлено ≠ выполнено») был закрыт только для случая, когда критерии есть. В поле
    оказалось, что чаще их нет вовсе: отчёт честно писал «сверять нечего», а человек видел
    `delivered` и ни слова про критерии.
    """
    from ai_ops_kit.engine.ai_ops_run import _print_pipeline

    _print_pipeline({"workitem_id": "w", "status": "READY_FOR_PR", "base_workflow": "QUICK",
                     "provider": "claude-cli", "profile": {"display": []}, "commit": {},
                     "ready_for_pr": True,
                     "gates": {"evaluated": [], "unmet": [], "blocked": False},
                     "acceptance_criteria": {"declared": False, "count": 0, "verified": False,
                                             "reason": "критерии приёмки не объявлены — сверять нечего"}})
    out = capsys.readouterr().out

    assert "критериев приёмки не было объявлено" in out, out
    assert "не «результат сверен с ожиданием»" in out


def test_a_run_that_is_not_ready_does_not_lecture_about_criteria(capsys):
    """Границы: пока работа не готова, разговор о критериях преждевременен и стал бы шумом."""
    from ai_ops_kit.engine.ai_ops_run import _print_pipeline

    _print_pipeline({"workitem_id": "w", "status": "BLOCKED", "base_workflow": "QUICK",
                     "provider": "claude-cli", "profile": {"display": []}, "commit": {},
                     "ready_for_pr": False,
                     "gates": {"evaluated": [], "unmet": ["security"], "blocked": True},
                     "acceptance_criteria": {"declared": False, "count": 0, "verified": False}})

    assert "критериев приёмки не было объявлено" not in capsys.readouterr().out


# ─── B2-20 ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rep,expected,why", [
    ({"resume": {"reused_branch": True}, "commit": {}, "loop": {"applied_writes": 0}}, True,
     "продолжили поверх готовой ветки и ничего не дописали — это ожидание доставки"),
    ({"resume": {"reused_branch": True}, "commit": {"sha": "abc", "changed_files": ["a.md"]}}, False,
     "новые правки есть — обычный прогон, не ожидание доставки"),
    ({"resume": {"reused_branch": False}, "commit": {}, "loop": {"applied_writes": 0}}, False,
     "ветки не было: ноль правок здесь и правда означает «код не написан»"),
    ({"commit": {}, "loop": {"applied_writes": 0}}, False, "не resume вовсе"),
])
def test_delivery_pending_distinguishes_waiting_from_unwritten_code(rep, expected, why):
    """Продолжение поверх готовой ветки без новых правок — «ждёт доставки», а не «код не написан».

    Именно подмена этих двух состояний хоронила готовый READY_FOR_PR: `resume` завершённой работы
    получал ноль правок (делать нечего) и помечал её `blocked: код не написан`. Предикат отвечает на
    один вопрос и потому проверяем прямо — без живого провайдера.
    """
    from ai_ops_kit.engine.pipeline_helpers import delivery_pending

    assert delivery_pending(rep) is expected, why


def test_the_run_uses_the_predicate_and_names_the_waiting_state():
    """ШОВ: предикат действительно стоит в решении о статусе работы, а не лежит рядом."""
    src = (PKG / "ai_ops_kit" / "engine" / "ai_ops_run.py").read_text(encoding="utf-8")

    assert 'if _st == "blocked" and delivery_pending(rep):' in src, "предикат не подключён к решению"
    assert "ждёт доставки: работа готова на ветке, новых правок нет" in src
