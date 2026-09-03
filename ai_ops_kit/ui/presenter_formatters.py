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


# ── Переводчики внутренних отчётов ────────────────────────────────────────────────────────────
# Вторая группа, вынесенная из `presenter.py`: переводчики сырых внутренних отчётов (понимание
# репозитория, сверка контуров, здоровье продукта, экономика сессии, bootstrap, doctor и др.).
# Поведение не меняется — это тот же шов «внутренние имена внутри, наружу выходит смысл».
# В `presenter.py` остались только три переводчика с мутационными пробами.

def from_repository_understanding(rep: dict) -> dict:
    """`repo_audit.run()` -> UserMessage.

    Плохо: «Artifact coverage 8/15. architecture=inferred, data_model=partial, delivery=verified».
    Хорошо: «Осмотрел проект. Техническую картину восстановил сам; не хватает того, что из кода
    честно не узнать». Числа остаются в технических деталях — они не врут, они просто не ответ.
    """
    cls = rep["classification"]["class"]
    aud = rep["audit"]
    ask = rep["ask"]
    n_q = len(ask["questions"])
    known = ", ".join(k.replace("_", " ") for k, v in rep["reconstructed"].items()
                      if v["status"] in ("verified", "inferred") and v.get("value"))
    human_needed = [c["title"] for c in aud["contours"] if c["needs_human"]]

    if cls == "NEW_PRODUCT":
        summary = ("Похоже, это новый продукт: работающей системы и истории разработки я не нашёл. "
                   "Сначала соберём минимальную модель продукта, потом смогу предложить "
                   "архитектуру и план работ.")
        why = None
    elif cls == "UNKNOWN":
        summary = "Не смог осмотреть репозиторий — прочитать его содержимое не получилось."
        why = "Без этого любой мой вывод о проекте был бы выдумкой, поэтому я не начинаю."
    else:
        summary = ("Я разобрался с проектом. Это " + ("уже работающий продукт"
                   if cls == "EXISTING_PRODUCT" else "ранняя стадия продукта") + ".")
        why = ("Техническую картину я восстановил сам" + (f": {known}" if known else "") +
               ". А то, что из кода честно узнать нельзя, спрошу у тебя — "
               "выдумывать это я не буду.") if known else None

    steps = []
    if n_q:
        steps.append(f"задам {n_q} "
                     + ("короткий " if n_q % 10 == 1 and n_q % 100 != 11 else "коротких ")
                     + _q(n_q))
    # ОНБОРДИНГ ЗАКАНЧИВАЕТСЯ РАБОТОЙ. Прежде здесь стояло «соберу недостающие материалы и покажу
    # их тебе на проверку» — обещание, которого кит не выполнял ничем: BOOTSTRAP существовал строкой
    # в реестре. Теперь названа команда, которая это делает, и она рядом.
    steps.append("соберу первое направление и план из фактов репозитория: ./ai-ops bootstrap")
    if not n_q:
        steps.append("после этого покажу, какую работу имеет смысл взять первой")

    return message(
        status="needs_input" if n_q else "ok",
        summary=summary, why_it_matters=why, next_steps=steps,
        decision=({"question": f"ответить на {n_q} {_q(n_q)} о продукте, направлении и границах",
                   "recommendation": "ответить сразу — дальше я работаю без остановок",
                   "on_approve": "соберу базовую модель продукта и предложу первые задачи",
                   "on_reject": "оставлю эти области помеченными как «не подтверждено» и не буду "
                                "их выдумывать"} if n_q else None),
        technical={"classification": cls,
                   "confidence": rep["classification"]["confidence"],
                   "contours_verified": len(aud["ready"]),
                   "contours_total": len(aud["contours"]),
                   "ai_can_build": ", ".join(aud["ai_can_build"]) or "—",
                   "needs_human": ", ".join(human_needed) or "—",
                   "blocking_gaps": ", ".join(aud["blocking_gaps"]) or "—",
                   "questions": n_q})


