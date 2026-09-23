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

from ai_ops_kit.intelligence.knowledge_graph_util import _slug, _text
from ai_ops_kit.shared import review_verdict

# Пары (from_type, relation, to_type), которые вокабуляр (registry/entities.yaml) разрешает и
# которыми пользуется сборщик. Не источник истины (им остаётся реестр) — но сборщик обязан выпускать
# только валидные рёбра, иначе validate_knowledge_graph отвергнет граф целиком.
CONTAINS_LADDER = ("goal", "initiative", "epic", "feature", "story")


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


def _iter_review_verdicts(root: Path):
    """Записи review-вердиктов: `features/<id>/review/verdict.yaml` и демо-каталог кита.

    Источник — тот же, что пишет ПУТЬ РЕВЬЮ (`shared.review_verdict.persist`, судья ≠ писатель); здесь
    только читаем. Нечитаемое/не тот kind -> запись пропускается (нет источника — нет узла)."""
    seen: set = set()
    for pattern in ("features/*/review/verdict.yaml",
                    "examples/feature-blueprint-demo/*/review/verdict.yaml"):
        for p in sorted(root.glob(pattern)):
            if not p.is_file() or p in seen:
                continue
            seen.add(p)
            rec = _load_yaml(p)
            if isinstance(rec, dict) and rec.get("kind") == review_verdict.RECORD_KIND:
                yield rec


