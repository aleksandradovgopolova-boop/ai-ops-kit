"""Селфтест run_handoff, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from run_handoff import (  # noqa: F401 — имена, которые использует тело
    Path,
    _git,
    build_handoff,
    resume_preflight,
    subprocess,
    yaml,
)


@pytest.mark.slow
def test_run_handoff_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # build_handoff из ready-отчёта
    rep_ready = {"workitem_id": "feat-x", "ready_for_pr": True,
                 "commit": {"sha": "a" * 40, "branch": "ai-ops/feat-x", "evidence_on_exact_sha": True},
                 "loop": {"applied_writes": 2, "stopped": "done"},
                 "gates": {"evaluated": ["requirements", "code_review"], "unmet": []},
                 "not_yet": [], "checks": {}}
    h = build_handoff(rep_ready)
    expect("handoff: kind=RunHandoff", h["kind"] == "RunHandoff")
    expect("handoff: resume_from_revision = commit SHA", h["resume_from_revision"] == "a" * 40)
    expect("handoff: ready -> next_action про PR", "PR" in h["next_action"])
    expect("handoff: verification.passed непуст", set(h["verification"]["passed"]) == {"requirements", "code_review"})

    # build_handoff из not-ready (гейты unmet) -> next_action про гейты
    rep_block = {"workitem_id": "feat-y", "ready_for_pr": False,
                 "commit": {"sha": "b" * 40, "branch": "ai-ops/feat-y", "evidence_on_exact_sha": True},
                 "loop": {"applied_writes": 1, "stopped": "done"},
                 "gates": {"evaluated": ["requirements", "security"], "unmet": ["security"]},
                 "security_scan": {"secrets": [{"path": "a"}], "new_dependencies": [], "injection_flags": []},
                 "not_yet": ["draft PR"], "checks": {}}
    hb = build_handoff(rep_block)
    expect("handoff: unmet -> next_action про гейты", "security" in hb["next_action"])
    expect("handoff: known_risks содержит секреты", any("секрет" in r for r in hb["known_risks"]))
    expect("handoff: verification.failed содержит security", "security" in hb["verification"]["failed"])

    # resume_preflight: нет handoff -> can_resume False
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "-C", td, "init", "-q"])
        subprocess.run(["git", "-C", td, "config", "user.email", "t@t"])
        subprocess.run(["git", "-C", td, "config", "user.name", "t"])
        (root / "f").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"]); subprocess.run(["git", "-C", td, "commit", "-q", "-m", "i"])
        pf0 = resume_preflight(root, "nope")
        expect("resume: нет handoff -> can_resume=False", pf0["can_resume"] is False)

        # положим handoff, ветку не создаём -> revalidation (worktree утерян)
        rc, head, _ = _git(root, "rev-parse", "HEAD")
        fdir = root / "features" / "feat-z"; fdir.mkdir(parents=True)
        (fdir / "run-handoff.yaml").write_text(yaml.safe_dump(
            {"kind": "RunHandoff", "workitem_id": "feat-z", "resume_from_revision": head,
             "next_action": "продолжить", "open_questions": []}), encoding="utf-8")
        pf = resume_preflight(root, "feat-z", base="master")
        expect("resume: handoff есть -> can_resume=True", pf["can_resume"] is True)
        expect("resume: ветки нет -> revalidation_needed", pf["revalidation_needed"] is True)
        expect("resume: next_action перенесён из handoff", pf["next_action"] == "продолжить")

        # base ушёл вперёд -> revalidation
        (root / "g").write_text("y", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"]); subprocess.run(["git", "-C", td, "commit", "-q", "-m", "advance"])
        # текущая ветка (master/main) ушла вперёд от head
        cur = _git(root, "rev-parse", "--abbrev-ref", "HEAD")[1]
        pf2 = resume_preflight(root, "feat-z", base=cur)
        expect("resume: base ушёл вперёд -> revalidation + причина",
               pf2["revalidation_needed"] is True and any("вперёд" in r for r in pf2["reasons"]))
        # v2.105 (самоаудит): неразрешимая base-ветка -> НЕ молчим, требуем ревалидацию из осторожности
        pf3 = resume_preflight(root, "feat-z", base="no-such-branch-xyz")
        expect("resume: неразрешимая base -> revalidation + честная причина (не молча 'актуально')",
               pf3["revalidation_needed"] is True and any("не удалось разрешить" in r for r in pf3["reasons"]))
        expect("resume: fast-forward base -> base_rewritten=False (не переписан, снимается force)",
               pf2.get("base_rewritten") is False)

    # v3.0.10 (finding аудита P0): build_handoff несёт исходный BaseBinding; resume_preflight отличает
    # FAST-FORWARD (снимается force) от REWRITE базы (force-push/пересоздание — force НЕ снимает).
    hbb = build_handoff({"workitem_id": "bb", "ready_for_pr": True,
                         "commit": {"sha": "c" * 40, "branch": "ai-ops/bb", "evidence_on_exact_sha": True},
                         "base_binding": {"kind": "BaseBinding", "base_ref": "main",
                                          "base_sha": "d" * 40, "mode": "auto", "source": "upstream"},
                         "loop": {"applied_writes": 1, "stopped": "done"}, "gates": {}, "checks": {}})
    expect("v3.0.10 handoff: BaseBinding.base_sha сохранён в RunHandoff",
           hbb.get("base_binding", {}).get("base_sha") == "d" * 40)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
            _git(root, *a)
        (root / "f").write_text("x", encoding="utf-8")
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "base-A")
        base_A = _git(root, "rev-parse", "HEAD")[1]
        cur = _git(root, "rev-parse", "--abbrev-ref", "HEAD")[1]
        # рабочий коммит поверх base-A на ветке ai-ops/rw
        _git(root, "checkout", "-q", "-b", "ai-ops/rw")
        (root / "w").write_text("work", encoding="utf-8")
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "work")
        work_sha = _git(root, "rev-parse", "HEAD")[1]
        _git(root, "checkout", "-q", cur)
        fdir = root / "features" / "rw"; fdir.mkdir(parents=True)

        def _put_handoff(base_sha):
            (fdir / "run-handoff.yaml").write_text(yaml.safe_dump(
                {"kind": "RunHandoff", "workitem_id": "rw", "resume_from_revision": work_sha,
                 "base_binding": {"kind": "BaseBinding", "base_ref": cur, "base_sha": base_sha,
                                  "mode": "auto", "source": "upstream"},
                 "next_action": "продолжить", "open_questions": []}), encoding="utf-8")
        # (1) сохранённый base_sha == текущий HEAD базы -> НЕ переписан
        _put_handoff(base_A)
        pf_ok = resume_preflight(root, "rw", base=cur)
        expect("v3.0.10 resume: base_sha == текущий HEAD -> base_rewritten=False",
               pf_ok.get("base_rewritten") is False and pf_ok.get("base_moved") is False)
        # (1b) v3.0.14 (finding аудита #1, вариант B): FAST-FORWARD базы (A предок нового HEAD) -> base_moved
        #      (не rewrite); resume против сдвинувшейся базы запрещён без replan.
        (root / "b2").write_text("advance", encoding="utf-8")
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "base-B (ff)")
        pf_ff = resume_preflight(root, "rw", base=cur)   # handoff всё ещё хранит base_sha=base_A
        expect("v3.0.14 resume: fast-forward базы -> base_moved=True, base_rewritten=False",
               pf_ff.get("base_moved") is True and pf_ff.get("base_rewritten") is False
               and any("fast-forward" in r for r in pf_ff["reasons"]))
        # (2) base force-push НАЗАД на несвязанный коммит: пересоздаём ветку на orphan -> сохранённый
        #     base_sha больше НЕ предок нового HEAD -> REWRITE (не fast-forward)
        _git(root, "checkout", "-q", "--orphan", "reborn")
        (root / "z").write_text("reborn", encoding="utf-8")
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "unrelated")
        reborn_sha = _git(root, "rev-parse", "HEAD")[1]
        _git(root, "branch", "-f", cur, reborn_sha)
        _git(root, "checkout", "-q", cur)
        pf_rw = resume_preflight(root, "rw", base=cur)
        expect("v3.0.10 resume: base переписан (не предок) -> base_rewritten=True + причина",
               pf_rw.get("base_rewritten") is True
               and any("ПЕРЕПИСАН" in r for r in pf_rw["reasons"]))

        # v3.0.12 (finding аудита блок B): битый/пустой RunHandoff -> НЕ «resume безопасен» (fail-closed).
        (fdir / "run-handoff.yaml").write_text("", encoding="utf-8")   # оборванная запись
        pf_empty = resume_preflight(root, "rw", base=cur)
        expect("v3.0.12: пустой RunHandoff -> can_resume=False (не тихий 'актуально')",
               pf_empty["can_resume"] is False and any("повреждён" in r for r in pf_empty["reasons"]))
        (fdir / "run-handoff.yaml").write_text("kind: RunHandoff\n:::not yaml:::\n  - [", encoding="utf-8")
        pf_bad = resume_preflight(root, "rw", base=cur)
        expect("v3.0.12: битый YAML RunHandoff -> can_resume=False",
               pf_bad["can_resume"] is False)

    assert ok, "перенесённый селфтест run_handoff: см. строки FAIL в выводе"