def from_contour_consistency(rep: dict) -> dict:
    """`contours.reconcile()` -> UserMessage. Ровно тот случай, ради которого модель нужна.

    ГЛАВНЫЙ ИНВАРИАНТ ОБЯЗАН ДОЖИВАТЬ ДО ЧЕЛОВЕКА. Прежде при отсутствии major-находок перевод
    печатал «Изменение согласовано с описанием продукта», выбрасывая все `unknown_contour`: кит
    проверил один контур из восьми и сообщил владельцу, что всё согласовано. `unknown` был защищён
    в `contours.py` пятью тестами и не защищён здесь ни одним — мутационное ревью это и поймало.
    Непроверенное называется непроверенным на всех трёх уровнях детализации.
    """
    findings = rep.get("findings") or []
    major = [f for f in findings if f.get("severity") == "major"]
    unknown = [f for f in findings if f.get("id") == "unknown_contour"]

    if not rep.get("comparable"):
        # «Сверять нечего» — это не прогресс. Прежде здесь стоял `ok`, и ярлык печатал
        # «Работа продвинулась» на месте непроведённой проверки.
        return message(
            status="degraded", headline="Сверять нечего",
            summary="Изменений не предъявлено.",
            why_it_matters="Это не «всё согласовано» — это «проверка не проводилась».",
            next_steps=["сверю, когда появится изменение"],
            technical={"comparable": False, "findings": len(findings)})

    if major:
        behind = [f["contour"] for f in major if f.get("id") == "source_of_truth_behind"]
        parts = []
        if behind:
            parts.append("изменилось то, что описано в проекте, а само описание не обновлено")
        other = [f for f in major if f.get("id") != "source_of_truth_behind"]
        if other:
            parts.append("есть расхождения между заявленным и сделанным")
        msg = message(
            status="degraded",
            summary="Изменение готово, но описание продукта за ним не поспело: "
                    + "; ".join(parts) + ".",
            why_it_matters="Следующая сессия — и человек, и агент — прочитает устаревшее описание "
                           "как правду. Именно так расходятся код и представление о нём."
                           + (f" Ещё {len(unknown)} "
                              f"{_q(len(unknown), 'область', 'области', 'областей')} проверить "
                              f"нечем." if unknown else ""),
            next_steps=["обновлю затронутые описания и покажу изменения",
                        "либо скажи, что менять их не нужно, и я запишу это как решение"],
            technical={f["contour"]: f["detail"] for f in major})
        return msg

    if unknown:
        n = len(unknown)
        return message(
            status="degraded", headline="Проверил не всё",
            summary=f"Расхождений не нашёл, но {n} "
                    f"{_q(n, 'область', 'области', 'областей')} продукта мне здесь не видно.",
            why_it_matters="Про них я не говорю «в порядке» — я говорю «не знаю»: подменять "
                           "признание утверждением значит зеленить непроверенное.",
            next_steps=[f"назови, где в проекте живут эти области "
                        f"({', '.join(f['contour'] for f in unknown[:3])}…), и я начну их видеть"],
            technical={f["contour"]: f["detail"] for f in unknown})

    return message(status="ok", headline="Согласовано",
                   summary="Изменение согласовано с описанием продукта — проверены все области.",
                   next_steps=["продолжаю"],
                   technical={"findings": len(findings)})


def from_product_health(rep) -> dict:
    """Product Health -> UserMessage. Отсутствие данных — НЕ «всё хорошо».

    Прежняя формулировка была честной по сути («без данных score не считается») и негодной по форме:
    путь к файлу и слово `score` продакту не нужны, а что делать дальше — не сказано.
    """
    if not rep:
        return message(
            status="degraded", headline="Пока не могу измерить",
            summary="Данных о состоянии продукта я не получил.",
            why_it_matters="Это не «всё хорошо» — это «не знаю»: считать по пустому месту я не буду.",
            next_steps=["подключи метрики продукта, и я начну показывать динамику"],
            technical={"input": "product/product-health.yaml", "status": "unavailable"})
    hs = (rep.get("health_score") or {})
    band = hs.get("band")
    value = hs.get("value")
    good = band in ("good", "excellent", "healthy")
    return message(
        status="ok" if good else "degraded",
        summary=(f"Состояние продукта: {band}." if band else "Состояние продукта измерено."),
        why_it_matters=None if good else "Стоит посмотреть, что тянет вниз, до следующей работы.",
        next_steps=["покажу разбор по метрикам, если нужно"],
        technical={"health_score": value, "band": band})


