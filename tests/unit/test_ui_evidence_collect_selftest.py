"""Селфтест ui_evidence_collect, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from ui_evidence_collect import (  # noqa: F401 — имена, которые использует тело
    Path,
    collect,
    is_ui_stack,
    json,
)


@pytest.mark.slow
def test_ui_evidence_collect_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # python-only -> не UI
        (root / "pyproj").mkdir()
        expect("python-child (нет package.json) -> не UI-стек", is_ui_stack(root) is False)
        # package.json со storybook-скриптом -> UI
        (root / "package.json").write_text(json.dumps({
            "scripts": {"ui-evidence": "bash scripts/ui-evidence.sh"},
            "devDependencies": {"@storybook/react-vite": "^8"}}), encoding="utf-8")
        expect("package.json со storybook/ui-evidence -> UI-стек", is_ui_stack(root) is True)
        # collect без npm-запуска: пишет авторитетную meta с committed_sha
        res = collect(root, "abc123def", run_npm=False)
        expect("collect(run_npm=False) -> не skipped, meta записана", res["skipped"] is False)
        meta = json.loads((root / ".ai" / "ui-evidence" / "meta.json").read_text())
        expect("meta.commit_sha == переданный committed_sha (SHA-binding от kit)",
               meta["commit_sha"] == "abc123def")
        # без sha -> skipped (нельзя привязать)
        expect("collect без commit_sha -> skipped", collect(root, None, run_npm=False)["skipped"] is True)

    with tempfile.TemporaryDirectory() as td2:
        r2 = Path(td2)
        (r2 / "package.json").write_text(json.dumps({"dependencies": {"react": "^18"}}), encoding="utf-8")
        expect("package.json без storybook/ui-evidence -> НЕ UI-стек (skip)", is_ui_stack(r2) is False)

    assert ok, "перенесённый селфтест ui_evidence_collect: см. строки FAIL в выводе"
