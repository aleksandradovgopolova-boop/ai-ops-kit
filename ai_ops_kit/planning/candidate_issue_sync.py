#!/usr/bin/env python3
"""Сверка issue-трекера с задачами-кандидатами: каждая открытая находка = issue-предложение.

ЗАЧЕМ. Кит уже нарезает кандидатов (`candidates`) из двух источников — непокрытые направления
роадмапа и открытые наблюдения дочек — но они жили только в выводе команды. Направление получает
issue через `roadmap sync-issues`, а находки дочек НИКУДА не заводились: чтобы владелец увидел их в
трекере, приходилось помнить. Этот модуль замыкает ту же петлю, что `roadmap_issue_sync` для
направлений: открытый кандидат становится issue-ПРЕДЛОЖЕНИЕМ, устаревший — закрывается. Механизм, а
не память.

ПРЕДОХРАНИТЕЛЬ ЦЕЛ. Issue — только ПРЕДЛОЖЕНИЕ. Сам факт issue НЕ пишет `plan.yaml`: приём кандидата
в план остаётся явным действием владельца `candidates accept <id>`. Тело каждого issue несёт этот
призыв к действию, чтобы issue не путали с принятой работой (writer ≠ judge).

ПОРТЫ И АДАПТЕРЫ. `sync()` — чистая оркестрация на инъектируемом порте `Client` (переиспользуем
dataclasses `Issue/Client/Action/SyncPlan` из `roadmap_issue_sync` — второго определения не заводим).
Мутации только при `apply=True`; сеть (`gh`) живёт в адаптере CLI. Идемпотентно: ключ вшит в тело
маркером `<!-- candidate-sync: KEY -->`, где KEY = id кандидата (`cand-dir-<goal>` / `cand-<obs>`);
issue, заведённые ранее, усыновляются по маркеру, а не дублируются.

ДЕДУП ПРОТИВ roadmap-sync (ПОЧЕМУ ПО УМОЛЧАНИЮ ЗАВОДИМ ТОЛЬКО НАХОДКИ). `roadmap sync-issues` уже
заводит эпик (метка `roadmap-direction`) на КАЖДОЕ направление горизонтов «Сейчас»/«Следующий».
Кандидаты-направления (`source == "roadmap-direction"`) описывают ТУ ЖЕ цель по `source_goal` —
завести под них ещё и candidate-issue значило бы два issue на одну цель. Поэтому по умолчанию
candidate-sync МАТЕРИАЛИЗУЕТ только `child-finding`-кандидатов: у находок другого issue-дома нет, а
у направлений он уже есть (эпик roadmap-sync). Это простое правило гарантирует НОЛЬ дублей на цель.
Правило — один флаг `include_roadmap_directions` (шов), а не вшитое допущение: если политика
изменится (например, roadmap-sync перестанет заводить эпики), включение направлений — одна строка.

ЧЕСТНЫЕ ГРАНИЦЫ. Ядро ничего не знает о сети и не пишет план: только строит желаемое из списка
кандидатов и сводит его с существующими issue через порт. Сухой прогон (`apply=False`) не делает ни
одной мутации клиента.
"""
from __future__ import annotations

import re

from ai_ops_kit.planning.roadmap_issue_sync import (  # переиспользуем, не переопределяем
    Action,
    Client,
    Issue,
    SyncPlan,
)

__all__ = ["Action", "Client", "Issue", "SyncPlan", "LABEL", "sync", "parse_key",
           "candidate_title", "candidate_body"]

LABEL = "task-candidate"
_KEY_RE = re.compile(r"<!--\s*candidate-sync:\s*([A-Za-z0-9:_-]+)\s*-->")

_SOURCE_LABEL = {
    "roadmap-direction": "непокрытое направление роадмапа",
    "child-finding": "наблюдение из прогона дочки",
}


def _source_label(source: str) -> str:
    return _SOURCE_LABEL.get(str(source or ""), "наблюдение из прогона")


def parse_key(issue: Issue) -> str | None:
    """Ключ candidate-sync из тела issue (id кандидата). None — issue не наше."""
    m = _KEY_RE.search(issue.body or "")
    return m.group(1) if m else None


def candidate_title(c: dict) -> str:
    """Заголовок issue-кандидата: готовый `title` кандидата, обрезанный до трекер-дружелюбной длины."""
    title = str(c.get("title") or c.get("id") or "задача-кандидат").strip().replace("\n", " ")
    if len(title) > 100:
        title = title[:97] + "…"
    return title