def from_subsession_decision(decision: dict) -> dict:
    """SubsessionDecision -> UserMessage: может ли кит взять работу в отдельную сессию САМ.

    Читатель — владелец, а не инженер, поэтому здесь нет ни «подсессии», ни имён полей конфига в
    тексте: есть «беру сам» / «нужно твоё слово» и одно понятное действие. Внутренние имена
    (`session_economy.max_autonomous_spend_usd`, коды отказов) остаются В ДЕТАЛЯХ — по ним
    отлаживают, но наружу они не идут.

    Почему отказ не сводится к одной фразе «нельзя»: у семи отказов разное ЛЕЧЕНИЕ. «Потолок не
    объявлен» лечится одной строкой согласия, «потолок достигнут» — решением потратить ещё,
    «не могу доказать расход» — вообще не деньгами. Свести их в одно значило бы сказать человеку
    «нельзя» там, где на самом деле «скажи да».
    """
    n = (decision or {}).get("numbers") or {}
    action = (decision or {}).get("action")
    code = (decision or {}).get("refusal")
    ceiling, spent = n.get("ceiling_usd"), n.get("spent_usd")
    tech = {"решение": action, "код отказа": code or "—",
            "потолок $": ceiling if ceiling is not None else "не объявлен",
            "потрачено самостоятельно $": spent if spent is not None else "—",
            "подсессий использовано": n.get("subsessions_used", "—"),
            "состояние контекста": n.get("context_state"),
            "сессия": n.get("session_id") or "не опознана",
            "причина": (decision or {}).get("reason") or "—"}

    if action == "spawn_subsession":
        left = None if ceiling is None or spent is None else round(float(ceiling) - float(spent), 4)
        return message(
            status="ok", headline="Эту работу возьму отдельно и сам",
            summary="Начну её с чистого листа, чтобы не платить за перечитывание нашей истории."
                    + (f" В пределах разрешённого остаётся ${left}." if left is not None else ""),
            why_it_matters="Чем длиннее переписка, тем дороже каждый следующий запрос, а пользы от "
                           "старой части уже нет.",
            next_steps=["ничего не нужно — расскажу, что получилось"], technical=tech)

    if action == "continue_here":
        return message(
            status="ok", headline="Отдельная сессия пока не нужна",
            summary=(decision or {}).get("reason") or "Продолжаю здесь.",
            next_steps=["продолжаю"], technical=tech)

    # Отказы. Формулировка зависит от кода: разное лечение — разные слова.
    if code == "no_ceiling":
        # Спрашивать «сколько можно потратить» и не предлагать числа значило бы требовать решения,
        # для которого у человека нет данных: цену вызова видел только кит. Поэтому вопрос идёт
        # ВМЕСТЕ с посчитанной суммой и её основанием — владельцу остаётся согласиться.
        sug = n.get("suggested_usd")
        why = n.get("suggestion_reason")
        tech["предложено $"] = sug if sug is not None else "нет замера"
        tech["основание предложения"] = n.get("suggestion_basis") or "—"
        if sug:
            return message(
                status="blocked", headline=f"Могу дальше сам — нужно твоё «да» на ${sug}",
                summary=f"Я посчитал, сколько прошу: ${sug}. {why}",
                why_it_matters="Работать без названной границы значит тратить без границы. Пока "
                               "суммы нет, я не трачу ничего — даже когда вижу, что стоило бы.",
                decision={"question": f"разрешить мне тратить самостоятельно до ${sug}?",
                          "recommendation": f"да, ${sug} — это посчитано по реальной цене работы, "
                                            "не выбрано на глаз",
                          "on_approve": "буду брать подходящую работу отдельно и остановлюсь на "
                                        "этой сумме сам",
                          "on_reject": "останусь здесь и буду только советовать"},
                next_steps=["скажи «да» — запишу сумму в настройки проекта",
                            "или назови свою, если эта кажется большой"], technical=tech)
        return message(
            status="blocked", headline="Сам продолжить не могу — нечем обосновать сумму",
            summary="Я мог бы вести эту работу отдельно, но сумму назвать не могу: "
                    + (why or "у меня нет замеров стоимости в этом проекте")
                    + " Придумывать число я не буду.",
            why_it_matters="Названная от себя сумма выглядела бы расчётом, не будучи им. Лучше "
                           "честно попросить решение, чем подсунуть догадку.",
            decision={"question": "сколько мне можно потратить самостоятельно?",
                      "recommendation": "назначь небольшую сумму на пробу — после первых работ я "
                                        "посчитаю точнее сам",
                      "on_approve": "буду брать подходящую работу отдельно, не выходя за неё",
                      "on_reject": "останусь здесь и буду только советовать"},
            next_steps=["назови сумму — я запишу её в настройки проекта"], technical=tech)
    if code == "over_ceiling":
        return message(
            status="blocked", headline="Разрешённая сумма израсходована",
            summary=f"Самостоятельно потрачено ${spent} из ${ceiling}. Дальше — только с твоим словом.",
            why_it_matters="Это и есть та граница, о которой договаривались: дальше я не иду сам.",
            decision={"question": "продолжать самостоятельно?",
                      "recommendation": "решай по результату — что уже получено, видно",
                      "on_approve": "подними сумму, и я продолжу",
                      "on_reject": "останусь здесь"},
            next_steps=["подними разрешённую сумму или продолжим вместе"], technical=tech)
    if code == "spend_unprovable":
        return message(
            status="degraded", headline="Не могу доказать, сколько уже потратил",
            summary="Среди сделанных запросов есть такие, чья стоимость неизвестна, поэтому мой "
                    "подсчёт неполон.",
            why_it_matters="Сказать «я в пределах суммы» по неполному счёту значило бы пообещать "
                           "больше, чем я знаю. Поэтому не трачу.",
            next_steps=["продолжим здесь — я на виду"], technical=tech)
    if code == "session_unidentified":
        return message(
            status="degraded", headline="Не понимаю, к какому разговору отнести расход",
            summary="Пока я не опознаю текущий разговор, я не могу связать с ним трату.",
            why_it_matters="Иначе я потратил бы «в никуда»: проверить, остался ли я в пределах "
                           "суммы, было бы нечем.",
            next_steps=["продолжим здесь"], technical=tech)
    if code == "unsafe_boundary":
        return message(
            status="degraded", headline="Сейчас не время переключаться",
            summary="Работа в середине шага, который нельзя обрывать.",
            why_it_matters="Прерваться здесь дороже, чем дойти до безопасной точки.",
            next_steps=["дойду до безопасной точки и вернусь к этому решению"], technical=tech)
    return message(
        status="degraded", headline="Сам продолжить не могу",
        summary=(decision or {}).get("reason") or "Нет условий, чтобы взять работу отдельно.",
        next_steps=["продолжим здесь"], technical=tech)


