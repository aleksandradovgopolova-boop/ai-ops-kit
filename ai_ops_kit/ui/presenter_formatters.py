#!/usr/bin/env python3
"""Переводчики повседневных команд Human Communication Layer (вынесено из `presenter.py`).

Модуль-сосед `presenter.py`: он стал god-модулем на ~1500 строк, и группа переводчиков
повседневных команд («что я собираюсь сделать», онбординг стека, каркас работы, план, описание
задачи, discovery, ревью ветки, инженерный совет) выделена сюда без изменения поведения. Контракт
`UserMessage` и рендер остаются в `presenter.py`; здесь — только форматтеры, которые собирают
`UserMessage` из сырых внутренних отчётов.

`message` и `_q` импортируются из `presenter.py` (их дом), а сам `presenter.py` реэкспортирует
эти функции обратно — так внешние вызовы `presenter.from_review(...)` продолжают работать. Цикла
нет: `presenter.py` определяет `message`/`_q` в начале файла, задолго до реэкспорта в конце.
"""
from __future__ import annotations

from ai_ops_kit.ui.presenter import _q, message


# ── Переводчики повседневных команд ───────────────────────────────────────────────────────────
# Слой коммуникации существовал для трёх команд из двенадцати. Остальные печатали внутреннее
# состояние напрямую — `ONBOARD: стек python · профиль записан …`, `SPECIFY: создан …`,
# `■ intent: run · понял: QUICK -> workflow QUICK · спецификация L0`, — и настройка «с кем ты
# говоришь» на них не влияла вовсе. Пользовательское ревью назвало это одним дефектом: чаще всего
# человек видит именно эти команды, и именно в них он читает лог вместо ответа.

def from_execution_preview(pv: dict) -> dict:
    """`build_preview()` -> UserMessage. «Что я собираюсь сделать» до запуска.

    Внутренние имена стадий и флагов остаются в технических деталях: они нужны, когда прогон пошёл
    не так, но в них нет ни одного слова о том, что произойдёт с продуктом.
    """
    u = pv.get("understood") or {}
    wd = pv.get("will_do") or {}
    du = pv.get("data_used") or {}
    approvals = list(pv.get("approvals_needed") or [])
    ctx_error = du.get("context_error")
    tech = {"intent": pv.get("intent"), "task_type": u.get("task_type"),
            "workflow": u.get("workflow"), "spec_level": u.get("spec_level"),
            "stages": len(wd.get("stages") or []), "auto_flags": wd.get("auto_flags"),
            "agents": len(du.get("agents") or []),
            "estimated_tokens": du.get("estimated_tokens"),
            "context_budget": du.get("context_budget")}
    if ctx_error:
        tech["context_error"] = ctx_error
    what = str(pv.get("expected_result") or "выполню намерение").strip()
    summary = (what[:1].upper() + what[1:]).rstrip(".") + "."

    steps = []
    if pv.get("decomposition_advised"):
        steps.append("задача больше одного шага — советую разбить её, иначе результат будет трудно "
                     "проверить")

    if ctx_error:
        # ДЕГРАДАЦИЯ ВИДНА НА ВСЕХ ТРЁХ УРОВНЯХ. Прежде сбой сборки контекста давал `агентов 0 ·
        # ~None ток.` — прогон вслепую выглядел как обычный (137 проглоченных исключений, внешнее
        # ревью). Продакту тем более нельзя показывать это как норму: он не читает числа.
        return message(
            status="degraded", headline="Могу запустить, но материалы проекта не собрались",
            summary=summary,
            why_it_matters="Прогон пойдёт без контекста продукта: я не смогу опереться ни на "
                           "правила, ни на прошлые решения, и оценку стоимости тоже не дам.",
            next_steps=steps + ["скажи, если запускать всё равно — иначе сначала разберусь, "
                                "почему контекст не собрался"],
            technical=tech)

    if approvals:
        return message(
            status="needs_input",
            summary=summary,
            why_it_matters="Задача задевает то, что я не меняю без твоего слова.",
            decision={"question": "разрешить: " + "; ".join(approvals),
                      "recommendation": "посмотреть, что именно затронуто, и подтвердить — "
                                        "без ответа я не начинаю",
                      "on_approve": "запускаю и приношу результат на проверку",
                      "on_reject": "предложу вариант, который этого не трогает"},
            next_steps=steps or None, technical=tech)

    return message(status="ok", headline="Вот что я сделаю", summary=summary,
                   next_steps=steps or ["запускай, когда готов"], technical=tech)


