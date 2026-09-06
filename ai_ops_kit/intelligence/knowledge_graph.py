#!/usr/bin/env python3
"""Knowledge Graph как ЗАПРАШИВАЕМАЯ технология: тонкий слой ПОВЕРХ уже существующего.

ЗАЧЕМ. Ответ на вопрос «зачем существует эта функция и подтвердилась ли её ценность» сегодня
собирается РУКАМИ из трёх разных файлов: направление — в `planning/plan.yaml` (цель + её outcome),
сама функция — в `features/<id>/blueprint.yaml`, а вывод из данных — в `product-learning/FL-*.yaml`.
Здесь эти разрозненные источники СОБИРАЮТСЯ в один плоский граф (nodes/edges формата
`schemas/knowledge-graph.schema.json`), и над ним обход отвечает на вопрос за один проход.

ЧТО ЭТО НЕ ЕСТЬ. Не новый движок хранения и не дубль Entity Graph: граф — обычный dict со списками,
обход — проходы по спискам. Схема типов и связей уже объявлена в `registry/entities.yaml`, формат —
в `schemas/knowledge-graph.schema.json`, ссылочную целостность проверяет
`ai_ops_kit/validation/validate_knowledge_graph.py`. Здесь только СБОРКА из реальных источников и
несколько чистых вопросов к собранному.

ЧЕСТНОСТЬ. Нет источника — нет узла; связь не выдумывается. Функция без ребра `targets` к outcome —
это НАЗВАННЫЙ пробел (`gaps`), а не «всё хорошо»: «не знаю» и «не сказал» — разные состояния.

Слой: `intelligence` (читает данные ядра, наверх — `validation` — НЕ импортирует; обход тут
переписан чистыми функциями, а не взят из валидатора, чтобы не тянуть entrypoints вверх).
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

# Пары (from_type, relation, to_type), которые вокабуляр (registry/entities.yaml) разрешает и
# которыми пользуется сборщик. Не источник истины (им остаётся реестр) — но сборщик обязан выпускать
# только валидные рёбра, иначе validate_knowledge_graph отвергнет граф целиком.
CONTAINS_LADDER = ("goal", "initiative", "epic", "feature", "story")


def _slug(value) -> str:
    """Строка -> id узла графа (`^[a-z0-9][a-z0-9-]*$`)."""
    out: list[str] = []
    for ch in str(value or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-") or "node"


def _text(v) -> str:
    return str(v or "").strip()


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


class _Builder:
    """Накопитель узлов/рёбер с дедупликацией по id и защитой от рёбер-дубликатов."""

    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []

    def node(self, nid: str, ntype: str, **attrs) -> str:
        nid = _slug(nid)
        if nid in self.nodes:
            # Узел уже есть (например, цель объявлена планом и упомянута blueprint'ом ссылкой):
            # дозаполняем недостающие атрибуты, тип НЕ переписываем — первый источник главнее.
            for k, v in attrs.items():
                if v is not None and self.nodes[nid].get(k) in (None, ""):
                    self.nodes[nid][k] = v
            return nid
        node = {"id": nid, "type": ntype}
        for k, v in attrs.items():
            if v is not None and v != "":
                node[k] = v
        self.nodes[nid] = node
        return nid

    def edge(self, frm: str, typ: str, to: str) -> None:
        frm, to = _slug(frm), _slug(to)
        e = {"from": frm, "type": typ, "to": to}
        if e not in self.edges:
            self.edges.append(e)

    def has(self, nid: str) -> bool:
        return _slug(nid) in self.nodes

    def type_of(self, nid: str) -> str:
        return self.nodes.get(_slug(nid), {}).get("type", "")


def _iter_blueprints(root: Path):
    """Пути к blueprint'ам функций: и дочернее `features/<id>/`, и демо-каталог кита."""
    seen = set()
    for pattern in ("features/*/blueprint.yaml",
                    "examples/feature-blueprint-demo/*/blueprint.yaml"):
        for p in sorted(root.glob(pattern)):
            if p.is_file() and p not in seen:
                seen.add(p)
                yield p