def from_session_economy(snapshot: dict, rec: dict) -> dict:
    """Снимок сессии + SessionRecommendation -> UserMessage. Говорится ДО траты, а не после.

    ДВА ДЕФЕКТА ОДНОГО МЕСТА (найдено полем 2026-08-13). Первый: расход назывался только в ритуале
    ЗАВЕРШЕНИЯ WorkItem — то есть решение «здесь новую сессию не начинаем» человек мог принять лишь
    после того, как уже потратил. Второй: страж перед старом печатал что-либо только при исходах
    `new_session`/`compact`, а поскольку контекст всегда был `unknown` (транскрипт не читался
    никогда), этих исходов не наступало и страж молчал всегда. Молчание читалось как «всё в порядке».

    Поэтому здесь расход называется ВСЕГДА, и «не измерено» — отдельный, видимый ответ, а не тишина.
    """
    ctx = snapshot.get("context_current")
    status = snapshot.get("context_status")
    outcome = (rec or {}).get("outcome")
    spend = (rec or {}).get("session_spend") or "н/д"
    turns = snapshot.get("turns")
    # Внутренняя причина остаётся В ДЕТАЛЯХ: в ней живут имена вроде `WorkItem`, которым наружу
    # хода нет, а отлаживать по ней надо.
    tech = {"контекст": ctx, "статус измерения": status,
            "источник": snapshot.get("context_source") or "—",
            "ходов": turns, "источник ходов": snapshot.get("turns_source") or "—",
            "расход сессии": spend, "состояние расхода": (rec or {}).get("spend_state") or "—",
            "исход": outcome, "причина": (rec or {}).get("reason") or "—",
            # Путь — В ДЕТАЛЯХ (наружу путям хода нет), но САМ ФАКТ идёт в текст ниже: уйти из
            # сессии, не записав её состояние, — это потеря труда, а не деталь реализации.
            "handoff сессии": (rec or {}).get("handoff") or "—",
            "последняя компакция": snapshot.get("last_compaction_at") or "не обнаружена"}

    if status == "unavailable":
        why = snapshot.get("session_unavailable_reason")
        tech["почему не измерено"] = why or "—"
        return message(
            status="degraded", headline="Расход этой сессии я не вижу",
            summary="Сколько сессия уже прочитала — не измерено."
                    + (f" Причина: {why}" if why else ""),
            why_it_matters="Это не «мало»: без числа я не могу вовремя сказать, что пора начинать "
                           "новую сессию, и работа будет идти дороже молча.",
            next_steps=["покажи `/context` и передай число как `--context N`"],
            technical=tech)

    human_ctx = f"{ctx / 1000:.0f}k" if ctx else "н/д"
    measured = "измерено" if status == "measured" else "оценка"
    head = f"Сессия читает {human_ctx} на каждом запросе ({measured}); прочитала всего {spend}"

    if outcome in ("new_session", "compact", "clear"):
        advice = {"new_session": "начать чистую сессию",
                  "compact": "сжать историю на этой безопасной границе",
                  "clear": "очистить историю — следующая работа не связана с прошлой"}[outcome]
        return message(
            status="degraded", headline="Прежде чем тратить — стоит сменить сессию",
            summary=f"{head}.",
            why_it_matters="Каждый следующий запрос заново оплачивает перечитывание этой истории. "
                           "Дальше будет только дороже, а пользы от старой переписки уже нет.",
            decision={"question": "начинать работу здесь или в чистой сессии?",
                      "recommendation": advice,
                      "on_approve": "выполни команду ниже и повтори задачу",
                      "on_reject": "продолжу здесь — решение твоё, я не блокирую"},
            # Состояние handoff — ПЕРВЫЙ шаг, а не приписка: если состояние сессии не записано,
            # уходить из неё нечем, и это важнее самой команды выхода.
            next_steps=[(rec or {}).get("handoff") or "состояние сессии не проверено",
                        (rec or {}).get("command") or "продолжаю здесь"],
            technical=tech)
    # `attention` — не «всё хорошо»: сказать «история дешёвая» при растущем счёте значило бы
    # успокаивать там, где кит как раз обязан предупредить.
    growing = "attention" in ((rec or {}).get("context_state"), (rec or {}).get("spend_state"))
    return message(
        status="ok",
        headline="Счёт растёт, но сессию менять пока рано" if growing else "Сессию менять не нужно",
        summary=f"{head} — работаю здесь.",
        why_it_matters=("Расход подходит к порогу: следующую независимую задачу лучше начать "
                        "в чистой сессии, а эту — довести до конца здесь." if growing else
                        "Пока история дешёвая, собранное знание выгоднее переиспользовать, "
                        "чем начинать с нуля."),
        technical=tech)