# Внутреннее имя команды -> то, как её называет человек. Нужно потому, что пробел в профиле надо
# назвать своими словами: в поле продакт прочитал «не выведены команды ['build', 'lint',
# 'typecheck', 'test']» — repr списка Python посреди русской фразы.
_CMD_RU = {"build": "сборки", "test": "тестов", "lint": "линтера", "typecheck": "проверки типов",
           "install": "установки зависимостей", "dev": "запуска", "run": "запуска",
           "format": "форматирования", "e2e": "сквозных тестов"}


def from_onboarding_profile(prof: dict, written: str) -> dict:
    """`project_detector.detect()` -> UserMessage. «На чём написан проект и чем он проверяется».

    Отсутствие стека — не «проект пустой», а «не смог определить»: без него кит не знает, чем
    собирать и чем тестировать, и молчаливый `ok` здесь означал бы зелёный свет на пустом месте.

    Пробел называется по СТРУКТУРЕ профиля, а не пересказом готовых строк `undetermined`: те
    написаны для инженера и содержат внутренние подробности. Сами строки остаются в деталях.
    """
    stacks = list(prof.get("stacks") or [])
    langs = [str(s.get("language") or "?") for s in stacks]
    undetermined = list(prof.get("undetermined") or [])
    silent = [str(s.get("language") or "?") for s in stacks
              if not {k: v for k, v in (s.get("commands") or {}).items() if v}]
    tech = {"профиль": written, "стеки": ", ".join(langs) or "—",
            "команды": "; ".join(
                f"{s.get('language')}: " + (", ".join(f"{k}={v}" for k, v in
                                                      (s.get("commands") or {}).items() if v)
                                            or "не найдены") for s in stacks) or "—",
            "не определено": ", ".join(undetermined) or "—"}

    if not stacks:
        return message(
            status="degraded", headline="Не понял, на чём написан проект",
            summary="Стек определить не удалось.",
            why_it_matters="Это не «здесь ничего нет» — это «я не знаю»: без стека я не могу "
                           "сказать, чем проект собирается и чем проверяется.",
            next_steps=["назови язык и команды сборки и тестов — запишу и дальше буду ими "
                        "пользоваться"],
            technical=tech)

    what = ", ".join(langs)
    missing_cmds = sorted({k for s in stacks for k, v in (s.get("commands") or {}).items() if not v})
    notes = []
    if missing_cmds:
        notes.append("команды для " + ", ".join(_CMD_RU.get(k, k) for k in missing_cmds))
    if prof.get("monorepo"):
        notes.append("покрывают ли корневые команды все пакеты — это монорепозиторий")
    if silent and not missing_cmds:
        notes.append(f"ни одной команды для {', '.join(silent)}")
    if notes:
        return message(
            status="degraded", headline="Разобрался, но не до конца",
            summary=f"Проект написан на {what}.",
            why_it_matters="Чего я не знаю: " + "; ".join(notes) + ". Пока это так, часть проверок "
                           "я провести не смогу и не буду делать вид, что провела.",
            next_steps=["скажи недостающие команды — или спроси «что дальше», и я начну работу "
                        "с тем, что уже знаю"],
            technical=tech)
    if undetermined:
        # Остались непереведённые пробелы: назвать их своими словами я не умею, но и умолчать о том,
        # что профиль неполон, не имею права — «не знаю» не превращается в «в порядке».
        n = len(undetermined)
        return message(
            status="degraded", headline="Разобрался, но не до конца",
            summary=f"Проект написан на {what}.",
            why_it_matters=f"В профиле осталось {n} {_q(n, 'место', 'места', 'мест')}, где я не "
                           f"уверен; своими словами объяснить их не могу — покажу как есть.",
            next_steps=["покажу технические детали — там сказано, чего именно не хватает"],
            technical=tech)

    return message(status="ok", headline="Разобрался с проектом",
                   summary=f"Проект написан на {what}; чем его собирать и проверять — я нашёл.",
                   next_steps=["спроси «что дальше» — предложу работу с обоснованием"],
                   technical=tech)


