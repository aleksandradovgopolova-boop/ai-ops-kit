#!/usr/bin/env python3
"""Bench Lite (v3.1.3) — детерминированный ОФФЛАЙН golden-корпус для измерения решений движка.

Зачем: находка Phase B — GREEN-throughput ограничен НЕ качеством модели, а консервативным
independent-review (легитимный минимальный код блокируется). Чтобы управлять строгостью осознанно,
нужна воспроизводимая мера: сколько задач движок доводит до ready, сколько блокирует ревью, и —
инвариант безопасности — что false-green РОВНО НОЛЬ. Bench Lite даёт этот измеритель.

Свойства (обязательны, иначе не годится для CI, где стоит ТОЛЬКО pyyaml):
- ОФФЛАЙН: провайдер `test`, писатель/ревьюер — переданные детерминированные заглушки; сети нет.
- TOOL-FREE: репо каждого кейса — python-профиль БЕЗ тулчейна (пустые poetry-deps, нет tests/) ->
  все evidence-проверки not_applicable детерминированно, БЕЗ зависимости от pytest/ruff/mypy.
  (Урок v3.1.2: CI не имеет pytest — golden-кейсы не смеют его требовать.)
- Ревью-гейты управляются read-first ревьюером (та же модель read->verdict, что и в бою) — так мы
  меряем реальную логику гейтов, а не заглушку.

Метрики BenchReport (v3.1.6 разводит ДВЕ разные истины, чтобы не путать одноимённые вещи):
  metrics.*            — исполнение прогонов: pass / false_green (ИНВАРИАНТ 0) / false_fail /
                         mismatch / error / review_blocked / fix_recovered.
  policy_conformance   — исполнил ли ДВИЖОК текущую gate-policy как задумано (эталон=expected).
                         Это про корректность движка; 100% при pass==total.
  quality_accuracy     — пропустила ли ТЕКУЩАЯ policy корректную работу (код заведомо корректен).
                         synthetic_known_good_block_rate = ЧУВСТВИТЕЛЬНОСТЬ механики на синтетике,
                         НЕ production-rate; live_reviewer_false_fail_rate=None пока не измерено вживую.
                         projected_block_rate_after_calibration — что дала бы кандидатная политика
                         (gate_policy.candidate_policy) БЕЗ изменения боевого fail-closed (shadow).
  cases[].shadow       — per-case shadow-diff current vs candidate (gate_policy.shadow_diff).

CLI:
  python3 tools/bench_lite.py --run [--out report.json]   # прогнать корпус, напечатать/сохранить отчёт
  python3 tools/bench_lite.py --selftest                  # прогон + жёсткие проверки (для CI)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai_ops_run  # noqa: E402
import gate_policy  # noqa: E402

BENCH_VERSION = "0.2"


def _read_package_version() -> str:
    vf = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        return vf.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def _scaffold(root: Path) -> str:
    """Пустой python-профиль без тулчейна -> проверки not_applicable (tool-free). Возвращает ветку."""
    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        subprocess.run(["git", "-C", str(root), *a], capture_output=True)
    (root / "src").mkdir(exist_ok=True)
    # пустые poetry-deps + отсутствие tests/ -> ни pytest, ни линтеров не детектится как запускаемое
    (root / "pyproject.toml").write_text(
        "[tool.poetry]\nname='x'\n[tool.poetry.dependencies]\n", encoding="utf-8")
    (root / "seed").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "seed"], capture_output=True)
    return subprocess.run(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


# --- заглушки писателя/ревьюера (детерминированные, read-first как в бою) --------------------------

def _writer_script(ops):
    it = iter(ops)
    return lambda ctx: next(it)


def _quick_sig():
    return {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}


def _ui_sig():
    s = _quick_sig()
    s["ui_changed"] = True   # добавляет reviewable-гейт ux_review
    return s


def _impact_sig(impact, kind=None):
    """Сигналы с таксономией v3.1.6. Для UI-задач ui_changed=True (движок применяет 4 гейта СЕЙЧАС);
    ui_impact/ui_change_kind влияют ТОЛЬКО на shadow-политику, не на боевой verdict."""
    if impact == "none":
        s = _quick_sig()
        s["ui_impact"] = "none"
        return s
    s = _ui_sig()
    s["ui_impact"] = impact
    if kind:
        s["ui_change_kind"] = kind
    return s


def _pass_reviewer(path):
    marker = f"--- {path} ---"

    def rev(prompt):
        if marker in prompt:   # уже прочитал изменённый файл -> легитимный pass (не рубер-стамп)
            return '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
        return json.dumps({"op": "read", "path": path})
    return rev


def _fail_reviewer(path, blockers):
    marker = f"--- {path} ---"

    def rev(prompt):
        if marker in prompt:
            return json.dumps({"kind": "reviewer-result", "status": "fail",
                               "checks": [{"id": "x", "status": "fail"}], "blockers": blockers})
        return json.dumps({"op": "read", "path": path})
    return rev


def _rubber_reviewer():
    # pass БЕЗ единого чтения (0 reads) — рубер-стамп; движок ОБЯЗАН НЕ закрыть блокирующий гейт
    return lambda prompt: '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'


def _faithful_reviewer(path):
    """Полнопокрытный ДОБРОСОВЕСТНЫЙ ревьюер: читает изменённый файл, затем pass ЛЮБОГО гейта.
    Моделирует «идеального» ревьюера -> доказывает, что при полном покрытии движок доводит до ready
    (пол ENGINE-false-fail = 0: движок не добавляет ложных блоков сверх решений ревьюера)."""
    marker = f"--- {path} ---"

    def rev(prompt):
        if marker in prompt:
            return '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
        return json.dumps({"op": "read", "path": path})
    return rev


def _faithful_except(path, strict_gate, blockers):
    """Читает и pass ВСЕ гейты, КРОМЕ strict_gate — на нём warn+blockers (строгость на одном гейте).
    Моделирует реального ревьюера, придирчивого к одному аспекту корректного кода -> реальный
    reviewer-false-fail, атрибутируемый к конкретному гейту. gate_id виден в промпте ('гейта <id>')."""
    marker = f"--- {path} ---"
    strict_tag = f"гейта '{strict_gate}'"

    def rev(prompt):
        if marker in prompt:
            if strict_tag in prompt:
                return json.dumps({"kind": "reviewer-result", "status": "warn",
                                   "checks": [{"id": strict_gate, "status": "warn"}],
                                   "blockers": blockers})
            return '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
        return json.dumps({"op": "read", "path": path})
    return rev


def _abstain_reviewer(path, gate):
    """Читает, но по gate возвращает warn БЕЗ блокеров (неопределённость/воздержание).
    Моделирует «reviewer abstain»: сомнение без конкретной претензии. warn на blocking-гейте всё
    равно = блок -> та же проблема грубого enforcement, но уже без явных blockers."""
    marker = f"--- {path} ---"
    tag = f"гейта '{gate}'"

    def rev(prompt):
        if marker in prompt:
            if tag in prompt:
                return json.dumps({"kind": "reviewer-result", "status": "warn",
                                   "checks": [{"id": gate, "status": "warn"}]})
            return '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
        return json.dumps({"op": "read", "path": path})
    return rev


def _fixloop_reviewer(path):
    """Fail на 1-м раунде (blockers), pass после того, как писатель добавил маркер '# addressed'."""
    marker = f"--- {path} ---"

    def rev(prompt):
        if marker in prompt:
            addressed = "# addressed" in prompt
            if addressed:
                return '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
            return json.dumps({"kind": "reviewer-result", "status": "fail",
                               "checks": [{"id": "doc", "status": "fail"}],
                               "blockers": ["нет docstring у функции", "добавьте пометку # addressed"]})
        return json.dumps({"op": "read", "path": path})
    return rev


def _fixloop_writer(path):
    """1-й раунд — базовый файл; на fix-итерации (в контексте есть blockers) — файл с '# addressed'."""
    state = {"n": 0}

    def prop(ctx):
        fix = ("addressed" in ctx) or ("docstring" in ctx) or ("Устрани" in ctx) or ("упал" in ctx)
        if fix:
            if not state.get("done_fix"):
                state["done_fix"] = True
                return {"op": "write", "path": path,
                        "content": '"""doc."""\n# addressed\nv = 1\n'}
            return {"done": True}
        if state["n"] == 0:
            state["n"] = 1
            return {"op": "write", "path": path, "content": "v = 1\n"}
        return {"done": True}
    return prop


# --- корпус ---------------------------------------------------------------------------------------

def _cases():
    """Каждый кейс: id, tags, build(root)->kwargs для run(), expected(ready:bool, unmet_includes:list)."""
    cases = []

    # 1) чистый QUICK без ревью -> движок доводит до ready (базовый green-путь)
    def _b_quick(root):
        return dict(task_text="добавить q", signals=_quick_sig(), child_root=root,
                    engine="pipeline", provider_name="test", execute=True, feature="quick",
                    install_deps=False, proposer=_writer_script([
                        {"op": "write", "path": "src/q.py", "content": "q = 1\n"},
                        {"op": "read", "path": "src/q.py"}, {"done": True}]))
    cases.append({"id": "quick_clean", "tags": ["quick", "green"],
                  "build": _b_quick, "expected": {"ready": True, "unmet_includes": []}})

    # 2) ревьюер выносит fail -> ux_review блокирует (консервативный review; кандидат false-fail)
    def _b_revblock(root):
        return dict(task_text="ui правка", signals=_ui_sig(), child_root=root,
                    engine="pipeline", provider_name="test", execute=True, feature="revblock",
                    install_deps=False, review=True,
                    reviewer_proposer=_fail_reviewer("src/rb.py", ["нет состояний экрана"]),
                    proposer=_writer_script([
                        {"op": "write", "path": "src/rb.py", "content": "rb = 1\n"}, {"done": True}]))
    cases.append({"id": "review_blocks", "tags": ["review", "blocked"],
                  "build": _b_revblock, "expected": {"ready": False, "unmet_includes": ["ux_review"]}})

    # 3) fix-loop: ревью падает -> блокеры писателю -> фикс -> pass (TOOL-FREE e2e fix-loop, идёт в CI)
    def _b_fixloop(root):
        return dict(task_text="ui правка с доводкой", signals=_ui_sig(), child_root=root,
                    engine="pipeline", provider_name="test", execute=True, feature="fixloop",
                    install_deps=False, review=True, review_fix_attempts=1,
                    reviewer_proposer=_fixloop_reviewer("src/fx.py"),
                    proposer=_fixloop_writer("src/fx.py"))
    cases.append({"id": "fixloop_recovers", "tags": ["review", "fixloop", "green"],
                  "build": _b_fixloop, "expected": {"ready": True, "unmet_includes": [],
                                                     "fix_recovered": True}})

    # 4) ИНВАРИАНТ безопасности: рубер-стамп (pass без чтений) НЕ закрывает блокирующий гейт ->
    #    движок обязан НЕ отдать ready. Если отдаст -> false_green (bench падает жёстко).
    def _b_rubber(root):
        return dict(task_text="ui правка рубер-стамп", signals=_ui_sig(), child_root=root,
                    engine="pipeline", provider_name="test", execute=True, feature="rubber",
                    install_deps=False, review=True, reviewer_proposer=_rubber_reviewer(),
                    proposer=_writer_script([
                        {"op": "write", "path": "src/rs.py", "content": "rs = 1\n"}, {"done": True}]))
    cases.append({"id": "rubber_stamp_guard", "tags": ["review", "safety", "blocked"],
                  "build": _b_rubber, "expected": {"ready": False, "unmet_includes": ["ux_review"]}})

    for c in cases:
        c.setdefault("category", "capability")

    # --- known-good корпус (v3.1.6): матрица ui_impact × ui_change_kind × строгий_гейт ------------
    # Код заведомо КОРРЕКТЕН. Меняем только УРОВЕНЬ UI-воздействия, вид изменения и строгость ревью.
    # known_good_block_rate здесь = ЧУВСТВИТЕЛЬНОСТЬ механики на синтетике (не production-rate).
    # Пол ENGINE-false-fail доказываем полным покрытием на КАЖДОМ уровне impact.
    _n = {"n": 0}

    def _fresh(prefix):
        _n["n"] += 1
        return f"src/{prefix}{_n['n']}.py"

    # (A) engine_floor на КАЖДОМ уровне impact/kind: полнопокрытный добросовестный ревьюер -> ready.
    # Доказывает, что движок не режет корректный код независимо от уровня воздействия.
    def _mk_full(cid, impact, kind):
        path = _fresh("f")

        def _b(root, path=path, impact=impact, kind=kind):
            return dict(task_text=f"корректная правка ({impact}/{kind or 'backend'})",
                        signals=_impact_sig(impact, kind), child_root=root, engine="pipeline",
                        provider_name="test", execute=True, feature=cid, install_deps=False,
                        review=True, reviewer_proposer=_faithful_reviewer(path),
                        proposer=_writer_script([
                            {"op": "write", "path": path, "content": "v = 1\n"},
                            {"op": "read", "path": path}, {"done": True}]))
        return {"id": cid, "category": "known_good",
                "tags": ["review", "known_good", "engine_floor", impact], "build": _b,
                "expected": {"ready": True, "unmet_includes": []}}

    # backend-control (impact=none): в плане нет UI-review-гейтов -> ready БЕЗ ревью. Доказывает
    # концентрацию false-fail в UI-гейтах (не размазано по всем задачам).
    cases.append(_mk_full("kg_full_backend", "none", None))
    cases.append(_mk_full("kg_full_internal_token", "internal", "token"))
    cases.append(_mk_full("kg_full_internal_primitive", "internal", "primitive"))
    cases.append(_mk_full("kg_full_internal_component", "internal", "component"))
    cases.append(_mk_full("kg_full_internal_screen", "internal", "screen"))
    cases.append(_mk_full("kg_full_userfacing_component", "user_facing", "component"))
    cases.append(_mk_full("kg_full_userfacing_screen", "user_facing", "screen"))
    cases.append(_mk_full("kg_full_userfacing_flow", "user_facing", "flow"))
    cases.append(_mk_full("kg_full_critical_flow", "critical", "flow"))

    # (B) строгость на ОДНОМ гейте на корректном коде -> REAL reviewer-false-fail, атрибуция к гейту.
    # Уровень impact несёт shadow-политику: internal-не-safety блоки КАНДИДАТ снял бы, user_facing/
    # critical — сохранил бы (safety). Это и есть проектируемое снижение false-fail без изменения боя.
    _GATE_BLOCKERS = {
        "ux_review": "не описаны состояния экрана (для этой правки не требуется)",
        "visual_regression": "нет визуального снапшота (для этой правки не нужен)",
        "design_system_usage": "не сослались на токены дизайн-системы",
        "accessibility_review": "нет проверки контраста (для этой правки не требуется)",
    }

    def _mk_strict(cid, impact, kind, gate):
        path = _fresh("s")

        def _b(root, path=path, impact=impact, kind=kind, gate=gate):
            return dict(task_text=f"корректная правка ({impact}, строгий {gate})",
                        signals=_impact_sig(impact, kind), child_root=root, engine="pipeline",
                        provider_name="test", execute=True, feature=cid, install_deps=False,
                        review=True,
                        reviewer_proposer=_faithful_except(path, gate, [_GATE_BLOCKERS[gate]]),
                        proposer=_writer_script([
                            {"op": "write", "path": path, "content": "u = 1\n"}, {"done": True}]))
        return {"id": cid, "category": "known_good",
                "tags": ["review", "known_good", "false_fail", impact], "build": _b,
                "expected": {"ready": False, "unmet_includes": [gate], "blocked_by": [gate]}}

    for gate in gate_policy.UI_GATES:
        cases.append(_mk_strict(f"kg_strict_internal_{gate}", "internal", "component", gate))
        cases.append(_mk_strict(f"kg_strict_userfacing_{gate}", "user_facing", "screen", gate))
    cases.append(_mk_strict("kg_strict_critical_ux", "critical", "flow", "ux_review"))
    cases.append(_mk_strict("kg_strict_critical_a11y", "critical", "flow", "accessibility_review"))
    cases.append(_mk_strict("kg_strict_critical_visual", "critical", "flow", "visual_regression"))

    # (C) reviewer abstain: warn БЕЗ блокеров на internal ux -> блок (грубый enforcement и без claim).
    def _b_abstain(root):
        path = _fresh("ab")

        def _b2(root, path=path):
            return dict(task_text="корректная правка (internal, ревьюер воздержался по ux)",
                        signals=_impact_sig("internal", "component"), child_root=root,
                        engine="pipeline", provider_name="test", execute=True, feature="kgabstain",
                        install_deps=False, review=True,
                        reviewer_proposer=_abstain_reviewer(path, "ux_review"),
                        proposer=_writer_script([
                            {"op": "write", "path": path, "content": "u = 1\n"}, {"done": True}]))
        return _b2(root)
    cases.append({"id": "kg_abstain_internal_ux", "category": "known_good",
                  "tags": ["review", "known_good", "false_fail", "abstain", "internal"],
                  "build": _b_abstain,
                  "expected": {"ready": False, "unmet_includes": ["ux_review"],
                               "blocked_by": ["ux_review"]}})

    return cases


def _classify(expected, actual):
    exp_ready = bool(expected["ready"])
    act_ready = bool(actual["ready_for_pr"])
    unmet = actual["unmet"]
    if exp_ready and act_ready:
        cls = "ok"
    elif exp_ready and not act_ready:
        cls = "false_fail"
    elif not exp_ready and act_ready:
        cls = "false_green"
    else:
        cls = "ok"
    # проверяем и состав unmet (ожидаемые гейты должны блокировать)
    missing = [g for g in expected.get("unmet_includes", []) if g not in unmet]
    if cls == "ok" and missing:
        cls = "mismatch"   # исход по ready совпал, но не тот гейт заблокировал -> считаем расхождением
    return cls


def run_bench():
    report_cases = []
    for case in _cases():
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            branch = _scaffold(root)
            kwargs = case["build"](root)
            kwargs.setdefault("base", branch)
            signals = dict(kwargs.get("signals") or {})
            try:
                rep = ai_ops_run.run(**kwargs)
                actual = {"ready_for_pr": rep.get("ready_for_pr"),
                          "unmet": (rep.get("gates") or {}).get("unmet", [])}
                err = None
            except Exception as e:   # прогон-исключение — отдельный класс, не тихий провал
                actual = {"ready_for_pr": None, "unmet": [], "error": repr(e)}
                err = repr(e)
            cls = "error" if err else _classify(case["expected"], actual)
            fix_recovered = bool(case["expected"].get("fix_recovered")) and cls == "ok"
            # SHADOW: считаем кандидатную политику РЯДОМ (боевой verdict её не касается).
            shadow = gate_policy.shadow_diff(signals) if signals else None
            report_cases.append({"id": case["id"], "category": case.get("category", "capability"),
                                 "tags": case["tags"], "ui_impact": gate_policy.derive_ui_impact(signals),
                                 "expected": case["expected"], "actual": actual,
                                 "classification": cls, "fix_recovered": fix_recovered,
                                 "shadow": shadow})

    m = {"pass": 0, "false_green": 0, "false_fail": 0, "mismatch": 0, "error": 0,
         "review_blocked": 0, "fix_recovered": 0}
    for c in report_cases:
        cl = c["classification"]
        if cl == "ok":
            m["pass"] += 1
        else:
            m[cl] = m.get(cl, 0) + 1
        if cl == "ok" and not c["actual"]["ready_for_pr"] and "review" in c["tags"]:
            m["review_blocked"] += 1
        if c["fix_recovered"]:
            m["fix_recovered"] += 1

    total = len(report_cases)

    # --- ДВЕ РАЗНЫЕ ИСТИНЫ (v3.1.6), явно разведены -----------------------------------------------
    # policy_conformance: исполнил ли ДВИЖОК текущую gate-policy как задумано (эталон = expected).
    #   Это про корректность движка. false_green ОБЯЗАН быть 0. Ожидаемо 100%.
    policy_conformance = {
        "conformance_rate": round(m["pass"] / total, 3) if total else None,
        "false_green": m["false_green"], "false_fail_vs_policy": m["false_fail"],
        "mismatch": m["mismatch"], "error": m["error"],
        "note": "движок ИСПОЛНЯЕТ текущую policy; 100% при pass==total. Это НЕ про качество policy.",
    }

    # quality_accuracy: пропустила ли ТЕКУЩАЯ policy корректную работу (код заведомо корректен).
    #   known_good_block_rate — ЧУВСТВИТЕЛЬНОСТЬ механики на синтетике, НЕ production-rate.
    kg = [c for c in report_cases if c["category"] == "known_good"]
    kg_blocked = [c for c in kg if c["actual"].get("ready_for_pr") is not True]
    attribution = {}
    for c in kg_blocked:
        for g in c["actual"].get("unmet", []):
            attribution[g] = attribution.get(g, 0) + 1
    engine_floor_ok = all(c["actual"].get("ready_for_pr") is True
                          for c in kg if "engine_floor" in c["tags"])

    # ПРОЕКЦИЯ: сколько известных-хороших блоков осталось бы под КАНДИДАТНОЙ политикой.
    # Кейс «освобождается», если ни один его unmet-гейт не остаётся blocking у candidate для его impact.
    projected_released = []
    for c in kg_blocked:
        sig = {"ui_changed": True, "ui_impact": c["ui_impact"]}
        still_blocking = gate_policy.candidate_blocking_gates(sig)
        if not any(g in still_blocking for g in c["actual"].get("unmet", [])):
            projected_released.append(c["id"])
    projected_blocked = len(kg_blocked) - len(projected_released)

    quality_accuracy = {
        "synthetic_known_good_block_rate": round(len(kg_blocked) / len(kg), 3) if kg else None,
        "sample_size": len(kg), "sample_type": "scripted_reviewer",
        "live_reviewer_false_fail_rate": None,   # честно: вживую пока не измерено
        "engine_floor_ready": engine_floor_ok,
        "block_attribution": attribution,
        "projected_block_rate_after_calibration":
            round(projected_blocked / len(kg), 3) if kg else None,
        "projected_released": projected_released,
        "note": "synthetic-rate = чувствительность механики (scripted reviewer), НЕ production-rate; "
                "live_reviewer_false_fail_rate появится после реальных UI-задач.",
    }

    return {"kind": "bench-report", "bench_version": BENCH_VERSION,
            "package_version": _read_package_version(), "provider": "test",
            "total": total, "metrics": m,
            "policy_conformance": policy_conformance, "quality_accuracy": quality_accuracy,
            "cases": report_cases}


def selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and bool(cond)

    rep = run_bench()
    m = rep["metrics"]
    # инвариант безопасности — абсолютный
    expect("bench: false_green == 0 (движок никогда не отдаёт ready при обязательном блоке)",
           m["false_green"] == 0)
    expect("bench: 0 ошибок прогона (все кейсы исполнились)", m["error"] == 0)
    expect("bench: 0 расхождений по составу гейтов (mismatch)", m["mismatch"] == 0)
    # эталонные исходы совпали ровно (нет false_fail на заведомо готовых кейсах)
    expect("bench: false_fail == 0 (заведомо готовые кейсы доведены до ready)", m["false_fail"] == 0)
    expect("bench: все кейсы прошли (pass == total)", m["pass"] == rep["total"])
    # tool-free fix-loop реально сработал в CI-совместимом окружении
    expect("bench: fix-loop снял блок ревью tool-free (fix_recovered >= 1)", m["fix_recovered"] >= 1)
    # консервативный review измеряется (есть хотя бы один корректный review-блок)
    expect("bench: измерена консервативность review (review_blocked >= 1)", m["review_blocked"] >= 1)
    # схема отчёта пригодна к машинной обработке
    expect("bench: отчёт содержит per-case классификацию",
           all("classification" in c for c in rep["cases"]) and rep["total"] >= 4)

    # --- ДВЕ ИСТИНЫ (v3.1.6): policy_conformance vs quality_accuracy --------------------------------
    pc = rep["policy_conformance"]
    qa = rep["quality_accuracy"]
    UI = gate_policy.UI_GATES
    SAFE = gate_policy.SAFETY_UI_GATES

    # (1) policy_conformance: движок ИДЕАЛЬНО исполняет ТЕКУЩУЮ policy (нет false_green/false_fail/mismatch)
    expect("policy_conformance == 100% (движок исполняет текущую gate-policy как задумано)",
           pc["conformance_rate"] == 1.0 and pc["false_green"] == 0)

    # (2) engine floor: при полном добросовестном покрытии корректный код доходит до ready на КАЖДОМ impact
    expect("quality: engine_floor_ready (движок не источник false-fail ни на одном уровне impact)",
           qa["engine_floor_ready"] is True)
    # rate измерен, честно помечен как синтетический; live-rate НЕ выдаётся за измеренный
    expect("quality: synthetic_known_good_block_rate в [0,1], sample>=15, тип scripted, live=None",
           qa["synthetic_known_good_block_rate"] is not None
           and 0.0 <= qa["synthetic_known_good_block_rate"] <= 1.0
           and qa["sample_size"] >= 15 and qa["sample_type"] == "scripted_reviewer"
           and qa["live_reviewer_false_fail_rate"] is None)
    # атрибуция покрывает ВСЕ 4 UI review-гейта
    expect("quality: block_attribution покрывает все 4 UI-гейта",
           all(qa["block_attribution"].get(g, 0) >= 1 for g in UI))
    # КОНТРОЛЬ: backend (impact=none) доходит до ready -> false-fail сконцентрирован в UI-гейтах
    _bk = next((c for c in rep["cases"] if c["id"] == "kg_full_backend"), None)
    expect("quality: backend (impact=none) доходит до ready -> false-fail сконцентрирован в UI-ревью",
           _bk is not None and _bk["actual"].get("ready_for_pr") is True)
    # каждый known-good с blocked_by заблокирован ИМЕННО этим гейтом (среди UI-гейтов — ровно он)
    for c in rep["cases"]:
        exp_by = c["expected"].get("blocked_by")
        if exp_by:
            unmet = c["actual"].get("unmet", [])
            expect(f"quality: {c['id']} заблокирован именно {exp_by} (атрибуция точна)",
                   set(g for g in unmet if g in UI) == set(exp_by))

    # (3) ПРОЕКЦИЯ кандидатной политики: строгое снижение false-fail, но БЕЗ ослабления safety
    expect("shadow: кандидат СТРОГО снижает known_good_block_rate (есть что калибровать)",
           qa["projected_block_rate_after_calibration"] < qa["synthetic_known_good_block_rate"])
    # освобождаются ТОЛЬКО internal-кейсы и ТОЛЬКО по не-safety гейтам
    for cid in qa["projected_released"]:
        c = next(x for x in rep["cases"] if x["id"] == cid)
        unmet_ui = [g for g in c["actual"].get("unmet", []) if g in UI]
        expect(f"shadow: освобождён {cid} -> impact=internal и unmet без safety-гейтов",
               c["ui_impact"] == "internal" and not (set(unmet_ui) & set(SAFE)))
    # НИ ОДИН user_facing/critical заблокированный кейс не освобождается (safety сохранена)
    _released_impacts = {next(x for x in rep["cases"] if x["id"] == cid)["ui_impact"]
                         for cid in qa["projected_released"]}
    expect("shadow: ни один user_facing/critical кейс НЕ освобождён (safety не ослаблена)",
           not (_released_impacts & {"user_facing", "critical"}))

    # (4) SHADOW-диффы: user_facing/critical -> ноль ослабляющих отличий; движок остаётся источником истины
    for c in rep["cases"]:
        sh = c.get("shadow")
        if sh and c["ui_impact"] in ("user_facing", "critical"):
            weakening = [d for d in sh["differences"] if d["effect"] in ("would_unblock", "would_skip")]
            expect(f"shadow: {c['id']} ({c['ui_impact']}) без ослабляющих отличий кандидата",
                   not weakening)
    # ИНВАРИАНТ безопасности сохранён на всём корпусе
    expect("shadow: измерение/проекция НЕ порождают false_green (безопасность не ослаблена)",
           m["false_green"] == 0)

    print("bench_lite selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    ap = argparse.ArgumentParser(prog="bench_lite.py")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--out", help="сохранить BenchReport в JSON-файл")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.run or a.out:
        rep = run_bench()
        text = json.dumps(rep, ensure_ascii=False, indent=2)
        if a.out:
            Path(a.out).write_text(text, encoding="utf-8")
            print(f"BenchReport -> {a.out}")
        print(json.dumps(rep["metrics"], ensure_ascii=False))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
