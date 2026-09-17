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


def _load_decisions(root: Path) -> dict[str, str]:
    """id решения -> человекочитаемый текст. Источник — `decisions/registry.yaml`.

    Индексирует и эпизоды (`episodes`, id вида `ep-YYYY-MM-DD-…`, текст — поле `decision`), и
    принципы (`principles`, id вида `dp-***`, текст — поле `principle`): blueprint вправе сослаться
    на любой из них. Нет файла/секции -> пустой индекс (решений в проекте просто нет).
    """
    reg = _load_yaml(root / "decisions" / "registry.yaml")
    index: dict[str, str] = {}
    for ep in reg.get("episodes") or []:
        if isinstance(ep, dict) and _text(ep.get("id")):
            index[_slug(ep["id"])] = (_text(ep.get("decision")) or _text(ep.get("question"))
                                      or _text(ep["id"]))
    for pr in reg.get("principles") or []:
        if isinstance(pr, dict) and _text(pr.get("id")):
            index[_slug(pr["id"])] = _text(pr.get("principle")) or _text(pr["id"])
    return index


def _decision_refs(links: dict) -> list[str]:
    """Ссылки функции на решения из blueprint: `links.decision` (одна) и `links.decisions` (список).

    Обе формы поддержаны; порядок сохраняется, дубли по slug убираются. Пусто -> [].
    """
    raw: list[str] = []
    single = links.get("decision")
    if _text(single):
        raw.append(_text(single))
    many = links.get("decisions")
    if isinstance(many, list):
        raw.extend(_text(r) for r in many if _text(r))
    seen: set[str] = set()
    out: list[str] = []
    for r in raw:
        s = _slug(r)
        if s not in seen:
            seen.add(s)
            out.append(r)
    return out


def _load_history_works(root: Path) -> tuple[dict[str, dict], dict[str, str]]:
    """Закрытые работы из `history/plan-history.yaml`. -> (works_by_id, pr_index).

    `works_by_id[slug(id)] = {"title", "pr"}` — что за работа и каким PR закрыта; `pr_index[slug(pr)]
    = slug(id)` — чтобы ссылка `built_by` могла назвать работу и по номеру PR, и по её id. Нет файла/
    секции -> пустые индексы (закрытых работ у проекта просто нет). Источник истории — тот же файл,
    по которому `delivery_plan.validate_history` требует у каждой записи НАЗВАННЫЙ результат.
    """
    hist = _load_yaml(root / "history" / "plan-history.yaml")
    works: dict[str, dict] = {}
    pr_index: dict[str, str] = {}
    for w in hist.get("work") or []:
        if not isinstance(w, dict) or not _text(w.get("id")):
            continue
        wid = _slug(w["id"])
        pr = _text(w.get("pr")) if w.get("pr") is not None else ""
        works[wid] = {"title": _text(w.get("title")) or _text(w["id"]), "pr": pr}
        if pr:
            pr_index[_slug(pr)] = wid
    return works, pr_index