def from_new_feature(workitem_id, title, spec_created, next_command) -> dict:
    """Создание каркаса работы -> UserMessage. Каркас — это ещё не работа, и это надо сказать."""
    return message(
        status="ok", headline="Место для работы готово",
        summary=f"Завёл работу «{title}».",
        why_it_matters="Сделано пока ничего: это только место, куда лягут описание и результат.",
        next_steps=[f"опиши, что нужно получить: {next_command}"],
        technical={"workitem_id": str(workitem_id),
                   "workitem": f"features/{workitem_id}/workitem.yaml",
                   "spec": "создана" if spec_created else "уже была"})


def from_plan_built(workitem_id, workflow, spec_level, packages, context_error=None) -> dict:
    """Построенный RunPlan -> UserMessage. Главное для человека: КОД НЕ МЕНЯЛСЯ."""
    tech = {"workitem_id": str(workitem_id), "workflow": workflow, "spec_level": spec_level,
            "work_packages": packages, "артефакты": f"features/{workitem_id}/"}
    n = int(packages or 0)
    big = (f" Задача крупная, поэтому разбита на {n} "
           f"{_q(n, 'шаг', 'шага', 'шагов')}." if n else "")
    if context_error:
        tech["context_error"] = context_error
        return message(
            status="degraded", headline="План есть, но собран не полностью",
            summary="План работы готов; код я не менял." + big,
            why_it_matters="Материалы проекта не собрались, поэтому оценка объёма — по умолчаниям, "
                           "а не по твоему продукту.",
            next_steps=["разберусь, почему контекст не собрался, — иначе оценка будет неточной"],
            technical=tech)
    return message(
        status="ok", headline="План работы готов",
        summary="Понял, что и в каком порядке делать; код я не менял." + big,
        next_steps=["скажи «запускай» — начну исполнение и принесу результат на проверку"],
        technical=tech)


def from_specification(path, created, level_name, sections, blocking_missing, next_command,
                       added=None, add_error=None) -> dict:
    """Спецификация задачи -> UserMessage. Незаполненные разделы — работа человека, и она названа.

    F-029: `added` — разделы, ДОПИСАННЫЕ в уже существующий файл под поднявшийся уровень. Без него
    сообщение звучало «заготовка уже была; заполнить нужно 9 разделов», а в файле лежало 6 разделов
    прошлого уровня — заполнять было нечего. `add_error` — честная причина, если дописать не вышло
    (битый spec.yaml не переписываем: описанное человеком дороже незакрытого гейта)."""
    n_missing = len(blocking_missing or [])
    n_added = len(added or [])
    tech = {"spec": str(path), "уровень": level_name, "разделов": len(sections or []),
            "не заполнено": ", ".join(blocking_missing or []) or "—",
            "создана": bool(created), "дописано": ", ".join(added or []) or "—"}
    if add_error:
        tech["дописать не удалось"] = str(add_error)
    if created:
        _origin = "создана"
    elif n_added:
        _origin = (f"уже была, дописано {n_added} "
                   f"{_q(n_added, 'раздел', 'раздела', 'разделов')} под {level_name}")
    else:
        _origin = "уже была"
    if n_missing:
        return message(
            status="needs_input",
            summary=("Заготовка описания задачи " + _origin
                     + f"; заполнить нужно {n_missing} "
                       f"{_q(n_missing, 'раздел', 'раздела', 'разделов')}."
                     + (f" Дописать разделы не удалось: {add_error}." if add_error else "")),
            why_it_matters="Заполнять их за тебя я не буду: это как раз то, что из кода не "
                           "выводится, — зачем задача и как поймём, что получилось.",
            next_steps=[f"заполни разделы в {path}", f"потом запускай: {next_command}"],
            technical=tech)
    return message(status="ok", headline="Описание задачи готово",
                   summary="Всё, что нужно было описать, описано.",
                   next_steps=[f"запускай: {next_command}"], technical=tech)


