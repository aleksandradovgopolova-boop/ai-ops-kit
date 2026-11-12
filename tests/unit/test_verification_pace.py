"""#1514: успевает ли проверка за генерацией — из Git и реестров потолков, «не измерено» вместо нуля."""
from datetime import datetime, timezone
import subprocess

import pytest

from ai_ops_kit.intelligence import product_scorecard as vp
from ai_ops_kit.ui import presenter_graph

NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)


def _git(root, *args, when="2026-11-01T12:00:00Z"):
    env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when, "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, env=env, timeout=60)


def _commit(root, files, when):
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(root, "add", "-A", when=when)
    _git(root, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "c", when=when)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _commit(tmp_path, {"app/old.py": "x\n" * 50}, "2026-01-01T12:00:00Z")         # вне окна
    _commit(tmp_path, {"app/core.py": "a\n" * 10, "tests/test_core.py": "t\n" * 4,
                       "web/ui.test.ts": "u\n" * 1, "README.md": "doc\n" * 99,
                       ".ai/managed/ai_ops_kit/x.py": "k\n" * 500, "web/node_modules/l/i.js": "n\n" * 300},
            "2026-11-01T12:00:00Z")
    return tmp_path


def _parts(result):
    return {p["id"]: p for p in result["parts"]}


def test_growth_and_tests_counted_only_inside_window(repo):
    parts = _parts(vp.verification_pace(repo, now=NOW))
    assert parts["code_growth"]["value"] == 10 and "коммитов 1" in parts["code_growth"]["detail"]
    pace = parts["tests_keep_pace"]
    assert pace["measured"] and (pace["numerator"], pace["denominator"]) == (5, 10)


def test_unknown_is_never_zero(tmp_path):
    result = vp.verification_pace(tmp_path, now=NOW)                    # не Git-репозиторий
    parts = _parts(result)
    assert not result["measured"]
    assert all(not p["measured"] and p["reason"] and p["value"] is None for p in parts.values())


def test_no_code_growth_is_not_measured_ratio(tmp_path):
    _git(tmp_path, "init", "-q")
    _commit(tmp_path, {"README.md": "doc\n"}, "2026-11-01T12:00:00Z")
    parts = _parts(vp.verification_pace(tmp_path, now=NOW))
    assert parts["code_growth"]["value"] == 0
    assert not parts["tests_keep_pace"]["measured"]


def test_ceiling_raises_inside_window_and_broken_ledger_is_unknown(repo):
    (repo / "quality").mkdir()
    ledger = repo / "quality" / "delivery-budget.yaml"
    ledger.write_text("raises:\n  - at: '2026-10-01'\n  - at: '2026-11-02'\n  - at: '2026-01-01'\n"
                      "  - what: no-date\n", encoding="utf-8")
    assert _parts(vp.verification_pace(repo, now=NOW))["ceiling_raises"]["value"] == 2
    ledger.write_text("raises: [unclosed", encoding="utf-8")
    assert not _parts(vp.verification_pace(repo, now=NOW))["ceiling_raises"]["measured"]


def test_unwired_and_review_are_honest(repo):
    parts = _parts(vp.verification_pace(repo, now=NOW))
    assert not parts["unwired"]["measured"] and not parts["independent_review_share"]["measured"]
    (repo / "docs").mkdir()
    (repo / "docs" / "capability-map.md").write_text(
        "| `ai_ops_kit/a.py` | built≠wired | x |\n| `ai_ops_kit/b.py` | built≠wired | y |\n"
        "| `./ai-ops c` | built | z |\n", encoding="utf-8")
    assert _parts(vp.verification_pace(repo, now=NOW))["unwired"]["value"] == 2


@pytest.mark.parametrize("path,expected", [("tests/test_a.py", True), ("src/a_test.go", True),
                                           ("web/a.spec.ts", True), ("pkg/__tests__/x.js", True),
                                           ("src/contest.py", False), ("src/testing_utils.py", False)])
def test_test_path_detection(path, expected):
    assert vp.is_test_path(path) is expected


def test_scorecard_shows_pace_as_a_line_not_a_gate(repo):
    (repo / "docs").mkdir()
    (repo / "docs" / "capability-map.md").write_text("| `ai_ops_kit/x.py` | built≠wired | x |\n", encoding="utf-8")
    card = vp.build_scorecard(repo)
    assert card["verification_pace"]["id"] == "verification_pace"
    assert card["unmeasured_count"] == sum(1 for m in card["metrics"] if not m["measured"])   # не входит в пятёрку
    text = presenter_graph.from_scorecard(card)["summary"]
    assert "Построено, но не подключено: 1 (модулей без входа)" in text
    assert "Доля изменений с независимым ИИ-ревью: не измерено" in text
