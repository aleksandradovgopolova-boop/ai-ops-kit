#!/usr/bin/env python3
"""WorkView — единая машинная ПРОЕКЦИЯ «работы» по id (issue #549).

Концепция «работы» размазана по четырём источникам, у каждого свой файл и своя форма. Эта проекция
СВОДИТ их в один машинный dict по id — read-only, БЕЗ нового рантайма и БЕЗ новой схемы поведения.
Это агрегатор поверх существующего, а не пятая сущность жизненного цикла: ничего не пишет, ничего не
считает заново, только читает то, что уже записано, и честно говорит, чего нет.

Четыре источника (только читаются):
  1. workitem   — features/<id>/workitem.yaml (schemas/workitem.schema.json):
                  task/workflow/status/lifecycle_intent/human_approval_required/paths.
  2. active-work — .ai/runtime/active-work.yaml (schemas/active-work.schema.json): запись active[]
                  этого id — branch/status/affected_areas/depends_on/shared_contracts/owner_session.
  3. work-graph  — work-graph.yaml (schemas/work-graph.schema.json): packages[] с
                  write_scope/depends_on/shared_contracts + integration_order/execution_mode.
  4. plan        — planning/plan.yaml work[]-item: id/title/type/goal/status/owner_role/value/
                  write_scope/branch.

Обобщает паттерн `ai_ops_cli_intents._explain_state` (он уже сводит три из четырёх для одной
задачи), добавляя чтение work-graph.yaml и plan.yaml.

Почему поля читаются прямыми yaml-загрузками, а не импортами пакетов planning/governance: этот модуль
живёт в `lifecycle` (ядро), а `planning` ядру импортировать запрещено (kernel forbidden_imports).
Форма файлов — публичные контракты в schemas/, поэтому чтение по контракту устойчиво. Реестр решений
пишет `ai_ops_kit.governance.decision_log` — здесь мы лишь читаем тот же файл.

Использование:  python3 -m ai_ops_kit.lifecycle.work_view <child_root> <work_id> [--json]
"""
from __future__ import annotations

# v4: самодостаточный вход — файл можно запустить напрямую (без PYTHONPATH). Кладём корень пакета
# (маркер VERSION) в sys.path ДО пакетных импортов — как это делает lifecycle/workitem.py.
import sys as _sys
from pathlib import Path as _P_bootstrap
_root = next((_p for _p in _P_bootstrap(__file__).resolve().parents if (_p / "VERSION").is_file()), None)
if _root is not None and str(_root) not in _sys.path:
    _sys.path.insert(0, str(_root))

import json
import sys
from pathlib import Path

import yaml

# Реестр решений (тот же файл, что пишет governance.decision_log): в ките — decisions/registry.yaml,
# в дочке — .ai/project/decisions/registry.yaml. Читаем ОБА кандидата, ничего не создаём.
_DECISIONS_RELS = ("decisions/registry.yaml", ".ai/project/decisions/registry.yaml")
# Кандидаты расположения work-graph.yaml в дочке: движок материализует его эфемерно (validate ждёт
# <dir>/work-graph.yaml), фиксированного места нет — поэтому проверяем несколько, а не выдумываем одно.
_WORK_GRAPH_RELS = ("work-graph.yaml", ".ai/runtime/work-graph.yaml")

# Четыре имени источников — то, что проекция ЧЕСТНО сводит в `sources`.
SOURCE_NAMES = ("workitem", "active_work", "work_graph", "plan")


def _load_yaml(path: Path):
    """Прочитать yaml read-only. Отсутствие/битость -> None (не бросаем: проекция не обязана падать
    из-за одного недоступного источника — она честно скажет, что источника нет)."""
    if not path.is_file():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return None


def _read_workitem(child_root: Path, work_id: str) -> dict | None:
    """features/<id>/workitem.yaml. -> dict|None (None — источника нет)."""
    data = _load_yaml(child_root / "features" / str(work_id) / "workitem.yaml")
    return data if isinstance(data, dict) else None


def _read_active_entry(child_root: Path, work_id: str) -> dict | None:
    """Запись этого id из .ai/runtime/active-work.yaml. -> dict|None (None — записи/файла нет)."""
    data = _load_yaml(child_root / ".ai" / "runtime" / "active-work.yaml")
    if not isinstance(data, dict):
        return None
    for entry in data.get("active") or []:
        if isinstance(entry, dict) and str(entry.get("id") or "") == str(work_id):
            return entry
    return None


