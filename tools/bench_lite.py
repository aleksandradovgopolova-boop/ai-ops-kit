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
            report_cases.append({"id": case["id"], "tags": case["tags"],
                                 "expected": case["expected"], "actual": actual,
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

    return {"kind": "bench-report", "bench_version": BENCH_VERSION,
            "package_version": _read_package_version(), "provider": "test",
            "total": len(report_cases), "metrics": m, "cases": report_cases}


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