def from_discovery_draft(path, created) -> dict:
    """Черновик discovery -> UserMessage. Пустой черновик — не результат, а приглашение."""
    return message(
        status="needs_input",
        summary=("Черновик для обсуждения идеи " + ("создан" if created else "уже был") + "."),
        why_it_matters="Он пустой намеренно: чью боль решаем и как поймём, что помогло, "
                       "я за тебя не придумаю.",
        next_steps=[f"заполни разделы в {path}",
                    "потом попроси построить описание задачи — дальше я работаю сама"],
        technical={"draft": str(path), "создан": bool(created)})


def from_review(rep: dict) -> dict:
    """`review_branch.review()` -> UserMessage.

    ШЕСТЬ ВЕРДИКТОВ, И ТРИ ИЗ НИХ НЕ «ГОТОВО». `pass` — проверено. `no-ai-review-gates` — готово
    вливать, но НИЧЕГО не проверялось (ревьюируемых гейтов в плане нет). `needs-reviewer` — работа
    сделана, судить было некому: своё же изменение кит судить не вправе (writer ≠ judge).
    `no-branch` — сверять нечего. Каждый случай назван своим именем: общее «готово» на любом из них
    и есть то, из-за чего слой человеческого языка мог бы стать способом скрывать, а не объяснять.
    """
    readiness = rep.get("readiness") or {}
    ready = bool(readiness.get("ready_for_merge"))
    verdict = rep.get("verdict")
    reviews = rep.get("reviews") or []
    changed = len(rep.get("changed_files") or [])
    tech = {"verdict": verdict, "ready_for_merge": ready,
            "основание": readiness.get("reason") or "—",
            "гейтов на ревью": len(rep.get("reviewable") or []),
            "изменено файлов": changed,
            # БАЗА РЯДОМ С ЧИСЛОМ: «изменено файлов 0» без базы неотличимо от «база не выбрана»
            # (заявка #136 — там же справка обещала автоподбор, которого не было).
            "база дифа": (rep.get("base") or "не выбрана")
                         + (f" ({rep['base_source']})" if rep.get("base_source") and rep.get("base") else "")
                         + (f" — {rep['base_note']}" if rep.get("base_note") else ""),
            "по гейтам": "; ".join(f"{r.get('gate')}: {r.get('status') or 'без вердикта'}"
                                   for r in reviews) or "—",
            "evidence": rep.get("evidence_path") or "—", "note": rep.get("note") or "—"}

    if verdict == "no-branch":
        return message(
            status="degraded", headline="Проверять нечего",
            summary="Ветки с изменениями по этой работе нет.",
            why_it_matters="Это не «замечаний нет» — это «нечего смотреть».",
            next_steps=["скажи, какую работу проверять, или начни её — тогда появится что сверять"],
            technical=tech)

    if verdict == "error":
        return message(
            status="blocked", headline="Проверку провести не удалось",
            summary="Независимая проверка сломалась на полпути.",
            why_it_matters="Ни «готово», ни «не готово» я сказать не могу: проверки не было.",
            next_steps=["разберусь, почему она не запустилась"], technical=tech)

    if verdict == "no-ai-review-gates":
        return message(
            status="ok", headline="Вливать можно, но проверка не проводилась",
            summary="У этой работы нет мест, которые я обязана отдавать на независимую проверку.",
            why_it_matters="Поэтому «замечаний нет» здесь значит «их никто не искал» — "
                           "решение вливать за тобой.",
            next_steps=["можно вливать"], technical=tech)

    # «Вердикта нет» — это либо явный `needs-reviewer`, либо ни одного годного вердикта среди
    # проведённых ревью. Второй случай важнее: он выглядит как проведённая проверка.
    no_verdict = verdict == "needs-reviewer" or (
        bool(reviews) and all((r.get("status") or "") in ("", "invalid") for r in reviews))
    if no_verdict:
        return message(
            status="degraded", headline="Проверять было некому",
            summary="Работа сделана, но независимую проверку я не провела.",
            why_it_matters="Своё же изменение я судить не имею права, а живого проверяющего "
                           "здесь не было. Это не «всё хорошо» — это «не проверено».",
            next_steps=["подключи проверяющего — тогда у вердикта появится основание"],
            technical=tech)

    if ready:
        return message(
            status="ok", headline="Проверено",
            summary=f"Независимая проверка прошла: изменений в {changed} "
                    f"{_q(changed, 'файле', 'файлах', 'файлах')}, замечаний нет.",
            next_steps=["можно вливать"], technical=tech)

    if verdict != "needs-changes":
        # Незнакомый вердикт — не «всё плохо» и тем более не «всё хорошо»: я его не понимаю.
        return message(
            status="degraded", headline="Не понимаю итог проверки",
            summary=f"Проверка вернула незнакомый мне итог: {verdict}.",
            why_it_matters="Пересказывать его своими словами я не буду — это была бы выдумка.",
            next_steps=["покажу отчёт проверки как есть"], technical=tech)

    return message(
        status="blocked", headline="Пока вливать нельзя",
        summary="Проверка нашла, что нужно доделать.",
        why_it_matters="Пока замечания не закрыты, изменение не готово — даже если код работает.",
        next_steps=["покажу замечания по порядку и закрою их"], technical=tech)


