"""Селфтест review_branch, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from review_branch import (  # noqa: F401 — имена, которые использует тело
    Path,
    _git,
    review,
)


@pytest.mark.slow
def test_review_branch_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    import ai_ops_run
    import io
    import contextlib

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t"),
                  ("add", "-A"), ("commit", "-q", "-m", "i")):
            _git(root, *a)
        cur = _git(root, "rev-parse", "--abbrev-ref", "HEAD")[1]

        # сначала — реальный прогон, создающий ветку ai-ops/rv + план (ENGINEERING -> code_review reviewable)
        it = iter([{"op": "write", "path": "src/rv.py", "content": "x=1\n"}, {"done": True}])
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            # v2.121: heavy требует спеку ДО tool loop -> запускаем с author=True (движок авторизует спеку)
            ai_ops_run.run("рефактор", {"task_type": "ENGINEERING", "size": "small", "risk": "low",
                                        "affected_areas": ["core"], "decomposition_confirmed": True},
                           root, engine="pipeline", proposer=lambda c: next(it), execute=True,
                           feature="rv", install_deps=False, author=True)

        # нет ветки -> честный no-branch
        r_nb = review(root, "never", reviewer_proposer=lambda p: '{"kind":"reviewer-result","status":"pass"}', base=cur)
        expect("review: нет ветки -> verdict=no-branch (нечего ревьюить)", r_nb["verdict"] == "no-branch")

        # существующая ветка + reviewer pass -> verdict pass, БЕЗ нового коммита (read-only)
        _, sha_before, _ = _git(root / ".ai" / "worktrees" / "rv", "rev-parse", "HEAD")
        # v3.0.11: ревьюер читает изменённый файл ПЕРЕД pass (иначе блокирующий code_review не закрывается
        # по 0-read рубер-стампу).
        def passrev(p):
            if "--- src/rv.py ---" in p:
                return '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
            return '{"op":"read","path":"src/rv.py"}'
        r_ok = review(root, "rv", reviewer_proposer=passrev, base=cur)
        _, sha_after, _ = _git(root / ".ai" / "worktrees" / "rv", "rev-parse", "HEAD")
        expect("review: reviewer pass -> verdict=pass, есть вердикт code_review",
               r_ok["verdict"] == "pass" and any(rv["gate"] == "code_review" and rv["status"] == "pass"
                                                 for rv in r_ok["reviews"]))
        expect("review: read-only — ветка НЕ получила новый коммит", sha_before == sha_after)

        # reviewer fail -> verdict needs-changes (не pass)
        failrev = lambda p: '{"kind":"reviewer-result","status":"fail","checks":[{"id":"x","status":"fail"}],"blockers":["плохо"]}'
        r_bad = review(root, "rv", reviewer_proposer=failrev, base=cur)
        expect("review: reviewer fail -> verdict=needs-changes", r_bad["verdict"] == "needs-changes")

        # v2.121 (P1.3): вердикт пере-считывает готовность и фиксируется артефактом (lifecycle, не диагностика)
        expect("v2.121 review: pass -> readiness.ready_for_merge=True",
               (r_ok.get("readiness") or {}).get("ready_for_merge") is True)
        expect("v2.121 review: needs-changes -> ready_for_merge=False",
               (r_bad.get("readiness") or {}).get("ready_for_merge") is False)
        ev = root / "features" / "rv" / "branch-review.yaml"
        expect("v2.121 review: вердикт зафиксирован артефактом features/rv/branch-review.yaml", ev.is_file())
        if ev.is_file():
            import yaml as _y
            rec = _y.safe_load(ev.read_text(encoding="utf-8"))
            # последний прогон был needs-changes -> артефакт отражает актуальный вердикт + метку времени
            expect("v2.121 review: артефакт хранит вердикт + created_at",
                   rec.get("verdict") == "needs-changes" and bool(rec.get("created_at")))

        # v2.121 (P1.3): needs-reviewer (нет живого ревьюера) -> готовность НЕ подтверждена
        r_nr = review(root, "rv", reviewer_proposer=None, base=cur)
        expect("v2.121 review: needs-reviewer -> ready_for_merge=False (вердикт не вынесен)",
               r_nr["verdict"] == "needs-reviewer"
               and (r_nr.get("readiness") or {}).get("ready_for_merge") is False)

    assert ok, "перенесённый селфтест review_branch: см. строки FAIL в выводе"
