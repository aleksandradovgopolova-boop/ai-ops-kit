"""Первый сценарий: DISCOVER -> CLASSIFY -> RECONSTRUCT -> AUDIT -> ASK (v3.35).

  * positive     — пустой репозиторий классифицируется как новый продукт, живой — как существующий;
                   восстановленное несёт статус и основание;
  * fail-closed  — нечитаемое дерево даёт UNKNOWN, а не «пустой»; догадка не публикуется как факт;
  * side-effect  — закрытый контур ВОПРОСОВ НЕ ЗАДАЁТ (не спрашивать то, что видно).
"""
from __future__ import annotations

import subprocess

from ai_ops_kit.planning import contours as C
from ai_ops_kit.planning import repo_audit as A

MODEL = C.load_model()


def _git_repo(tmp_path, commits=1):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for cfg in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(tmp_path), "config", *cfg], check=True)
    for i in range(commits):
        (tmp_path / f"f{i}.txt").write_text(str(i), encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", f"c{i}"], check=True)
    return tmp_path


# ── positive ──────────────────────────────────────────────────────────────────────────────────

def test_empty_repo_is_new_product(tmp_path):
    ev = A.discover(tmp_path)
    cls = A.classify(ev, MODEL)
    assert cls["class"] == "NEW_PRODUCT"
    assert cls["onboarding"] == "product_bootstrap"


def test_living_system_is_existing_product(tmp_path):
    r = _git_repo(tmp_path, commits=1)
    (r / "src").mkdir()
    for i in range(20):
        (r / "src" / f"m{i}.py").write_text("x = 1\n", encoding="utf-8")
    (r / "tests").mkdir()
    (r / "tests" / "test_a.py").write_text("def test_a(): pass\n", encoding="utf-8")
    (r / ".github" / "workflows").mkdir(parents=True)
    (r / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
    (r / "migrations").mkdir()
    ev = A.discover(r)
    cls = A.classify(ev, MODEL)
    # Коммитов мало, но CI + тесты + миграции — три сильных признака живой системы.
    assert cls["class"] == "EXISTING_PRODUCT"
    assert cls["confidence"] == "medium"


def test_code_without_history_is_early_product(tmp_path):
    (tmp_path / "src").mkdir()
    for i in range(30):
        (tmp_path / "src" / f"m{i}.py").write_text("x = 1\n", encoding="utf-8")
    cls = A.classify(A.discover(tmp_path), MODEL)
    assert cls["class"] == "EARLY_PRODUCT"


def test_reconstruction_carries_status_and_evidence(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "migrations").mkdir()
    rec = A.reconstruct(tmp_path, A.discover(tmp_path), MODEL)
    assert rec["persistence"]["status"] == A.VERIFIED
    assert rec["persistence"]["evidence"]              # утверждение без основания недопустимо


# ── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_unreadable_tree_is_unknown_not_empty(tmp_path):
    """UNKNOWN != «пустой репозиторий»: первое не читается, второе читается и даёт нули."""
    cls = A.classify({"tree_readable": False, "source_files": None, "commits": None}, MODEL)
    assert cls["class"] == "UNKNOWN"
    assert cls["onboarding"] == "ask_before_acting"


def test_architecture_style_is_never_verified(tmp_path):
    """Имена папок не являются архитектурой: догадка обязана остаться догадкой."""
    (tmp_path / "src" / "modules").mkdir(parents=True)
    (tmp_path / "src" / "modules" / "a.py").write_text("x = 1\n", encoding="utf-8")
    rec = A.reconstruct(tmp_path, A.discover(tmp_path), MODEL)
    assert rec["architecture_style"]["status"] == A.INFERRED
    assert rec["architecture_style"]["status"] != A.VERIFIED


def test_unknowable_facts_are_declared_unknown(tmp_path):
    """О том, что из кода не выводится, слой говорит прямо, а не молчит."""
    rec = A.reconstruct(tmp_path, A.discover(tmp_path), MODEL)
    for key in ("primary_user", "product_goal", "production_environment", "sensitive_data"):
        assert rec[key]["status"] == A.UNKNOWN
        assert rec[key]["note"]


def test_evidence_never_points_into_worktree_copies(tmp_path):
    """`.claude/worktrees/*` — копии самого репозитория; путь туда доказательством не является."""
    wt = tmp_path / ".claude" / "worktrees" / "copy" / "migrations"
    wt.mkdir(parents=True)
    ev = A.discover(tmp_path)
    assert all(".claude" not in m for m in (ev["migrations"] or []))


def test_exactly_one_gap_tier_blocks_work():
    """Иначе онбординг снова требует «заполнить всё до работы»."""
    blocking = [t for t in MODEL["gap_tiers"] if t.get("blocks_work")]
    assert len(blocking) == 1
    assert blocking[0]["id"] == "required_now"


# ── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_closed_contour_asks_no_questions(tmp_path):
    """Если ProductOverview/Status/ROADMAP заполнены — «кто ваш пользователь» не спрашивается."""
    p = tmp_path / "context" / "product"
    p.mkdir(parents=True)
    for f in ("ProductOverview.md", "ProductStatus.md", "UsersAndRoles.md"):
        (p / f).write_text("# есть\n", encoding="utf-8")
    (tmp_path / "ROADMAP.md").write_text("# ROADMAP\n", encoding="utf-8")
    aud = A.audit(tmp_path, A.discover(tmp_path), MODEL)
    row = next(r for r in aud["contours"] if r["contour"] == "product_strategy")
    assert row["state"] == A.VERIFIED
    assert row["questions"] == []
    assert row["needs_human"] is False
    ask = A.question_package(aud, {})
    assert not [q for q in ask["questions"] if q["contour"] == "product_strategy"]


def test_open_contour_does_ask(tmp_path):
    aud = A.audit(tmp_path, A.discover(tmp_path), MODEL)
    ask = A.question_package(aud, {})
    assert [q for q in ask["questions"] if q["contour"] == "product_strategy"]
    assert ask["summary"]


def test_stale_source_of_truth_returns_questions(tmp_path):
    """Устаревший документ отвечает, но неизвестно, на какой год — вопросы возвращаются."""
    p = tmp_path / "context" / "product"
    p.mkdir(parents=True)
    for f in ("ProductOverview.md", "ProductStatus.md"):
        (p / f).write_text("---\nreviewed_at: 2019-01-01\n---\n\n# старое\n", encoding="utf-8")
    (tmp_path / "ROADMAP.md").write_text("# ROADMAP\n", encoding="utf-8")
    aud = A.audit(tmp_path, A.discover(tmp_path), MODEL)
    row = next(r for r in aud["contours"] if r["contour"] == "product_strategy")
    assert row["state"] == "stale"
    assert row["questions"]


def test_question_package_attaches_proposal_when_there_is_ground(tmp_path):
    """Где есть основание — подтвердить дешевле, чем сформулировать."""
    aud = A.audit(tmp_path, A.discover(tmp_path), MODEL)
    rec = {"sensitive_data": {"value": "поля с персональными данными", "status": A.INFERRED,
                              "evidence": ["схемы"]}}
    ask = A.question_package(aud, rec)
    q = next(q for q in ask["questions"] if q["id"] == "sensitive_data")
    assert q["proposal"] and q["proposal"]["status"] == A.INFERRED


def test_gap_plan_separates_blocking_from_later(tmp_path):
    aud = A.audit(tmp_path, A.discover(tmp_path), MODEL)
    gp = A.gap_plan(aud, MODEL)
    assert gp["required_now"]["blocks_work"] is True
    assert gp["opportunistic"]["blocks_work"] is False


def test_run_returns_whole_scenario(tmp_path):
    rep = A.run(tmp_path)
    for key in ("classification", "evidence", "reconstructed", "audit", "gap_plan", "ask"):
        assert key in rep
    assert A.render(rep)
