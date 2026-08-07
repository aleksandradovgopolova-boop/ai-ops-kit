"""Селфтест project_detector, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from project_detector import (  # noqa: F401 — имена, которые использует тело
    PROFILE_REL,
    Path,
    detect,
    json,
    load_or_detect,
)


@pytest.mark.slow
def test_project_detector_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text(json.dumps({
            "dependencies": {"react": "^18", "next": "^14"},
            "devDependencies": {"typescript": "^5", "eslint": "^9"},
            "scripts": {"build": "next build", "lint": "eslint .", "test": "vitest", "typecheck": "tsc --noEmit"}}),
            encoding="utf-8")
        (root / "package-lock.json").write_text("{}", encoding="utf-8")
        (root / ".github" / "workflows").mkdir(parents=True)
        prof = detect(root)
        s = prof["stacks"][0]
        expect("node определён", s["language"] == "node" and s["package_manager"] == "npm")
        expect("frameworks: next+react", {"next", "react"} <= set(s["frameworks"]))
        expect("команды из scripts", s["commands"]["build"] == "npm run build"
               and s["commands"]["test"] == "npm run test"
               and s["commands"]["typecheck"] == "npm run typecheck")
        expect("install-команда node с lockfile -> npm ci", s.get("install_command") == "npm ci")
        expect("CI обнаружен", "github-actions" in prof["ci"])
        expect("status draft (подтверждает человек)", prof["status"] == "draft")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "pyproject.toml").write_text(
            "[tool.poetry]\nname='x'\n[tool.poetry.dependencies]\nfastapi='*'\npytest='*'\nmypy='*'\n",
            encoding="utf-8")
        (root / "tests").mkdir()
        prof = detect(root)
        s = prof["stacks"][0]
        expect("python определён (poetry)", s["language"] == "python" and s["package_manager"] == "poetry")
        expect("fastapi во frameworks", "fastapi" in s["frameworks"])
        expect("python test/typecheck выведены", s["commands"]["test"] == "pytest"
               and s["commands"]["typecheck"] == "mypy .")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        prof = detect(root)
        expect("пустой репо -> стек не определён (честно в undetermined)",
               prof["stacks"] == [] and any("стек не определён" in u for u in prof["undetermined"]))

    # v2.84: java wrapper (./gradlew, ./mvnw) предпочитается глобальному бинарю (иначе exit 127)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "build.gradle").write_text("plugins {}\n", encoding="utf-8")
        (root / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
        s = detect(root)["stacks"][0]
        expect("java: ./gradlew предпочтён глобальному gradle",
               s["commands"]["build"] == "./gradlew build" and s["commands"]["test"] == "./gradlew test")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "pom.xml").write_text("<project/>\n", encoding="utf-8")
        s = detect(root)["stacks"][0]
        expect("java: без wrapper -> глобальный mvn (fallback)",
               s["commands"]["build"] == "mvn -q package")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "pom.xml").write_text("<project/>\n", encoding="utf-8")
        (root / "mvnw").write_text("#!/bin/sh\n", encoding="utf-8")
        s = detect(root)["stacks"][0]
        expect("java: ./mvnw предпочтён глобальному mvn", s["commands"]["test"] == "./mvnw -q test")

    # v2.84: монорепо-маркеры (pnpm-workspace / turbo) + честный undetermined-note
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text("{}", encoding="utf-8")
        (root / "pnpm-workspace.yaml").write_text("packages:\n  - 'packages/*'\n", encoding="utf-8")
        prof = detect(root)
        expect("monorepo: pnpm-workspace.yaml -> monorepo=True с причиной",
               prof["monorepo"] is True and "pnpm-workspace" in (prof.get("monorepo_reason") or ""))
        expect("monorepo: честный undetermined-note про покрытие пакетов",
               any("монорепо" in u for u in prof["undetermined"]))
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "apps").mkdir(); (root / "packages").mkdir()
        (root / "apps" / "package.json").write_text("{}", encoding="utf-8")
        (root / "packages" / "package.json").write_text("{}", encoding="utf-8")
        expect("monorepo: несколько package.json в apps/packages -> monorepo",
               detect(root)["monorepo"] is True)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}), encoding="utf-8")
        expect("не-монорепо: одиночный package.json -> monorepo=False",
               detect(root)["monorepo"] is False)

    # v3.28.1: вывод команд ТОЛЬКО по фактам + единая точка детекции (кеш профиля)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        s = detect(root)["stacks"][0]
        expect("нет признаков раннера -> команды None (не выдуманы)",
               s["commands"]["test"] is None and s["commands"]["lint"] is None
               and s["command_evidence"] == {})
        (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        (root / ".ruff.toml").write_text("line-length = 100\n", encoding="utf-8")
        s = detect(root)["stacks"][0]
        expect("pytest.ini/.ruff.toml -> команды выведены с источником",
               s["commands"]["test"] == "pytest" and s["commands"]["lint"] == "ruff check ."
               and s["command_evidence"]["test"] == "pytest.ini"
               and s["command_evidence"]["lint"] == ".ruff.toml")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".ai").mkdir()
        (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        p1 = load_or_detect(root)
        expect("load_or_detect: профиль РЕАЛЬНО записан с manifest_hash",
               (root / PROFILE_REL).is_file() and p1.get("manifest_hash"))
        (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        p2 = load_or_detect(root)
        expect("протухший кеш перечитан (не устаревший стек)",
               p2["manifest_hash"] != p1["manifest_hash"]
               and p2["stacks"][0]["commands"]["test"] == "pytest")
        expect("свежий кеш отдаётся без пере-детекта",
               load_or_detect(root)["manifest_hash"] == p2["manifest_hash"])

    assert ok, "перенесённый селфтест project_detector: см. строки FAIL в выводе"