def candidate_body(c: dict) -> str:
    """Тело issue-кандидата: маркер + источник + причина + призыв «как принять в план».

    Тело ОБЯЗАНО нести: маркер идемпотентности, ярлык источника, причину и явный призыв к действию
    (`./ai-ops candidates accept <id>`, а для находки без направления — `--goal <id>`), плюс строку
    о том, что это ЧЕРНОВИК-предложение и сам факт issue НЕ кладёт задачу в план."""
    cid = str(c.get("id") or "").strip()
    source = str(c.get("source") or "").strip()
    rationale = str(c.get("rationale") or "").strip()
    # У находок нет своего направления (`source_goal`) — приём в многоцелевой план требует `--goal`.
    needs_goal = not str(c.get("source_goal") or "").strip()
    accept = f"    ./ai-ops candidates accept {cid}"
    if needs_goal:
        accept += " --goal <id-направления>"

    lines = [
        f"<!-- candidate-sync: {cid} -->",
        f"Задача-**кандидат** (DRAFT) из источника: {_source_label(source)}.",
        "",
    ]
    if rationale:
        lines += [f"**Почему:** {rationale}", ""]
    lines += [
        "**Как принять в план.** Это ПРЕДЛОЖЕНИЕ, а не работа: сам факт этого issue НЕ кладёт "
        "задачу в `plan.yaml`. Принимает владелец явной командой:",
        "",
        accept,
        "",
    ]
    if needs_goal:
        lines += [
            "У находки нет своего направления — при приёме укажите `--goal <id-направления>`, "
            "к которому её отнести.",
            "",
        ]
    lines += [
        "_Задача-кандидат. Поддерживается командой `candidates sync-issues`; решение о плане — "
        "за владельцем (`candidates accept`)._",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _canonical(body: str) -> str:
    return (body or "").strip()


def _is_desired(c: dict, include_roadmap_directions: bool) -> bool:
    """Политика дедупа против roadmap-sync (см. docstring модуля). Шов — один флаг."""
    if str(c.get("source") or "") == "roadmap-direction":
        return include_roadmap_directions
    return True


def sync(candidates: list[dict], client: Client, apply: bool = False,
         *, include_roadmap_directions: bool = False) -> SyncPlan:
    """Свести issue-трекер с открытыми задачами-кандидатами. Возвращает план; при apply=True выполняет.

    `candidates` — union кандидатов из CLI (`gather_candidates`). `client` — порт к трекеру.
    По умолчанию материализуются только `child-finding`-кандидаты (см. дедуп в docstring модуля);
    `include_roadmap_directions=True` — шов, включающий и направления.
    Пуро: мутирует клиент ТОЛЬКО при `apply=True`; вся сеть (`gh`) — в адаптере CLI.
    """
    desired = [c for c in candidates
               if c.get("id") and _is_desired(c, include_roadmap_directions)]
    desired_keys = {str(c["id"]) for c in desired}

    existing = client.list()
    by_key: dict[str, Issue] = {}
    for iss in existing:
        k = parse_key(iss)
        if k is not None:
            # Открытая перекрывает закрытую при коллизии ключа: сверяем с живой.
            if k not in by_key or iss.state == "open":
                by_key[k] = iss

    plan = SyncPlan()

    # 1) Желаемые кандидаты: создать новых, обновить дрейфнувших/переоткрыть закрытых.
    for c in desired:
        key = str(c["id"])
        title = candidate_title(c)
        body = candidate_body(c)
        cur = by_key.get(key)
        if cur is None:
            num = client.create(title, body, [LABEL]) if apply else None
            plan.actions.append(Action("create", key, title, num))
        elif cur.state == "closed" or _canonical(cur.body) != _canonical(body):
            if apply:
                client.edit(cur.number, body)
            plan.actions.append(Action("update", key, title, cur.number))

    # 2) Устаревшие: наши issue (с маркером candidate-sync) вне желаемого — закрыть
    #    (направление получило работу / находка закрыта или уже принята в план).
    for key, iss in by_key.items():
        if iss.state == "open" and key not in desired_keys:
            if apply:
                client.close(iss.number)
            plan.actions.append(Action("close", key, iss.title, iss.number))

    return plan