def _outcome_verdict(outcome: dict) -> str:
    """Свод булевых исходов цели в вердикт узла outcome. Пусто/не булево -> `pending`."""
    values = [v for v in outcome.values() if isinstance(v, bool)]
    if not values:
        return "pending"
    return "met" if all(values) else "unmet"


def build_graph(child_root) -> dict:
    """Собрать Knowledge Graph из plan.yaml + FL-*.yaml + feature blueprints.

    Возвращает dict формата `schemas/knowledge-graph.schema.json`
    (`{schema_version, kind, nodes, edges}`). Read-only: ничего не пишет.

    Источники (нет источника — нет узла):
      * `planning/plan.yaml`: goals -> узлы `goal` (+ узел `outcome` на цель с непустым `outcome`);
        work -> узлы `initiative` с ребром `goal -contains-> initiative`.
      * feature blueprints: узлы `feature` (+ `metric` из `metrics`), рёбра `feature -measured-by->
        metric`; цепочка `goal/initiative/epic -contains-> feature` из `links` (только валидные
        пары лестницы); `feature -targets-> <goal>-outcome`, и если у функции есть метрика —
        `outcome -measured-by-> metric`.
      * `product-learning/FL-*.yaml`: узлы `insight`; `insight -feeds-> feature` при совпадении
        `feature`; `insight -derived-from-> outcome`, если эта функция нацелена на outcome.

    Пути blueprint'а в узлах — ОТНОСИТЕЛЬНО `<child_root>/knowledge` (туда пишется graph.yaml),
    чтобы `validate_knowledge_graph` проверил их существование без ложного срабатывания.
    """
    root = Path(child_root)
    graph_dir = root / "knowledge"
    b = _Builder()

    # feature -> id outcome-узла, на который она нацелена (для привязки ins‑ов и метрик).
    feature_outcome: dict[str, str] = {}

    # 1) plan.yaml — цели, их outcome, работы как initiative.
    plan = _load_yaml(root / "planning" / "plan.yaml")
    goal_outcome: dict[str, str] = {}   # goal id -> outcome node id
    for g in plan.get("goals") or []:
        if not isinstance(g, dict) or not _text(g.get("id")):
            continue
        gid = b.node(g["id"], "goal", title=_text(g.get("id")), ref="planning/plan.yaml")
        outcome = g.get("outcome")
        if isinstance(outcome, dict) and outcome:
            oid = b.node(f"{gid}-outcome", "outcome",
                         title=f"исход цели «{gid}»",
                         verdict=_outcome_verdict(outcome),
                         ref="planning/plan.yaml")
            goal_outcome[gid] = oid
    for w in plan.get("work") or []:
        if not isinstance(w, dict) or not _text(w.get("id")):
            continue
        goal_ref = _slug(w.get("goal")) if _text(w.get("goal")) else None
        if goal_ref and b.type_of(goal_ref) == "goal":
            iid = b.node(w["id"], "initiative", title=_text(w.get("title")) or _text(w["id"]),
                         ref="planning/plan.yaml")
            b.edge(goal_ref, "contains", iid)

    # 2) feature blueprints — функции, метрики, цепочка вверх к цели, нацеленность на outcome.
    for bp_path in _iter_blueprints(root):
        bp = _load_yaml(bp_path)
        feat = bp.get("feature") or {}
        if not _text(feat.get("id")):
            continue
        rel = os.path.relpath(bp_path, graph_dir)
        fid = b.node(feat["id"], "feature",
                     title=_text(feat.get("name")) or _text(feat["id"]),
                     blueprint=rel)

        # Цепочка вверх: goal -> initiative -> epic -> feature. Только смежные валидные пары
        # лестницы: пропущенный средний уровень честно оставляет разрыв (пробел ловит trace).
        links = bp.get("links") or {}
        chain = [("goal", links.get("goal")), ("initiative", links.get("initiative")),
                 ("epic", links.get("epic")), ("feature", feat["id"])]
        present = [(t, _slug(v)) for t, v in chain if _text(v)]
        for (ptype, pid), (ctype, cid) in zip(present, present[1:]):
            gap_idx = CONTAINS_LADDER.index(ctype) - CONTAINS_LADDER.index(ptype)
            if gap_idx != 1:
                continue   # уровни не смежны в лестнице — валидного ребра contains нет
            if ptype != "feature" and not b.has(pid):
                b.node(pid, ptype, title=pid)
            b.edge(pid, "contains", cid)

        # Метрики функции.
        metric_ids: list[str] = []
        for m in bp.get("metrics") or []:
            name = m.get("name") if isinstance(m, dict) else m
            mid_src = (m.get("id") if isinstance(m, dict) else None) or f"{fid}-{name}"
            if not _text(name) and not _text(mid_src):
                continue
            mid = b.node(mid_src, "metric", title=_text(name) or _slug(mid_src))
            b.edge(fid, "measured-by", mid)
            metric_ids.append(mid)

        # Нацеленность функции на outcome своей цели.
        goal_of = _slug(links.get("goal")) if _text(links.get("goal")) else None
        oid = goal_outcome.get(goal_of)
        if oid:
            b.edge(fid, "targets", oid)
            feature_outcome[fid] = oid
            # Есть чем измерить исход -> outcome измеряется метрикой функции.
            for mid in metric_ids:
                b.edge(oid, "measured-by", mid)

    # 3) FL-*.yaml — выводы из данных.
    learning_dir = root / "product-learning"
    for fl_path in sorted(learning_dir.glob("FL-*.yaml")) if learning_dir.is_dir() else []:
        fl = _load_yaml(fl_path)
        if not _text(fl.get("id")):
            continue
        learnings = fl.get("learnings") or []
        title = _text(learnings[0]) if learnings else _text(fl.get("hypothesis")) or _text(fl["id"])
        iid = b.node(fl["id"], "insight", title=title[:120],
                     ref=os.path.relpath(fl_path, graph_dir))
        feat_ref = _slug(fl.get("feature")) if _text(fl.get("feature")) else None
        if feat_ref and b.type_of(feat_ref) == "feature":
            b.edge(iid, "feeds", feat_ref)
            oid = feature_outcome.get(feat_ref)
            if oid:
                b.edge(iid, "derived-from", oid)

    return {"schema_version": 1, "kind": "knowledge-graph",
            "nodes": list(b.nodes.values()), "edges": b.edges}


