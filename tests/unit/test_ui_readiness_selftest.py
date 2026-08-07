"""Селфтест ui_readiness, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from ui_readiness import (  # noqa: F401 — имена, которые использует тело
    Path,
    assess,
    check,
    script_template,
    should_run_ui_evidence,
)


@pytest.mark.slow
def test_ui_readiness_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    import tempfile
    # gating
    r, _ = should_run_ui_evidence(["src/features/x.tsx"])
    expect("gating: изменён .tsx -> UI-CI ON", r is True)
    r, _ = should_run_ui_evidence(["server/api.py"])
    expect("gating: не-UI изменение -> UI-CI OFF", r is False)
    r, _ = should_run_ui_evidence(["docs/readme.md"], {"task_type": "VISUAL"})
    expect("gating: VISUAL-задача -> UI-CI ON даже без UI-файла", r is True)
    r, _ = should_run_ui_evidence([".storybook/main.ts"])
    expect("gating: .storybook/ файл -> UI-CI ON", r is True)

    # maturity absent (пустой репо)
    with tempfile.TemporaryDirectory() as td:
        a = assess(td)
        expect("пустой репо -> maturity=absent (не маскируем)", a["storybook_maturity"] == "absent")
        expect("check валиден + installs_dependencies=False", check(a) == [] and a["installs_dependencies"] is False)

    # maturity configured (есть .storybook, нет build-скрипта/dep)
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / ".storybook").mkdir()
        (Path(td) / "package.json").write_text('{"name":"x"}', encoding="utf-8")
        a = assess(td)
        expect("есть .storybook, нет скрипта -> configured", a["storybook_maturity"] == "configured")

    # maturity runnable (есть storybook dep + build-скрипт)
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "package.json").write_text(
            '{"devDependencies":{"storybook":"^8"},"scripts":{"build-storybook":"storybook build -o storybook-static"}}',
            encoding="utf-8")
        a = assess(td)
        expect("dep + build-скрипт, нет evidence -> runnable", a["storybook_maturity"] == "runnable")

    expect("check: installs_dependencies=True -> ошибка",
           any("не ставит зависимости" in x for x in check({"kind": "UIReadiness",
               "storybook_maturity": "absent", "installs_dependencies": True, "evidence_status": {}})))
    expect("script_template не ставит deps (есть предупреждение)", "_note" in script_template())

    assert ok, "перенесённый селфтест ui_readiness: см. строки FAIL в выводе"
