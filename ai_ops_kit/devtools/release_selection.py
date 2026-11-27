"""Объяснение состава уже слитого выпуска по работам и целям канонического плана."""
from __future__ import annotations

from collections import defaultdict

from ai_ops_kit.planning import plan_model, plan_validate


def _goal_context(plan, intent):
    goals = plan_model.goals(plan)
    ids = [g["id"] for g in goals]
    valid = (isinstance(plan.get("goals", []), list) and len(goals) == len(plan.get("goals", []))
             and all(isinstance(gid, str) for gid in ids) and len(set(ids)) == len(ids)
             and all(g.get("status") is None or g["status"] in plan_model.GOAL_STATUSES for g in goals))
    ranks = plan_model.goal_priority(plan) if valid else {}
    milestone = plan_model.current_milestone(plan)
    if (not valid or milestone is None or not isinstance(milestone.get("name"), str)
            or plan_validate._milestone_errors(milestone, ids)
            or intent["milestone"] not in (milestone["id"], milestone["name"])):
        return None, ranks
    return {k: milestone[k] for k in ("id", "name", "linked_goals")}, ranks


def explain(plan, intent, work, implementations, deferred):
    """Проекция текущего цикла. Исторические PR доказывают зависимости, но не состав."""
    milestone, ranks = _goal_context(plan, intent)
    merged = {p["pr"] for p in implementations if p["merged_change_observed"]}
    by_issue = defaultdict(set)
    for p in implementations:
        if p["pr"] in merged:
            for issue in p["closing_issues"]:
                by_issue[issue].add(p["pr"])

    active = {w["id"] for w in plan_model.items(plan)}
    rows = []
    mapped = set()
    for wid, w in work.items():
        issue, goal = w.get("issue"), w.get("goal")
        if (not isinstance(wid, str) or (goal is not None and not isinstance(goal, str))
                or any(type(n) is not int or n <= 0 for n in (issue, w.get("pr")) if n is not None)):
            raise ValueError("invalid release work identity")
        prs = set(by_issue.get(issue, ()))
        if w.get("pr") in merged:
            prs.add(w["pr"])
        if wid not in active and not prs and issue not in deferred:
            continue
        mapped.update(prs)
        rank = ranks.get(goal)
        scope = "unknown"
        if milestone and rank is not None:
            scope = "in_milestone" if goal in milestone["linked_goals"] else "outside_milestone"
        reason = "merged_change" if prs else "completed_only"
        if issue in deferred:
            reason = "deferred_for_version"
        rows.append({"work_id": wid, "title": w.get("title") or wid, "issue": issue, "goal": goal,
                     "goal_rank": None if rank is None else rank + 1, "scope": scope,
                     "reason": reason, "merged_prs": sorted(prs)})

    # Отложить можно и issue, ещё не связанное с работой плана.
    unknown_deferred = sorted(set(deferred) - {row["issue"] for row in rows})
    rows.sort(key=lambda row: (row["scope"] != "in_milestone", row["goal_rank"] or float("inf"),
                               row["work_id"]))
    milestone_prs = list(dict.fromkeys(pr for row in rows
                        if row["scope"] == "in_milestone" and row["reason"] == "merged_change"
                        for pr in row["merged_prs"]))
    unmapped = merged - mapped
    return {"prioritized_milestone_prs": milestone_prs if milestone else None,
            "release_milestone": intent["milestone"], "milestone": milestone,
            "candidate_limit": intent["candidate_limit"], "work": rows,
            "unmapped_prs": [{"pr": p["pr"], "closing_issues": p["closing_issues"], "reason": "merged_change",
                              "scope": "unknown", "goal_rank": None} for p in implementations
                             if p["pr"] in unmapped],
            "unmapped_deferred_issues": unknown_deferred}
