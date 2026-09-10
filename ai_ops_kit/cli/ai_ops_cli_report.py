"""Проб-свободные read-only intent-хендлеры отчётности, вынесенные из `ai_ops_cli_intents`.

Здесь живут владельческие карточки `explain` (что с моей задачей прямо сейчас) и `inbox`
(что требует моего внимания). Обе команды ТОЛЬКО ЧИТАЮТ реестры, workitem, живой статус-док
и журналы — ничего не пишут и ничего не сверяют с записью, поэтому проб-свободны.

`_inbox_release_warnings` переиспользует `_product_health_report` из `ai_ops_cli_product`.
Регистрация обработчиков делается в `ai_ops_cli`. Модуль НЕ импортирует `ai_ops_cli` на
верхнем уровне — обращения к его хелперам идут ленивым импортом внутри функции.
"""
from __future__ import annotations

import json
from pathlib import Path
from ai_ops_kit.cli.ai_ops_cli_product import _product_health_report

# ── ai-ops explain (#539): владельческая карточка «что с моей задачей прямо сейчас» ──────────────
# Одна карточка на один вопрос владельца: какая задача, на какой она стадии, что готово, что идёт,
# ЧТО МЕШАЕТ И ПОЧЕМУ (последствием, простыми словами — не гейтом и не трейсбеком), следующий шаг и
# оценка стоимости. Команда ТОЛЬКО ЧИТАЕТ: реестр идущих работ, workitem дочки, живой статус-док
# (living_status.describe — read-only, не бросает) и журнал расхода (usage-ledger). Ничего не пишет
# и ничего не сверяет с записью (в отличие от `status`, который снятое сверкой ПЕРСИСТИТ) — поэтому
# обработчик проб-свободен и живёт здесь, а не в ai_ops_cli.py.

_EXPLAIN_STATUS_LABEL = {
    "draft": "заведена, ещё не оценивалась",
    "in_progress": "в работе",
    "blocked": "остановлена",
    "needs_human_decision": "ждёт твоего решения",
    "needs_more_evidence": "не подтверждена",
    "done": "готова",
}


def _explain_wid(entry):
    """id работы из записи active-work: движок пишет `workitem` ПУТЁМ `features/<id>/workitem.yaml`.
    Та же нормализация, что у delivery_plan._workitem_key — своя, чтобы не тянуть приватный хелпер."""
    wi = str(entry.get("workitem") or "").replace("\\", "/").strip()
    if wi:
        parts = [x for x in wi.split("/") if x]
        if len(parts) >= 2 and parts[0] == "features":
            return parts[1]
        if not wi.endswith(".yaml"):
            return wi
    return str(entry.get("id") or "")


def _explain_reconcile(team, child_root):
    """Сверить заявки с базой (снять уже влитое) read-only. Сбой git -> исходный список без сверки:
    карточка не обязана падать из-за недоступного/непроверяемого репозитория."""
    from ai_ops_kit.lifecycle import active_work
    try:
        return active_work.reconcile_with_base(team, child_root)   # чистая: исходные не мутируются
    except Exception:  # noqa: BLE001 — сверка с базой не обязана удаваться, карточку не роняем
        return team


def _explain_active(child_root):
    """READ-ONLY список идущих работ: реестр + носитель копий + сверка с базой БЕЗ записи.

    Снятое (done/superseded) и мёртвые держатели исключены — как это делает `status`, но здесь без
    `persist_reconciliation`: карточка ничего не переписывает. Битый реестр -> None (сигнал «не знаю,
    что идёт», а не «ничего не идёт»)."""
    from ai_ops_kit.lifecycle import active_work
    awp = Path(child_root) / ".ai" / "runtime" / "active-work.yaml"
    local = []
    if awp.is_file():
        try:
            local = active_work.load(awp).get("active") or []
        except active_work.ActiveWorkCorrupt:
            return None
    pub = active_work.publication_enabled(child_root)
    team = active_work.team_view(child_root, local, pub)
    team = _explain_reconcile(team, child_root)   # чистая сверка с базой, БЕЗ persist
    out = []
    for a in team:
        if (a.get("status") or "") in ("done", "superseded"):
            continue
        if active_work.holder_is_gone(a):
            continue
        out.append(a)
    return out