def from_bootstrap(rep: dict, applied=False) -> dict:
    """`bootstrap.plan()` / `bootstrap.apply()` -> UserMessage. Онбординг заканчивается РАБОТОЙ.

    Запись артефактов в чужой репозиторий владелец обязан увидеть ДО того, как она произошла, —
    поэтому сухой прогон спрашивает решение, а не сообщает о сделанном.
    """
    if rep.get("error"):
        return message(status="blocked", headline="Создавать не стал",
                       summary=str(rep["error"]),
                       why_it_matters="Перезаписать файл, который я не смог прочитать, значит "
                                      "уничтожить работу, которую в нём кто-то делал.",
                       next_steps=["починим файл и повторим"],
                       technical={"error": rep["error"]})

    if applied:
        wrote = rep.get("written") or []
        skipped = rep.get("skipped") or []
        n_work = rep.get("work_items") or 0
        n_q = rep.get("blocking_questions") or 0
        if not wrote:
            return message(
                status="ok", headline="Всё уже было на месте",
                summary="Создавать было нечего: направление и план в проекте уже есть.",
                next_steps=["спроси «что дальше» — предложу работу по существующему плану"],
                technical={"пропущено": ", ".join(s["path"] for s in skipped) or "—"})
        # СКОЛЬКО ИЗ НИХ МОЖНО НАЧАТЬ БЕЗ МЕНЯ — РАЗНЫЕ ОТВЕТЫ. Если каждая работа начинается с
        # ответа владельца, обещать «спроси что дальше — назову первую работу» нельзя: там будет
        # «ждёт решения человека», и это ровно тот разрыв обещания, из-за которого правится тир 4.
        doable = rep.get("ready_without_human")
        waiting = rep.get("awaiting_human") or 0
        tech = {"создано": ", ".join(w["path"] for w in wrote),
                "пропущено": ", ".join(s["path"] for s in skipped) or "—",
                "работ": n_work, "ждут ответа": waiting, "вопросов": n_q}
        if doable == 0 and n_work:
            return message(
                status="needs_input", headline="План есть, и он начинается с тебя",
                summary=f"Собрал направление и план: {n_work} "
                        f"{_q(n_work, 'работа', 'работы', 'работ')}; все они начинаются с твоего "
                        f"ответа.",
                why_it_matters="Это не бюрократия: без ответов я не знаю ни для кого продукт, ни "
                               "что считать результатом, — и выдумывать это я не буду.",
                next_steps=["впиши ответы в .ai/project/onboarding-answers.yaml",
                            "потом спроси «что дальше» — работа станет готовой"],
                technical=tech)
        return message(
            status="ok", headline="Готово: теперь есть с чем работать",
            summary=f"Собрал направление и план: {n_work} "
                    f"{_q(n_work, 'работа', 'работы', 'работ')} по тому, чего проекту "
                    f"не хватает.",
            why_it_matters=(f"Из них {waiting} ждут твоего ответа — из кода это не выводится, и я "
                            f"это не выдумывал; остальное могу начать сам." if waiting else
                            "Всё это выведено из твоего репозитория, а не придумано за тебя."),
            next_steps=["спроси «что дальше» — назову первую работу и обоснование",
                        "в файлах есть пометки «нужно ваше слово» — там я не стал догадываться"],
            technical=tech)

    will = rep.get("will_write") or []
    items = rep.get("work_items") or []
    if not will:
        return message(
            status="ok", headline="Создавать нечего",
            summary="Направление и план в проекте уже есть — трогать их я не буду.",
            why_it_matters="Существующий файл — факт о продукте, и он сильнее любого моего шаблона.",
            next_steps=["спроси «что дальше» — предложу работу по существующему плану"],
            technical={a["path"]: a["why"] for a in (rep.get("actions") or [])})
    n = len(items)
    return message(
        status="needs_input", headline="Могу собрать первый план",
        summary=f"Готов создать направление и план работ: {n} "
                f"{_q(n, 'работа', 'работы', 'работ')} по тому, чего проекту не хватает.",
        why_it_matters="Всё это выведено из твоего репозитория: каждая работа — область, где у "
                       "проекта нет описания. Продуктовые цели я выдумывать не буду — там, где "
                       "нужен твой ответ, останется пометка.",
        decision={"question": "создать " + " и ".join(will),
                  "recommendation": "создать — существующие файлы я не перезаписываю",
                  "on_approve": "создам и сразу скажу, какую работу брать первой",
                  "on_reject": "ничего не пишу; понимание проекта останется, плана не будет"},
        next_steps=[f"первой пойдёт «{items[0]['title']}»"] if items else None,
        technical={a["path"]: a["why"] for a in (rep.get("actions") or [])})


