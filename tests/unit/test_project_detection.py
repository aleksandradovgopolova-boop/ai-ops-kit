"""Unit-тесты tools/project_detector.py — единая точка детекции и честный вывод команд.

Три обязательных теста на capability (AGENTS.md):
  * positive       — стек и команды выведены с evidence; свежий профиль читается из кеша;
  * fail-closed    — нет доказательства -> команда None + причина в undetermined;
                     протухший кеш перечитывается, а не отдаётся устаревшим;
  * side-effect    — .ai/repository-profile.yaml РЕАЛЬНО записан на диск и содержит manifest_hash.

Всё на временных каталогах (tmp_path), без сети и без внешних тулчейнов.
"""
from __future__ import annotations

import textwrap

import pytest
import yaml

from ai_ops_kit.shared import project_detector


def _py_repo(root, *, pytest_section=True, tests_dir=True, with_ai=True):
    """Минимальный python-репозиторий: pyproject (+ [tool.pytest.ini_options]) и tests/."""
    body = "[project]\nname = 'demo'\nversion = '0.1.0'\n"
    if pytest_section:
        body += "\n[tool.pytest.ini_options]\naddopts = '-q'\n"
    (root / "pyproject.toml").write_text(body, encoding="utf-8")
    if tests_dir:
        (root / "tests").mkdir()
        (root / "tests" / "test_demo.py").write_text("def test_ok():\n    assert True\n",
                                                     encoding="utf-8")
    if with_ai:
        (root / ".ai").mkdir()
    return root


# ---------------------------------------------------------------- positive ---