def _plan_records_lost_with(goal_id: str, plan: dict) -> int:
    """Сколько ЕЩЁ записей плана остаётся за графом вместе с целью-тёзкой. -> число.

    Считает ровно то, что стало бы узлами: исход цели (если объявлен) и работы под ней — по тем же
    правилам, что применяет сборщик. Запись без `id` он пропускает, тёзок по `id` схлопывает в один
    узел, поэтому и здесь они не считаются: иначе названное число было бы больше настоящей потери.
    """
    lost = 0
    for g in plan.get("goals") or []:
        if isinstance(g, dict) and _slug(g.get("id")) == goal_id:
            if isinstance(g.get("outcome"), dict) and g.get("outcome"):
                lost += 1
            break                         # исход у цели один: дубликат id цели узла не добавит
    works = {_slug(w.get("id")) for w in (plan.get("work") or [])
             if isinstance(w, dict) and _text(w.get("id")) and _slug(w.get("goal")) == goal_id}
    return lost + len(works)


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
        metric`; цепочка `goal/initiative/epic -contains-> feature` из `links` — связываются
        СОСЕДНИЕ ОБЪЯВЛЕННЫЕ уровни, пропущенный (не заведённый у продукта) уровень нить не рвёт;
        ссылка на цель, которой нет в плане, даёт узел с `unresolved` — разрыв называется, а не
        прячется; `feature -targets-> <goal>-outcome`, и если у функции есть метрика —
        `outcome -measured-by-> metric`.
      * `product-learning/FL-*.yaml`: узлы `insight`; `insight -feeds-> feature` при совпадении
        `feature`; `insight -derived-from-> outcome`, если эта функция нацелена на outcome.
      * `decisions/registry.yaml` + blueprint `links.decision`/`links.decisions`: узел `decision`
        (текст решения) и ребро `decision -motivates-> feature` — «зачем функция появилась».
      * `history/plan-history.yaml` + blueprint `links.built_by` (id работы или № PR): узел `work`
        (название + PR) и ребро `work -builds-> feature` — «что построило функцию и где».
      * `product-learning/FL-*.yaml` `derived_from_outcome`: явное ребро `insight -derived-from->
        outcome` — «чему научились по этому конкретному результату» (без косвенного вывода).
      * `features/<id>/review/verdict.yaml`: узел `review` (кем проверено + verified + ревизия) и ребро
        `review -reviewed-> feature` — «кто/что проверил функцию». Пишет путь ревью (судья), не писатель.

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

    # Паспорта читаются ПЕРВЫМИ — до плана и до всех узлов. Имя функции принадлежит функции: если
    # его же носит работа плана (а работу обычно называют именем функции, которую она строит), узел
    # заводился раньше и функция навсегда оставалась инициативой — валидатор ронял граф, указывая
    # не на причину. Теперь id функций известны до первого узла, и спор имён решается в её пользу.
    blueprints = [(bp_path, _load_yaml(bp_path)) for bp_path in _iter_blueprints(root)]
    feature_ids = {_slug((bp.get("feature") or {}).get("id"))
                   for _, bp in blueprints if _text((bp.get("feature") or {}).get("id"))}
    # id функции -> что в плане носит то же имя: {"цель"} / {"работа"} / обе. Кит РАЗЛИЧАЕТ источник
    # спора, поэтому и человеку говорит, что именно искать в плане, а не «цель или работа».
    name_taken_in_plan: dict = {}
    # id функции -> сколько ЕЩЁ записей плана не вошло в граф вместе с тёзкой (исход цели и работы
    # под ней). Без этого числа пробел занижал бы масштаб: терялась не одна строка, а поддерево, и
    # вместе с ним из `gaps` пропадал честный негатив (исход, который нечем измерить).
    name_conflict_dropped: dict = {}

    # 1) plan.yaml — цели, их outcome, работы как initiative.
    plan = _load_yaml(root / "planning" / "plan.yaml")
    goal_outcome: dict[str, str] = {}   # goal id -> outcome node id
    for g in plan.get("goals") or []:
        if not isinstance(g, dict) or not _text(g.get("id")):
            continue
        if _slug(g["id"]) in feature_ids:
            # Цель плана — тёзка функции. Узел-цель не заводим по той же причине, что и работу:
            # иначе функция навсегда становится целью, получает чужие для этого типа атрибуты, и
            # сборка отвечает про «устаревший реестр типов» — мимо настоящей причины. Вместе с
            # целью за графом остаётся её поддерево: исход и работы под ней — считаем их, чтобы
            # пробел назвал масштаб потери, а не одну строку.
            gid_conflict = _slug(g["id"])
            name_taken_in_plan.setdefault(gid_conflict, set()).add("цель")
            name_conflict_dropped[gid_conflict] = _plan_records_lost_with(gid_conflict, plan)
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
        # Цель работы «есть», если она стала узлом ИЛИ не стала ровно из-за спора имён: во втором
        # случае работа тоже осталась за графом по вине конфликта, и молчать о ней нельзя. Прежде
        # выход происходил раньше проверки на тёзку, и при двойном споре второй конфликт пропадал.
        goal_exists = bool(goal_ref) and (b.type_of(goal_ref) == "goal"
                                          or "цель" in name_taken_in_plan.get(goal_ref, set()))
        if not goal_exists:
            continue                      # работа без резолвимой цели узлом не была и раньше
        if _slug(w["id"]) in feature_ids:
            # Работа плана — тёзка функции. Узел-инициативу не заводим (иначе функция им и
            # останется), потерю называем на самой функции: молчать о ней значило бы спрятать
            # конфликт данных. Говорим об этом только когда работа ДЕЙСТВИТЕЛЬНО стала бы узлом:
            # иначе пробел сообщал бы о потере там, где терять было нечего. Если цель работы сама
            # за графом из-за спора имён, называем ПЕРВОПРИЧИНУ: переименовать работу мало —
            # родителя всё равно нет, и совет «переименуй одну из них» обещал бы лечение, которого
            # не будет.
            kind = ("работа" if b.type_of(goal_ref) == "goal"
                    else "работа, но первым разведи имена у её цели")
            name_taken_in_plan.setdefault(_slug(w["id"]), set()).add(kind)
            continue
        if b.type_of(goal_ref) != "goal":
            continue                      # цель за графом из-за спора имён — вешать работу не на что
        iid = b.node(w["id"], "initiative", title=_text(w.get("title")) or _text(w["id"]),
                     ref="planning/plan.yaml")
        b.edge(goal_ref, "contains", iid)

    # 2) feature blueprints — функции, метрики, цепочка вверх к цели, нацеленность на outcome.
    for bp_path, bp in blueprints:
        feat = bp.get("feature") or {}
        if not _text(feat.get("id")):
            continue
        rel = os.path.relpath(bp_path, graph_dir)
        links = bp.get("links") or {}
        # ЧЬЯ ЦЕЛЬ. Принадлежность функции цели объявляет ЕЁ ПАСПОРТ, и это записывается на самой
        # функции. Выводить её подъёмом по графу нельзя: эпик — общий узел без собственного
        # источника, его родителя-цель объявляют паспорта СОСЕДНИХ функций. Две функции одного
        # эпика с разными целями дали бы эпику двух родителей, и обход приписал бы функции цель
        # соседа — тем увереннее, чем случайнее порядок чтения каталогов.
        fid = b.node(feat["id"], "feature",
                     title=_text(feat.get("name")) or _text(feat["id"]),
                     blueprint=rel,
                     declared_goal=_slug(links.get("goal")) if _text(links.get("goal")) else None)

        # Цепочка вверх: goal -> initiative -> epic -> feature. Связываются СОСЕДНИЕ ОБЪЯВЛЕННЫЕ
        # уровни, даже если между ними пропущен уровень, которого у продукта просто нет
        # (`registry/entities.yaml` объявляет такие пары явно). Раньше требовалась смежность, и
        # объявленная автором цель ПРОПАДАЛА: паспорт с goal+epic без initiative давал только
        # `epic contains feature`, а функция оказывалась «ни к какой цели не привязана» — при том
        # что цель названа. Ничего не додумывается: связь идёт сверху вниз и только между уровнями,
        # которые автор назвал сам.
        chain = [("goal", links.get("goal")), ("initiative", links.get("initiative")),
                 ("epic", links.get("epic")), ("feature", feat["id"])]
        declared_levels = [(t, _slug(v)) for t, v in chain if _text(v)]
        # Уровень, чьё имя носит ФУНКЦИЯ, выпадает из цепочки ЦЕЛИКОМ, а не пропускается в одной
        # паре: иначе пара, где тёзка стоит РЕБЁНКОМ, выпускала ребро «цель содержит чужую функцию»
        # — связь, которой никто не объявлял, и функция молча получала чужую цель.
        broken_links = [pid for ptype, pid in declared_levels
                        if ptype != "feature" and pid in feature_ids]
        present = [(t, pid) for t, pid in declared_levels
                   if t == "feature" or pid not in feature_ids]
        for (ptype, pid), (ctype, cid) in zip(present, present[1:]):
            if CONTAINS_LADDER.index(ctype) <= CONTAINS_LADDER.index(ptype):
                continue   # не сверху вниз по лестнице — валидного ребра contains нет
            if not b.has(pid):
                # Уровень объявлен ссылкой, а своего источника у него нет. Для эпика и инициативы
                # это норма (их нигде и не объявляют отдельно). Для ЦЕЛИ — нет: цели живут в
                # `planning/plan.yaml`, и ссылка на отсутствующую там цель означает, что нить
                # оборвана в данных. Помечаем узел `unresolved`, чтобы обход назвал разрыв вслух, а
                # не выдавал заглушку за настоящую цель (см. trace: вердикт остаётся `unmoored`).
                extra = {"unresolved": True} if ptype == "goal" else {}
                b.node(pid, ptype, title=pid, **extra)
            elif b.type_of(pid) != ptype:
                # Имя занято узлом ДРУГОГО типа (например, работа плана зовётся так же, как
                # объявленная цель). Связать разнотипное значило бы выдать тёзку за родителя:
                # ребра нет, потеря названа, а про цель обход и так увидит по `declared_goal`.
                broken_links.append(pid)
                continue
            b.edge(pid, "contains", cid)
        if broken_links or fid in name_taken_in_plan:
            # Дозапись на узле функции: потеря не молчит — `trace` назовёт и потерянный уровень, и
            # запись плана, которая носит то же имя (её узла в графе нет, чтобы не подменить
            # функцию), и сколько ещё записей ушло за графом вместе с ней.
            # Порядок фиксирован смыслом, а не алфавитом: цель выше работы в лестнице плана.
            taken = name_taken_in_plan.get(fid, ())
            order = ("цель", "работа", "работа, но первым разведи имена у её цели")
            kinds = [k for k in order if k in taken]
            b.node(feat["id"], "feature", broken_links=broken_links or None,
                   name_taken_in_plan=" и ".join(kinds) or None,
                   name_conflict_dropped=name_conflict_dropped.get(fid) or None)

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

    # 4) review-вердикты — «кто/что проверил функцию» как ПЕРСИСТЕНТНАЯ запись, а не эхо прогона.
    # Источник — `features/<id>/review/verdict.yaml`, который пишет ПУТЬ РЕВЬЮ (независимый судья), а не
    # построившая работа: иначе «проверку» приписали бы писателю и нарушили бы writer≠judge. Узел review
    # создаётся ИЗ САМОЙ ЗАПИСИ (она и есть источник), ребро `review -reviewed-> feature` выпускается
    # всегда. Запись на несуществующую фичу оставляет висящий конец -> validate_knowledge_graph краснит
    # (сломанная запись обязана быть громкой). Нет записи -> нет узла (проверки могло не быть — это НЕ
    # пробел; trace честно молчит «проверка не записана», а не объявляет дыру).
    for rec in _iter_review_verdicts(root):
        feat_ref = _slug(rec.get("feature")) if _text(rec.get("feature")) else None
        if not feat_ref:
            continue
        rid = b.node(f"review-{feat_ref}", "review",
                     title=review_verdict.node_title(rec),
                     verified=bool(rec.get("verified")),
                     reviewed_revision=_text(rec.get("reviewed_revision")) or None,
                     ref=review_verdict.record_rel(feat_ref))
        b.edge(rid, "reviewed", feat_ref)

    return {"schema_version": 1, "kind": "knowledge-graph",
            "nodes": list(b.nodes.values()), "edges": b.edges}


# ── Вопросы к собранному графу — в сателлите `knowledge_graph_query` ─────────────────────────────
# Реэкспорт намеренный: зовущий код (CLI, презентер, scorecard) знает один вход `knowledge_graph`,
# и разрез файла по размеру не должен становиться переездом публичной поверхности.
from ai_ops_kit.intelligence.knowledge_graph_query import (  # noqa: E402,F401
    _climb_to_goal,
    _index,
    _parents,
    _path_down,
    _reachable_goals,
    _verdict,
    gaps,
    trace,
)