def from_intake_gap(missing, hint_command=None) -> dict:
    """Незаданные intake-сигналы -> UserMessage. Спрашиваем ДО прогона, а не после.

    В живой квалификации так сгорело 6 прогонов из 6, самый долгий — 36 минут: `size` требует
    блокирующий гейт, вывести его из репозитория нечем, и человек узнавал об этом из вердикта.
    Команду с готовым ответом печатаем в `next` — на уровне `product` он тоже виден, иначе
    сообщение сообщало бы о препятствии и не давало его убрать.
    """
    miss = list(missing or [])
    names = {"size": "насколько большая задача", "risk": "насколько рискованная",
             "task_type": "какого рода работа"}
    human = [names.get(m.get("signal"), m.get("signal")) for m in miss]
    steps = ["ответь одной строкой: " + hint_command] if hint_command else []
    return message(
        status="needs_input", headline="Пары слов о задаче не хватает",
        summary="Прежде чем запускать, мне нужно понять: " + ", ".join(human) + ".",
        why_it_matters="Из кода это не выводится, а без этого прогон остановится на проверке — "
                       "уже потратив время. Спрашиваю секундой, а не часом.",
        next_steps=steps or ["скажи размер и риск задачи"],
        technical={m.get("signal"): " | ".join(m.get("allowed") or []) or "значение"
                   for m in miss})