def _explain_workitem(child_root, wid):
    """workitem.yaml идущей работы: task/workflow/status/human_approval. -> dict (read-only)."""
    import yaml
    p = Path(child_root) / "features" / str(wid) / "workitem.yaml"
    if not p.is_file():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}


def _explain_gates(child_root, wid):
    """Сколько гейтов в плане работы (features/<wid>/run-plan.yaml) — для стадии. -> int|None."""
    import yaml
    p = Path(child_root) / "features" / str(wid) / "run-plan.yaml"
    if not p.is_file():
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    g = data.get("gates")
    return len(g) if isinstance(g, list) else None


def _explain_conflicts(focus, others):
    """Пересечение области записи фокусной работы с другими идущими. -> список веток/id.

    То же правило, что у delivery_plan._scope_conflict: сравнение по префиксу до первого `*`.
    Пересечение — реальная причина остановиться (две ветки перепишут одно место)."""
    from ai_ops_kit.planning.delivery_plan import scope_prefix, scopes_overlap
    mine = [scope_prefix(x) for x in (focus.get("affected_areas") or focus.get("areas") or [])]
    if not mine:
        return []
    hits = []
    for o in others:
        theirs = [scope_prefix(x) for x in (o.get("affected_areas") or o.get("areas") or [])]
        if any(scopes_overlap(m, t) for m in mine for t in theirs):
            hits.append(_explain_wid(o) or o.get("branch") or "другая работа")
    return sorted(set(hits))


def _explain_cost(child_root, wid):
    """Оценка стоимости работы из usage-ledger (persist). Честно про неизмеренное. -> dict."""
    from ai_ops_kit.shared import usage_ledger
    try:
        recs = usage_ledger.load_task(child_root, wid)
    except Exception:  # noqa: BLE001 — журнал расхода не обязан существовать/читаться
        recs = None
    if not recs:
        return {"measured": False}
    agg = usage_ledger.aggregate(recs)
    return {"measured": True, "cost_usd": agg.get("cost"),
            "cost_complete": agg.get("cost_complete"), "calls": agg.get("calls"),
            "tokens": (agg.get("input_tokens") or 0) + (agg.get("output_tokens") or 0)}


def _explain_blocker(status, human_approval, conflicts):
    """Что мешает и ПОЧЕМУ — последствием, не местом в коде и не именем гейта. -> строка|None.

    Пересечение областей — самая конкретная причина, поэтому первым. Дальше — по статусу WorkItem;
    формулировки объясняют СЛЕДСТВИЕ («к выпуску не готова», «жду решения»), а не гейт."""
    if conflicts:
        who = ", ".join(conflicts[:3])
        return ("работа трогает файлы, которые уже правит другая работа — если продолжить, две "
                f"ветки перепишут одно место (пересечение с: {who})")
    return {
        "blocked": ("к выпуску пока не готова: обязательная проверка не пройдена, и я не выдаю за "
                    "готовое то, что не проверено"),
        "needs_human_decision": ("жду твоего решения: работа затрагивает то, что я не меняю без "
                                 "твоего подтверждения"),
        "needs_more_evidence": ("подтвердить готовность не могу: не хватает доказательств, что "
                                "изменение действительно проверено"),
    }.get(status)


def _explain_next(status, wid, task, no_active):
    """Следующий шаг простыми словами."""
    if no_active:
        return "скажи, что взять, или спроси «что дальше» — предложу с обоснованием"
    q = task or wid
    return {
        "blocked": f"покажу, что именно не прошло, и доведу: ./ai-ops resume . {wid} --execute",
        "needs_human_decision": "подтверди изменение — и я продолжу",
        "needs_more_evidence": f"соберу недостающие доказательства: ./ai-ops resume . {wid} --execute",
        "in_progress": "продолжу то, что уже в работе",
        "draft": f'опишу и запущу: ./ai-ops specify "{q}" --feature {wid}',
        "done": "работа готова — можно доставлять или брать следующую",
    }.get(status, "продолжу то, что уже в работе")


