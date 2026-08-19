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


# ─── B2-17 / B2-19 (вторая порция пере-прогона) ────────────────────────────────────────────────

def test_status_compares_content_not_only_version_numbers():
    """`status` и `diff` обязаны отвечать про ОДНО состояние.

    B2-17: `status` сравнивал только номера и говорил «✓ актуально», пока `diff` перечислял 20
    изменений — версия не менялась, менялось содержимое. Владелец, поверивший первому ответу, не
    получал ничего из влитой работы.
    """
    src = INSTALLER.read_text(encoding="utf-8")
    head = src[src.index("def cmd_status():"):src.index("def cmd_diff():")]

    assert "build_diff()" in head, "status снова не смотрит на содержимое"
    assert "содержимое разошлось" in head
    assert "содержимое сравнить НЕ УДАЛОСЬ" in head, "«не знаю» не отличается от «чисто»"


def test_every_installer_command_is_routed_by_the_wrapper():
    """Команда установщика, не перечисленная в обёртке, недостижима из дочки.

    B2-19: `usage` объявлена в справке установщика, но обёртка отправляла её в интент-CLI —
    `invalid choice: 'usage'`. Список в обёртке отставал от кода молча; теперь расхождение краснеет.
    Пересечения (`status`, `onboard`) отданы интент-CLI осознанно: у владельца это вопросы к работе,
    а не к киту, и для состояния кита есть отдельная команда `kit-status`.
    """
    import re

    installer_cmds = set(re.findall(r'cmd == "([a-z-]+)"', INSTALLER.read_text(encoding="utf-8")))
    wrapper = WRAPPER.read_text(encoding="utf-8")
    routed = set()
    for line in wrapper.splitlines():
        m = re.match(r"\s{2}([a-z|-]+)\)\s*$", line)
        if m:
            routed |= set(m.group(1).split("|"))
    # ОСОЗНАННЫЕ ПЕРЕСЕЧЕНИЯ: команда есть и у установщика, и у движка, и в дочке её обслуживает
    # ДВИЖОК — потому что установщик в поставку не едет, а движок едет.
    #   status/onboard — у владельца это вопросы к работе, а не к киту (для состояния кита есть
    #     отдельная `kit-status`);
    #   session (19.08.2026) — интент перенесён в CLI работой `session-command-reaches-the-child`
    #     ровно ради дочки, но маршрут остался на установщике, и `./ai-ops session` в дочке без
    #     клона парента отвечал «исходник рядом не найден». Маршрут исправлен; здесь имя
    #     перечислено, чтобы проверка не требовала вернуть его установщику.
    #   doctor (19.08.2026) — в дочке отвечает движок (проверка силами самой дочки), полная
    #     проверка установщика доступна как `kit-doctor`, по образцу `status`/`kit-status`.
    intent_owned = {"status", "onboard", "session", "doctor"}

    # НЕ ДЛЯ ВЛАДЕЛЬЦА — и это отдельная категория, а не «забыли». Команда обслуживает МАШИНУ и
    # работает на клоне parent'а, а не в дочке; вести её через обёртку дочки было бы неправдой о
    # том, где она исполняется. Каждая запись обязана нести причину — иначе категория превратится
    # в место, куда прячут забытое.
    machine_only = {
        "resolve-ref": "зовётся из templates/ci/ai-ops-update.yml на клоне parent'а: какую "
                       "ревизию брать под объявленный канал. Владелец её не запускает",
    }
    assert all(v.strip() for v in machine_only.values()), \
        "запись в machine_only без причины — тихий обход проверки маршрутов"

    # ДВЕ СТОРОНЫ, А НЕ ОДНА. Слева — команда установщика без маршрута (недостижима). Справа —
    # имя, объявленное «за движком», которого движок не знает: тогда команда пропала бы совсем.
    import sys as _sys
    _sys.path.insert(0, str(PKG / "tools"))
    import ai_ops_cli as _cli
    orphan = sorted(n for n in intent_owned if n not in _cli.INTENTS)
    assert not orphan, (f"объявлено, что команду обслуживает движок, но такого интента нет: "
                        f"{orphan} — команда исчезла бы для владельца")

    missing = sorted(installer_cmds - routed - intent_owned - set(machine_only))
    assert not missing, f"команды установщика недостижимы из дочки: {missing}"