def from_advice(result: dict) -> dict:
    """`engineering_advisor.advise()` -> UserMessage. Совет — не исполнение, и это должно быть видно."""
    recs = list(result.get("recommendations") or [])
    urgent = [r for r in recs if int(r.get("priority") or 3) == 1]
    tech = {"repository": result.get("repository"), "task_type": result.get("task_type") or "—",
            "рекомендаций": len(recs), "сводка": result.get("summary")}
    tech.update({f"[{r.get('category')}] {i + 1}": f"{r.get('advice')} (источник: {r.get('source')})"
                 for i, r in enumerate(recs)})
    if not recs:
        return message(status="ok", headline="Замечаний по инженерной части нет",
                       summary="Смотрела окружения, поставку и процесс — советовать нечего.",
                       next_steps=["спроси «что дальше» — предложу работу"], technical=tech)
    n = len(recs)
    if urgent:
        return message(
            status="degraded", headline="Есть то, что стоит починить сначала",
            summary=f"Нашла {n} {_q(n, 'совет', 'совета', 'советов')} по инженерной части, "
                    f"из них {len(urgent)} "
                    f"{_q(len(urgent), 'срочный', 'срочных', 'срочных')}.",
            why_it_matters="Срочное здесь значит: пока это так, остальная работа будет идти "
                           "медленнее или её результат будет труднее проверить. "
                           + urgent[0].get("advice", ""),
            next_steps=["возьмусь за срочное, если скажешь", "остальное покажу списком"],
            technical=tech)
    return message(
        status="ok", headline="Совет по инженерной части",
        summary=f"Нашла {n} {_q(n, 'место', 'места', 'мест')}, где можно сделать лучше; "
                f"срочного нет.",
        why_it_matters=recs[0].get("advice"),
        next_steps=["покажу список целиком, если нужно"], technical=tech)