def _explain_living_note(doc):
    """Строка о судьбе статус-дока — в технические детали (не блокер сам по себе)."""
    doc = doc or {}
    if doc.get("managed"):
        return ("статус-док свеж на сегодня" if doc.get("fresh_today")
                else f"статус-док обновлялся {doc.get('reviewed_at') or '—'}")
    return f"статус-док: {doc.get('reason') or 'не найден'}"


def _explain_cost_line(cost):
    """Человеческая строка о стоимости для summary."""
    if not cost.get("measured"):
        return "Стоимость пока не измерена — обращений к модели по этой задаче ещё не было."
    usd, calls = cost.get("cost_usd"), cost.get("calls") or 0
    if usd is None or (not usd and not cost.get("cost_complete")):
        return f"Обращений к модели: {calls}; их стоимость пока не измерена."
    approx = "" if cost.get("cost_complete") else " (часть обращений без стоимости)"
    return f"Пока потрачено примерно ${usd:.2f} (обращений к модели: {calls}){approx}."


def _explain_cost_tech(cost):
    """Стоимость для технических деталей."""
    if not cost.get("measured"):
        return "не измерена (нет журнала расхода задачи)"
    usd = cost.get("cost_usd")
    money = f"${usd:.4f}" if usd is not None else "—"
    return (f"{money}, обращений {cost.get('calls')}, токенов {cost.get('tokens')}, "
            + ("стоимость полная" if cost.get("cost_complete") else "стоимость неполная"))


def _explain_outcome(child_root):
    """Продуктовый ИТОГ по релизу для карточки explain (#566). Read-only, опционально.

    Автообнаружение OutcomeContract(+Readout) и прогон делает ЕДИНЫЙ путь
    post_release_loop.discover_and_run — тот же механизм, что у `readout`/`inbox`/`next`, не второй.
    Нет артефактов -> None (карточка не меняется)."""
    from ai_ops_kit.cli import post_release_loop
    result = post_release_loop.discover_and_run(child_root)
    if result is None:
        return None
    ev = (result.get("outcome") or {}).get("measured_evaluation") or {}
    return {"product_status": result.get("product_status"),
            "outcome_verdict": result.get("outcome_verdict"),
            "reason": ev.get("reason"), "flip_ready": result.get("outcome_flip_ready")}


def _explain_state(child_root):
    """READ-ONLY снимок «что с моей задачей прямо сейчас». Ничего не пишет. -> dict."""
    from ai_ops_kit.engine import living_status
    root = Path(child_root)
    doc = living_status.describe(root)                       # read-only, не бросает
    active = _explain_active(root)
    if active is None:
        return {"registry_ok": False, "focus": None, "living_status": doc}
    if not active:
        return {"registry_ok": True, "focus": None, "active_count": 0, "living_status": doc,
                "product_outcome": _explain_outcome(root)}
    focus = active[0]
    wid = _explain_wid(focus)
    # #565: per-work факты берём из ЕДИНОЙ Work-проекции (тот же источник, что у `work show` и
    # `status`), а не своим набором чтений workitem/active-work. Так explain и work show не расходятся.
    from ai_ops_kit.lifecycle import work_view
    view = work_view.project_work(wid, root)
    status = view.get("status") or "in_progress"
    return {
        "registry_ok": True, "active_count": len(active),
        "focus": {"wid": wid, "task": view.get("title") or focus.get("title") or wid,
                  "workflow": view.get("workflow"), "status": status,
                  "branch": view.get("branch") or focus.get("branch"),
                  "human_approval": bool(view.get("human_approval_required"))},
        "conflicts": _explain_conflicts(focus, active[1:]),
        "cost": _explain_cost(root, wid), "gates": _explain_gates(root, wid),
        "work_view": view,
        "living_status": doc,
        "product_outcome": _explain_outcome(root),
    }


