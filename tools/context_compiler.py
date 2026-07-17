#!/usr/bin/env python3
"""Context Compiler -> ContextBundle (v2.97, эпик Context Engineering, этап 1).

Перед прогоном формируем МИНИМАЛЬНЫЙ релевантный пакет контекста для WorkItem, а не грузим в модель
весь репозиторий, все правила и всех агентов. Селекция ДЕТЕРМИНИРОВАННА и обоснована реальными
данными (RunPlan/workflows/gates/tracks/registry), а не догадками:

  * agents   — владельцы стадий base_workflow + responsible_role гейтов плана (∩ registry);
  * skills   — uses_skills по стадиям base_workflow;
  * rules    — категории правил по workflow + трекам (core всегда);
  * repository_context — RepositoryProfile (project_detector);
  * files    — манифесты стека (evidence_source профиля) — детерминированный релевантный набор;
  * specifications/decisions — существующие артефакты features/<wid>/ и .ai/ (если есть).

Что ИСКЛЮЧАЕМ (с причиной): агентов не из RunPlan, правила не по задаче, skills не из плана.
Бюджет: estimated_tokens считается ДО вызова модели; превышение НЕ обрезает контекст молча —
поднимается overflow-флаг + open_question. Устаревшие артефакты помечаются (stale-warning).
Инвариант: тот же WorkItem при тех же входах -> ВОСПРОИЗВОДИМЫЙ пакет (сортировки, без времени/рандома).

Использование:
  context_compiler.py <child_root> --signals '{...}' [--feature name] [--json]
  context_compiler.py --selftest
Возврат 0 — ок, 1 — ошибка (или overflow при --strict).
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
for _p in (PKG / "tools",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import run_plan            # noqa: E402
import project_detector    # noqa: E402

CONTEXT_BUDGET_DEFAULT = 120_000   # токенов; override через signals["context_budget"] или config

# workflow -> категории правил (rules/<category>). core — всегда.
WORKFLOW_RULES = {
    "QUICK": ["core", "engineering"],
    "ENGINEERING": ["core", "engineering", "quality", "thinking"],
    "PRODUCT": ["core", "product", "research", "content", "thinking"],
    "RESEARCH": ["core", "research", "thinking"],
    "AI_FEATURE": ["core", "ai", "engineering", "quality"],
    "CRITICAL": ["core", "engineering", "quality", "thinking"],
    "VISUAL": ["core", "design"],
    "ANALYTICS": ["core", "product"],
    "INSIGHTS": ["core", "research"],
    "DECISION": ["core", "thinking"],
    "ADOPTION": ["core", "product"],
}
# трек -> дополнительные категории правил
TRACK_RULES = {
    "VISUAL": ["design"], "ANALYTICS": ["product"], "SECURITY": ["quality"],
    "DOCUMENTATION": ["documentation"], "EVENTS": ["engineering"], "AI": ["ai"], "RELEASE": ["engineering"],
}


def _load(path, default):
    try:
        return yaml.safe_load((PKG / path).read_text(encoding="utf-8")) or default
    except OSError:
        return default


def _agent_index():
    """id -> запись реестра агентов (с полем file)."""
    data = _load("registry/agents.yaml", {})
    agents = data.get("agents", data) if isinstance(data, dict) else data
    idx = {}
    if isinstance(agents, list):
        for a in agents:
            if isinstance(a, dict) and a.get("id"):
                idx[a["id"]] = a
    elif isinstance(agents, dict):
        for k, v in agents.items():
            if isinstance(v, dict):
                idx[v.get("id", k)] = v
    return idx


def _workflow_def(wf_id):
    wfs = _load("registry/workflows.yaml", {}).get("workflows", {})
    return wfs.get(wf_id, {})


def _gate_roles(gate_ids):
    gates = _load("quality/gates.yaml", {}).get("gates", {})
    roles = set()
    for gid in gate_ids:
        role = (gates.get(gid) or {}).get("responsible_role")
        if role:
            roles.add(role)
    return roles


def _est_tokens(text):
    # грубая, детерминированная оценка: ~4 символа на токен
    return (len(text) + 3) // 4


def _file_tokens(rel):
    p = PKG / rel
    if p.is_file():
        try:
            return _est_tokens(p.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            return 0
    return 0


def compile_bundle(signals, child_root, plan=None, context_budget=None):
    """Собрать ContextBundle. Детерминированно; без времени/рандома -> воспроизводимо."""
    child_root = Path(child_root)
    signals = dict(signals or {})
    if plan is None:
        plan = run_plan.build_plan(signals, workitem_id=signals.get("feature"))
    wid = plan["workitem_id"]
    base_wf = plan["base_workflow"]
    gate_ids = list(plan.get("gates", []))
    tracks = [t["track"] for t in plan.get("required_tracks", [])] + \
             [t["track"] for t in plan.get("conditional_tracks", [])]

    agent_idx = _agent_index()
    wf = _workflow_def(base_wf)

    # --- agents: владельцы/ревьюеры стадий + responsible_role гейтов, только реальные из registry ---
    role_ids, why_agent = set(), {}
    for st in wf.get("stages", []) or []:
        for key in ("owner", "writer"):
            r = st.get(key)
            if r:
                role_ids.add(r); why_agent.setdefault(r, f"стадия {st.get('id')} ({key})")
    for r in _gate_roles(gate_ids):
        role_ids.add(r); why_agent.setdefault(r, "responsible_role гейта RunPlan")
    included_agents = sorted(r for r in role_ids if r in agent_idx)
    # роли, которых нет в registry как агентов (напр. final-verifier) — честно отметим в допущениях
    unknown_roles = sorted(r for r in role_ids if r not in agent_idx)

    # --- skills: uses_skills по стадиям ---
    skills = set()
    for st in wf.get("stages", []) or []:
        for sk in st.get("uses_skills", []) or []:
            skills.add(sk)
    included_skills = sorted(skills)

    # --- rules: категории по workflow + трекам, core всегда ---
    rule_cats = set(WORKFLOW_RULES.get(base_wf, ["core"]))
    for tr in tracks:
        rule_cats |= set(TRACK_RULES.get(tr, []))
    rule_cats.add("core")
    included_rules = sorted(c for c in rule_cats if (PKG / "rules" / c).is_dir())

    # --- repository_context: RepositoryProfile ---
    profile = project_detector.detect(child_root)
    repo_ctx = [f"{s['language']} ({', '.join(s.get('frameworks') or []) or 'no-fw'})"
                for s in profile.get("stacks", [])]
    files = sorted({src for s in profile.get("stacks", []) for src in (s.get("evidence_source") or [])})

    # --- specifications / decisions: существующие артефакты (если есть) ---
    specs, decisions = [], []
    feat_dir = child_root / "features" / wid
    for name in ("requirements.md", "requirements.yaml", "plan.md", "spec.md"):
        if (feat_dir / name).is_file():
            specs.append(f"features/{wid}/{name}")
    dec_dir = child_root / ".ai" / "project" / "decisions"
    if dec_dir.is_dir():
        decisions = sorted(f"{p.relative_to(child_root)}" for p in dec_dir.glob("*.md"))

    # --- excluded (с причиной): агенты не из RunPlan, правила и skills не по задаче ---
    all_rule_cats = sorted(p.name for p in (PKG / "rules").iterdir() if p.is_dir()) if (PKG / "rules").is_dir() else []
    excluded = []
    for aid in sorted(agent_idx):
        if aid not in included_agents:
            excluded.append({"source": f"agent:{aid}", "reason": "не участвует в RunPlan этого WorkItem"})
    for c in all_rule_cats:
        if c not in included_rules:
            excluded.append({"source": f"rules/{c}", "reason": "категория правил не применима к workflow/трекам задачи"})

    # --- токены: агенты + правила (то, что реально попадёт в контекст) ---
    tok = 0
    tok += _est_tokens(signals.get("task_text", ""))
    for aid in included_agents:
        tok += _file_tokens(agent_idx[aid].get("file", ""))
    for c in included_rules:
        for p in sorted((PKG / "rules" / c).glob("*.md")):
            tok += _file_tokens(str(p.relative_to(PKG)))
    for rel in specs:
        tok += _est_tokens((child_root / rel).read_text(encoding="utf-8", errors="ignore")) if (child_root / rel).is_file() else 0

    budget = context_budget or signals.get("context_budget") or CONTEXT_BUDGET_DEFAULT

    assumptions, open_questions = [], []
    if unknown_roles:
        assumptions.append("роли без отдельного агента в registry (исполняет рантайм/верификатор): "
                           + ", ".join(unknown_roles))
    # overflow: НЕ обрезаем молча — поднимаем вопрос
    overflow = tok > budget
    if overflow:
        open_questions.append(
            f"контекст ({tok} ток.) превышает бюджет ({budget}) — нужна декомпозиция задачи или "
            "сокращение включённого (этап 4 Atomic Planning); контекст НЕ обрезан молча")
    # stale-предупреждение: артефакты плана ссылаются на прошлую версию кита
    cur_ver = (PKG / "VERSION").read_text(encoding="utf-8").strip() if (PKG / "VERSION").is_file() else "?"
    for rel in specs:
        try:
            txt = (child_root / rel).read_text(encoding="utf-8", errors="ignore")
            if "installed_version" in txt and cur_ver not in txt:
                open_questions.append(f"{rel}: возможно устарел (installed_version не совпадает с {cur_ver}) — проверить")
        except OSError:
            pass

    return {
        "schema_version": 1, "kind": "ContextBundle",
        "workitem_id": wid, "base_workflow": base_wf,
        "revision": _git_head(child_root),
        "included": {
            "project_context": [signals.get("task_text", "")[:200]] if signals.get("task_text") else [],
            "repository_context": repo_ctx,
            "specifications": specs,
            "decisions": decisions,
            "files": files,
            "rules": included_rules,
            "skills": included_skills,
            "agents": included_agents,
        },
        "included_reasons": {"agents": why_agent},
        "excluded": excluded,
        "assumptions": assumptions,
        "open_questions": open_questions,
        "estimated_tokens": tok,
        "context_budget": budget,
        "overflow": overflow,
    }


def _git_head(root):
    import subprocess
    r = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text('{"dependencies":{"react":"^18"}}', encoding="utf-8")
        eng = {"task_type": "ENGINEERING", "risk": "medium", "affected_areas": ["core"],
               "task_text": "отрефакторить модуль расчёта"}
        b = compile_bundle(eng, root)
        expect("kind=ContextBundle", b["kind"] == "ContextBundle")
        expect("включены агенты из RunPlan (непусто)", len(b["included"]["agents"]) > 0)
        expect("для каждого включённого агента есть причина",
               all(a in b["included_reasons"]["agents"] for a in b["included"]["agents"]))
        expect("ENGINEERING включает правила engineering+core",
               {"core", "engineering"} <= set(b["included"]["rules"]))
        expect("repository_context определил node", any("node" in r for r in b["included"]["repository_context"]))
        expect("excluded непуст и с причинами",
               b["excluded"] and all("reason" in e and "source" in e for e in b["excluded"]))
        expect("estimated_tokens измерен ДО модели (>0)", b["estimated_tokens"] > 0)
        expect("context_budget присутствует", b["context_budget"] == CONTEXT_BUDGET_DEFAULT)
        # воспроизводимость: тот же вход -> тот же пакет (без времени/рандома; revision может отличаться в не-git)
        b2 = compile_bundle(eng, root)
        expect("воспроизводимость: included идентичен при тех же входах",
               b["included"] == b2["included"] and b["excluded"] == b2["excluded"])

        # overflow: маленький бюджет -> overflow=True + open_question, контекст НЕ обрезан
        b_of = compile_bundle(eng, root, context_budget=10)
        expect("overflow: бюджет превышен -> overflow=True", b_of["overflow"] is True)
        expect("overflow: поднят open_question (не обрезано молча)",
               any("бюджет" in q for q in b_of["open_questions"])
               and b_of["included"]["agents"] == b["included"]["agents"])

        # QUICK легче ENGINEERING по правилам (меньше категорий)
        q = compile_bundle({"task_type": "QUICK", "risk": "low", "affected_areas": ["core"], "task_text": "мелкая правка"}, root)
        expect("QUICK: правил не больше, чем у ENGINEERING (минимальность)",
               len(q["included"]["rules"]) <= len(b["included"]["rules"]))

        # PRODUCT включает product-правила
        p = compile_bundle({"task_type": "PRODUCT", "risk": "medium", "affected_areas": ["catalog"],
                            "measurable_behavior": True, "task_text": "новая фича"}, root)
        expect("PRODUCT включает правила product", "product" in p["included"]["rules"])

    print("context_compiler selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    ap = argparse.ArgumentParser(prog="context_compiler.py")
    ap.add_argument("child_root", nargs="?", default=".")
    ap.add_argument("--signals", default="{}")
    ap.add_argument("--feature")
    ap.add_argument("--budget", type=int)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="ненулевой код при overflow")
    a = ap.parse_args(argv)
    signals = json.loads(a.signals)
    if a.feature:
        signals["feature"] = a.feature
    b = compile_bundle(signals, Path(a.child_root), context_budget=a.budget)
    if a.json:
        print(json.dumps(b, ensure_ascii=False, indent=2))
    else:
        inc = b["included"]
        print(f"CONTEXT-BUNDLE {b['workitem_id']} ({b['base_workflow']}) · ~{b['estimated_tokens']}/"
              f"{b['context_budget']} ток.{' ⚠OVERFLOW' if b['overflow'] else ''}")
        print(f"  агенты ({len(inc['agents'])}): {', '.join(inc['agents']) or '—'}")
        print(f"  правила: {', '.join(inc['rules']) or '—'} · skills: {', '.join(inc['skills']) or '—'}")
        print(f"  стек: {', '.join(inc['repository_context']) or 'не определён'}")
        print(f"  исключено источников: {len(b['excluded'])}")
        for q in b["open_questions"]:
            print(f"  ? {q}")
    return 1 if (a.strict and b["overflow"]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