def _built_by_refs(links: dict) -> list[str]:
    """Ссылки функции на построившую её работу/PR: `links.built_by` (строка или список).

    Обе формы поддержаны (как у `decision`/`decisions`): одиночная строка и список. Порядок
    сохраняется, дубли по slug убираются. Пусто -> [].
    """
    raw: list[str] = []
    one = links.get("built_by")
    if isinstance(one, list):
        raw.extend(_text(r) for r in one if _text(r))
    elif _text(one):                       # скаляр: id-строка или № PR числом
        raw.append(_text(one))
    seen: set[str] = set()
    out: list[str] = []
    for r in raw:
        s = _slug(r)
        if s not in seen:
            seen.add(s)
            out.append(r)
    return out


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
      * `decisions/registry.yaml` + blueprint `links.decision`/`links.decisions`: узел `decision`
        (текст решения) и ребро `decision -motivates-> feature` — «зачем функция появилась».
      * `history/plan-history.yaml` + blueprint `links.built_by` (id работы или № PR): узел `work`
        (название + PR) и ребро `work -builds-> feature` — «что построило функцию и где».
      * `product-learning/FL-*.yaml` `derived_from_outcome`: явное ребро `insight -derived-from->
        outcome` — «чему научились по этому конкретному результату» (без косвенного вывода).

    Пути blueprint'а в узлах — ОТНОСИТЕЛЬНО `<child_root>/knowledge` (туда пишется graph.yaml),
    чтобы `validate_knowledge_graph` проверил их существование без ложного срабатывания.
    """
    root = Path(child_root)
    graph_dir = root / "knowledge"
    b = _Builder()

    # feature -> id outcome-узла, на который она нацелена (для привязки ins‑ов и метрик).
    feature_outcome: dict[str, str] = {}
    # id решения -> текст (для узла decision, из которого «появилась» функция).
    decisions = _load_decisions(root)
    # Закрытые работы (для узла work, который «построил» функцию): по id и по номеру PR.
    history_works, history_pr_index = _load_history_works(root)

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

        # Решение, из которого функция появилась («зачем она вообще есть» — из истории, не из кода).
        # Ссылку ОБЪЯВЛЯЕТ автор blueprint'а (links.decision / links.decisions) — это НЕ авто-вывод
        # из данных, как `targets`, а декларация. Поэтому и правило другое: объявленную связь мы
        # ВЫПУСКАЕМ ребром всегда, а узел решения создаём только если ссылка резолвится в
        # decisions/registry.yaml. Ссылка на несуществующее решение оставляет ребро с висящим
        # концом — и validate_knowledge_graph честно отвергает граф целиком: сломанная декларация
        # обязана быть громкой, а не тихо пропасть. Нет ссылки -> нет ребра (функция без «зачем»
        # допустима, история просто честно не знает причину — это НЕ пробел).
        for ref in _decision_refs(links):
            did = _slug(ref)
            text = decisions.get(did)
            if text:
                b.node(did, "decision", title=text[:160], ref="decisions/registry.yaml")
            b.edge(did, "motivates", fid)

        # Работа/PR, построившая функцию («что построили и где» — из истории, не из пересказа кода).
        # Правило то же, что у decision: связь ОБЪЯВЛЯЕТ автор blueprint'а (links.built_by), это
        # декларация, а не авто-вывод. Ссылку резолвим по id работы ИЛИ по номеру её PR
        # (history/plan-history.yaml); резолвится -> создаём узел work с названием и PR, всегда
        # ВЫПУСКАЕМ ребро work -builds-> feature. Ссылка на несуществующую работу оставляет ребро с
        # висящим концом -> validate_knowledge_graph отвергает граф целиком: сломанная декларация
        # обязана быть громкой. Нет ссылки -> нет ребра (история просто не записала, кто построил, —
        # это НЕ пробел).
        for ref in _built_by_refs(links):
            wid = _slug(ref)
            info = history_works.get(wid)
            if info is None and wid in history_pr_index:
                wid = history_pr_index[wid]          # ссылка дана номером PR — назовём работу по id
                info = history_works.get(wid)
            if info is not None:
                b.node(wid, "work", title=info["title"][:160], pr=info.get("pr") or None,
                       ref="history/plan-history.yaml")
            b.edge(wid, "builds", fid)

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

        # Явная привязка урока к outcome, из которого он извлечён («чему научились по результату»).
        # До сих пор `insight -derived-from-> outcome` появлялось лишь КОСВЕННО — через совпадение
        # feature и его нацеленность на исход. Здесь урок ОБЪЯВЛЯЕТ outcome напрямую (`derived_from_
        # outcome`), и это ДЕКЛАРАЦИЯ (как decision/built_by): нить «outcome -> чему научились»
        # замыкается на КОНКРЕТНЫЙ исход, а не выводится молча. Ребро выпускаем всегда; ссылка на
        # несуществующий outcome оставляет висящий конец -> validate_knowledge_graph краснит. Нет
        # поля -> нет объявленного ребра (косвенная привязка выше остаётся) — это НЕ пробел.
        oref = fl.get("derived_from_outcome")
        if _text(oref):
            b.edge(iid, "derived-from", _slug(oref))

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
    "decision": {id,title}|None, "built_by": [{id,title,pr}], "verdict": str, "gaps": [...]}`.

    `decision` — из какого РЕШЕНИЯ (истории) появилась функция («зачем она есть»); `built_by` — какая
    РАБОТА/PR её построила («что построили и где»). Оба — словами человека, а не пересказом кода. Нет
    объявленной связи -> пусто (не пробел: связь просто не записана, а не потеряна).
    """
    nodes, edges = _index(graph)
    fid = _slug(feature)
    gaps: list[str] = []

    def summary(nid: str) -> dict:
        n = nodes.get(nid, {})
        return {"id": nid, "type": _text(n.get("type")) or "?",
                "title": _text(n.get("title")) or nid}

    if fid not in nodes:
        return {"feature": fid, "chain": [], "goal": None, "outcome": None, "decision": None,
                "built_by": [], "verdict": "unknown",
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

    # Решение, из которого функция появилась («зачем она есть» — из истории). Отсутствие решения
    # НЕ пробел: причина может быть просто не записана. Но если решение есть, история его называет.
    decision_ids = [e["from"] for e in edges if e.get("type") == "motivates"
                    and e.get("to") == fid and e.get("from") in nodes]
    decision = None
    if decision_ids:
        dn = nodes[decision_ids[0]]
        decision = {"id": decision_ids[0], "title": _text(dn.get("title")) or decision_ids[0]}

    # Работа/PR, построившая функцию («что построили» — из истории). Отсутствие НЕ пробел: история
    # могла просто не записать, кто построил. Но если работа объявлена, история её называет.
    built_by = []
    for wid in [e["from"] for e in edges if e.get("type") == "builds"
                and e.get("to") == fid and e.get("from") in nodes]:
        wn = nodes[wid]
        built_by.append({"id": wid, "title": _text(wn.get("title")) or wid,
                         "pr": _text(wn.get("pr")) or None})

    verdict = _verdict(goal, outcome)
    return {"feature": fid, "chain": [summary(i) for i in chain_ids], "goal": goal,
            "outcome": outcome, "decision": decision, "built_by": built_by,
            "verdict": verdict, "gaps": gaps}


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