def _explain_apply_outcome(msg, po):
    """Вплести продуктовый ИТОГ в карточку explain (#566): «технически done, продуктово нет» — явно.

    Итог ещё не измерен (unknown) — карточку НЕ трогаем: unknown ≠ провал. Провал измеренного итога
    при зелёной доставке — отдельный явный заголовок, чтобы «хорошо сделали» не читалось как «сделали
    правильное»."""
    if not po:
        return msg
    ps = po.get("product_status") or {}
    verdict = po.get("outcome_verdict")
    if verdict not in ("met", "failed"):
        return msg
    reason = po.get("reason") or ""
    base_summary = (msg.get("summary") or "").rstrip(". ")
    if ps.get("technically_done_not_product"):
        msg["headline"] = "Технически done, продуктово нет"
        msg["summary"] = base_summary + ". Доставка зелёная, но измеренный продуктовый результат " \
                                        "цель не берёт."
        msg["why_it_matters"] = ("«Сделали хорошо» и «сделали правильное» — это разные вещи. "
                                 + reason).strip()
        msg["status"] = "degraded"
    elif verdict == "failed":
        msg["summary"] = base_summary + ". Продуктовый результат по релизу не достигнут."
        msg["why_it_matters"] = ((msg.get("why_it_matters") or "") + " " + reason).strip()
        msg["status"] = "degraded"
    else:  # met
        msg["summary"] = base_summary + ". Продуктовый результат по релизу достигнут."
    td = msg.setdefault("technical_details", {"available": True, "payload": {}})
    td["available"] = True
    td.setdefault("payload", {})["продуктовый итог"] = ps.get("label")
    return msg


def _explain_message(state):
    """Снимок -> UserMessage (одна карточка). presenter скрывает технические детали и лексику для
    аудитории `product`; здесь мы лишь собираем факты и говорим блокер СЛЕДСТВИЕМ."""
    from ai_ops_kit.ui import presenter
    ls = _explain_living_note(state.get("living_status"))
    po = state.get("product_outcome")
    if not state.get("registry_ok"):
        return presenter.message(
            status="degraded", headline="Не знаю, что идёт прямо сейчас",
            summary="Запись об идущих работах повреждена, поэтому карточку задачи собрать не могу.",
            why_it_matters="Пока это так, я не поручусь, что новая работа не перепишет то, что уже "
                           "правит другая сессия.",
            next_steps=["восстановить запись об идущих работах и повторить"],
            technical={"статус-док": ls})
    if state.get("focus") is None:
        return _explain_apply_outcome(presenter.message(
            status="ok", headline="Прямо сейчас ничего не идёт",
            summary="Активной работы нет — ни одной начатой задачи.",
            why_it_matters="Сужу по заявкам на работу: открытых нет.",
            next_steps=["скажи, что взять, или спроси «что дальше» — предложу с обоснованием"],
            technical={"идёт работ": 0, "статус-док": ls}), po)
    f = state["focus"]
    st = f["status"]
    label = _EXPLAIN_STATUS_LABEL.get(st, "в работе")
    cost = state.get("cost") or {}
    # Имя ветки — жаргон для product-аудитории (как SHA/gate-id): держим его в technical, а в
    # продуктовой строке говорим состоянием, не идентификатором. #539 judge-fix.
    where = ("Работа идёт." if f.get("branch") else "Работа начата.")
    blocker = _explain_blocker(st, f.get("human_approval"), state.get("conflicts") or [])
    if blocker:
        why = "Что мешает: " + blocker + "."
        status = "needs_input" if st == "needs_human_decision" else "blocked"
    else:
        why = "Сейчас ничего не мешает — работа продолжается."
        status = "ok"
    return _explain_apply_outcome(presenter.message(
        status=status, headline=f'«{f["task"]}» — {label}',
        summary=f"{where} {_explain_cost_line(cost)}",
        why_it_matters=why,
        next_steps=[_explain_next(st, f["wid"], f["task"], no_active=False)],
        technical={"работа": f["wid"], "workflow": f.get("workflow") or "—", "статус": st,
                   "гейтов в плане": state.get("gates") if state.get("gates") is not None else "—",
                   "оценка стоимости": _explain_cost_tech(cost), "ветка": f.get("branch") or "—",
                   "идёт работ всего": state.get("active_count"),
                   "пересечение областей": ", ".join(state.get("conflicts") or []) or "—",
                   "статус-док": ls}), po)


def _intent_explain(task, child_root, signals, a):
    js = a.json
    from ai_ops_kit.ui import presenter
    state = _explain_state(Path(child_root))
    if js:
        print(json.dumps(state, ensure_ascii=False, indent=2, default=str))
    else:
        print(presenter.render(_explain_message(state),
                               audience=presenter.audience_from_config(Path(child_root))))
    # Код возврата — ГОТОВНОСТЬ ОТВЕТИТЬ, а не наличие работы: карточка собрана -> 0; недостоверный
    # реестр (собрать честно не смогли) -> 1. «Ничего не идёт» — это ответ, а не отказ, поэтому 0.
    return 0 if state.get("registry_ok") else 1


