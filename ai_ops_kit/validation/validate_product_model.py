#!/usr/bin/env python3
"""Валидация модели продуктового репозитория (v3.35.0 Product Operating Model).

Три реестра стали источниками правды для кода, значит их порча обязана краснеть:
`registry/product-operating-model.yaml`, `registry/communication-policy.yaml` и — если он есть в
репозитории — `planning/plan.yaml`. Порча, которую не ловит никто, — это тот же класс дефекта, что
`registry/tracks.yaml` в 3.33: реестр врал, а зелёный CI это подтверждал.

Инварианты:
  1. МОДЕЛЬ НЕПУСТА и полна: контуры есть; `cycle` — перестановка id контуров (замкнутый цикл
     без пропусков, иначе цепочка PRODUCT->…->INSIGHTS обрывается молча);
  2. У каждого контура есть question, owner_role, хотя бы один источник истины, реконструируемость
     и ярус достройки — поле, которого нет, читается кодом как «ничего не требуется»;
  3. ССЫЛОЧНАЯ ЦЕЛОСТНОСТЬ РОЛЕЙ: `roles[].contour` существует; `roles[].agents` — существующие
     id из `registry/agents.yaml`. Роль, ссылающаяся на несуществующего агента, — ошибка реестра;
  4. `work_types[].contour` существует; каждый контур `owner_role` есть в словаре ролей;
  5. СЛОВАРИ СОСТОЯНИЙ ЗАМКНУТЫ: `statuses.declarable` и `statuses.derived` не пересекаются
     (иначе «объявлять нельзя» и «объявлять можно» сказано об одном слове); `artifact_states`
     содержит и `unknown`, и `missing` — различение незнания и отсутствия обязательно;
  6. `gap_tiers` непусты и ровно один ярус блокирует работу (`blocks_work: true` у required_now);
  7. КОММУНИКАЦИЯ: `default_audience` объявлен и присутствует в `audiences`; контракт сообщения
     содержит обязательные `summary` и `next`; `order` — перестановка объявленных вопросов;
  8. ПЛАН (если есть): проходит `plan.validate` без ошибок, и `ROADMAP.md` — без ошибок контракта.

  validate_product_model.py [<repo>] [--json] | --selftest
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[1])
MODEL = PKG / "registry" / "product-operating-model.yaml"
COMMS = PKG / "registry" / "communication-policy.yaml"


def _agent_ids(pkg=PKG):
    try:
        d = yaml.safe_load((pkg / "registry" / "agents.yaml").read_text(encoding="utf-8")) or {}
    except OSError:
        return set()
    return {a.get("id") for a in (d.get("agents") or []) if a.get("id")}


def check(data, pkg=PKG):
    """Инварианты модели контуров. -> список ошибок (пустой = валидна)."""
    e = []
    if not isinstance(data, dict):
        return ["модель контуров не является mapping"]
    contours = data.get("contours") or []
    if not contours:
        return ["контуров нет — связность проверять нечем, любая работа выглядит согласованной"]

    ids = [c.get("id") for c in contours]
    dup = sorted({i for i in ids if i and ids.count(i) > 1})
    if dup:
        e.append(f"дубли id контуров: {dup}")
    cycle = data.get("cycle") or []
    if sorted(x for x in cycle) != sorted(x for x in ids if x):
        e.append("cycle не является перестановкой id контуров — замкнутый цикл контуров разорван "
                 f"(в cycle {len(cycle)}, контуров {len(ids)})")
    if data.get("cycle_closes_to") not in ids:
        e.append(f"cycle_closes_to '{data.get('cycle_closes_to')}' не является id контура")

    roles = data.get("roles") or {}
    known_agents = _agent_ids(pkg)
    for rid, r in roles.items():
        if not isinstance(r, dict):
            e.append(f"роль '{rid}': ожидался mapping"); continue
        if r.get("contour") not in ids:
            e.append(f"роль '{rid}': contour '{r.get('contour')}' не является id контура")
        ags = r.get("agents") or []
        if not ags:
            e.append(f"роль '{rid}': не названо ни одного агента — роль, которую некому исполнять")
        for a in ags:
            if known_agents and a not in known_agents:
                e.append(f"роль '{rid}': агента '{a}' нет в registry/agents.yaml")

    for c in contours:
        cid = c.get("id") or "<без id>"
        if not (c.get("question") or "").strip():
            e.append(f"контур '{cid}': нет question — контур обязан объявлять, на что отвечает")
        if not (c.get("source_of_truth") or []):
            e.append(f"контур '{cid}': нет ни одного источника истины")
        if c.get("owner_role") not in roles:
            e.append(f"контур '{cid}': owner_role '{c.get('owner_role')}' вне словаря ролей")
        rec = c.get("reconstruction") or {}
        if rec.get("ability") not in ("full", "partial", "none"):
            e.append(f"контур '{cid}': reconstruction.ability '{rec.get('ability')}' "
                     f"вне (full|partial|none) — кит не знает, вправе ли он это восстанавливать")
        tiers = [t.get("id") for t in (data.get("gap_tiers") or [])]
        if c.get("gap_tier") not in tiers:
            e.append(f"контур '{cid}': gap_tier '{c.get('gap_tier')}' вне объявленных ярусов")
        for q in c.get("questions") or []:
            if not q.get("id") or not (q.get("ask") or "").strip():
                e.append(f"контур '{cid}': вопрос без id или без текста")

    for wt, v in (data.get("work_types") or {}).items():
        if (v or {}).get("contour") not in ids:
            e.append(f"тип работы '{wt}': contour '{(v or {}).get('contour')}' не является id контура")

    st = data.get("statuses") or {}
    decl, der = set(st.get("declarable") or []), set(st.get("derived") or [])
    if not decl or not der:
        e.append("statuses: declarable/derived обязаны быть непусты — иначе неизвестно, что вправе "
                 "объявлять человек, а что обязан считать код")
    if decl & der:
        e.append(f"statuses: пересечение declarable и derived: {sorted(decl & der)} — про одно "
                 f"слово сказано и «объявлять нельзя», и «объявлять можно»")

    ast = data.get("artifact_states") or {}
    for need in ("verified", "inferred", "missing", "unknown", "user_confirmed", "stale", "partial"):
        if need not in ast:
            e.append(f"artifact_states: нет состояния '{need}' — различение «увидел / вывел / "
                     f"спросил / не знаю» неполно")

    tiers = data.get("gap_tiers") or []
    if not tiers:
        e.append("gap_tiers пусты — достройка перестаёт быть progressive")
    blocking = [t.get("id") for t in tiers if t.get("blocks_work")]
    if len(blocking) != 1:
        e.append(f"gap_tiers: блокирующих ярусов должно быть ровно один, объявлено {blocking} — "
                 f"иначе онбординг снова требует «заполнить 14 документов до работы»")

    cls = (data.get("classification") or {}).get("classes") or {}
    for need in ("NEW_PRODUCT", "EARLY_PRODUCT", "EXISTING_PRODUCT", "UNKNOWN"):
        if need not in cls:
            e.append(f"classification: нет класса '{need}'")
    return e


def check_comms(data):
    """Инварианты политики коммуникации."""
    e = []
    if not isinstance(data, dict):
        return ["политика коммуникации не является mapping"]
    auds = data.get("audiences") or {}
    if not auds:
        return ["audiences пусты — уровня детализации нет, значит наружу пойдёт внутренний язык"]
    default = data.get("default_audience")
    if default not in auds:
        e.append(f"default_audience '{default}' отсутствует в audiences")
    if default != "product":
        e.append("default_audience обязан быть 'product': по умолчанию кит разговаривает с "
                 "владельцем продукта, а не с отладчиком — обратный default и есть причина утечки "
                 "внутреннего языка")
    mc = data.get("message_contract") or {}
    qs = mc.get("questions") or []
    qids = [q.get("id") for q in qs]
    if not qs:
        e.append("message_contract.questions пусты — контракта сообщения нет")
    for need in ("summary", "next"):
        q = next((x for x in qs if x.get("id") == need), None)
        if not q:
            e.append(f"message_contract: нет вопроса '{need}'")
        elif not q.get("required"):
            e.append(f"message_contract: '{need}' обязан быть required")
    order = mc.get("order") or []
    if sorted(order) != sorted(x for x in qids if x):
        e.append("message_contract.order не является перестановкой questions")
    if mc.get("technical_details") != "on_request":
        e.append("message_contract.technical_details обязан быть 'on_request': удалить детали "
                 "значит сделать кит непроверяемым, показывать всегда — вернуть лог")
    for r in data.get("rules") or []:
        if not r.get("id") or not (r.get("rule") or "").strip():
            e.append("rules: правило без id или без текста")
    if not data.get("adapters"):
        e.append("adapters пусты — политика без адаптеров не доезжает ни до одного runtime")
    return e


def _run_json(entry, args):
    """Точка входа кита ПОДПРОЦЕССОМ + машиночитаемый вывод. -> (dict|None, ошибка|None).

    Почему не импортом. Валидатор, зовущий движок библиотекой, добавляет ребро `validation ->
    planning`, а вместе с ним 43 новых цикла через `lifecycle -> validation` — ратчет
    `packages/layering.yaml` поймал это в том же прогоне, где ребро появилось. Развязка через
    подпроцесс объявлена в 3.34 как способ разобрать шесть таких же связей; здесь она применена
    сразу, чтобы срез не увеличивал долг, который сам же и называет.

    Запуск идёт через плоскую точку входа `tools/<модуль>.py`: она кладёт корень в `sys.path`
    (`_bootstrap`) и исполняет цель через runpy. Запуск файла из пакета напрямую корня на пути не
    имеет — ровно дефект 3.31.1.
    """
    exe = PKG / "tools" / entry
    if not exe.is_file():
        return None, f"точка входа не найдена: {exe}"
    try:
        r = subprocess.run([sys.executable, str(exe), *args, "--json"],
                           capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"{entry} не запустился: {exc}"
    out = (r.stdout or "").strip()
    if not out:
        # Пустой вывод при ненулевом коде — это сообщение об отсутствии артефакта, не поломка.
        return None, None if r.returncode == 0 else ((r.stdout or r.stderr or "").strip() or None)
    try:
        return json.loads(out), None
    except json.JSONDecodeError:
        return None, (out.splitlines() or [""])[0]


def check_repo(repo_root):
    """План и roadmap РЕПОЗИТОРИЯ (если заполнены). Отсутствие плана — не ошибка валидатора:
    пустой контур находит `ai-ops model`, а здесь проверяется достоверность заполненного."""
    e = []
    repo = str(repo_root)
    if not (Path(repo) / "planning" / "plan.yaml").is_file():
        return []                                      # контур не заполнен — это забота `ai-ops model`
    rep, err = _run_json("delivery_plan.py", ["validate", repo])
    if err:
        return [f"planning/plan.yaml: {err}"]
    if rep:
        e.extend(f"planning/plan.yaml: {x}" for x in rep.get("errors") or [])
    rm, err = _run_json("roadmap.py", ["check", repo])
    if err:
        e.append(f"ROADMAP.md: {err}")
    elif rm:
        e.extend(f"ROADMAP.md: {x}" for x in rm.get("errors") or [])
    return e


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    repo = Path(args[0]) if args else PKG
    as_json = "--json" in argv

    errs = []
    try:
        errs += check(yaml.safe_load(MODEL.read_text(encoding="utf-8")))
    except OSError:
        errs.append(f"модель контуров не найдена: {MODEL}")
    except yaml.YAMLError as exc:
        errs.append(f"модель контуров не разбирается: {exc}")
    try:
        errs += check_comms(yaml.safe_load(COMMS.read_text(encoding="utf-8")))
    except OSError:
        errs.append(f"политика коммуникации не найдена: {COMMS}")
    except yaml.YAMLError as exc:
        errs.append(f"политика коммуникации не разбирается: {exc}")
    errs += check_repo(repo)

    if as_json:
        print(json.dumps({"errors": errs, "ok": not errs}, ensure_ascii=False, indent=2))
    elif errs:
        print("PRODUCT-MODEL: ошибки:")
        for x in errs:
            print(f"  - {x}")
    else:
        print("PRODUCT-MODEL-OK: модель контуров, политика коммуникации и план валидны.")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