def from_short_path(decision: dict, trace: dict = None, next_command: str = None) -> dict:
    """Решение о коротком пути -> UserMessage. Три случая, и они РАЗНЫЕ для человека.

    Короткий путь взят — говорим, что описание не переписываем и что от него осталось в следе.
    Заявлено, но минимума нет — называем ровно то, чего не хватает: это единственное, что человеку
    нужно сделать, чтобы получить короткий путь. Не заявлено — сообщения нет вовсе: кит не
    предлагает владельцу выключить собственные проверки.
    """
    names = decision.get("human_names") or {}
    keys = list(names)
    if decision.get("short_path"):
        tr = trace or {}
        declined = len(tr.get("declined") or [])
        return message(
            status="ok", headline="Работа уже описана — иду сразу делать",
            summary="Описание у тебя есть: понятно, чего добиваемся, как поймём, что готово, и где "
                    "править. Заново расспрашивать и планировать не буду.",
            why_it_matters="Я останусь в этой работе как след: что решено, по каким признакам это "
                           "видно и что я пропустил — записано, и это можно проверить позже."
                           + (f" Разделов, которые я не требую, {declined} — у каждого написано, "
                              f"почему." if declined else ""),
            next_steps=[f"делаю: {next_command}"] if next_command else ["беру работу в исполнение"],
            technical={"признаки": {names[k]: decision["minimum"][k]["detail"] for k in keys},
                       "заявлено": decision.get("declared_by"),
                       "пропущено": ", ".join(decision.get("skipped_steps") or []) or "—",
                       "решение": decision.get("decision_ref"),
                       "след": str((trace or {}).get("record") or "—")})
    if decision.get("unknown"):
        return message(
            status="degraded", headline="Похоже, описание есть, но я его не читаю",
            summary="Ты сказала, что работа описана, но проверить это я не могу: "
                    + "; ".join(decision["minimum"][k]["detail"] for k in decision["unknown"]),
            why_it_matters="Пойти коротким путём на непрочитанном описании — то же самое, что "
                           "поверить на слово. Поэтому иду обычным путём, а не притворяюсь, что "
                           "проверил.",
            next_steps=["поправить описание, чтобы оно читалось, — и короткий путь включится сам"],
            technical={"не прочитано": decision["unknown"]})
    return message(
        status="needs_input", headline="Чтобы идти сразу делать, не хватает малого",
        summary="Ты сказала, что работа описана. Чего я в описании не нашёл: "
                + ", ".join(decision.get("missing_names") or []) + ".",
        why_it_matters="Это тот самый минимум, по которому потом можно сказать «готово» и не "
                       "обмануться. Без него я не пропускаю разбор — иначе проверять результат "
                       "будет нечем.",
        next_steps=["дописать это в описание — дальше пойду коротким путём без вопросов"],
        technical={names.get(k, k): decision["minimum"][k]["detail"]
                   for k in (decision.get("missing") or [])})


def from_process_spend(check: dict, continue_command: str = None,
                       run_command: str = None) -> dict:
    """Потолок траты на описание до первой правки кода -> UserMessage (решение владельца 2026-08-17).

    Это ВОПРОС, а не отказ: владелец решила предупреждать и спрашивать, а не останавливать молча.
    Поэтому у сообщения есть и рекомендация, и то, что будет при обоих ответах.
    """
    spent, limit = check.get("spent_on_process"), check.get("ceiling")

    def _t(n):
        return "н/д" if n is None else (f"{n / 1000:.0f} тысяч" if n >= 1000 else str(n))

    if check.get("state") == "unknown":
        return message(
            status="degraded", headline="Сколько уходит на разбор — не вижу",
            summary="Потолок траты на описание я применить не могу: расход этой сессии не измеряется.",
            why_it_matters="Называть это нормой было бы неправдой: я не знаю числа, а не знаю, что "
                           "оно маленькое.",
            technical={"причина": check.get("reason")})
    step = check.get("intent") or "разбор"
    return message(
        status="needs_input", headline="Разбор уже дороже, чем ты разрешила",
        summary=f"На то, чтобы разобраться и описать, ушло в этой сессии {_t(spent)} токенов, а кода я "
                f"ещё не тронул. Твой потолок на это — {_t(limit)}.",
        why_it_matters="Ровно так уже сгорали сессии: описание уточнялось по кругу, а работа не "
                       "начиналась. Но пропускать объявленный шаг я не советую — путь "
                       "specify→plan→run затем и объявлен, чтобы результат было чем проверить.",
        decision={"question": f"довести шаг «{step}» до конца или ты считаешь описание готовым?",
                  "recommendation": f"довести {step} и идти дальше по объявленному пути; если разбор "
                                    "пошёл по кругу — назвать, чего конкретно не хватает, а не "
                                    "углубляться дальше. Шаг не пропускать.",
                  "on_approve": f"продолжаю {step}: {continue_command}" if continue_command
                                else f"продолжаю {step}",
                  "on_reject": f"описание готово — беру в исполнение: {run_command}" if run_command
                               else "описание готово — беру работу в исполнение"},
        next_steps=[c for c in (continue_command, run_command) if c],
        technical={"потрачено на описание": spent, "потолок": limit,
                   "шаги описания": ", ".join(check.get("process_steps") or []) or "—",
                   "расход сессии всего": check.get("session_total_tokens"),
                   "решение": check.get("decision_ref")})