@pytest.mark.unit
class TestPositiveDetection:
    """Стек и команды выводятся из реальных фактов, кеш профиля работает."""

    def test_pyproject_with_pytest_section_yields_test_command_with_evidence(self, tmp_path):
        profile = project_detector.detect(_py_repo(tmp_path))
        stacks = [s for s in profile["stacks"] if s["language"] == "python"]
        assert stacks, "python-стек должен быть определён по pyproject.toml"
        stack = stacks[0]
        assert stack["commands"]["test"] == "pytest"
        # каждая выведенная команда обязана иметь файл-источник
        assert stack["command_evidence"]["test"] == "pyproject.toml"
        assert "pyproject.toml" in stack["evidence_source"]

    def test_ruff_and_mypy_config_yield_lint_and_typecheck(self, tmp_path):
        _py_repo(tmp_path)
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'demo'\n\n[tool.ruff]\nline-length = 100\n\n[tool.mypy]\nstrict = true\n",
            encoding="utf-8")
        stack = project_detector.detect(tmp_path)["stacks"][0]
        assert stack["commands"]["lint"] == "ruff check ."
        assert stack["commands"]["typecheck"] == "mypy ."
        assert stack["command_evidence"]["lint"] == "pyproject.toml"
        assert stack["command_evidence"]["typecheck"] == "pyproject.toml"

    def test_precommit_hooks_are_evidence_for_lint(self, tmp_path):
        """Хук объявлен в .pre-commit-config.yaml -> команда есть, источник — этот файл."""
        _py_repo(tmp_path)
        (tmp_path / ".pre-commit-config.yaml").write_text(
            "repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n"
            "    rev: v0.8.0\n    hooks:\n      - id: ruff\n", encoding="utf-8")
        stack = project_detector.detect(tmp_path)["stacks"][0]
        assert stack["commands"]["lint"] == "ruff check ."
        assert stack["command_evidence"]["lint"] == ".pre-commit-config.yaml"

    def test_github_workflow_command_is_evidence(self, tmp_path):
        """Команда, которая РЕАЛЬНО запускается в CI, закрывает пустой слот с источником-workflow."""
        _py_repo(tmp_path, pytest_section=False, tests_dir=False)
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(textwrap.dedent("""\
            name: ci
            on: [push]
            jobs:
              t:
                runs-on: ubuntu-latest
                steps:
                  - run: |
                      python3 -m pytest tests/ -q
            """), encoding="utf-8")
        stack = project_detector.detect(tmp_path)["stacks"][0]
        assert stack["commands"]["test"] == "python3 -m pytest tests/ -q"
        assert stack["command_evidence"]["test"] == ".github/workflows/ci.yml"

    def test_makefile_target_is_evidence(self, tmp_path):
        _py_repo(tmp_path, pytest_section=False, tests_dir=False)
        (tmp_path / "Makefile").write_text("VERSION := 1\n\nbuild:\n\techo build\n", encoding="utf-8")
        stack = project_detector.detect(tmp_path)["stacks"][0]
        assert stack["commands"]["build"] == "make build"
        assert stack["command_evidence"]["build"] == "Makefile"

    def test_node_scripts_have_evidence(self, tmp_path):
        (tmp_path / "package.json").write_text(
            '{"scripts": {"build": "tsc", "test": "vitest"}}', encoding="utf-8")
        stack = project_detector.detect(tmp_path)["stacks"][0]
        assert stack["commands"]["build"] == "npm run build"
        assert stack["command_evidence"] == {"build": "package.json", "test": "package.json"}

    def test_load_or_detect_uses_cache_on_second_call(self, tmp_path, monkeypatch):
        """Свежий профиль читается с диска — detect() второй раз НЕ вызывается (счётчик вызовов)."""
        _py_repo(tmp_path)
        first = project_detector.load_or_detect(tmp_path)
        assert first["stacks"][0]["commands"]["test"] == "pytest"

        calls = {"n": 0}
        real_detect = project_detector.detect

        def counting_detect(root):
            calls["n"] += 1
            return real_detect(root)

        monkeypatch.setattr(project_detector, "detect", counting_detect)
        second = project_detector.load_or_detect(tmp_path)
        assert calls["n"] == 0, "свежий профиль обязан читаться из кеша, а не детектиться заново"
        assert second["stacks"][0]["commands"]["test"] == "pytest"
        assert second["manifest_hash"] == first["manifest_hash"]

    def test_load_or_detect_without_ai_dir_does_not_create_it(self, tmp_path):
        """Без каталога .ai/ детект работает, но чужой репозиторий не засоряется."""
        _py_repo(tmp_path, with_ai=False)
        profile = project_detector.load_or_detect(tmp_path)
        assert profile["stacks"][0]["language"] == "python"
        assert not (tmp_path / ".ai").exists()


# ------------------------------------------------------------- fail-closed ---

