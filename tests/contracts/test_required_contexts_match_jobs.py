"""Обязательные статусы защиты ветки сверяются с реальными CI-джобами.

Работа `required-contexts-match-jobs`, цель `checks-that-run`.

ЗАМЕР 20.08.2026 (docs/parallel-execution-retro.md §1 п.5): удаление джобы python39-compat
не убрало её из обязательных контекстов — ВСЕ PR зависли BLOCKED навсегда.

РЕШЕНИЕ: quality/required-contexts.yaml декларирует обязательные контексты; валидатор
(validate_required_contexts.py) сверяет декларацию с реальными джобами в CI-workflows.
Рассинхрон — красное в CI.

Три invariant-проверки:
  * declared contexts file существует и валиден;
  * все declared contexts имеют соответствующие джобы в workflows;
  * валидатор ловит рассинхрон (мутация «объявили несуществующую джобу» краснеет).
"""
from __future__ import annotations

import sys
import importlib.util
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.contract, pytest.mark.critical_path]


@pytest.fixture(scope="module")
def validator():
    """Загрузить валидатор как модуль."""
    spec = importlib.util.spec_from_file_location(
        "_validate_required_contexts",
        KIT / "ai_ops_kit" / "validation" / "validate_required_contexts.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestDeclaredContextsFileExists:
    """Файл декларации обязательных контекстов существует и валиден."""

    def test_required_contexts_file_exists(self):
        """quality/required-contexts.yaml существует — иначе проверка не работает."""
        ctx_file = KIT / "quality" / "required-contexts.yaml"
        assert ctx_file.exists(), (
            "quality/required-contexts.yaml не найден. "
            "Файл декларирует обязательные контексты защиты ветки; без него валидатор "
            "не может сверить объявленное с реальным (required-contexts-match-jobs)."
        )

    def test_required_contexts_file_is_valid_yaml(self):
        """Файл парсится как YAML и имеет поле contexts."""
        ctx_file = KIT / "quality" / "required-contexts.yaml"
        doc = yaml.safe_load(ctx_file.read_text(encoding="utf-8"))
        assert isinstance(doc, dict), "required-contexts.yaml не словарь"
        assert "contexts" in doc, "required-contexts.yaml не имеет поля 'contexts'"
        assert isinstance(doc["contexts"], list), "contexts не список"
        assert len(doc["contexts"]) > 0, "contexts пуст — защита ветки не работает"


class TestDeclaredContextsMatchJobs:
    """Все объявленные контексты имеют соответствующие джобы в workflows."""

    def test_no_declared_context_without_a_job(self, validator):
        """Главная проверка: если контекст объявлен, джоба ОБЯЗАНА существовать.

        Это ловит капкан: объявили контекст в защите ветки, но джобы нет (удалили,
        переименовали) — PR зависают BLOCKED навсегда.
        """
        result = validator.validate(KIT)
        assert result["declared"] is not None, "required-contexts.yaml не прочитан"
        assert result["ok"], (
            f"Объявленные контексты не имеют соответствующих джоб:\n"
            + "\n".join(f"  - {ctx}" for ctx in result["missing_jobs"])
            + "\n\nЭто повесит очередь: PR будут BLOCKED навсегда. "
            "Удалите контекст из quality/required-contexts.yaml или восстановите джобу."
        )

    def test_all_workflows_are_parsed(self, validator):
        """Валидатор видит все workflow-файлы."""
        wf_dir = KIT / ".github" / "workflows"
        expected_files = {f.stem for f in wf_dir.glob("*.yml")}
        jobs_by_wf = validator.extract_jobs_from_workflows(wf_dir)
        assert set(jobs_by_wf.keys()) == expected_files, (
            f"Валидатор не видит workflows: {expected_files - set(jobs_by_wf.keys())}"
        )


class TestValidatorCatchesDesync:
    """Валидатор ловит рассинхрон между декларацией и реальностью."""

    def test_fake_context_is_caught(self, validator, tmp_path):
        """Мутация: объявили несуществующую джобу — валидатор краснеет."""
        # Создаём фейковый репозиторий
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "test.yml").write_text(
            "name: test\njobs:\n  real-job:\n    runs-on: ubuntu-latest\n",
            encoding="utf-8",
        )

        # Декларация с несуществующей джобой
        ctx_dir = tmp_path / "quality"
        ctx_dir.mkdir(parents=True)
        (ctx_dir / "required-contexts.yaml").write_text(
            "contexts:\n  - test / real-job\n  - test / fake-job\n",
            encoding="utf-8",
        )

        result = validator.validate(tmp_path)
        assert not result["ok"], "валидатор не поймал несуществующую джобу"
        assert "test / fake-job" in result["missing_jobs"]

    def test_undeclared_job_is_warning_not_error(self, validator, tmp_path):
        """Джоба есть, но не объявлена — это WARNING, не ошибка."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "test.yml").write_text(
            "name: test\njobs:\n  real-job:\n    runs-on: ubuntu-latest\n  extra-job:\n    runs-on: ubuntu-latest\n",
            encoding="utf-8",
        )

        ctx_dir = tmp_path / "quality"
        ctx_dir.mkdir(parents=True)
        (ctx_dir / "required-contexts.yaml").write_text(
            "contexts:\n  - test / real-job\n",
            encoding="utf-8",
        )

        result = validator.validate(tmp_path)
        assert result["ok"], "undeclared job не должен красить проверку"
        assert "test / extra-job" in result["undeclared_jobs"]
