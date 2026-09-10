#!/usr/bin/env python3
"""Сверка issue-трекера с роадмапом: эпик на направление + подзадача на каждую открытую работу.

Правило владельца: каждое открытое направление роадмапа ВСЕГДА имеет issue — держит механизм, а не
память. Гибрид (решение владельца): направление под «Сейчас»/«Следующий» = эпик; незакрытая работа
(`todo`/`in_progress`) = подзадача, связанная task-list'ом.

Порты и адаптеры: `sync()` — чистая оркестрация (желаемое из `roadmap_manager.check` + работ плана,
существующее через инъектируемый `client`) → ПЛАН (создать/обновить/закрыть); мутации только при
`apply=True`. Сеть (`gh`) — в адаптере CLI, ядро тестируется на фейковом клиенте. Идемпотентно: ключ
вшит в тело `<!-- roadmap-sync: KEY -->`; issue, заведённые вручную, усыновляются по заголовку/телу.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

LABEL = "roadmap-direction"
_KEY_RE = re.compile(r"<!--\s*roadmap-sync:\s*([a-z0-9:_-]+)\s*-->")
_LEGACY_EPIC_RE = re.compile(r"\[roadmap:([A-Za-z0-9_-]+)\]")
_LEGACY_WORK_TITLE_RE = re.compile(r"^\[([A-Za-z0-9_-]+)\]")
_LEGACY_WORK_RE = re.compile(r"Работа\s+`([^`]+)`")

_HZ_HUMAN = {"now": "Сейчас", "next": "Следующий результат"}
# Человекочитаемые заголовки направлений; неизвестному — сам slug.
DIRECTION_TITLES = {
    "checks-that-run": "Каждая объявленная проверка реально исполняется",
    "green-means-checked": "«Зелёное» не врёт под нагрузкой",
    "team-works-in-parallel": "Команда работает над продуктом одновременно, без конфликтов",
    "product-decision-loop": "Обоснованное продуктовое решение: baseline/target/guardrails",
    "storybook-as-visual-contract": "UI-задача проектируется и проверяется через Storybook",
    "owner-speaks-product-not-pipeline": "Владелец говорит обычным языком, кит ведёт остальное",
    "layering-ring-is-a-dag": "Кольцо capability-слоёв становится DAG (без циклов)",
    "kit-release-strategy": "Кит собирает релизы осознанно, владелец выбирает стратегию обновления",
    "nightly-product-review": "Ночной продуктовый обзор",
    "uiux-standard-as-product": "UI/UX-стандарт как продукт",
}
_OPEN_WORK = {"todo", "in_progress"}


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    state: str  # "open" | "closed"


class Client(Protocol):
    """Порт к трекеру. Реальная реализация зовёт `gh`; тестовая — держит issue в памяти."""

    def list(self) -> list[Issue]: ...
    def create(self, title: str, body: str, labels: list[str]) -> int: ...
    def edit(self, number: int, body: str) -> None: ...
    def close(self, number: int) -> None: ...


@dataclass
class Action:
    kind: str            # "create" | "update" | "close"
    key: str             # dir:<goal> | work:<goal>:<workid>
    title: str
    number: int | None = None   # для update/close; для create — присвоенный после apply


@dataclass
class SyncPlan:
    actions: list[Action] = field(default_factory=list)

    @property
    def creates(self) -> list[Action]:
        return [a for a in self.actions if a.kind == "create"]

    @property
    def updates(self) -> list[Action]:
        return [a for a in self.actions if a.kind == "update"]

    @property
    def closes(self) -> list[Action]:
        return [a for a in self.actions if a.kind == "close"]

    @property
    def in_sync(self) -> bool:
        return not self.actions


def parse_key(issue: Issue) -> str | None:
    """Ключ roadmap-sync из тела: явный маркер, иначе — эвристика для issue, заведённых вручную."""
    m = _KEY_RE.search(issue.body or "")
    if m:
        return m.group(1)
    me = _LEGACY_EPIC_RE.search(issue.title or "")
    if me and "roadmap:" in (issue.title or ""):
        return f"dir:{me.group(1)}"
    mw = _LEGACY_WORK_RE.search(issue.body or "")
    if mw:
        mt = _LEGACY_WORK_TITLE_RE.search(issue.title or "")
        goal = mt.group(1) if mt else "?"
        return f"work:{goal}:{mw.group(1)}"
    return None


def _epic_key(goal: str) -> str:
    return f"dir:{goal}"


def _work_key(goal: str, work_id: str) -> str:
    return f"work:{goal}:{work_id}"


def epic_title(goal: str) -> str:
    return f"[roadmap:{goal}] {DIRECTION_TITLES.get(goal, goal)}"


def work_title(goal: str, work: dict) -> str:
    title = str(work.get("title") or work["id"]).strip().replace("\n", " ")
    if len(title) > 90:
        title = title[:87] + "…"
    return f"[{goal}] {title}"


def epic_body(goal: str, horizon: str, reached: int, total: int,
              missing: list[str], sub_numbers: list[int | None]) -> str:
    lines = [f"<!-- roadmap-sync: {_epic_key(goal)} -->",
             f"Направление роадмапа **`{goal}`** (горизонт: {_HZ_HUMAN.get(horizon, horizon)}). "
             f"Готово {reached} из {total} исходов.", "", "### Что ещё не достигнуто"]
    for m in missing:
        lines.append(f"- [ ] `{m}`")
    lines.append("")
    if sub_numbers:
        lines.append("### Подзадачи (работы плана)")
        for n in sub_numbers:
            lines.append(f"- [ ] #{n}" if n is not None else "- [ ] _(будет заведена)_")
    else:
        lines.append("_Заведённых работ под направлением сейчас нет — открыт только исход выше._")
    lines.append("")
    lines.append("_Эпик направления. Поддерживается командой `roadmap sync-issues`; трекер "
                 "деталей — `planning/plan.yaml` и `ROADMAP.md`._")
    return "\n".join(lines).rstrip() + "\n"


def work_body(goal: str, work: dict) -> str:
    # Ссылка на эпик — по slug направления, не по номеру: номер эпика может появиться позже
    # (эпик заводится вторым), а тело работы должно быть стабильным ради идемпотентности. Связь
    # «эпик → подзадача» несёт task-list в теле эпика — именно его GitHub рисует как sub-issue.
    return (f"<!-- roadmap-sync: {_work_key(goal, work['id'])} -->\n"
            f"Работа `{work['id']}` под направлением-эпиком `{goal}`. "
            f"Статус в плане: **{work.get('status')}**.\n\n"
            f"Трекер работы — `planning/plan.yaml` (id `{work['id']}`): там зависимости, "
            f"write_scope и исходы. Issue закрывается вместе с работой.\n\n"
            f"_Подзадача направления. Поддерживается командой `roadmap sync-issues`._\n")


def _canonical(body: str) -> str:
    return (body or "").strip()


def _open_works_by_goal(plan_items: list[dict]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for w in plan_items:
        if w.get("status") in _OPEN_WORK and w.get("goal"):
            by.setdefault(w["goal"], []).append(w)
    return by


def sync(report: dict, plan_items: list[dict], client: Client, apply: bool = False) -> SyncPlan:
    """Свести issue-трекер с роадмапом. Возвращает план; при apply=True выполняет его.

    `report` — вывод `roadmap_manager.check` (ключи roadmap.now/next, errors, authored_present).
    `plan_items` — работы плана (`delivery_plan.items`). `client` — порт к трекеру.
    """
    roadmap = report.get("roadmap") or {}
    directions = []  # (goal, horizon, reached, total, missing)
    for hz in ("now", "next"):
        for g in roadmap.get(hz, []) or []:
            missing = [o["name"] for o in g.get("outcomes", []) if not o.get("reached")]
            directions.append((g["goal"], hz, g.get("reached", 0), g.get("total", 0), missing))
    works_by = _open_works_by_goal(plan_items)

    existing = client.list()
    by_key: dict[str, Issue] = {}
    for iss in existing:
        k = parse_key(iss)
        if k is not None:
            # Открытая перекрывает закрытую при коллизии ключа: сверяем с живой.
            if k not in by_key or iss.state == "open":
                by_key[k] = iss

    plan = SyncPlan()
    desired_keys: set[str] = set()

    # 1) Подзадачи-работы: создаём/усыновляем, чтобы знать их номера для тел эпиков.
    work_number: dict[str, int | None] = {}
    for goal, _hz, _r, _t, _m in directions:
        for w in works_by.get(goal, []):
            key = _work_key(goal, w["id"])
            desired_keys.add(key)
            title = work_title(goal, w)
            cur = by_key.get(key)
            if cur is None:
                body = work_body(goal, w)
                if apply:
                    num = client.create(title, body, [LABEL])
                else:
                    num = None
                work_number[key] = num
                plan.actions.append(Action("create", key, title, num))
            else:
                work_number[key] = cur.number
                body = work_body(goal, w)
                if cur.state == "closed" or _canonical(cur.body) != _canonical(body):
                    if apply:
                        client.edit(cur.number, body)
                    plan.actions.append(Action("update", key, title, cur.number))

    # 2) Эпики направлений: тело ссылается на номера подзадач.
    for goal, hz, reached, total, missing in directions:
        key = _epic_key(goal)
        desired_keys.add(key)
        subs = [work_number.get(_work_key(goal, w["id"])) for w in works_by.get(goal, [])]
        title = epic_title(goal)
        body = epic_body(goal, hz, reached, total, missing, subs)
        cur = by_key.get(key)
        if cur is None:
            num = client.create(title, body, [LABEL]) if apply else None
            plan.actions.append(Action("create", key, title, num))
        elif cur.state == "closed" or _canonical(cur.body) != _canonical(body):
            if apply:
                client.edit(cur.number, body)
            plan.actions.append(Action("update", key, title, cur.number))

    # 3) Устаревшие: наши issue (с ключом roadmap-sync) вне желаемого — закрыть (цель/работа ушла).
    for key, iss in by_key.items():
        if iss.state == "open" and key not in desired_keys:
            if apply:
                client.close(iss.number)
            plan.actions.append(Action("close", key, iss.title, iss.number))

    return plan
