"""Воспроизводимый локальный pipeline, без LLM/сети/стоимости провайдера."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import yaml

from ai_ops_kit.engine import ai_ops_run


LABELS = {"relevant": ["task", "docs/needed.md", "docs/not-selected.md"],
          "irrelevant": ["docs/noise.md"],
          "evidence": "qualification/context_resource/run.py: ручная source-разметка fixture до прогона; не семантическая оценка проекта"}


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True, timeout=15).stdout.strip()


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
           "context_budget": {"run_tokens": 20000 if mode == "positive" else 100}}
    (root / ".ai-ops.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (root / "labels.json").write_text(json.dumps(LABELS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "config", "user.name", "Local qualification")
    git(root, "config", "user.email", "qualification@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture: context resource")
    before = git(root, "rev-parse", "HEAD")
    calls = []
    actions = iter([{"op": "write", "path": "src/result.txt", "content": "LOCAL_CONTEXT_1403\n"}, {"done": True}])

    def local_proposer(context):
        text = str(context)
        calls.append({"required_present": "LOCAL_CONTEXT_1403" in text,
                      "forbidden_present": "FORBIDDEN_1403_MUST_NOT_REACH_WRITER" in text})
        if not calls[-1]["required_present"] or calls[-1]["forbidden_present"]:
            raise RuntimeError("нарушена граница контекста")
        return next(actions)

    signals = {"task_type": "QUICK", "size": "small", "risk": "low",
               "affected_areas": ["src"], "context_relevance": LABELS}
    report = ai_ops_run.run("Запиши ответ из docs/needed.md в src/result.txt", signals, root,
                            execute=True, feature="context-resource", proposer=local_proposer)
    artifact = yaml.safe_load((root / "features/context-resource/context-payload.yaml").read_text())
    output = root / ".ai/worktrees/context-resource/src/result.txt"
    observed = output.read_text() if output.is_file() else None
    positive = mode == "positive"
    assert (len(calls) == 2 and observed == "LOCAL_CONTEXT_1403\n") if positive else (not calls and observed is None)
    assert artifact["resource_check"]["ok"] is positive
    assert report.get("overall_status") != "blocked-preflight" if positive else report["overall_status"] == "blocked-preflight"
    assert git(root, "rev-parse", "HEAD") == before
    return {"scope": "local-pipeline-controlled-proposer", "external_model_calls": 0,
            "mode": mode, "writer_calls": calls, "output": observed,
            "loop": report.get("loop"), "commit": report.get("commit"),
            "overall_status": report.get("overall_status"), "preflight": report.get("preflight"),
            "context": artifact}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="новый каталог, без перезаписи")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    results = [scenario(args.output / mode, mode) for mode in ("positive", "over-budget")]
    package = Path(__file__).resolve().parents[2]
    sources = ["ai_ops_kit/context/context_compiler.py", "ai_ops_kit/context/context_cost.py",
               "ai_ops_kit/gates/preflight.py", "ai_ops_kit/engine/ai_ops_run_reporting.py",
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
