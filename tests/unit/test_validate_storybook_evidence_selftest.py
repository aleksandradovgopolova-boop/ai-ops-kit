"""Селфтест validate_storybook_evidence, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_storybook_evidence import (  # noqa: F401 — имена, которые использует тело
    BUILD,
    PKG,
    Path,
    SCHEMA,
    STATUS3,
    check,
    json,
    sys,
)


@pytest.mark.slow
def test_validate_storybook_evidence_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # источник валидного bundle — реальный адаптер (drift между адаптером и валидатором ловится)
    sys.path.insert(0, str(PKG / "tools"))
    import storybook_adapter  # noqa: E402
    import tempfile

    def _w(root, rel, obj):
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj), encoding="utf-8")

    with tempfile.TemporaryDirectory() as td:
        _w(td, "storybook-static/index.json", {"v": 5, "entries": {
            "c--default": {"type": "story", "id": "c--default", "title": "C", "name": "Default",
                           "importPath": "./C.tsx"},
            "c--loading": {"type": "story", "id": "c--loading", "title": "C", "name": "Loading",
                           "importPath": "./C.tsx"},
            "c--empty": {"type": "story", "id": "c--empty", "title": "C", "name": "Empty",
                         "importPath": "./C.tsx"},
            "c--error": {"type": "story", "id": "c--error", "title": "C", "name": "Error",
                         "importPath": "./C.tsx"}}})
        _w(td, ".ai/ui-evidence/interaction.json", {"status": "pass", "total": 3, "passed": 3})
        _w(td, ".ai/ui-evidence/a11y.json", {"blocking_violations": 0, "total_violations": 1})
        _w(td, ".ai/ui-evidence/visual.json", {"status": "pass", "changed": 0})
        _w(td, ".ai/ui-evidence/design-system.json",
           {"reused_components": ["C"], "new_components": [], "new_components_justified": True})
        good = storybook_adapter.build_bundle(td, commit_sha="abc", changed_files=["C.tsx"])
    expect("валидный bundle из адаптера проходит (полное покрытие)", check(good) == [])

    # семантические сломы
    bad_a11y = json.loads(json.dumps(good))
    bad_a11y["accessibility"] = {"status": "pass", "blocking_violations": 3, "total_violations": 3}
    expect("a11y pass при blocking>0 -> ошибка",
           any("blocking_violations>0" in x for x in check(bad_a11y)))

    bad_inter = json.loads(json.dumps(good))
    bad_inter["interaction_tests"] = {"status": "pass", "total": 5, "passed": 3}
    expect("interaction pass при passed<total -> ошибка",
           any("passed=total" in x for x in check(bad_inter)))

    bad_sc = json.loads(json.dumps(good))
    bad_sc["state_coverage"] = {"required": ["default", "empty"],
                                "states": {"default": True, "empty": False},
                                "missing": [], "complete": True}
    errs = check(bad_sc)
    expect("state_coverage complete=true при непокрытом required -> ошибка",
           any("missing несогласован" in x for x in errs) or any("complete" in x for x in errs))

    bad_ds = json.loads(json.dumps(good))
    bad_ds["design_system"] = {"status": "pass", "reused_components": [],
                               "new_components": ["AdHoc"], "new_components_justified": False}
    expect("design_system pass с новым необоснованным компонентом -> ошибка",
           any("без обоснования" in x for x in check(bad_ds)))

    bad_key = json.loads(json.dumps(good))
    bad_key["accessibility"]["nonsense"] = 1
    expect("лишний ключ в секции (closed) -> ошибка",
           any("лишний ключ" in x for x in check(bad_key)))

    bad_kind = json.loads(json.dumps(good))
    bad_kind["kind"] = "Nope"
    expect("неверный kind -> ошибка", any("kind" in x for x in check(bad_kind)))

    # v3.2.3 component-reuse: новый компонент дублирует каталог -> ошибка
    dup = json.loads(json.dumps(good))
    dup["component_catalog"] = ["c", "button"]
    dup["design_system"] = {"status": "pass", "reused_components": [],
                            "new_components": ["Button"], "new_components_justified": True}
    expect("новый компонент, дублирующий каталог -> reuse-ошибка",
           any("reuse" in x for x in check(dup)))
    # уникальный новый компонент при наличии каталога -> без reuse-ошибки
    uniq = json.loads(json.dumps(dup))
    uniq["design_system"]["new_components"] = ["BrandNewThing"]
    expect("уникальный новый компонент -> без reuse-ошибки",
           not any("reuse" in x for x in check(uniq)))

    # drift-guard: enum'ы валидатора совпадают со схемой
    try:
        sch = json.loads(SCHEMA.read_text(encoding="utf-8"))
        sec_enum = set(sch["properties"]["interaction_tests"]["properties"]["status"]["enum"])
        build_enum = set(sch["properties"]["storybook"]["properties"]["build_status"]["enum"])
        expect("enum'ы валидатора == схема (нет дрейфа)", sec_enum == STATUS3 and build_enum == BUILD)
    except Exception as ex:
        expect(f"схема читается ({ex})", False)

    assert ok, "перенесённый селфтест validate_storybook_evidence: см. строки FAIL в выводе"