def from_kit_feedback_recorded(path, created, errors, has_evidence, declared_class) -> dict:
    """Наблюдение о ките записано (или не записано) -> UserMessage.

    Отказ здесь — не бюрократия: «дефект» без улики попал бы в кит утверждением, за которое некому
    отвечать. Поэтому сообщение НЕ ругает человека, а называет, что именно приложить.
    """
    if errors:
        return message(
            status="needs_input", headline="Записать не могу — не на что опереться",
            summary="Ты говоришь, что я сделал что-то не так, и я хочу это запомнить. Но как "
                    "дефект это уйдёт ко мне утверждением без доказательства, а такие я сам же и "
                    "учусь не производить.",
            why_it_matters="Достаточно одной опоры: файл и строка из него — или команда и то, что "
                           "она напечатала. Если опоры нет, скажи это как трение или вопрос — их я "
                           "принимаю без доказательств.",
            next_steps=["добавить файл со строкой или команду с выводом",
                        "либо записать как трение: то же самое со словом «мешает», без улик"],
            technical={"почему не записано": "; ".join(errors)})
    if not created:
        return message(
            status="ok", headline="Это я уже записал",
            summary="Такое наблюдение у меня уже есть — второй раз не завожу, чтобы не считать одно "
                    "и то же дважды.",
            next_steps=["посмотреть судьбу сказанного: ./ai-ops feedback"],
            technical={"файл": path})
    return message(
        status="ok", headline="Записал — и это дойдёт до меня самого",
        summary="Твоё замечание сохранено в проекте вместе с тем, чем оно подтверждено."
                + ("" if has_evidence else " Улик нет, поэтому дефектом я это не называю."),
        why_it_matters="Раньше такое доезжало до меня только пересказом — то есть если человек "
                       "вспомнит. Теперь это данные: их видно, у них будет ответ.",
        next_steps=["посмотреть судьбу сказанного: ./ai-ops feedback"],
        technical={"файл": path, "класс": declared_class or "выведен из улик",
                   "улики": "есть" if has_evidence else "нет"})


# Состояние строки doctor -> насколько это плохо. Порядок важен: вердикт следует за ХУДШЕЙ строкой.
_DOCTOR_RANK = {"ok": 0, "info": 0, "unknown": 1, "gap": 1, "warn": 1, "fail": 2, "blocked": 2}


def from_doctor(lines) -> dict:
    """Строки проверки установки -> UserMessage. Вердикт следует за ХУДШЕЙ строкой.

    Прежде итог `doctor: OK` не зависел от строк с `✗` в том же выводе: человек либо перестаёт
    читать строки, либо перестаёт верить вердикту. Оба исхода делают проверку бесполезной.
    """
    rows = list(lines or [])
    worst = max((_DOCTOR_RANK.get(r.get("state"), 1) for r in rows), default=0)
    gaps = [r for r in rows if _DOCTOR_RANK.get(r.get("state"), 1) >= 1]
    blocking = [r for r in rows if _DOCTOR_RANK.get(r.get("state"), 1) >= 2]

    if worst == 0:
        return message(status="ok", headline="Всё в порядке",
                       summary="Кит на месте и работает как ожидается.",
                       next_steps=["можно ставить задачу"],
                       technical={"проверок": len(rows)})
    n = len(gaps)
    if worst >= 2:
        # БЛОКИРУЮЩЕЕ СЧИТАЕМ ОТДЕЛЬНО ОТ ЗАМЕЧАНИЙ. Общий счётчик называл «проблемами, из-за
        # которых работать нельзя» и обычные предупреждения — число врало в сторону паники, а это
        # такая же неправда, как зелёный вердикт на красном выводе.
        nb = len(blocking)
        rest = n - nb
        return message(
            status="blocked",
            summary=f"Кит проверил себя и нашёл {nb} {_q(nb, 'причину', 'причины', 'причин')}, "
                    f"из-за которых работать нельзя: "
                    + "; ".join(r.get("text", "") for r in blocking[:2])
                    + ("…" if nb > 2 else "."),
            why_it_matters="Пока это не исправлено, всё остальное, что я скажу, ничего не доказывает."
                           + (f" Кроме этого есть {rest} "
                              f"{_q(rest, 'замечание', 'замечания', 'замечаний')}." if rest else ""),
            next_steps=[r.get("text", "") for r in blocking][:2],
            technical={r.get("id", f"строка{i}"): r.get("text") for i, r in enumerate(rows)})
    return message(
        status="degraded", headline="Работать можно, но есть замечания",
        summary=f"Кит на месте; замечаний {n}.",
        why_it_matters="Работать можно; замечания стоит закрыть, чтобы проверки говорили полную правду.",
        next_steps=[r.get("text", "") for r in gaps][:2],
        technical={r.get("id", f"строка{i}"): r.get("text") for i, r in enumerate(rows)})
