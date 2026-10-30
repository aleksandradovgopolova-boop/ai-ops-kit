"""Воспроизводимый локальный pipeline, без LLM/сети/стоимости провайдера."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import yaml

from ai_ops_kit.engine import ai_ops_run


LABELS = {"relevant": ["task", "docs/needed.md", "docs/not-selected.md"],
          "irrelevant": ["docs/noise.md"],
          "evidence": "qualification/context_resource/run.py: ручная source-разметка fixture до прогона; не семантическая оценка проекта"}


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True, timeout=15).stdout.strip()


def setup_hybrid(root, cfg):
    (root / "src").mkdir()
    (root / "src/hybrid.py").write_text("# ответ HYBRID_ALLOWED_1403\n")
    (root / "src/denied.py").write_text("# ответ FORBIDDEN_1403_MUST_NOT_REACH_WRITER\n")
    (root / "src/alias.py").symlink_to("DENIED.PY")
    (root / "src/sécret.py").write_text("# ответ FORBIDDEN_1403_MUST_NOT_REACH_WRITER\n")
    (root / "src/unicode-alias.py").symlink_to("SE\u0301CRET.PY")
    (root / ".gitignore").write_text("features/\n.ai/runtime/\n.ai/worktrees/\n__pycache__/\n")
    cfg["context"]["forbidden"] += ["src/denied.py", "src/sécret.py", "labels.json", "docs/noise.md", "docs/not-selected.md"]
    policies = root / ".ai/policies"
    policies.mkdir(parents=True)
    (policies / "access-filter.yaml").write_text(yaml.safe_dump({"id":"fixture-afp", "rules":[
        {"role":"executor", "allowed_classes":["public", "internal"]}]}))
    (policies / "data-classification.yaml").write_text(yaml.safe_dump(
        {"id":"fixture-dcp", "default_class":"internal", "rules":[]}))
    return {"case_alias_exists": (root / "src/alias.py").exists(),
            "unicode_alias_exists": (root / "src/unicode-alias.py").exists()}


def scenario(root, mode):
    root.mkdir(parents=True, exist_ok=False)
    (root / "docs").mkdir()
    (root / "docs/needed.md").write_text("Ответ для результата: LOCAL_CONTEXT_1403\n", encoding="utf-8")
    (root / "docs/noise.md").write_text("История постороннего проекта.\n" * 10, encoding="utf-8")
    (root / "docs/not-selected.md").write_text("Дополнительный критерий, который compiler не выбрал.\n", encoding="utf-8")
    (root / "docs/forbidden.md").write_text("FORBIDDEN_1403_MUST_NOT_REACH_WRITER\n", encoding="utf-8")
    cfg = {"context": {"required": ["docs/needed.md"],
           "optional": ["docs/noise.md", "docs/forbidden.md"],
           "forbidden": ["rules/", "skills", "docs/forbidden.md"]},
           "context_budget": {"run_tokens": 100 if mode == "over-budget" else 20000}}
    hybrid_fixture = setup_hybrid(root, cfg) if mode == "hybrid" else None
    (root / ".ai-ops.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (root / "labels.json").write_text(json.dumps(LABELS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "config", "user.name", "Local qualification")
    git(root, "config", "user.email", "qualification@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture: context resource")
    before = git(root, "rev-parse", "HEAD")
    calls, denied_reads = [], []
    expected_output = "LOCAL_CONTEXT_1403\n" + ("HYBRID_ALLOWED_1403\n" if mode == "hybrid" else "")
    actions = iter([{"op": "write", "path": "src/result.txt", "content": expected_output}, {"done": True}])

    def local_proposer(context):
        text = str(context)
        calls.append({"required_present": "LOCAL_CONTEXT_1403" in text,
                      "forbidden_present": "FORBIDDEN_1403_MUST_NOT_REACH_WRITER" in text,
                      "hybrid_present": "HYBRID_ALLOWED_1403" in text})
        if not calls[-1]["required_present"] or calls[-1]["forbidden_present"]:
            raise RuntimeError("нарушена граница контекста")
        if mode == "hybrid" and not calls[-1]["hybrid_present"]:
            raise RuntimeError("разрешённый hybrid не дошёл до writer")
        return next(actions)

    signals = {"task_type": "QUICK", "size": "small", "risk": "low",
               "affected_areas": ["src"], "context_relevance": LABELS}
    if mode == "hybrid":
        signals.pop("context_relevance")  # разметка v1 не является разметкой новых additions
    read_text = Path.read_text
    forbidden_files = [root / "docs/forbidden.md"]
    if mode == "hybrid":
        forbidden_files += [root / p for p in ("src/denied.py", "src/sécret.py", "labels.json", "docs/noise.md", "docs/not-selected.md")]

    def observed_read(path, *args, **kwargs):
        if path.is_file() and any(path.samefile(f) for f in forbidden_files):
            denied_reads.append(str(path))
        return read_text(path, *args, **kwargs)

    with patch.object(Path, "read_text", observed_read):
        report = ai_ops_run.run("Запиши ответ из docs/needed.md в src/result.txt", signals, root,
            execute=True, feature="context-resource", proposer=local_proposer, context_hybrid=mode == "hybrid")
    artifact = yaml.safe_load((root / "features/context-resource/context-payload.yaml").read_text())
    output = root / ".ai/worktrees/context-resource/src/result.txt"
    observed = output.read_text() if output.is_file() else None
    positive = mode != "over-budget"
    assert (len(calls) == 2 and observed == expected_output) if positive else (not calls and observed is None)
    assert artifact["resource_check"]["ok"] is positive
    assert report.get("overall_status") != "blocked-preflight" if positive else report["overall_status"] == "blocked-preflight"
    assert denied_reads == []
    if mode == "hybrid":
        assert report["context_hybrid"]["mode"] == "hybrid"
        assert report["context_hybrid"]["snapshot_verified"]
        assert "context:" in report["context_hybrid"]["cache_key"]
        assert report["context_hybrid"]["fed_additions"] == ["src/hybrid.py"]
        assert artifact["metrics"]["status"] == "unknown"
    assert git(root, "rev-parse", "HEAD") == before
    return {"scope": "local-pipeline-controlled-proposer", "external_model_calls": 0,
            "mode": mode, "writer_calls": calls, "output": observed,
            "loop": report.get("loop"), "commit": report.get("commit"),
            "overall_status": report.get("overall_status"), "preflight": report.get("preflight"),
            "context": artifact, "context_hybrid": report.get("context_hybrid"),
            "forbidden_read_calls": denied_reads, "hybrid_fixture": hybrid_fixture}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="новый каталог, без перезаписи")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    results = [scenario(args.output / mode, mode) for mode in ("positive", "over-budget", "hybrid")]
    package = Path(__file__).resolve().parents[2]
    sources = ["ai_ops_kit/context/context_compiler.py", "ai_ops_kit/context/context_cost.py",
               "ai_ops_kit/gates/preflight.py", "ai_ops_kit/engine/ai_ops_run_reporting.py",
               "ai_ops_kit/context/context_engine.py", "ai_ops_kit/context/context_hybrid.py",
               "ai_ops_kit/context/repo_graph.py", "ai_ops_kit/context/semantic_lite.py",
               "qualification/context_resource/run.py"]
    evidence = {"source_sha256": {p: hashlib.sha256((package / p).read_bytes()).hexdigest() for p in sources},
                "scenarios": results}
    (args.output / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": str(args.output / "evidence.json"),
                      "results": [{"mode": r["mode"], "writer_calls": len(r["writer_calls"]),
                                   "resource_check": r["context"]["resource_check"],
                                   "metrics": r["context"]["metrics"]} for r in results]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