# ── ai-ops inbox (#540): единая владельческая очередь «что ждёт моего решения» ────────────────────
# Один список всего, что застряло на человеке: решения (компактная карточка что/варианты/рекомендация),
# остановленные работы, работы, ждущие подтверждения, свежий ночной обзор и предупреждения о выпуске.
# Команда ТОЛЬКО ЧИТАЕТ те же источники, что explain/health и каталог решений, и ничего не пишет и не
# сверяет с записью — поэтому обработчик проб-свободен и живёт здесь. Пусто -> честное «ничего не
# ждёт», а не выдуманный список; битый реестр идущих работ -> «не знаю, что ждёт» (не ложное «ничего»).


def _inbox_decisions(child_root):
    """Ожидающие решения владельца (product-decision, status pending) — read-only. Карточка:
    что/варианты/рекомендация. Каталог решений читаем НАПРЯМУЮ, а не через его API-обёртку
    (list-decisions): та на входе делает mkdir каталога, а inbox обязан ничего не писать. Сбой чтения
    файла -> пропуск (решение молча НЕ показываем ложно)."""
    import yaml
    ddir = Path(child_root) / ".ai" / "project" / "decisions"
    if not ddir.is_dir():
        return []
    out = []
    for f in sorted(ddir.glob("*.yaml")):
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(d, dict) or d.get("status") != "pending":
            continue
        out.append({"id": d.get("id"), "what": d.get("proposal") or d.get("id") or "решение",
                    "options": [str(o) for o in (d.get("options") or [])],
                    "recommendation": d.get("recommendation") or ""})
    return out


def _inbox_works(child_root):
    """Идущие работы, застрявшие на человеке: остановленные (blocked/needs_more_evidence) и ждущие
    подтверждения (needs_human_decision / требуется одобрение). Переиспользует read-only сборку
    explain (реестр + сверка с базой БЕЗ persist). -> (blocked, reviews) либо (None, None) при
    недостоверном реестре (сигнал «не знаю, что идёт», а не «ничего»)."""
    root = Path(child_root)
    active = _explain_active(root)                 # read-only, без persist
    if active is None:
        return None, None
    blocked, reviews = [], []
    for entry in active:
        wid = _explain_wid(entry)
        wi = _explain_workitem(root, wid)
        st = wi.get("status") or "in_progress"
        task = wi.get("task") or entry.get("title") or wid
        if st in ("blocked", "needs_more_evidence"):
            why = _explain_blocker(st, wi.get("human_approval_required"), []) or "продолжить нельзя"
            blocked.append({"wid": wid, "task": task, "why": why})
        elif st == "needs_human_decision" or wi.get("human_approval_required"):
            reviews.append({"wid": wid, "task": task,
                            "why": "работа затрагивает то, что я не меняю без твоего подтверждения"})
    return blocked, reviews


# Путь durable-инбокса ночных обзоров. Держим строкой, а НЕ импортом
# nightly_review.BRIEFS_DIR_REL: этот модуль диспетчируется процессом (CI-workflow), и dormant-
# инвентарь стережёт его «0 импортеров» как легит-вход — импорт ради одной константы пробил бы этот
# инвариант. Формат стабилен (deliver_brief пишет ровно сюда).
_INBOX_BRIEFS_LATEST_REL = ".ai/project/nightly-review/briefs/latest.md"


def _inbox_insight(child_root):
    """Свежий ночной обзор владельцу: доставлен ли бриф (`latest.md` в durable-инбоксе обзоров).
    read-only. -> dict|None (None — обзора нет, а не «нечего сказать»)."""
    latest = Path(child_root) / _INBOX_BRIEFS_LATEST_REL
    if not latest.is_file():
        return None
    return {"what": "ночной обзор изменений — что поменялось и на что взглянуть",
            "path": _INBOX_BRIEFS_LATEST_REL}


