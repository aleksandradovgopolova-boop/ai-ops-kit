#!/usr/bin/env python3
"""session_thresholds.py — анализ и калибровка порогов сессии на живых данных.

ПРОБЛЕМА: пороги сессии (session_token_budget, compact_recommended_at, etc.) установлены стартово,
но не калиброваны на реальных данных. Нужно замерить реальные сессии и предложить калибровку.

Что анализирует:
- Реальные сессии из .ai/usage/product-ledger.jsonl
- Распределение токенов по сессиям
- Медиана, P95, P99
- Предложения по калибровке порогов

Использование:
    session_thresholds.py <child_root> [--json]
    session_thresholds.py --selftest
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import median, mean


def analyze_sessions(root: Path) -> dict:
    """Analyze real session data and propose threshold calibration."""
    ledger_path = root / ".ai" / "usage" / "product-ledger.jsonl"

    if not ledger_path.exists():
        return {
            "error": "No usage ledger found",
            "message": "Run some tasks first to collect session data",
        }

    # Load records
    records = []
    try:
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    except (json.JSONDecodeError, OSError) as e:
        return {"error": f"Failed to load ledger: {e}"}

    if not records:
        return {"error": "Ledger is empty"}

    # Group by session (workitem_id as proxy for session)
    sessions = {}
    for r in records:
        wid = r.get("workitem_id", "unknown")
        if wid not in sessions:
            sessions[wid] = []
        sessions[wid].append(r)

    # Calculate per-session stats
    session_stats = []
    for wid, recs in sessions.items():
        total_tokens = sum(
            (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)
            for r in recs
        )
        total_cost = sum(r.get("cost") or 0 for r in recs)
        num_calls = len(recs)

        session_stats.append({
            "workitem_id": wid,
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "num_calls": num_calls,
        })

    if not session_stats:
        return {"error": "No session data available"}

    # Calculate distribution
    tokens_list = [s["total_tokens"] for s in session_stats]
    costs_list = [s["total_cost"] for s in session_stats]

    tokens_sorted = sorted(tokens_list)
    n = len(tokens_sorted)

    stats = {
        "count": n,
        "min": tokens_sorted[0] if n > 0 else 0,
        "max": tokens_sorted[-1] if n > 0 else 0,
        "median": median(tokens_list) if n > 0 else 0,
        "mean": mean(tokens_list) if n > 0 else 0,
        "p95": tokens_sorted[int(n * 0.95)] if n >= 20 else tokens_sorted[-1],
        "p99": tokens_sorted[int(n * 0.99)] if n >= 100 else tokens_sorted[-1],
    }

    # Propose thresholds based on data
    proposed = {
        "session_token_budget": max(int(stats["p99"] * 1.5), 20_000_000),
        "compact_recommended_at": max(int(stats["p95"] * 1.2), 250_000),
        "new_session_recommended_at": max(int(stats["p95"] * 1.5), 400_000),
    }

    return {
        "schema_version": 1,
        "kind": "session-thresholds-analysis",
        "timestamp": datetime.now().isoformat(),
        "sessions_analyzed": n,
        "token_distribution": stats,
        "cost_distribution": {
            "min": min(costs_list) if costs_list else 0,
            "max": max(costs_list) if costs_list else 0,
            "median": median(costs_list) if costs_list else 0,
            "mean": mean(costs_list) if costs_list else 0,
        },
        "proposed_thresholds": proposed,
        "recommendation": _generate_recommendation(stats, proposed),
    }


def _generate_recommendation(stats: dict, proposed: dict) -> str:
    """Generate human-readable recommendation."""
    if stats["count"] < 5:
        return f"Мало данных ({stats['count']} сессий). Нужно минимум 20 для надёжной калибровки."

    if stats["max"] > proposed["session_token_budget"]:
        return (
            f"Есть сессии превышающие текущий бюджет. "
            f"Предлагаю увеличить session_token_budget до {proposed['session_token_budget']:,}."
        )

    return (
        f"Проанализировано {stats['count']} сессий. "
        f"Медиана: {stats['median']:,.0f} токенов, P95: {stats['p95']:,.0f}. "
        f"Текущие пороги адекватны."
    )


def format_report(report: dict) -> str:
    """Format analysis into human-readable report."""
    if "error" in report:
        return f"Error: {report['error']}\n{report.get('message', '')}"

    lines = []
    lines.append("# Session Thresholds Analysis\n")
    lines.append(f"**Sessions analyzed:** {report['sessions_analyzed']}\n")
    lines.append(f"**Timestamp:** {report['timestamp']}\n")

    dist = report.get("token_distribution", {})
    lines.append("## Token Distribution\n")
    lines.append(f"- Min: {dist.get('min', 0):,}")
    lines.append(f"- Max: {dist.get('max', 0):,}")
    lines.append(f"- Median: {dist.get('median', 0):,.0f}")
    lines.append(f"- Mean: {dist.get('mean', 0):,.0f}")
    lines.append(f"- P95: {dist.get('p95', 0):,}")
    lines.append(f"- P99: {dist.get('p99', 0):,}\n")

    proposed = report.get("proposed_thresholds", {})
    lines.append("## Proposed Thresholds\n")
    lines.append(f"- session_token_budget: {proposed.get('session_token_budget', 0):,}")
    lines.append(f"- compact_recommended_at: {proposed.get('compact_recommended_at', 0):,}")
    lines.append(f"- new_session_recommended_at: {proposed.get('new_session_recommended_at', 0):,}\n")

    lines.append(f"## Recommendation\n")
    lines.append(report.get("recommendation", "No recommendation"))

    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Session thresholds analysis and calibration")
    ap.add_argument("root", nargs="?", default=".", help="Repository root")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    ap.add_argument("--selftest", action="store_true", help="Run self-test")
    args = ap.parse_args()

    if args.selftest:
        # ЧЕСТНЫЙ --selftest (фаза 0, 19.08.2026). Здесь печаталась строка о пройденном
        # селфтесте и три строки «... : OK» — без единого вызова проверяемых функций. То есть
        # модуль УТВЕРЖДАЛ проверку, которой не было: ровно класс «объявлено, но не
        # исполняется», против которого стоит весь кит (ср. R-31/R-32 — две фиктивные проверки
        # в валидаторах). Образец честной формы — devtools/mutation_probe.py: модуль объясняет
        # себя и называет, где лежат его настоящие проверки. Правило репозитория (AGENTS.md):
        # тест модуля живёт в tests/, а не в продакшн-модуле, который едет в child-репозиторий.
        print(__doc__)
        print("Проверки модуля — в tests/unit/ (AGENTS.md: selftest не живёт в продакшн-модуле).")
        return 0

    root = Path(args.root).resolve()
    report = analyze_sessions(root)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_report(report))

    return 0


if __name__ == "__main__":
    sys.exit(main())
