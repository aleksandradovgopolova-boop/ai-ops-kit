#!/usr/bin/env python3
"""candidate_intake.py — приёмка задач-кандидатов пачкой: ЕДИНСТВЕННОЕ место, что пишет plan.yaml.

ПОВОД (эпик auto-slice-candidates). Кит НАРЕЗАЕТ кандидатов (непокрытые направления роадмапа —
`intelligence.roadmap_candidates`; наблюдения дочек — `intelligence.child_findings`), но
предохранитель владельца требует: кит сам НЕ дописывает активную работу в план. Здесь — обратная
половина: явная приёмка. Владелец выбирает кандидатов, и ТОЛЬКО тогда, ТОЛЬКО с `apply=True`,
выбранные становятся work items в `planning/plan.yaml`.

ПОЧЕМУ КАНДИДАТЫ ПРИХОДЯТ СПИСКОМ, А НЕ СОБИРАЮТСЯ ЗДЕСЬ. Union источников (findings + roadmap)
живёт в `intelligence`, а слой `planning` (ниже `intelligence`) импортировать его ВВЕРХ не вправе
(инвариант слоёв, `packages/layering.yaml`). Поэтому `accept_candidates` принимает уже собранный
список кандидатов, а собирает его вызыватель из слоя `entrypoints` (CLI), которому разрешены оба
источника. Так предохранитель и границы слоёв соблюдены одновременно.

ЧЕСТНЫЕ ГРАНИЦЫ:
  * БЕЗ `apply=True` не пишется НИЧЕГО — сухой прогон возвращает, что было бы добавлено.
  * ИДЕМПОТЕНТНО: кандидат, чья целевая работа уже есть в плане, пропускается (`skipped_existing`).
    Повторная приёмка того же кандидата дубля не создаёт.
  * plan.yaml НЕ round-trip'ится через `yaml.safe_dump`: файл насыщен комментариями (конституция
    их ценит), а ruamel в ките нет. Новые записи ДОПИСЫВАЮТСЯ ТЕКСТОМ в конец блока `work:` —
    каждый существующий байт и комментарий сохраняется.
  * Роль/тип кандидата (DRAFT — `owner_role: product-manager`, `type: improvement`) переводятся в
    словарь модели (`delivery_plan.validate` их сверяет): агент→роль, тип→ближайший валидный.
    Итоговый work item обязан проходить `delivery_plan.validate`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ai_ops_kit.planning import delivery_plan as _plan
from ai_ops_kit.planning import contours as _contours


# Перевод DRAFT-типа кандидата (`improvement`/`investigation` — метки проекций, НЕ словарь плана) в
# валидный `work_types` модели. Если тип кандидата уже валиден — оставляем как есть.
_CAND_TYPE_MAP = {"improvement": "product", "investigation": "engineering"}
_DEFAULT_TYPE = "product"
_DEFAULT_ROLE = "product"


def _slug(candidate_id: str) -> str:
    """id кандидата → чистый slug работы: снимаем префиксы `cand-dir-`/`cand-`, нижний регистр.

    `cand-dir-<goal>` и `cand-<obs>` — технические id проекций. Работе плана нужен slug нижнего
    регистра (правило `delivery_plan._engine_id_ok`), поэтому префикс проекции срезаем."""
    s = str(candidate_id or "").strip().lower()
    for prefix in ("cand-dir-", "cand-"):
        if s.startswith(prefix):
            return s[len(prefix):]
    return s


def _agent_to_role(model: dict) -> dict:
    """{agent: role} из модели: кандидат называет АГЕНТА (`product-manager`), план — РОЛЬ."""
    out: dict = {}
    for role, spec in (model.get("roles") or {}).items():
        for agent in (spec or {}).get("agents") or []:
            out.setdefault(str(agent), role)
    return out


def _role_for(cand_role, model: dict) -> str:
    """Роль кандидата → валидная роль модели. Уже роль — оставляем; агент — резолвим в его роль;
    иначе — безопасный дефолт `product` (или первая роль модели)."""
    roles = set((model.get("roles") or {}).keys())
    r = str(cand_role or "").strip()
    if r in roles:
        return r
    mapped = _agent_to_role(model).get(r)
    if mapped in roles:
        return mapped
    if _DEFAULT_ROLE in roles:
        return _DEFAULT_ROLE
    return sorted(roles)[0] if roles else _DEFAULT_ROLE


def _type_for(cand_type, model: dict) -> str:
    """Тип кандидата → валидный `work_types` модели. Уже валиден — оставляем; DRAFT-метку переводим;
    иначе — безопасный дефолт `product` (или первый тип модели)."""
    types = set((model.get("work_types") or {}).keys())
    t = str(cand_type or "").strip()
    if t in types:
        return t
    mapped = _CAND_TYPE_MAP.get(t)
    if mapped in types:
        return mapped
    if _DEFAULT_TYPE in types:
        return _DEFAULT_TYPE
    return sorted(types)[0] if types else _DEFAULT_TYPE


def _plan_item_from_candidate(cand: dict, model: dict) -> dict:
    """Кандидат → work item плана. Роль/тип переводятся в словарь модели; `goal` — только если у
    кандидата есть `source_goal` (у находок его нет). `source` метит происхождение для обратной связи."""
    slug = _slug(cand.get("id"))
    item = {
        "id": slug,
        "title": _text(cand.get("title")) or slug,
        "type": _type_for(cand.get("type"), model),
        "status": "todo",
        "owner_role": _role_for(cand.get("owner_role"), model),
        "source": _text(cand.get("source")) or "candidate",
        "rationale": _text(cand.get("rationale")),
    }
    goal = _text(cand.get("source_goal"))
    if goal:
        item["goal"] = goal
    return item


def _text(v) -> str:
    return str(v or "").strip()


def accept_candidates(child_root, candidate_ids, candidates, *, apply: bool = False) -> dict:
    """Принять выбранных кандидатов пачкой. -> {"to_add", "skipped_existing", "applied", ["error"]}.

    `candidate_ids` — id кандидатов к приёмке (в порядке владельца). `candidates` — уже собранный
    список кандидатов (union источников делает вызыватель, см. докстринг модуля). `apply=True` —
    ЕДИНСТВЕННЫЙ режим, что пишет plan.yaml.

    ИДЕМПОТЕНТНО: кандидат, чей целевой slug уже есть в `plan["work"]` (или встретился в этой же
    пачке), уходит в `skipped_existing`, а не дублируется. Пустого плана здесь не бывает: без плана
    дописывать не во что — возвращаем `error`, ничего не трогаем.
    """
    root = Path(child_root)
    result = {"to_add": [], "skipped_existing": [], "applied": False}
    try:
        plan = _plan.load(root)
    except _plan.PlanCorrupt as e:
        return {**result, "error": f"план не прочитан ({e}) — приёмка небезопасна"}
    if plan is None:
        return {**result, "error": "плана нет — дописывать кандидатов не во что"}

    model = _contours.load_model()
    existing = {w.get("id") for w in _plan.items(plan) if w.get("id")}
    by_id = {c.get("id"): c for c in (candidates or []) if isinstance(c, dict) and c.get("id")}

    to_add, skipped, seen = [], [], set()
    for cid in (candidate_ids or []):
        cand = by_id.get(cid)
        if cand is None:
            continue                       # id, которого нет среди кандидатов — молча мимо
        slug = _slug(cid)
        if slug in existing or slug in seen:
            skipped.append(slug)
            continue
        seen.add(slug)
        to_add.append(_plan_item_from_candidate(cand, model))

    result["to_add"] = to_add
    result["skipped_existing"] = skipped
    if apply and to_add:
        _apply_to_plan_file(root, to_add)
        result["applied"] = True
    return result


# ── Запись в plan.yaml ТЕКСТОМ (комментарии сохраняются) ─────────────────────────────────────────

def _yaml_scalar(s: str) -> str:
    """Строка → безопасный YAML-скаляр. JSON-строка — валидный YAML flow-скаляр в двойных кавычках,
    поэтому `json.dumps(..., ensure_ascii=False)` корректно экранирует кавычки/переводы строк и не
    зависит от содержимого (в отличие от ручного `>-`, где легко ошибиться с отступом)."""
    return json.dumps(str(s), ensure_ascii=False)


def _render_items_yaml(items: list) -> str:
    """work items → YAML-текст для дописывания под `work:` (отступ списка — 2 пробела)."""
    lines = ["  # ── Принято приёмкой кандидатов (candidate_intake) ─────────────────────────────"]
    for it in items:
        lines.append(f"  - id: {it['id']}")
        lines.append(f"    title: {_yaml_scalar(it['title'])}")
        lines.append(f"    type: {it['type']}")
        if it.get("goal"):
            lines.append(f"    goal: {it['goal']}")
        lines.append(f"    status: {it['status']}")
        lines.append(f"    owner_role: {it['owner_role']}")
        lines.append(f"    source: {_yaml_scalar(it['source'])}")
        if it.get("rationale"):
            lines.append(f"    rationale: {_yaml_scalar(it['rationale'])}")
    return "\n".join(lines) + "\n"


def _append_work_items_text(text: str, items_yaml: str) -> str:
    """Дописать `items_yaml` в конец блока `work:`, сохранив каждый существующий байт/комментарий.

    Находим верхнеуровневый ключ `work:` и конец его блока — следующий верхнеуровневый ключ (строка,
    начинающаяся не с пробела и не с `#`), либо конец файла. Вставляем новые записи перед ним.
    """
    lines = text.splitlines(keepends=True)
    work_idx = next((i for i, ln in enumerate(lines) if re.match(r"^work\s*:", ln)), None)
    if work_idx is None:
        raise ValueError("в plan.yaml нет верхнеуровневого блока work: — дописывать некуда")
    end = len(lines)
    for i in range(work_idx + 1, len(lines)):
        ln = lines[i]
        stripped = ln.lstrip()
        if ln and not ln[0].isspace() and stripped and not stripped.startswith("#"):
            end = i
            break
    head = "".join(lines[:end])
    if head and not head.endswith("\n"):
        head += "\n"
    tail = "".join(lines[end:])
    return head + items_yaml + tail


def _apply_to_plan_file(root: Path, items: list) -> None:
    """Дописать work items в plan.yaml ТЕКСТОМ. Не round-trip'ит YAML — комментарии остаются."""
    p = _plan.plan_path(root)
    text = p.read_text(encoding="utf-8")
    new_text = _append_work_items_text(text, _render_items_yaml(items))
    p.write_text(new_text, encoding="utf-8")
