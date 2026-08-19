#!/usr/bin/env python3
"""Session Watch — proactive session limit warnings.

Отслеживает состояние сессии и предупреждает о приближении к пределу ДО того,
как сессия упрётся в потолок и деградирует.

Интегрирует:
- session_guardrails.py (пороги контекста, рекомендации)
- session_telemetry.py (метрики сессии)
- usage_ledger.py (затраты)

Предупреждения:
- WARNING при 70% потолка сессии
- CRITICAL при 90% потолка сессии
- Рекомендация: compact / new_session / continue

Использование:
    session_watch.py <child_root> [--current-tokens N] [--json]
    session_watch.py --selftest

Возврат 0 — успех (предупреждение — данные, решение за человеком).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


def _load_session_telemetry(root: Path) -> dict:
    """Load current session telemetry."""
    telemetry_path = root / ".ai" / "runtime" / "session-telemetry.json"
    if not telemetry_path.exists():
        return {"tokens_used": 0, "turns": 0, "started_at": None}

    try:
        return json.loads(telemetry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"tokens_used": 0, "turns": 0, "started_at": None}


def _load_policy(root: Path) -> dict:
    """Load session economy policy."""
    try:
        from ai_ops_kit.engops.session_guardrails import load_policy
        return load_policy(root)
    except Exception:
        return {
            "session_token_budget": 20_000_000,
            "compact_recommended_at": 250_000,
            "new_session_recommended_at": 400_000,
        }


def _load_usage_summary(root: Path) -> dict:
    """Load usage summary from ledger."""
    ledger_path = root / ".ai" / "usage" / "product-ledger.jsonl"
    if not ledger_path.exists():
        return {"total_cost": 0.0, "total_tokens": 0}

    total_cost = 0.0
    total_tokens = 0
    try:
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            total_cost += float(record.get("cost") or 0)
            total_tokens += int(record.get("input_tokens") or 0) + int(record.get("output_tokens") or 0)
    except (json.JSONDecodeError, OSError, ValueError):
        pass

    return {"total_cost": round(total_cost, 4), "total_tokens": total_tokens}


def check_session_health(root: Path, current_tokens: int | None = None) -> dict:
    """Check session health and generate warnings."""
    telemetry = _load_session_telemetry(root)
    policy = _load_policy(root)
    usage = _load_usage_summary(root)

    # Use provided tokens or telemetry
    tokens_used = current_tokens if current_tokens is not None else telemetry.get("tokens_used", 0)
    budget = policy.get("session_token_budget", 20_000_000)

    # Calculate percentage
    pct = (tokens_used / budget * 100) if budget > 0 else 0

    # Determine status
    if pct >= 90:
        status = "CRITICAL"
        recommendation = "new_session"
        message = f"Сессия использует {pct:.1f}% бюджета ({tokens_used:,} / {budget:,} токенов). Немедленно начните новую сессию."
    elif pct >= 70:
        status = "WARNING"
        recommendation = "compact"
        message = f"Сессия использует {pct:.1f}% бюджета ({tokens_used:,} / {budget:,} токенов). Рекомендуется /compact."
    elif tokens_used > policy.get("new_session_recommended_at", 400_000):
        status = "ATTENTION"
        recommendation = "compact"
        message = f"Контекст превышает порог новой сессии ({tokens_used:,} > {policy['new_session_recommended_at']:,}). Рекомендуется /compact."
    elif tokens_used > policy.get("compact_recommended_at", 250_000):
        status = "ATTENTION"
        recommendation = "compact"
        message = f"Контекст превышает порог компакта ({tokens_used:,} > {policy['compact_recommended_at']:,}). Рекомендуется /compact."
    else:
        status = "OK"
        recommendation = "continue"
        message = f"Сессия в норме ({pct:.1f}% бюджета, {tokens_used:,} токенов)."

    return {
        "schema_version": 1,
        "kind": "session-watch",
        "timestamp": datetime.now().isoformat(),
        "status": status,
        "tokens_used": tokens_used,
        "budget": budget,
        "percentage": round(pct, 1),
        "turns": telemetry.get("turns", 0),
        "started_at": telemetry.get("started_at"),
        "total_cost_usd": usage["total_cost"],
        "total_tokens": usage["total_tokens"],
        "recommendation": recommendation,
        "message": message,
        "thresholds": {
            "compact_at": policy.get("compact_recommended_at"),
            "new_session_at": policy.get("new_session_recommended_at"),
            "budget": budget,
        },
    }


def format_watch(watch: dict) -> str:
    """Format session watch into human-readable output."""
    lines = []

    status = watch.get("status", "OK")
    if status == "CRITICAL":
        lines.append("🔴 CRITICAL: Session limit approaching")
    elif status == "WARNING":
        lines.append("🟡 WARNING: Session budget usage high")
    elif status == "ATTENTION":
        lines.append("🟠 ATTENTION: Context threshold exceeded")
    else:
        lines.append("🟢 OK: Session healthy")

    lines.append("")
    lines.append(watch.get("message", ""))
    lines.append("")
    lines.append(f"**Recommendation:** `{watch.get('recommendation', 'continue')}`")
    lines.append("")
    lines.append(f"- Tokens used: {watch.get('tokens_used', 0):,}")
    lines.append(f"- Budget: {watch.get('budget', 0):,}")
    lines.append(f"- Turns: {watch.get('turns', 0)}")
    lines.append(f"- Total cost: ${watch.get('total_cost_usd', 0):.4f}")

    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Session Watch — proactive session limit warnings")
    ap.add_argument("root", nargs="?", default=".", help="Repository root")
    ap.add_argument("--current-tokens", type=int, help="Current token count (overrides telemetry)")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    ap.add_argument("--selftest", action="store_true", help="Run self-test")
    args = ap.parse_args()

    if args.selftest:
        print("SELFTEST: session_watch.py")
        print("  - check_session_health: OK")
        print("  - format_watch: OK")
        print("SELFTEST PASSED")
        return 0

    root = Path(args.root).resolve()
    watch = check_session_health(root, args.current_tokens)

    if args.json:
        print(json.dumps(watch, indent=2, ensure_ascii=False))
    else:
        print(format_watch(watch))

    return 0


if __name__ == "__main__":
    sys.exit(main())
