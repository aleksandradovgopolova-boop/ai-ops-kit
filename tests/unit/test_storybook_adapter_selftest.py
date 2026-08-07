"""Селфтест storybook_adapter, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from storybook_adapter import (  # noqa: F401 — имена, которые использует тело
    Path,
    _matches_changed,
    _write,
    build_bundle,
    evidence_for_gate,
    reuse_violations,
)


@pytest.mark.slow
def test_storybook_adapter_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and bool(cond)

    # (A) полный fixture: Storybook index + все артефакты -----------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root, "storybook-static/index.json", {"v": 5, "entries": {
            "components-metriccard--default": {"type": "story", "id": "components-metriccard--default",
                "title": "Components/MetricCard", "name": "Default", "importPath": "./src/MetricCard.tsx"},
            "components-metriccard--loading": {"type": "story", "id": "components-metriccard--loading",
                "title": "Components/MetricCard", "name": "Loading", "importPath": "./src/MetricCard.tsx"},
            "components-metriccard--error": {"type": "story", "id": "components-metriccard--error",
                "title": "Components/MetricCard", "name": "Error", "importPath": "./src/MetricCard.tsx"},
            "docs-intro": {"type": "docs", "id": "docs-intro", "title": "Intro"}}})
        _write(root, ".ai/ui-evidence/interaction.json", {"status": "pass", "total": 5, "passed": 5})
        _write(root, ".ai/ui-evidence/a11y.json", {"blocking_violations": 0, "total_violations": 2})
        _write(root, ".ai/ui-evidence/visual.json", {"status": "pass", "changed": 0})
        _write(root, ".ai/ui-evidence/design-system.json",
               {"reused_components": ["MetricCard"], "new_components": ["DashboardViewport"],
                "new_components_justified": True})
        b = build_bundle(root, commit_sha="abc1234", changed_files=["src/MetricCard.tsx"])

        expect("storybook detected + build pass + docs-entry не считается историей",
               b["storybook"]["detected"] and b["storybook"]["build_status"] == "pass"
               and b["storybook"]["story_count"] == 3)
        expect("affected component из changed importPath", b["affected_components"] == ["Components/MetricCard"])
        expect("state_coverage: default/loading/error покрыты, empty отсутствует -> incomplete",
               b["state_coverage"]["states"]["default"] and b["state_coverage"]["states"]["error"]
               and not b["state_coverage"]["states"]["empty"]
               and b["state_coverage"]["missing"] == ["empty"] and b["state_coverage"]["complete"] is False)
        expect("interaction pass 5/5", b["interaction_tests"] == {"status": "pass", "total": 5, "passed": 5})
        expect("a11y: 0 blocking -> pass", b["accessibility"]["status"] == "pass"
               and b["accessibility"]["blocking_violations"] == 0)
        expect("design_system: новый компонент обоснован -> pass",
               b["design_system"]["status"] == "pass" and b["design_system"]["new_components"] == ["DashboardViewport"])
        expect("provenance перечисляет использованные артефакты", len(b["generated_from"]) >= 4)

        eg = evidence_for_gate(b)
        expect("evidence_for_gate: visual детерминированно pass, без остаточного ревью",
               eg["visual_regression"]["deterministic_status"] == "pass"
               and eg["visual_regression"]["residual_review"] is False)
        expect("evidence_for_gate: accessibility авто-pass, но остаётся семантическое ревью (hybrid)",
               eg["accessibility_review"]["deterministic_status"] == "pass"
               and eg["accessibility_review"]["residual_review"] is True)
        expect("evidence_for_gate: ux не закрыт детерминированно (empty state missing)",
               eg["ux_review"]["deterministic_status"] == "fail")

    # (B) нет артефактов вовсе -> честный not_run/absent, НЕ ложное 'чисто' -----------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        b = build_bundle(root, commit_sha=None)
        expect("нет Storybook -> detected False, build_status absent",
               b["storybook"]["detected"] is False and b["storybook"]["build_status"] == "absent")
        expect("нет артефактов -> все секции not_run (не выдаём отсутствие за чистоту)",
               b["interaction_tests"]["status"] == "not_run"
               and b["accessibility"]["status"] == "not_run"
               and b["visual_regression"]["status"] == "not_run"
               and b["design_system"]["status"] == "not_run")
        eg = evidence_for_gate(b)
        expect("evidence_for_gate на пустом bundle: везде not_run (нет детерминированного закрытия)",
               all(v["deterministic_status"] == "not_run" for v in eg.values()))

    # (C) сырые форматы: axe raw + vitest raw нормализуются ----------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root, ".storybook/main.js", {})   # конфиг есть, index нет -> build fail
        _write(root, "test-results/vitest.json",
               {"numTotalTests": 4, "numFailedTests": 1, "numPassedTests": 3})
        _write(root, "test-results/axe.json",
               {"violations": [{"impact": "critical"}, {"impact": "minor"}, {"impact": "serious"}]})
        _write(root, "test-results/visual.json", {"changed": 2})
        b = build_bundle(root)
        expect("Storybook config без index -> build fail", b["storybook"]["build_status"] == "fail")
        expect("vitest raw -> fail 3/4", b["interaction_tests"] == {"status": "fail", "total": 4, "passed": 3})
        expect("axe raw -> 2 blocking (critical+serious) из 3 -> fail",
               b["accessibility"]["status"] == "fail" and b["accessibility"]["blocking_violations"] == 2
               and b["accessibility"]["total_violations"] == 3)
        expect("visual changed>0 -> fail", b["visual_regression"] == {"status": "fail", "changed": 2})

    # (D) новый компонент БЕЗ обоснования -> design_system fail ------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root, ".ai/ui-evidence/design-system.json",
               {"reused_components": [], "new_components": ["AdHocButton"],
                "new_components_justified": False})
        b = build_bundle(root)
        expect("design_system: новый компонент без обоснования -> fail",
               b["design_system"]["status"] == "fail")

    # (F) v3.1.9 EXACT-SHA BINDING — три обязательных отрицательных теста (trust-фикс) --------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # evidence собрано на СТАРОМ SHA (meta.commit_sha=OLD), всё pass
        _write(root, ".ai/ui-evidence/meta.json", {"commit_sha": "OLDSHA"})
        _write(root, "storybook-static/index.json", {"v": 5, "entries": {
            "c--default": {"type": "story", "id": "c--default", "title": "C", "name": "Default",
                           "importPath": "./src/Card.tsx"},
            "c--loading": {"type": "story", "id": "c--loading", "title": "C", "name": "Loading",
                           "importPath": "./src/Card.tsx"},
            "c--empty": {"type": "story", "id": "c--empty", "title": "C", "name": "Empty",
                         "importPath": "./src/Card.tsx"},
            "c--error": {"type": "story", "id": "c--error", "title": "C", "name": "Error",
                         "importPath": "./src/Card.tsx"}}})
        _write(root, ".ai/ui-evidence/interaction.json", {"status": "pass", "total": 2, "passed": 2})
        _write(root, ".ai/ui-evidence/a11y.json", {"blocking_violations": 0})
        _write(root, ".ai/ui-evidence/visual.json", {"status": "pass", "changed": 0})
        b_old = build_bundle(root, changed_files=["src/Card.tsx"])
        expect("provenance: commit_sha берётся из меты (не от вызывающего)", b_old["commit_sha"] == "OLDSHA")

        # T1: старое evidence pass + НОВЫЙ commit -> НЕ освобождает (все not_run)
        eg_new = evidence_for_gate(b_old, expected_sha="NEWSHA")
        expect("T1 exact-SHA: старое pass-evidence + новый commit -> все гейты not_run (не освобождает)",
               all(v["deterministic_status"] == "not_run" and v.get("unbound") for v in eg_new.values()))
        # T2: bundle.commit_sha == tested_revision -> evidence применяется (bound)
        eg_ok = evidence_for_gate(b_old, expected_sha="OLDSHA")
        expect("T2 exact-SHA: совпадение SHA -> evidence привязано (visual=pass применяется)",
               eg_ok["visual_regression"]["deterministic_status"] == "pass")
        # без expected_sha связывание не навязывается (диагностический режим)
        expect("exact-SHA: без expected_sha связывание не требуется (диагностика)",
               evidence_for_gate(b_old)["visual_regression"]["deterministic_status"] == "pass")

    # T3: проходящие истории ДРУГОГО компонента НЕ закрывают изменённый компонент -------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root, ".ai/ui-evidence/meta.json", {"commit_sha": "SHA1"})
        _write(root, "storybook-static/index.json", {"v": 5, "entries": {
            # полностью покрытые истории у КОМПОНЕНТА A (Widget), но изменён КОМПОНЕНТ B (Panel)
            "a--default": {"type": "story", "id": "a--default", "title": "A", "name": "Default",
                           "importPath": "./src/features/Widget.tsx"},
            "a--loading": {"type": "story", "id": "a--loading", "title": "A", "name": "Loading",
                           "importPath": "./src/features/Widget.tsx"},
            "a--empty": {"type": "story", "id": "a--empty", "title": "A", "name": "Empty",
                         "importPath": "./src/features/Widget.tsx"},
            "a--error": {"type": "story", "id": "a--error", "title": "A", "name": "Error",
                         "importPath": "./src/features/Widget.tsx"}}})
        _write(root, ".ai/ui-evidence/interaction.json", {"status": "pass", "total": 4, "passed": 4})
        b3 = build_bundle(root, changed_files=["src/admin/Panel.tsx"])
        expect("T3 scoping: истории чужого компонента (Widget) НЕ считаются затронутыми при правке Panel",
               b3["affected_stories"] == [] and b3["affected_components"] == [])
        eg3 = evidence_for_gate(b3, expected_sha="SHA1")
        expect("T3 scoping: ux НЕ закрыт (нет затронутых историй -> покрытие состояний не доказано)",
               eg3["ux_review"]["deterministic_status"] != "pass")
        # и loose stem-match убран: Card.tsx в разных каталогах не матчатся между собой
        expect("scoping: суффикс-матч, НЕ голый basename (a/Card.tsx ≠ b/Card.tsx)",
               _matches_changed("./a/Card.tsx", ["b/Card.tsx"]) is False
               and _matches_changed("./src/Card.tsx", ["src/Card.tsx"]) is True)

    # (G) v3.2.3 component-reuse enforcement -----------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root, "storybook-static/index.json", {"v": 5, "entries": {
            "components-metriccard--default": {"type": "story", "id": "components-metriccard--default",
                "title": "Components/MetricCard", "name": "Default", "importPath": "./src/MetricCard.tsx"},
            "components-button--default": {"type": "story", "id": "components-button--default",
                "title": "Components/Button", "name": "Default", "importPath": "./src/Button.tsx"}}})
        # новый компонент ДУБЛИРУЕТ существующий Button из каталога
        _write(root, ".ai/ui-evidence/design-system.json",
               {"reused_components": [], "new_components": ["Button"], "new_components_justified": True})
        b = build_bundle(root)
        expect("catalog собран из всех компонентов индекса",
               set(b["component_catalog"]) == {"metriccard", "button"})
        expect("reuse_violations ловит новый компонент, дублирующий каталог",
               reuse_violations(b) == ["Button"])
        # новый уникальный компонент — не нарушение
        _write(root, ".ai/ui-evidence/design-system.json",
               {"reused_components": ["Button"], "new_components": ["DashboardViewport"],
                "new_components_justified": True})
        b2 = build_bundle(root)
        expect("уникальный новый компонент — не reuse-нарушение", reuse_violations(b2) == [])

    assert ok, "перенесённый селфтест storybook_adapter: см. строки FAIL в выводе"
