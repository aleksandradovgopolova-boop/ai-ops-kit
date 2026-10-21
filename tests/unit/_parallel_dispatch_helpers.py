"""Общие Git fixtures для параллельного dispatch и local availability."""
from ai_ops_kit.engine import parallel_live_dispatch as dsp


def _real_repo(tmp_path, monkeypatch):
    from ai_ops_kit.engine import parallel_live as live
    root = tmp_path / "child"
    root.mkdir()
    live._git(root, "init", "-q", "-b", "main")
    live._git(root, "config", "user.email", "test@example.test")
    live._git(root, "config", "user.name", "Test")
    (root / ".gitignore").write_text("features/\n.ai/\n")
    (root / "seed.txt").write_text("base\n")
    live._git(root, "add", ".")
    live._git(root, "commit", "-qm", "seed")
    live._git(root, "remote", "add", "origin", "https://github.com/example/child.git")
    base = live._git(root, "rev-parse", "HEAD").stdout.strip()
    wg = {"id": "WG", "packages": [
        {"id": "aa", "depends_on": [], "write_scope": ["aa.py"]},
        {"id": "bb", "depends_on": [], "write_scope": ["bb.py"]}]}
    monkeypatch.setattr(dsp, "build_work_graph", lambda *a: (wg, {"aa": "A", "bb": "B"}))
    from ai_ops_kit.gates import evidence_collector
    monkeypatch.setattr(evidence_collector, "collect", lambda *a, **k: {
        "gate_evidence": {"implementation_verification": {"status": "pass"}}, "checks": {},
        "revision": live._git(a[1], "rev-parse", "HEAD").stdout.strip()})
    return root, base, wg


def _real_commit(task, signals, root, **options):
    from ai_ops_kit.engine import parallel_live as live
    pid = options["feature"]
    live._git(root, "checkout", "-q", "-B", f"ai-ops/{pid}")
    (root / f"{pid}.py").write_text(f"VALUE = '{pid}'\n")
    live._git(root, "add", f"{pid}.py")
    live._git(root, "commit", "-qm", pid)
    return {"ready_for_pr": True,
            "commit": {"sha": live._git(root, "rev-parse", "HEAD").stdout.strip()}}
