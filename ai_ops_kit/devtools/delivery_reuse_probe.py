"""Воспроизводимый offline fixture: измеряет исполнения, не скорость продуктового deploy.

Реальные subprocess static/build/publish пишут следы в изолированном временном репозитории.
Runtime/public — fixture-файлы, не внешняя платформа. Использует текущие receipts/broker/delivery.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import tempfile
from pathlib import Path

from ai_ops_kit.delivery import record_delivery as release_delivery
from ai_ops_kit.engine import tool_broker
from ai_ops_kit.shared import lifecycle_store as vr


def run_example(root):
    root = Path(root)
    subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=15)
    (root / "source.py").write_text("value = 42\n")
    runtime = root / ".ai/runtime"
    runtime.mkdir(parents=True)
    policy = tool_broker.sandbox_policy(root)
    context = vr.python_context(root, isolated_stdlib=True)
    if not context.get("complete"):
        raise RuntimeError("fixture toolchain непроверяем: замер не выполнен")
    # Fixture сознательно НЕ меняет внешние зависимости/среду на протяжении измерения.
    def command(body):
        # Флаг -I -S запрещает ambient packages/.pth/PYTHONPATH: адаптер только stdlib.
        return shlex.join(["python3", "-I", "-S", "-c", body])

    commands = {}
    for name, body in {
        "static": "compile(Path('source.py').read_text(), 'source.py', 'exec')",
        "build": "Path('.ai/runtime/artifact').write_bytes(Path('source.py').read_bytes())",
    }.items():
        commands[name] = command("from pathlib import Path; " + body + "; "
            f"p=Path('.ai/runtime/{name}-count'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')")

    def execute(cmd):
        ev = tool_broker.execute({"op": "shell", "command": cmd}, root, policy)
        return {"status": "PASS" if ev.get("ok") else "BLOCKED" if not ev.get("allowed") else "FAIL",
                "exit_code": ev.get("exit_code")}

    for _ in ("draft", "ready_for_review", "release"):
        for cmd in commands.values():
            assert execute(cmd)["status"] == "PASS"
    baseline = sum(int((runtime / f"{name}-count").read_text()) for name in commands)
    for name in commands:
        (runtime / f"{name}-count").unlink()
    requested, reused = 0, 0
    for _ in ("draft", "ready_for_review", "release"):
        for name, cmd in commands.items():
            receipt = vr.run(root, name, cmd, lambda cmd=cmd: execute(cmd), lambda: context)
            if receipt["status"] != "PASS":
                raise RuntimeError("fixture check не прошёл")
            requested += 1
            reused += int(receipt["reused"])
    executions = sum(int((runtime / f"{name}-count").read_text()) for name in commands)
    expected = {"version": "fixture-1.0.0", "sha": "a" * 40, "environment": "offline-fixture",
                "artifact_digest": "sha256:" + vr.file_digest(runtime / "artifact")}

    def checks():
        result = []
        for name, cmd in commands.items():
            receipt = vr.run(root, name, cmd, lambda cmd=cmd: execute(cmd), lambda: context)
            result.append({"name": name, "status": receipt["status"], "source": receipt["source"],
                           "inputs_digest": vr.digest(receipt["inputs"])})
        return result

    publish = command("from pathlib import Path; "
        f"Path('.ai/runtime/published.json').write_text({json.dumps(expected)!r}); "
        "p=Path('.ai/runtime/deploy-count'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')")

    def observe(source):
        actual = json.loads((runtime / "published.json").read_text())
        scenario = (runtime / "artifact").read_bytes() == (root / "source.py").read_bytes()
        return {**actual, "status": "PASS" if scenario else "FAIL", "source": source}

    kwargs = {"owner": "fixture-release-owner", "expected": expected, "checks": checks,
              "recovery": {"procedure": "Сверить fixture-файлы и вручную восстановить известный артефакт.",
                           "automatic_rollback": False},
              "preflight": lambda: release_delivery.access_preflight(
                  [{"surface": "agent", "operation": "read-fixture"}],
                  lambda *_: {"status": "PASS", "code": "fixture_readable"}),
              "deploy": lambda: execute(publish)["exit_code"],
              "observe_runtime": lambda: observe("fixture:runtime-file"),
              "observe_public": lambda: observe("fixture:public-file")}
    first = release_delivery.deliver(root, **kwargs)
    second = release_delivery.deliver(root, **kwargs)
    saved_record = json.loads(Path(second["path"]).read_text())
    embedded = {}
    for check in saved_record["checks"]:
        source = Path(check["source"])
        embedded[source.name] = vr.load(source)
        check["source"] = "embedded-receipt:" + source.name
    return {"scope": "offline-fixture-only", "requested_checks": requested,
            "baseline_executions": baseline, "executions_with_reuse": executions,
            "reused_results": reused, "avoided_executions": baseline - executions,
            "deploy_executions": int((runtime / "deploy-count").read_text()),
            "release_status": first["status"], "repeat_action": second["action"],
            "repeat_status": second["status"], "release_record": saved_record, "check_receipts": embedded,
            "external_ci_verified": False, "external_public_verified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="ai-ops-delivery-fixture-") as directory:
        result = run_example(Path(directory))
    if args.output:
        vr.atomic_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["release_status"] == result["repeat_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