def _read_work_graph(child_root: Path, work_id: str) -> dict | None:
    """work-graph.yaml, относящийся к этому id: feature/один-из-package-id/integration_order несёт id.
    -> dict|None (None — графа нет либо он не про этот id). Первый подходящий кандидат."""
    for rel in _WORK_GRAPH_RELS:
        data = _load_yaml(child_root / rel)
        if not isinstance(data, dict):
            continue
        pkg_ids = {str((p or {}).get("id") or "") for p in (data.get("packages") or [])}
        feature = str(data.get("feature") or "")
        # id связан с графом, если он и есть feature графа, или совпадает с id пакета, или граф
        # прямо перечисляет его в integration_order. Иначе граф — про другую работу, и мы его НЕ
        # приписываем этой (ложная сводка хуже отсутствия).
        if (str(work_id) == feature or str(work_id) in pkg_ids
                or str(work_id) in {str(x) for x in (data.get("integration_order") or [])}
                or feature.endswith(f":{work_id}")):
            return data
    return None


def _read_plan_item(child_root: Path, work_id: str) -> dict | None:
    """work[]-item этого id из planning/plan.yaml. -> dict|None. Заготовку (`template: true`) НЕ
    читаем как план: иначе пример кита выдавался бы за работу продукта."""
    data = _load_yaml(child_root / "planning" / "plan.yaml")
    if not isinstance(data, dict) or data.get("template"):
        return None
    for item in data.get("work") or []:
        if isinstance(item, dict) and str(item.get("id") or "") == str(work_id):
            return item
    return None


def _read_related_decisions(child_root: Path, work_id: str, feature: str | None) -> list:
    """Эпизоды реестра решений, связанные с этой работой. Связь — упоминание id/feature работы в
    полях эпизода (id/question/decision/context/derived_from/feature/work). Структурного поля «работа»
    в реестре нет, поэтому связь — по упоминанию, и это ЧЕСТНО отражено (мы не выдумываем привязку).
    -> список {id, question, actor}. Нет реестра/совпадений -> []."""
    needles = {str(work_id)}
    if feature:
        needles.add(str(feature))
    episodes = None
    for rel in _DECISIONS_RELS:
        data = _load_yaml(child_root / rel)
        if isinstance(data, dict) and isinstance(data.get("episodes"), list):
            episodes = data["episodes"]
            break
    if not episodes:
        return []
    out = []
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        # Явная привязка полем — сильнее упоминания в прозе; учитываем и её, и текстовое совпадение.
        explicit = {str(ep.get("feature") or ""), str(ep.get("work") or ""),
                    str(ep.get("work_id") or "")}
        hay = " ".join(str(ep.get(k) or "") for k in ("id", "question", "decision", "context"))
        derived = " ".join(str(x) for x in (ep.get("derived_from") or []))
        hay = hay + " " + derived
        if (needles & explicit) or any(n in hay for n in needles):
            out.append({"id": ep.get("id"), "question": ep.get("question") or ep.get("decision"),
                        "actor": ep.get("actor") or "human"})
    return out


def _existing_artifacts(child_root: Path, workitem: dict | None, branch: str | None) -> list:
    """Пути-артефакты из workitem.paths, которые РЕАЛЬНО существуют, + ветка если есть. Только
    существующие ссылки — обещанный, но не созданный путь артефактом не называем."""
    out = []
    paths = (workitem or {}).get("paths") or {}
    for key in ("blueprint", "run_state", "workitem"):
        rel = paths.get(key)
        if rel and (child_root / rel).exists():
            out.append({"kind": key, "path": rel})
    if branch:
        out.append({"kind": "branch", "ref": branch})
    return out


def _evidence_refs(child_root: Path, work_id: str, workitem: dict | None) -> list:
    """Ссылки на gate-evidence этой работы, если файл существует (schemas/gate-evidence.schema.json).
    Смотрим каталог прогона .ai/runtime/workitems/<id>/ и путь run_state из workitem.paths. Файла нет
    -> [] (доказательств пока не собрано — честно, а не выдуманная ссылка)."""
    out = []
    run_dir = child_root / ".ai" / "runtime" / "workitems" / str(work_id)
    for name in ("gate-evidence.yaml", "gate-evidence.json", "evidence.json", "evidence.yaml"):
        p = run_dir / name
        if p.is_file():
            out.append({"kind": "gate_evidence", "path": str(p.relative_to(child_root))})
    run_state = ((workitem or {}).get("paths") or {}).get("run_state")
    if run_state and (child_root / run_state).exists():
        out.append({"kind": "run_state", "path": run_state})
    return out


def _union(*lists) -> list:
    """Порядок-сохраняющий union непустых строк из нескольких списков (дедупликация)."""
    seen, out = set(), []
    for lst in lists:
        for x in lst or []:
            s = str(x)
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out