# ── Query-слой: чистые функции обхода над ПОСТРОЕННЫМ графом ─────────────────────────────────────


def _index(graph: dict):
    nodes = {n.get("id"): n for n in (graph.get("nodes") or [])
             if isinstance(n, dict) and n.get("id")}
    edges = [e for e in (graph.get("edges") or []) if isinstance(e, dict)]
    return nodes, edges


def trace(graph: dict, feature: str) -> dict:
    """«Зачем существует функция»: цепочка goal -> … -> feature -> outcome + вердикт + пробелы.

    Обобщение `validate_product_objects.trace_feature_rationale` до вопроса, задаваемого над
    СОБРАННЫМ графом: идёт вверх по `contains` до цели и вперёд по `targets` к outcome. Честная
    цепочка — если данных на полный путь нет, отдаётся лучший фрагмент с НАЗВАННЫМИ `gaps`.

    Результат: `{"feature", "chain": [{id,type,title}], "goal": id|None, "outcome": {...}|None,
    "verdict": str, "gaps": [...]}`.
    """
    nodes, edges = _index(graph)
    fid = _slug(feature)
    gaps: list[str] = []

    def summary(nid: str) -> dict:
        n = nodes.get(nid, {})
        return {"id": nid, "type": _text(n.get("type")) or "?",
                "title": _text(n.get("title")) or nid}

    if fid not in nodes:
        return {"feature": fid, "chain": [], "goal": None, "outcome": None,
                "verdict": "unknown",
                "gaps": [f"узла «{fid}» нет в графе — цепочку строить не от чего"]}

    # Вверх по contains до цели.
    chain_ids = [fid]
    current, seen = fid, {fid}
    while nodes.get(current, {}).get("type") != "goal":
        parents = [e["from"] for e in edges if e.get("type") == "contains"
                   and e.get("to") == current and e.get("from") in nodes]
        parent = next((p for p in parents if p not in seen), None)
        if parent is None:
            gaps.append(f"выше «{current}» нет родителя — путь до цели (goal) неполон")
            break
        seen.add(parent)
        chain_ids.insert(0, parent)
        current = parent
    goal = chain_ids[0] if nodes.get(chain_ids[0], {}).get("type") == "goal" else None

    # Вперёд к outcome.
    outcome_ids = [e["to"] for e in edges if e.get("type") == "targets"
                   and e.get("from") == fid and e.get("to") in nodes]
    outcome = None
    if outcome_ids:
        onode = nodes[outcome_ids[0]]
        outcome = {"id": outcome_ids[0], "verdict": _text(onode.get("verdict")) or "pending",
                   "title": _text(onode.get("title")) or outcome_ids[0],
                   "measured_by": [e["to"] for e in edges if e.get("type") == "measured-by"
                                   and e.get("from") == outcome_ids[0]]}
        if not outcome["measured_by"]:
            gaps.append(f"у исхода «{outcome_ids[0]}» нет метрики (ребро measured-by) — "
                        f"измерить его нечем")
    else:
        gaps.append(f"у «{fid}» нет outcome (ребро targets) — зачем функция существует, "
                    f"не подтверждается измеримым результатом")

    verdict = _verdict(goal, outcome)
    return {"feature": fid, "chain": [summary(i) for i in chain_ids], "goal": goal,
            "outcome": outcome, "verdict": verdict, "gaps": gaps}


