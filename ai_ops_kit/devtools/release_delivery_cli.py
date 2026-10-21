"""Исполнение контракта поставки Kit через существующий Tool Broker.

Контракт содержит команды адаптеров, а не доступы/токены. Read probes должны быть
безопасными; это обязанность адаптера, не эвристика по имени shell-команды.
CLI подтверждает только поверхность agent. Connector и user_terminal здесь недоступны.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_ops_kit.delivery import record_delivery as release_delivery
from ai_ops_kit.engine import tool_broker
from ai_ops_kit.gates.deploy_readiness import confirmation
from ai_ops_kit.shared import lifecycle_store as receipts
from ai_ops_kit.shared import gitio


def run_contract(root, contract, owner, broker, policy):
    expected = contract["expected"]
    rc, sha, _ = gitio.git(root, "rev-parse", "--verify", "HEAD")
    if rc or sha != expected["sha"]:
        raise release_delivery.ReleaseBlocked("ожидаемый SHA не совпадает с локальным исходником")
    rc_dirty, _, _ = gitio.git(root, "diff", "--quiet", "HEAD")
    rc_new, untracked, _ = gitio.git(root, "ls-files", "--others", "--exclude-standard", "-z")
    if rc_dirty or rc_new or any(p and not p.startswith(".ai/runtime/") for p in untracked.split("\0")):
        raise release_delivery.ReleaseBlocked("исходники не соответствуют чистому SHA; выпуск не начат")
    version = Path(root) / "VERSION"
    if version.exists() and version.read_text().strip() != expected["version"]:
        raise release_delivery.ReleaseBlocked("версия исходника отличается от ожидаемой")
    artifact = Path(root) / contract["artifact"]
    if not artifact.is_file() or "sha256:" + receipts.file_digest(artifact) != expected["artifact_digest"]:
        raise release_delivery.ReleaseBlocked("digest локального артефакта не подтверждён")

    def execute(command):
        return broker.execute({"op": "shell", "command": command}, root, policy)

    def read(command):
        ev = execute(command)
        if not ev.get("allowed") or not ev.get("ok"):
            return {"status": "BLOCKED", "code": ev.get("exit_code")}
        try:
            result = json.loads(ev.get("output_tail", ""))
            return result if isinstance(result, dict) else {"status": "BLOCKED"}
        except ValueError:
            return {"status": "BLOCKED", "code": "invalid_observation"}

    operations = contract["preflight"]
    def probe(surface, operation):
        if surface != "agent":
            return {"status": "BLOCKED", "code": "surface_unavailable"}
        spec = next(s for s in operations if s["surface"] == surface and s["operation"] == operation)
        return read(spec["command"])

    def checks():
        observed = []
        for spec in contract["checks"]:
            if spec.get("receipt"):
                previous = receipts.load(Path(root) / spec["receipt"])
                inputs, _ = receipts.fingerprint(root, spec["command"], receipts.python_context(root),
                                                  scope="local", extra=spec.get("extra"))
                status = "PASS" if receipts.reusable(previous, inputs) else "BLOCKED"
                observed.append({"name": spec["name"], "status": status,
                                 "kind": "local", "source": spec["receipt"], "inputs_digest": receipts.digest(inputs)})
            else:
                evidence = read(spec["command"])
                # CI observer обязан проверить актуальный SHA. Локальный receipt — не CI.
                if evidence.get("sha") != expected["sha"] or evidence.get("name") != spec["name"]:
                    evidence["status"] = "BLOCKED"
                observed.append({**{k: evidence.get(k) for k in ("name", "status", "source", "inputs_digest", "sha")},
                                 "kind": "ci"})
        return observed

    def deploy():
        ev = execute(contract["deploy_command"])
        return ev.get("exit_code") if ev.get("allowed") else None

    return release_delivery.deliver(root, owner=owner, expected=expected, checks=checks,
        recovery=contract["recovery"],
        preflight=lambda: release_delivery.access_preflight(operations, probe), deploy=deploy,
        observe_runtime=lambda: read(contract["runtime_command"]),
        observe_public=lambda: read(contract["public_command"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--owner")
    parser.add_argument("--inspect", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.inspect:
            record = receipts.load(args.inspect)
            status, reason = confirmation(record)
            print(json.dumps({"status": status, "reason": reason}, ensure_ascii=False))
            return 0 if status == "PASS" else 1
        if not args.contract or not args.owner:
            parser.error("нужны --contract и --owner либо --inspect")
        contract = json.loads(args.contract.read_text())
        # Та же ограниченная политика исполнения; исключений для deploy не добавляем.
        policy = tool_broker.sandbox_policy(args.root)
        result = run_contract(args.root.resolve(), contract, args.owner, tool_broker, policy)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 1
    except (OSError, ValueError, KeyError, release_delivery.ReleaseBlocked) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