def _graph_scopes(work_graph: dict | None, work_id: str) -> tuple[list, list, list]:
    """Свести write_scope/depends_on/shared_contracts из work-graph. Если id совпал с пакетом — берём
    ЕГО поля; иначе (id = feature графа) — union по всем пакетам графа. -> (write_scope, depends_on,
    shared_contracts)."""
    if not work_graph:
        return [], [], []
    packages = [p for p in (work_graph.get("packages") or []) if isinstance(p, dict)]
    own = [p for p in packages if str(p.get("id") or "") == str(work_id)]
    chosen = own or packages
    ws = _union(*[p.get("write_scope") or [] for p in chosen])
    dep = _union(*[p.get("depends_on") or [] for p in chosen])
    sc = _union(*[p.get("shared_contracts") or [] for p in chosen])
    return ws, dep, sc


def project_work(work_id, child_root) -> dict:
    """READ-ONLY проекция «работы» по id: сводит четыре источника в один машинный dict.

    Ничего не пишет и не мутирует. Отсутствующий источник -> связанные поля пустые/None И источник
    НЕ попадает в `sources` (проекция честна о том, что сведено, а что отсутствует).

    Поля результата:
      id, title, status, lifecycle_intent, branch,
      current_agent, participants[], artifacts[], evidence[], decisions[],
      write_scope[], depends_on[], shared_contracts[], sources[].
    """
    root = Path(child_root)
    wid = str(work_id)

    workitem = _read_workitem(root, wid)
    active = _read_active_entry(root, wid)
    plan_item = _read_plan_item(root, wid)
    work_graph = _read_work_graph(root, wid)

    sources = [name for name, found in (
        ("workitem", workitem is not None),
        ("active_work", active is not None),
        ("work_graph", work_graph is not None),
        ("plan", plan_item is not None),
    ) if found]

    wi, aw, pi = workitem or {}, active or {}, plan_item or {}

    # branch — из active-work (живой факт), иначе из плана.
    branch = aw.get("branch") or pi.get("branch")
    # title — план даёт человеческий заголовок, workitem — task; иначе сам id.
    title = pi.get("title") or wi.get("task") or aw.get("title") or wid
    # status — факт workitem'а сильнее объявленного в плане/реестре (он выводится из гейтов).
    status = wi.get("status") or aw.get("status") or pi.get("status")

    # current_agent — ЕДИНСТВЕННЫЙ источник — owner_session active-work. Нет записи -> None.
    current_agent = aw.get("owner_session")
    # participants — причастные сессии/роли из того, что УЖЕ записано: owner_session (active-work) +
    # owner_role (plan). Нового рантайма трекинга участников не заводим.
    # TODO(#549): полноценный список участников (кто реально касался работы за её жизнь) требует
    #   источника, которого пока нет — лога смены владельцев/ревьюеров. Пока отдаём то, что записано.
    participants = _union([aw.get("owner_session")] if aw.get("owner_session") else [],
                          [pi.get("owner_role")] if pi.get("owner_role") else [])

    # Союзы областей: work-graph + active-work + plan (все три — законные источники write-области).
    g_ws, g_dep, g_sc = _graph_scopes(work_graph, wid)
    write_scope = _union(g_ws, aw.get("affected_areas") or [], pi.get("write_scope") or [])
    depends_on = _union(g_dep, aw.get("depends_on") or [], pi.get("depends_on") or [])
    shared_contracts = _union(g_sc, aw.get("shared_contracts") or [])

    # TODO(#549): artifacts частично — из workitem.paths + ветка. Ссылки на PR здесь нет: связь
    #   работа->PR живёт в delivery-приёмнике, отдельного источника у проекции пока нет.
    artifacts = _existing_artifacts(root, workitem, branch)
    evidence = _evidence_refs(root, wid, workitem)
    decisions = _read_related_decisions(root, wid, wi.get("id") or pi.get("goal"))

    return {
        "id": wid,
        "title": title,
        "status": status,
        "lifecycle_intent": wi.get("lifecycle_intent"),
        "branch": branch,
        "current_agent": current_agent,
        "participants": participants,
        "artifacts": artifacts,
        "evidence": evidence,
        "decisions": decisions,
        "write_scope": write_scope,
        "depends_on": depends_on,
        "shared_contracts": shared_contracts,
        "sources": sources,
    }


def main(argv) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return 1
    child_root, work_id = args[0], args[1]
    if not Path(child_root).is_dir():
        print(f"не каталог: {child_root}", file=sys.stderr)
        return 2
    view = project_work(work_id, child_root)
    print(json.dumps(view, ensure_ascii=False, indent=2, default=str))
    # Код возврата — «нашлась ли работа хоть в одном источнике»: пусто -> 2 (не нашли), иначе 0.
    return 0 if view["sources"] else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