def _verdict(goal, outcome) -> str:
    """Короткий машиночитаемый вердикт цепочки функции."""
    if goal is None:
        return "unmoored"          # функция ни к какой цели не привязана
    if outcome is None:
        return "no-outcome"        # цель есть, измеримого результата — нет
    if not outcome.get("measured_by"):
        return "outcome-unmeasured"
    return {"met": "confirmed", "unmet": "refuted"}.get(outcome.get("verdict"), "pending")


def gaps(graph: dict) -> dict:
    """Что в графе НЕ покрыто измеримым результатом — три честных списка.

    * `outcomes_without_metric` — исходы, которые ничем не измеряются (нет `outcome -measured-by->
      metric`): цель объявлена, а сигнала нет;
    * `metrics_without_release` — метрики, которых не наблюдает ни один релиз (нет `release
      -observed-by-> metric`): считать вроде есть чем, а откуда придут данные — не сказано;
    * `features_without_outcome` — функции без ребра `targets`: строим, а зачем — не подтверждено.
    """
    nodes, edges = _index(graph)
    measured = {e["from"] for e in edges if e.get("type") == "measured-by"}
    observed = {e["to"] for e in edges if e.get("type") == "observed-by"}
    targeted = {e["from"] for e in edges if e.get("type") == "targets"}

    def title(nid):
        return _text(nodes.get(nid, {}).get("title")) or nid

    outcomes = [{"id": n["id"], "title": title(n["id"])} for n in nodes.values()
                if n.get("type") == "outcome" and n["id"] not in measured]
    metrics = [{"id": n["id"], "title": title(n["id"])} for n in nodes.values()
               if n.get("type") == "metric" and n["id"] not in observed]
    features = [{"id": n["id"], "title": title(n["id"])} for n in nodes.values()
                if n.get("type") == "feature" and n["id"] not in targeted]
    return {"outcomes_without_metric": outcomes,
            "metrics_without_release": metrics,
            "features_without_outcome": features}