def _inbox_outcome_candidate(child_root):
    """Кандидат-работа из обратной петли Outcome→Insight (#567) — ждёт решения владельца. read-only.

    Автообнаружение контракта/отчёта и прогон петли делает ЕДИНЫЙ путь post_release_loop.discover_and_run
    (тот же, что у `readout`/`explain` — один механизм). Инсайт рождается только на РЕАЛЬНОМ замере
    (met/failed); на `unknown` кандидата нет — «нет данных», а не пункт очереди. Кандидат — DRAFT:
    показываем как предложение с рекомендацией, активной работой без решения человека он не станет.
    -> dict|None (None — контракта/инсайта/кандидата нет)."""
    from ai_ops_kit.cli import post_release_loop
    result = post_release_loop.discover_and_run(child_root) or {}
    cand = result.get("candidate_work")
    if not cand:
        return None
    rec, ins = result.get("recommendation") or {}, result.get("insight") or {}
    return {"wid": cand.get("id"), "what": cand.get("title"), "confidence": ins.get("confidence"),
            "proposal": rec.get("proposal") or "", "facts": rec.get("facts") or [],
            "assumptions": rec.get("assumptions") or [],
            "critical_unknowns": rec.get("critical_unknowns") or [], "sources": rec.get("sources")}


def _inbox_findings(child_root):
    """Обратное наследование §28 (#585): наблюдения дочек из findings/from-children → кандидаты + уроки.

    READ-ONLY проекция через ЕДИНЫЙ путь intelligence.child_findings (кандидаты из ОТКРЫТЫХ наблюдений,
    уроки-прецеденты из ВСЕХ — факт+число случаев+контексты, без причинности, #586). Кандидаты — DRAFT:
    активной работой без решения человека не станут (writer ≠ judge). Нет наблюдений → None (не пункт
    очереди, а «нечего показать»). Сбой сбора → None (выдуманного не показываем).
    -> dict|None: {candidates:[...], precedents:[...], open_count, observation_count}."""
    try:
        from ai_ops_kit.intelligence import child_findings
        proj = child_findings.project_findings(Path(child_root))
    except Exception:  # noqa: BLE001 — обратный канал обогащает очередь, не является её предусловием
        return None
    if not proj.get("observation_count"):
        return None
    return {"candidates": proj.get("candidates") or [], "precedents": proj.get("precedents") or [],
            "open_count": proj.get("open_count", 0), "observation_count": proj.get("observation_count", 0)}


def _inbox_release_warnings(child_root):
    """Предупреждения о выпуске из живого здоровья продукта: band red/yellow -> выпускать рискованно.
    Нет метрик/сбой сбора -> пусто (выдуманного предупреждения не даём). read-only (health считает
    intelligence, как в contract/team)."""
    rep = _product_health_report(child_root)
    if not rep:
        return []
    band = (rep.get("band") or "").lower()
    if band not in ("red", "yellow"):
        return []
    sev = "красное" if band == "red" else "жёлтое"
    drivers = [str(x) for x in (rep.get("reasons") or [])][:3]
    return [{"what": f"здоровье продукта {sev} — выпускать рискованно",
             "why": "; ".join(drivers) if drivers else "см. здоровье продукта", "band": band}]


def _inbox_attention(child_root):
    """#633: durable сток внимания — эфемерные вызовы человека (blocked-preflight, эскалация модели,
    граница решений), у которых нет иного durable-дома. Гарантия охвата: что записано в шину, видно
    здесь. Read-only. -> [{key, source, reason, kind, work_id}]."""
    from ai_ops_kit.lifecycle import attention_bus as _ab
    try:
        return _ab.collect(child_root)
    except Exception:  # noqa: BLE001 — сток внимания не роняет inbox; пропавший повод вернётся
        return []


