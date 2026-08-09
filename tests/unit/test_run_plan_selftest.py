"""Селфтест run_plan, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from run_plan import (  # noqa: F401 — имена, которые использует тело
    build_plan,
    validate_plan,
    validate_tracks,
    validate_workitem_id,
)


@pytest.mark.slow
def test_run_plan_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    expect("tracks.yaml целостен (гейты резолвятся)", validate_tracks() == [])

    # продуктовая фича: UI + измеримое поведение + граница безопасности
    sig = {"task_type": "PRODUCT", "risk": "medium",
           "available_providers": ["anthropic"], "available_runtimes": ["claude-code"],
           "ui_changed": True, "measurable_behavior": True, "security_surface_changed": True,
           "user_facing_change": True, "task_text": "фильтр по статусу в каталоге заказов"}
    p = build_plan(sig)
    req = {t["track"] for t in p["required_tracks"]}
    expect("PRODUCT + UI/analytics/security -> треки VISUAL/ANALYTICS/SECURITY/DOCUMENTATION",
           {"VISUAL", "ANALYTICS", "SECURITY", "DOCUMENTATION"} <= req)
    # аудит: PRODUCT сам по себе не имел ux/analytics гейтов — трек их добавил
    expect("гейты треков добавлены к base (ux_review/analytics_design_readiness/security)",
           {"ux_review", "analytics_design_readiness", "security"} <= set(p["gates"]))
    expect("base_workflow = PRODUCT", p["base_workflow"] == "PRODUCT")
    expect("plan валиден", validate_plan(p) == [])

    # пропуски объяснены: без UI VISUAL уходит в skipped с причиной
    sig2 = dict(sig); sig2["ui_changed"] = False
    p2 = build_plan(sig2)
    vis_skip = next((t for t in p2["skipped_tracks"] if t["track"] == "VISUAL"), None)
    expect("нет UI -> VISUAL в skipped с причиной", vis_skip and "UI" in vis_skip["reason"])
    expect("skipped VISUAL -> его гейтов нет в наборе", "ux_review" not in p2["gates"])

    # conditional: AI-компонент -> AI в conditional_tracks
    sig3 = dict(sig); sig3["ai_component"] = True
    p3 = build_plan(sig3)
    expect("ai_component -> AI в conditional_tracks",
           any(t["track"] == "AI" for t in p3["conditional_tracks"]))
    expect("AI-трек добавил ai_red_team", "ai_red_team" in p3["gates"])

    # P1.1: валидация workitem_id (доходит до путей)
    expect("валидный wid принят", validate_workitem_id("wi-abc_123.v2") == "wi-abc_123.v2")
    expect("wid принят в build_plan", build_plan(sig, "feat-42")["workitem_id"] == "feat-42")
    for bad in ["../evil", "a/b", "/abs", "..", ".hidden", "UPPER", "x" * 65, "", "a b", "a\\b"]:
        try:
            validate_workitem_id(bad)
            expect(f"невалидный wid отвергнут: {bad!r}", False)
        except ValueError:
            expect(f"невалидный wid отвергнут: {bad!r}", True)

    assert ok, "перенесённый селфтест run_plan: см. строки FAIL в выводе"