@pytest.mark.unit
class TestFailClosed:
    """Нет доказательства — нет команды. Протухший кеш не отдаётся."""

    def test_no_test_runner_evidence_leaves_command_none(self, tmp_path):
        """Репо без единого признака тест-раннера: test=None + честная запись в undetermined."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'bare'\nversion = '0'\n",
                                                 encoding="utf-8")
        profile = project_detector.detect(tmp_path)
        stack = profile["stacks"][0]
        assert stack["commands"]["test"] is None, "команду нельзя выдумывать: гейт станет зелёным вхолостую"
        assert stack["commands"]["lint"] is None
        assert stack["commands"]["typecheck"] is None
        assert "test" not in stack["command_evidence"]
        assert any("не выведены команды" in u and "test" in u for u in profile["undetermined"])

    def test_empty_tests_dir_is_not_evidence(self, tmp_path):
        """Пустой каталог tests/ — не доказательство: тестовых файлов нет."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'bare'\n", encoding="utf-8")
        (tmp_path / "tests").mkdir()
        assert project_detector.detect(tmp_path)["stacks"][0]["commands"]["test"] is None

    def test_ci_step_allowed_to_fail_is_not_evidence(self, tmp_path):
        """`|| true` и continue-on-error маскируют падение — такую команду в гейт не берём."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'bare'\n", encoding="utf-8")
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(textwrap.dedent("""\
            name: ci
            on: [push]
            jobs:
              t:
                runs-on: ubuntu-latest
                steps:
                  - run: pytest -q || true
                  - continue-on-error: true
                    run: mypy .
            """), encoding="utf-8")
        stack = project_detector.detect(tmp_path)["stacks"][0]
        assert stack["commands"]["test"] is None
        assert stack["commands"]["typecheck"] is None

    def test_every_command_has_evidence(self, tmp_path):
        """Инвариант: в профиле не бывает команды без файла-источника."""
        _py_repo(tmp_path)
        (tmp_path / "go.mod").write_text("module demo\n", encoding="utf-8")
        (tmp_path / "Cargo.toml").write_text("[package]\nname = 'demo'\n", encoding="utf-8")
        for stack in project_detector.detect(tmp_path)["stacks"]:
            for slot, cmd in stack["commands"].items():
                if cmd:
                    assert stack["command_evidence"].get(slot), \
                        f"{stack['language']}.{slot}={cmd} без источника — выдуманная команда"

    def test_stale_profile_is_re_detected_not_served(self, tmp_path):
        """Манифесты изменились -> кеш протух -> прогон НЕ идёт по устаревшему стеку."""
        _py_repo(tmp_path, pytest_section=False, tests_dir=False)
        stale = project_detector.load_or_detect(tmp_path)
        assert stale["stacks"][0]["commands"]["test"] is None
        stale_hash = stale["manifest_hash"]

        # появился настоящий тест-раннер
        (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
        fresh = project_detector.load_or_detect(tmp_path)
        assert fresh["manifest_hash"] != stale_hash
        assert fresh["stacks"][0]["commands"]["test"] == "pytest"
        assert fresh["stacks"][0]["command_evidence"]["test"] == "pytest.ini"
        # кеш на диске тоже обновлён — следующий потребитель получит свежий профиль
        on_disk = yaml.safe_load((tmp_path / ".ai" / "repository-profile.yaml").read_text(encoding="utf-8"))
        assert on_disk["manifest_hash"] == fresh["manifest_hash"]

    def test_stale_detection_survives_manifest_removal(self, tmp_path):
        """Манифест удалён — профиль тоже протух (иначе гоняли бы команду, которой уже нет)."""
        _py_repo(tmp_path)
        (tmp_path / "package.json").write_text('{"scripts": {"test": "vitest"}}', encoding="utf-8")
        before = project_detector.load_or_detect(tmp_path)
        assert {s["language"] for s in before["stacks"]} == {"node", "python"}
        (tmp_path / "package.json").unlink()
        after = project_detector.load_or_detect(tmp_path)
        assert {s["language"] for s in after["stacks"]} == {"python"}

    def test_broken_or_hashless_profile_is_ignored(self, tmp_path):
        """Битый профиль и профиль без manifest_hash (старая версия кита) не считаются свежими."""
        _py_repo(tmp_path)
        prof_path = tmp_path / ".ai" / "repository-profile.yaml"

        prof_path.write_text(": не yaml: [", encoding="utf-8")
        assert project_detector.load_or_detect(tmp_path)["stacks"][0]["commands"]["test"] == "pytest"

        legacy = project_detector.detect(tmp_path)
        legacy.pop("manifest_hash")
        legacy["stacks"][0]["language"] = "cobol"        # заведомо устаревшее содержимое
        prof_path.write_text(yaml.safe_dump(legacy, allow_unicode=True), encoding="utf-8")
        assert project_detector.load_or_detect(tmp_path)["stacks"][0]["language"] == "python"


# --------------------------------------------------------- side-effect proof ---

@pytest.mark.unit
class TestSideEffectProof:
    """Сначала доказываем, что файл РЕАЛЬНО записан, потом проверяем поведение чтения."""

    def test_profile_is_written_to_disk_with_manifest_hash(self, tmp_path):
        _py_repo(tmp_path)
        prof_path = tmp_path / ".ai" / "repository-profile.yaml"
        assert not prof_path.exists()

        returned = project_detector.load_or_detect(tmp_path)

        # 1) side-effect: файл существует и непуст
        assert prof_path.is_file(), "профиль обязан быть записан на диск"
        raw = prof_path.read_text(encoding="utf-8")
        assert raw.strip(), "профиль на диске пуст"

        # 2) содержимое: kind, стек, хеш манифестов
        on_disk = yaml.safe_load(raw)
        assert on_disk["kind"] == "repository-profile"
        assert on_disk["stacks"][0]["language"] == "python"
        assert on_disk["manifest_hash"] == project_detector.manifest_fingerprint(tmp_path)
        assert on_disk["manifest_hash"] == returned["manifest_hash"]

        # 3) и только теперь — что чтение опирается именно на этот файл
        on_disk["stacks"][0]["frameworks"] = ["marker-from-disk"]
        prof_path.write_text(yaml.safe_dump(on_disk, allow_unicode=True), encoding="utf-8")
        assert project_detector.load_or_detect(tmp_path)["stacks"][0]["frameworks"] == ["marker-from-disk"]

    def test_manifest_fingerprint_changes_with_manifest_content(self, tmp_path):
        _py_repo(tmp_path)
        before = project_detector.manifest_fingerprint(tmp_path)
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = 'demo'\n\n[tool.mypy]\nstrict = true\n", encoding="utf-8")
        assert project_detector.manifest_fingerprint(tmp_path) != before

    def test_manifest_fingerprint_stable_without_changes(self, tmp_path):
        _py_repo(tmp_path)
        assert project_detector.manifest_fingerprint(tmp_path) == \
            project_detector.manifest_fingerprint(tmp_path)


# ------------------------------------------------------------- потребители ---

@pytest.mark.unit
def test_consumers_use_single_detection_entrypoint(tmp_path):
    """context_compiler и engineering_advisor ходят через load_or_detect (общий кеш профиля)."""
    import inspect

    from ai_ops_kit.context import context_compiler
    from ai_ops_kit.engops import engineering_advisor

    assert "load_or_detect" in inspect.getsource(context_compiler.compile_bundle)
    assert "load_or_detect" in inspect.getsource(engineering_advisor._delivery_plan)

    _py_repo(tmp_path)
    engineering_advisor._delivery_plan(tmp_path)
    assert (tmp_path / ".ai" / "repository-profile.yaml").is_file()


@pytest.mark.unit
def test_compile_bundle_does_not_write_profile(tmp_path):
    """compile_bundle читает профиль, но не пишет его: через него проходит `preview`, а preview
    обязан не менять репозиторий. Регрессия: write=True здесь делал `preview onboard` действием."""
    from ai_ops_kit.context import context_compiler

    _py_repo(tmp_path)
    (tmp_path / ".ai").mkdir(exist_ok=True)     # каталог есть -> запись была бы разрешена
    prof = tmp_path / ".ai" / "repository-profile.yaml"
    assert not prof.exists()

    bundle = context_compiler.compile_bundle(
        {"task_type": "QUICK", "risk": "low", "affected_areas": ["core"], "task_text": "правка"},
        tmp_path)

    assert not prof.exists(), "compile_bundle создал профиль — preview перестал быть безопасным"
    assert any("python" in c for c in bundle["included"]["repository_context"]), \
        "профиль не прочитан: стек в бандле не отражён"


@pytest.mark.unit
def test_preview_onboard_leaves_repo_untouched(tmp_path):
    """`ai-ops preview onboard` не производит побочных эффектов — ни профиля, ни иных файлов."""
    from ai_ops_kit.cli import ai_ops_cli

    _py_repo(tmp_path)
    (tmp_path / ".ai").mkdir(exist_ok=True)
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))

    assert ai_ops_cli.main(["preview", "onboard", str(tmp_path)]) == 0

    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert after == before, f"preview изменил дерево: {sorted(set(after) - set(before))}"