def _inbox_collect(child_root):
    """READ-ONLY снимок очереди владельца из всех источников. Ничего не пишет. -> dict."""
    root = Path(child_root)
    decisions = _inbox_decisions(root)
    blocked, reviews = _inbox_works(root)
    registry_ok = blocked is not None
    insight = _inbox_insight(root)
    candidate = _inbox_outcome_candidate(root)   # #567: кандидат-работа из обратной петли
    findings = _inbox_findings(root)             # #585: наблюдения дочек §28 -> кандидаты + уроки
    warnings = _inbox_release_warnings(root)
    attention = _inbox_attention(root)           # #633: шина внимания — вызовы человека из прогона
    findings_items = len((findings or {}).get("candidates") or []) + (
        1 if (findings or {}).get("precedents") else 0)
    total = (len(decisions) + len(blocked or []) + len(reviews or [])
             + (1 if insight else 0) + (1 if candidate else 0) + findings_items + len(warnings)
             + len(attention))
    return {"registry_ok": registry_ok, "total": total, "decisions": decisions,
            "blocked": blocked or [], "reviews": reviews or [], "insight": insight,
            "candidate": candidate, "findings": findings, "warnings": warnings,
            "attention": attention}


def _inbox_status(queue):
    """Статус контракта для очереди: решения/подтверждения -> нужно решение; остановки/предупреждения
    -> заблокировано; иначе ок; недостоверный реестр -> degraded (не знаем, что застряло)."""
    if not queue.get("registry_ok", True):
        return "degraded"
    findings = queue.get("findings") or {}
    attention = queue.get("attention") or []
    # #633: повод-решение из шины -> нужно решение; повод-остановка -> заблокировано.
    att_decision = any(a.get("kind") == "decision" for a in attention)
    att_blocked = any(a.get("kind") != "decision" for a in attention)
    if (queue["decisions"] or queue["reviews"] or queue.get("candidate")
            or findings.get("candidates") or att_decision):
        return "needs_input"
    if queue["blocked"] or queue["warnings"] or att_blocked:
        return "blocked"
    return "ok"


def _inbox_counts(queue):
    """Однострочная сводка очереди человеческими словами (без «0/N» и идентификаторов)."""
    parts = []
    if queue["decisions"]:
        parts.append(f"решений — {len(queue['decisions'])}")
    if queue["blocked"]:
        parts.append(f"остановлено работ — {len(queue['blocked'])}")
    if queue["reviews"]:
        parts.append(f"ждут подтверждения — {len(queue['reviews'])}")
    if queue.get("candidate"):
        parts.append("предложенная работа по итогу релиза")
    findings = queue.get("findings") or {}
    if findings.get("candidates"):
        parts.append(f"наблюдений дочек к разбору — {len(findings['candidates'])}")
    if findings.get("precedents"):
        parts.append("уроки из прогонов")
    if queue["insight"]:
        parts.append("свежий обзор")
    if queue["warnings"]:
        parts.append(f"предупреждений о выпуске — {len(queue['warnings'])}")
    if queue.get("attention"):
        parts.append(f"вызовов из прогона — {len(queue['attention'])}")
    return ", ".join(parts)