# ─── B2-22 / B2-23 (третья порция пере-прогона) ────────────────────────────────────────────────

def test_the_loop_reports_progress_so_a_human_can_tell_work_from_a_hang(capsys):
    """Каждый шаг называет себя: «шаг N/M — жду ответа модели».

    B2-22: прогон шёл девять минут без единой строки. Один и тот же пустой экран означал и
    «работает», и «повисло»; отличить удалось только через `ps`. Строка идёт в stderr — stdout
    остаётся машиночитаемым.
    """
    from ai_ops_kit.engine import tool_loop, tool_broker

    calls = {"n": 0}

    def proposer(_ctx):
        calls["n"] += 1
        return {"done": True, "summary": "готово", "behavior_unchanged": "тест"}

    tool_loop.run_loop(proposer, PKG, tool_broker.Policy(level="read-only", child_root=str(PKG)),
                       max_steps=3)
    err = capsys.readouterr().err

    assert "шаг 1/3" in err and "жду ответа модели" in err, err
    assert calls["n"] == 1, "тест смотрит не на тот прогон"


@pytest.mark.parametrize("open_pr,expect", [(False, False), (True, True)])
def test_delivery_preflight_warns_before_spending(tmp_path, open_pr, expect):
    """B2-23: о невозможной доставке говорится ДО работы, а не после полной траты.

    Прогон отработал 13.5 минуты живой модели и ~$3.5 и только на шаге доставки сообщил, что база на
    remote сдвинулась. Отказ верный, момент — нет: база резолвится до первого вызова модели.
    Предупреждение НЕ останавливает прогон: решение «платить или нет» остаётся за владельцем, ему
    лишь возвращают факт вовремя.
    """
    from ai_ops_kit.engine.pipeline_git import delivery_preflight

    out = delivery_preflight(tmp_path, "main", "abc123", open_pr)

    assert bool(out) is expect, out
    if expect:
        assert "PR открыть не удастся" in out["warning"]
        assert "Сказано ДО работы" in out["warning"]


def test_delivery_preflight_is_wired_before_the_model_call():
    """ШОВ: предупреждение стоит в конвейере ДО петли, иначе оно приходит после траты."""
    src = (PKG / "ai_ops_kit" / "engine" / "execution_pipeline.py").read_text(encoding="utf-8")

    assert src.index("_delivery_preflight(") < src.index("tool_loop.run_loop"), (
        "предупреждение о базе стоит после вызова модели — то есть после траты, как и было")
    assert '"preflight": delivery_pf' in src, "предупреждение не доехало до отчёта"


# ─── второй brownfield (`ai-product-quest`, 15.08.2026) ────────────────────────────────────────

def test_the_transcript_records_what_was_executed(tmp_path):
    """След прогона называет КОМАНДУ и ФАЙЛ, а не только вид операции.

    Полевой замер: три прогона подряд дали «шагов 10 · правок 0», и разобрать было нечем — транскрипт
    хранил вид операции и вердикт брокера, но не команду и не путь. Владелец видит «кит не справился»
    без единой зацепки, а сам кит объясняет это неверной причиной («нужен живой провайдер» при
    работающем провайдере).
    """
    from ai_ops_kit.engine import tool_loop, tool_broker

    (tmp_path / "a.txt").write_text("ок\n", encoding="utf-8")
    steps = iter([{"op": "read", "path": "a.txt"},
                  {"done": True, "summary": "прочитал", "behavior_unchanged": "тест"}])

    rep = tool_loop.run_loop(lambda _c: next(steps), tmp_path,
                             tool_broker.Policy(level="read-only", child_root=str(tmp_path)),
                             max_steps=4)
    tr = [t for t in rep["transcript"] if t.get("op")]

    assert tr and tr[0].get("what") == "a.txt", tr
