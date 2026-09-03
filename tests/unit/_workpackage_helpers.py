"""Общие хелперы и фикстуры для разрезанных тестов workpackage_executor (не собирается pytest)."""
from __future__ import annotations

import re
import sys
from pathlib import Path as _StdPath

import pytest

PKG_ROOT = _StdPath(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from ai_ops_kit.engine.workpackage_executor import (
    Path,
    _git,
    _ordered,
    _pkg_hash,
    _plan_hash,
    json,
)


# ─── helpers ───────────────────────────────────────────────────────────────────

def _mkrepo(td):
    (Path(td) / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    for a in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t"),
              ("add", "-A"), ("commit", "-q", "-m", "i")):
        _git(td, *a)
    return _git(td, "rev-parse", "--abbrev-ref", "HEAD")[1]


def _author(prompt):
    if "requirements-artifact" in prompt:
        return ("schema_version: 1\nkind: requirements-artifact\nrequirements:\n"
                "  - id: R1\n    statement: пакет реализован\n    acceptance:\n      - when готово then тест зелёный\n")
    if "spec-change" in prompt:
        return ("schema_version: 1\nkind: spec-change\ncapability: mod\nwhy: нужно\n"
                "what_changes:\n  - изменение\ntasks:\n  - шаг\nrequirements:\n"
                "  - name: R\n    text: The system SHALL work.\n    scenarios:\n"
                "      - {name: T, when: x, then: y}\n")
    return ("schema_version: 1\nkind: plan-artifact\nwork_packages:\n"
            "  - id: WP1\n    summary: пакет\n    depends_on: []\nwrite_scope:\n  - .\n")


def _pass_reviewer(prompt):
    p = prompt or ""
    _cand = re.search(r"\+\+\+ b/(\S+)", p)
    _path = _cand.group(1) if _cand else "calc.py"
    if f"--- {_path} ---" not in p:
        return json.dumps({"op": "read", "path": _path})
    res = {"kind": "reviewer-result", "status": "pass", "checks": [{"id": "ok", "status": "pass"}]}
    m = re.search(r"применимым доменам:\s*([^\n(]+)", p)
    if m:
        doms = [d.strip() for d in m.group(1).split(",") if d.strip()]
        if doms:
            res["domain_results"] = [{"domain": d, "status": "pass",
                                      "checks": [{"id": f"{d}_ok", "status": "pass"}],
                                      "evidence": [{"type": "code-read", "path": _path, "lines": "1-10"}]}
                                     for d in doms]
    return json.dumps(res, ensure_ascii=False)


def _prop_for(pkg):
    fname = f"src/{pkg['id']}.py"
    it = iter([{"op": "write", "path": fname, "content": f"# {pkg['id']}\nx=1\n"}, {"done": True}])
    return lambda c: next(it)


def _prop_ws(pkg):
    sub = (pkg.get("scope") or ["core"])[0]
    it = iter([{"op": "write", "path": f"src/{sub}/mod.py", "content": "x = 1\n"}, {"done": True}])
    return lambda c: next(it)


def _valid_plan(wid="seq"):
    _o = _ordered([{"id": "WP1", "order": 1, "depends_on": [], "scope": "a", "write_scope": ["."]},
                   {"id": "WP2", "order": 2, "depends_on": ["WP1"], "scope": "b", "write_scope": ["."]}])
    return {"schema_version": 1, "kind": "SequencePlan", "workitem_id": wid, "total": 2,
            "plan_hash": _plan_hash(_o), "base_ref": "main", "sequence_base_sha": "deadbeef",
            "packages": [{"id": p["id"], "order": p["order"], "depends_on": p["depends_on"],
                          "scope": p["scope"], "write_scope": p["write_scope"],
                          "pkg_hash": _pkg_hash(p)} for p in _o]}


def _reseal(plan):
    for _p in plan["packages"]:
        _p["pkg_hash"] = _pkg_hash(_p)
    plan["plan_hash"] = _plan_hash(_ordered(plan["packages"]))
    return plan


# ─── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def three_area_sig():
    return {"task_type": "ENGINEERING", "size": "large", "risk": "low",
            "affected_areas": ["catalog", "orders", "billing"]}


@pytest.fixture
def two_area_sig():
    return {"task_type": "ENGINEERING", "size": "large", "risk": "low",
            "affected_areas": ["catalog", "orders"]}
