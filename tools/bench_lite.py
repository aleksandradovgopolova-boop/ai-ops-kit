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

Метрики BenchReport:
  pass          — исход движка совпал с эталоном (ok)
  false_green   — движок сказал ready, а эталон требует блока  (ИНВАРИАНТ: обязан быть 0)
  false_fail    — движок заблокировал легитимную готовую задачу
  review_blocked— корректно заблокировано independent-review (мера консервативности)
  fix_recovered — блок ревью снят fix-loop'ом за отведённые попытки (tool-free e2e fix-loop)

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

BENCH_VERSION = "0.1"


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

    # --- known-good корпус для reviewer false-fail rate --------------------------------------------
    # Код заведомо КОРРЕКТЕН. Меняем только ПОКРЫТИЕ/строгость ревьюера. false-fail здесь = движок
    # заблокировал корректный код из-за решения ревью. Пол ENGINE-false-fail доказываем полным покрытием.

    # KG1: добросовестный полнопокрытный ревьюер закрывает ВСЕ применимые review-гейты -> ready.
    # Доказывает: движок НЕ источник false-fail; при полном покрытии корректный код доходит до PR.
    def _b_kg_full(root):
        return dict(task_text="корректная ui правка", signals=_ui_sig(), child_root=root,
                    engine="pipeline", provider_name="test", execute=True, feature="kgfull",
                    install_deps=False, review=True, reviewer_proposer=_faithful_reviewer("src/kf.py"),
                    proposer=_writer_script([
                        {"op": "write", "path": "src/kf.py", "content": "kf = 1\n"}, {"done": True}]))
    cases.append({"id": "kg_full_coverage", "category": "known_good",
                  "tags": ["review", "known_good", "engine_floor"], "build": _b_kg_full,
                  "expected": {"ready": True, "unmet_includes": []}})

    # KG2: ревьюер придирчив к visual_regression (warn) на корректном коде -> REAL false-fail,
    #      атрибутируется visual_regression. (Гейт низкой ценности для backend-подобной правки.)
    def _b_kg_vis(root):
        return dict(task_text="корректная ui правка (строгий visual)", signals=_ui_sig(),
                    child_root=root, engine="pipeline", provider_name="test", execute=True,
                    feature="kgvis", install_deps=False, review=True,
                    reviewer_proposer=_faithful_except("src/kv.py", "visual_regression",
                                                       ["нет визуального снапшота (для этой правки не нужен)"]),
                    proposer=_writer_script([
                        {"op": "write", "path": "src/kv.py", "content": "kv = 1\n"}, {"done": True}]))
    cases.append({"id": "kg_strict_visual", "category": "known_good",
                  "tags": ["review", "known_good", "false_fail"], "build": _b_kg_vis,
                  "expected": {"ready": False, "unmet_includes": ["visual_regression"],
                               "blocked_by": ["visual_regression"]}})

    # KG3: ревьюер придирчив к design_system_usage на корректном коде -> REAL false-fail, атрибуция.
    def _b_kg_ds(root):
        return dict(task_text="корректная ui правка (строгий design-system)", signals=_ui_sig(),
                    child_root=root, engine="pipeline", provider_name="test", execute=True,
                    feature="kgds", install_deps=False, review=True,
                    reviewer_proposer=_faithful_except("src/kd.py", "design_system_usage",
                                                       ["не сослались на токены дизайн-системы"]),
                    proposer=_writer_script([
                        {"op": "write", "path": "src/kd.py", "content": "kd = 1\n"}, {"done": True}]))
    cases.append({"id": "kg_strict_designsys", "category": "known_good",
                  "tags": ["review", "known_good", "false_fail"], "build": _b_kg_ds,
                  "expected": {"ready": False, "unmet_includes": ["design_system_usage"],
                               "blocked_by": ["design_system_usage"]}})

    # --- golden tasks (v3.1.5): расширяем known-good разными формами задач -> замер на широкой выборке.
    # KG-control: backend/QUICK правка (НЕ ui) — в плане нет блокирующих review-гейтов -> ready БЕЗ ревью.
    # Ключевой контроль: доказывает, что reviewer-false-fail СКОНЦЕНТРИРОВАН в UI-гейтах (ui_changed), а
    # не размазан по всем задачам. Прямая опора для решения про advisory-тир.
    def _b_kg_backend(root):
        return dict(task_text="корректная backend-правка (без UI)", signals=_quick_sig(),
                    child_root=root, engine="pipeline", provider_name="test", execute=True,
                    feature="kgbk", install_deps=False, review=True,
                    reviewer_proposer=_faithful_reviewer("src/kb.py"),
                    proposer=_writer_script([
                        {"op": "write", "path": "src/kb.py", "content": "def total(a, b):\n    return a + b\n"},
                        {"op": "read", "path": "src/kb.py"}, {"done": True}]))
    cases.append({"id": "kg_backend_control", "category": "known_good",
                  "tags": ["known_good", "control", "backend"], "build": _b_kg_backend,
                  "expected": {"ready": True, "unmet_includes": []}})

    # KG: строгость на ux_review и accessibility_review -> покрываем ВСЕ 4 UI-гейта в атрибуции.
    def _mk_strict_ui(cid, path, gate, blockers):
        def _b(root):
            return dict(task_text=f"корректная ui правка (строгий {gate})", signals=_ui_sig(),
                        child_root=root, engine="pipeline", provider_name="test", execute=True,
                        feature=cid, install_deps=False, review=True,
                        reviewer_proposer=_faithful_except(path, gate, blockers),
                        proposer=_writer_script([
                            {"op": "write", "path": path, "content": "u = 1\n"}, {"done": True}]))
        return {"id": cid, "category": "known_good", "tags": ["review", "known_good", "false_fail"],
                "build": _b, "expected": {"ready": False, "unmet_includes": [gate], "blocked_by": [gate]}}

    cases.append(_mk_strict_ui("kg_strict_ux", "src/ku.py", "ux_review",
                               ["не описаны состояния экрана (для этой правки не требуется)"]))
    cases.append(_mk_strict_ui("kg_strict_a11y", "src/ka.py", "accessibility_review",
                               ["нет проверки контраста (для этой правки не требуется)"]))

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
            report_cases.append({"id": case["id"], "category": case.get("category", "capability"),
                                 "tags": case["tags"], "expected": case["expected"], "actual": actual,
                                 "classification": cls, "fix_recovered": fix_recovered})

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

    # reviewer false-fail rate: доля known-good кейсов, где КОРРЕКТНЫЙ код заблокирован решением ревью.
    # ENGINE-пол: known-good с полным покрытием (engine_floor) обязан быть ready -> движок не источник.
    # Атрибуция: какие review-гейты режут корректный код (unmet каждого заблокированного known-good).
    kg = [c for c in report_cases if c["category"] == "known_good"]
    kg_blocked = [c for c in kg if c["actual"].get("ready_for_pr") is not True]
    attribution = {}
    for c in kg_blocked:
        for g in c["actual"].get("unmet", []):
            attribution[g] = attribution.get(g, 0) + 1
    engine_floor_ok = all(c["actual"].get("ready_for_pr") is True
                          for c in kg if "engine_floor" in c["tags"])
    ffr = {"known_good_total": len(kg), "known_good_blocked": len(kg_blocked),
           "reviewer_false_fail_rate": round(len(kg_blocked) / len(kg), 3) if kg else None,
           "engine_floor_ready": engine_floor_ok, "block_attribution": attribution}

    return {"kind": "bench-report", "bench_version": BENCH_VERSION,
            "package_version": _read_package_version(), "provider": "test",
            "total": len(report_cases), "metrics": m, "reviewer_false_fail": ffr,
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

    # --- reviewer false-fail rate (v3.1.4) ---
    ff = rep["reviewer_false_fail"]
    # ПОЛ движка: при полном добросовестном покрытии корректный код доходит до ready -> движок НЕ
    # источник false-fail (весь false-fail идёт от строгости/покрытия РЕВЬЮ, не от движка).
    expect("ffr: engine floor — known-good с полным покрытием ревью доходит до ready (движок не режет)",
           ff["engine_floor_ready"] is True)
    # rate измерен и в [0,1]; корпус нетривиален
    expect("ffr: reviewer_false_fail_rate измерен в [0,1] на непустом known-good корпусе",
           ff["known_good_total"] >= 3 and ff["reviewer_false_fail_rate"] is not None
           and 0.0 <= ff["reviewer_false_fail_rate"] <= 1.0)
    # атрибуция покрывает ВСЕ 4 UI review-гейта (широкая выборка golden tasks v3.1.5)
    expect("ffr: block_attribution покрывает все 4 UI-гейта (ux/accessibility/visual/design_system)",
           all(ff["block_attribution"].get(g, 0) >= 1 for g in
               ("ux_review", "accessibility_review", "visual_regression", "design_system_usage")))
    # КОНТРОЛЬ: backend/не-ui корректная правка доходит до ready -> false-fail сконцентрирован в UI-гейтах
    _bk = next((c for c in rep["cases"] if c["id"] == "kg_backend_control"), None)
    expect("ffr: backend-control (не-UI) доходит до ready -> false-fail сконцентрирован в UI-ревью",
           _bk is not None and _bk["actual"].get("ready_for_pr") is True)
    # каждый known-good с ожидаемым blocked_by действительно заблокирован ИМЕННО этим гейтом
    for c in rep["cases"]:
        exp_by = c["expected"].get("blocked_by")
        if exp_by:
            unmet = c["actual"].get("unmet", [])
            expect(f"ffr: {c['id']} заблокирован именно {exp_by} (атрибуция точна)",
                   all(g in unmet for g in exp_by))
    # ИНВАРИАНТ безопасности сохранён и на known-good: измерение строгости НЕ создаёт false-green
    expect("ffr: known-good измерение НЕ порождает false_green (безопасность не ослаблена)",
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