def _inbox_render(queue, aud):
    """Очередь -> текст. Для аудитории `product` внутренняя лексика скрыта (глоссарий политики), а
    идентификаторы работ/решений держим в технических деталях — как SHA/gate-id в explain. Пусто ->
    честное «ничего не ждёт», битый реестр -> «не знаю, что ждёт» (не ложное «ничего»)."""
    from ai_ops_kit.ui import presenter
    h = (lambda s: presenter._humanize(s)) if aud == "product" else (lambda s: s)
    L = presenter.statuses()
    if not queue.get("registry_ok", True):
        return (f"{L['degraded']}. Не знаю, что ждёт: запись об идущих работах повреждена.\n"
                "Восстанови её и повтори — иначе я не поручусь, что ничего не застряло на тебе.")
    if queue["total"] == 0:
        return (f"{L['ok']}. Ничего не ждёт твоего решения.\n"
                "Открытых решений, остановленных работ, непрочитанных обзоров и предупреждений о "
                "выпуске нет.")
    lines = [f"{L[_inbox_status(queue)]}. Тебя ждёт: {_inbox_counts(queue)}."]
    for d in queue["decisions"]:
        lines.append("")
        lines.append(h(f"• Реши: {d['what']}"))
        if d["options"]:
            lines.append("    варианты: " + h("; ".join(d["options"])))
        if d["recommendation"]:
            lines.append("    " + h(f"рекомендую: {d['recommendation']}"))
    for b in queue["blocked"]:
        lines.append("")
        lines.append(h(f"• Остановлена «{b['task']}»: {b['why']}"))
    for r in queue["reviews"]:
        lines.append("")
        lines.append(h(f"• Ждёт подтверждения «{r['task']}»: {r['why']}"))
    c = queue.get("candidate")
    if c:
        # #567: рекомендация несёт evidence ДО предложения — сколько наблюдений, что факт, что
        # допущение, что критично неизвестно; и только потом «предлагаю». Кандидат — черновик:
        # не станет активной работой без решения владельца (writer ≠ judge).
        lines.append("")
        lines.append(h(f"• Предлагаю по итогу релиза: {c['what']}"))
        lines.append("    " + h(f"на чём основано: наблюдений — {c.get('sources')}, "
                                f"фактов — {len(c['facts'])}, допущений — {len(c['assumptions'])}, "
                                f"критично неизвестно — {len(c['critical_unknowns'])} "
                                f"(уверенность {c.get('confidence')})"))
        for f_ in c["facts"][:3]:
            lines.append("      " + h(f"факт: {f_}"))
        for u in c["critical_unknowns"][:3]:
            lines.append("      " + h(f"не знаю: {u}"))
        lines.append("    " + h("это черновик — активной работой станет только по твоему решению"))
    # #585: обратное наследование §28 — наблюдения дочек как кандидаты к разбору (DRAFT) и уроки.
    findings = queue.get("findings") or {}
    for cand in findings.get("candidates") or []:
        lines.append("")
        lines.append(h(f"• Наблюдение из прогона к разбору: {cand.get('title')}"))
        if cand.get("source_context"):
            lines.append("    " + h(f"контекст: {cand['source_context']}"))
        lines.append("    " + h("это черновик — активной работой станет только по твоему решению"))
    precedents = findings.get("precedents") or []
    if precedents:
        # Урок = ПРЕЦЕДЕНТ: факт + В СКОЛЬКИХ случаях + контексты, БЕЗ утверждения причинности (#586).
        lines.append("")
        lines.append(h("• Уроки из прогонов (прецеденты, не правила):"))
        for p in precedents[:3]:
            ctx = ", ".join(p.get("contexts") or [])[:80]
            lines.append("    " + h(f"«{p.get('pattern')}» — {p.get('frequency_label')} "
                                    f"(случаев: {p.get('case_count')}"
                                    + (f"; контексты: {ctx}" if ctx else "") + ")"))
        lines.append("    " + h("кит показывает факт и число случаев — вывод и перенос за тобой"))
    # #633: вызовы человека из прогона (шина внимания) — durable-повод, у которого нет иного дома.
    for att in queue.get("attention") or []:
        lines.append("")
        verb = "Реши" if att.get("kind") == "decision" else "Остановлено"
        lines.append(h(f"• {verb} — {att.get('source')}: {att.get('reason')}"))
    if queue["insight"]:
        lines.append("")
        lines.append(h(f"• Есть {queue['insight']['what']}"))
    for w in queue["warnings"]:
        lines.append("")
        lines.append(h(f"• Предупреждение о выпуске: {w['what']}"))
        if w.get("why"):
            lines.append("    " + h(w["why"]))
    lines.append("")
    lines.append("Дальше: реши, что из очереди берём первым — по любому пункту скажу подробнее по запросу.")
    if aud in ("technical", "debug"):
        ids = [str(d["id"]) for d in queue["decisions"] if d.get("id")]
        ids += [b["wid"] for b in queue["blocked"]] + [r["wid"] for r in queue["reviews"]]
        if ids:
            lines.append("")
            lines.append("Технические детали:")
            lines.append("  идентификаторы: " + ", ".join(ids))
    return "\n".join(lines)


def _intent_inbox(task, child_root, signals, a):
    js = a.json
    from ai_ops_kit.ui import presenter
    root = Path(child_root)
    queue = _inbox_collect(root)
    if js:
        print(json.dumps(queue, ensure_ascii=False, indent=2, default=str))
    else:
        print(_inbox_render(queue, presenter.audience_from_config(root)))
    # Код возврата — ГОТОВНОСТЬ ОТВЕТИТЬ, а не наличие пунктов: очередь собрана -> 0 (в т.ч. пустая);
    # недостоверный реестр идущих работ (честно собрать не смогли) -> 1.
    return 0 if queue.get("registry_ok", True) else 1

