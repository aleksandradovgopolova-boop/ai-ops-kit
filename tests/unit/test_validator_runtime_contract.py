"""Контракт валидаторов без шва check(data) — вторая половина рекомендации №6.

`test_validator_contract.py` закрыл 28 валидаторов с однородным `check(data)`. Здесь — остальные:
они сканируют репозиторий целиком (`fail(...)` + печать) или требуют путь к артефакту, и общей
функции-шва у них нет. Проверяем их снаружи так, как их запускают на самом деле — процессом.

Что проверяется:
  * positive     — валидатор зелёный, будучи запущенным ИЗ КОПИИ репозитория. Это не формальность:
                   ровно так ловится класс, на котором кит горел в августе 2026 — зависимость от
                   места дерева и от editable-установки на машине разработчика;
  * fail-closed  — валидатору, требующему артефакт, пустой запуск даёт ненулевой код (молча
                   «всё хорошо» без входных данных он сказать не имеет права);
  * side-effect  — при РЕАЛЬНОЙ порче своего источника правды валидатор краснеет. Соответствие
                   «что портим -> кто ловит» получено замером, а не предположением.

Прогон порождает десятки subprocess'ов — помечено slow, чтобы CI держал это отдельной группой.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]

# Валидаторы, запускаемые без аргументов (сканируют репозиторий).
STANDALONE = [
    "validate_access_filter",
    "validate_adr_registry",
    "validate_agent_evals",
    "validate_agents_checklist",
    "validate_ai_first_config",
    "validate_ai_first_providers",
    "validate_ai_first_registry",
    "validate_ai_first_workflows",
    "validate_ai_ops_child",
    "validate_bootstrap_qualification",
    "validate_budget_contract",
    "validate_capability_scope",
    "validate_claims",
    "validate_container_assets",
    "validate_container_delivery",
    "validate_context_qualification",
    "validate_decisions",
    "validate_duties",
    "validate_engops_policy",
    "validate_event_catalog",
    "validate_feature_learning",
    "validate_freshness",
    "validate_integration_trace",
    "validate_key_lifecycle",
    "validate_layering",
    "validate_learning_loop",
    "validate_loop_trace",
    "validate_memory_governance",
    "validate_model_qualification",
    "validate_model_roles",
    "validate_openspec_change",
    "validate_package_boundaries",
    "validate_pipeline_e2e",
    "validate_post_release_readout",
    "validate_presets",
    "validate_product_qualification",
    "validate_promotion_qualification",
    "validate_provider_residency",
    "validate_python_compat",
    "validate_qualification",
    "validate_quality_attributes",
    "validate_references",
    "validate_regression_corpus",
    "validate_release_claims",
    "validate_research_artifacts",
    "validate_runtime_surface",
    "validate_scenario_evidence",
    "validate_security_domains",
    "validate_security_posture",
    "validate_stack_qualification",
    "validate_stale_gates",
    "validate_standalone_engine",
    "validate_supply_chain",
    "validate_surface_wiring",
    "validate_work_graph",
    "validate_workflow_gates",
]

# Валидаторы, которым нужен путь к артефакту.
NEEDS_ARTIFACT = [
    "validate_architecture_decision",
    "validate_context_architecture",
    "validate_context_bundle",
    "validate_context_completeness",
    "validate_cross_artifacts",
    "validate_feature_blueprint",
    "validate_knowledge_graph",
    "validate_loop_policy",
    "validate_plan_artifact",
    "validate_requirements_artifact",
    "validate_reviewer_result",
    "validate_run_handoff",
    "validate_spec_artifact",
    "validate_spec_coverage",
    "validate_storybook_evidence",
]

# Порча источника правды -> валидаторы, которые ОБЯЗАНЫ её заметить.
# Соответствие ЗАМЕРЕНО, а не предположено: каждый реестр опустошался в копии репозитория и
# фиксировалось, кто покраснел. Считались только standalone-валидаторы: требующие артефакт
# возвращают ненулевой код на пустом вызове ВСЕГДА, и первый замер из-за них показывал
# «ловят 15-21» на любую порчу — ложная картина, из которой вышли бы неверные тесты.
# Так нашлась дыра: порчу registry/tracks.yaml не ловил НИКТО (закрыто в validate_workflow_gates).
CORRUPTIONS = {
    "registry/agents.yaml": (
        "agents: []\n",
        ["validate_ai_first_registry", "validate_ai_first_workflows",
         "validate_presets", "validate_references"]),
    "registry/providers.yaml": (
        "providers: []\n",
        ["validate_ai_first_providers", "validate_pipeline_e2e",
         "validate_product_qualification"]),
    "quality/gates.yaml": (
        "schema_version: 1\nregistry_type: quality-gates\ngates: {}\nmvp_blocking_gates: []\n",
        ["validate_ai_first_workflows", "validate_references", "validate_claims"]),
    # v3.30: чеклист больше не список команд, и validate_agents_checklist его не читает — он
    # охраняет инвариант «CI не запускает проверки мимо pytest». Портим то, что он реально читает.
    # v3.32: слои пакетов — тоже источник правды. Пустой список слоёв означает, что про каждый
    # пакет нельзя ни запретить, ни разрешить ничего; валидатор обязан это заметить.
    "packages/layering.yaml": (
        "schema_version: 1\nkind: package-layering\nlayers: []\nrules: []\nknown_violations: []\n",
        ["validate_layering"]),
    "registry/models.yaml": (
        "models: []\n",
        ["validate_ai_first_providers", "validate_model_roles"]),
    "registry/workflows.yaml": (
        "workflows: {}\n",
        ["validate_ai_first_providers", "validate_ai_first_workflows", "validate_claims",
         "validate_pipeline_e2e", "validate_product_qualification", "validate_workflow_gates"]),
    "registry/runtimes.yaml": (
        "runtimes: {}\n",
        ["validate_ai_first_providers", "validate_release_claims"]),
    "registry/capability-index.yaml": (
        "capabilities: {}\n",
        ["validate_ai_first_registry"]),
    "registry/model-roles.yaml": (
        "roles: {}\n",
        ["validate_model_roles"]),
    "registry/tracks.yaml": (
        "schema_version: 1\nregistry_type: tracks\ntracks: []\n",
        ["validate_workflow_gates"]),
    ".github/workflows/pr-smoke.yml": (
        "name: x\non: {pull_request: {branches: [main]}}\njobs:\n  j:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: python3 validation/validate_ai_first_registry.py\n",
        ["validate_agents_checklist"]),
}

# Покрыты ШТУЧНЫМИ тестами в других файлах — под общие контракты не заводим, но объявляем,
# иначе тест полноты не отличит «покрыт иначе» от «забыт».
BESPOKE_ELSEWHERE = {
    "validate_container_assets": "test_installer.py",
    "validate_feature_blueprint": "test_process_applicability.py",
    "validate_package_boundaries": "test_installer.py",
    "validate_spec_coverage": "test_validation_layer.py",
    "validate_standalone_engine": "test_installer.py",
    "validate_workflow_gates": "test_validation_layer.py",
}

_IGNORE = shutil.ignore_patterns(".git", ".venv", "node_modules", "__pycache__", "*.pyc",
                                 ".pytest_cache", ".hypothesis", "htmlcov", "*.egg-info")


@pytest.fixture(scope="module")
def repo_copy(tmp_path_factory):
    """Копия репозитория: валидатор обязан работать вне своего исходного дерева."""
    dst = tmp_path_factory.mktemp("kit") / "copy"
    shutil.copytree(PKG, dst, ignore=_IGNORE)
    return dst


def _run(copy, name, *args, timeout=300):
    """Запуск валидатора так, как его запускает пользователь: БЕЗ PYTHONPATH.

    v3.31: прежде здесь ставился `PYTHONPATH=<copy>/tools:<copy>/validation`, и из-за него тест
    «валидатор зелёный из копии репозитория» не мог поймать дефект, ради которого написан: десять
    валидаторов не находили `_bootstrap` нигде, кроме окружения с этим поясом. Проверка, которая
    сама себе стелет путь, проверяет не то, что обещает.
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return subprocess.run([sys.executable, str(copy / "validation" / f"{name}.py"), *args],
                          cwd=str(copy), capture_output=True, env=env, timeout=timeout)


@pytest.mark.slow
@pytest.mark.parametrize("name", STANDALONE)
def test_standalone_validator_is_green_from_a_copy(repo_copy, name):
    r = _run(repo_copy, name)
    assert r.returncode == 0, (r.stdout + r.stderr).decode("utf-8", "replace")[-800:]


@pytest.mark.slow
@pytest.mark.parametrize("name", NEEDS_ARTIFACT)
def test_validator_requiring_artifact_refuses_empty_call(repo_copy, name):
    """Без входных данных проверять нечего — сказать «ок» валидатор не вправе."""
    r = _run(repo_copy, name)
    assert r.returncode != 0, f"{name} вернул 0 без артефакта — это молчаливый зелёный"


@pytest.mark.slow
@pytest.mark.parametrize("rel", sorted(CORRUPTIONS))
def test_corrupted_source_of_truth_is_caught(repo_copy, rel):
    """Порча реестра обязана краснеть у тех, кто на него опирается."""
    broken, catchers = CORRUPTIONS[rel]
    target = repo_copy / rel
    assert target.is_file(), f"нет файла {rel} — соответствие устарело"
    original = target.read_text(encoding="utf-8")
    target.write_text(broken, encoding="utf-8")
    try:
        missed = [n for n in catchers if _run(repo_copy, n).returncode == 0]
    finally:
        target.write_text(original, encoding="utf-8")
    assert not missed, f"порчу {rel} НЕ заметили: {missed}"


@pytest.mark.unit
@pytest.mark.parametrize("name,test_file", sorted(BESPOKE_ELSEWHERE.items()))
def test_bespoke_coverage_still_exists(name, test_file):
    """Объявленное «покрыт штучно» обязано быть правдой: тест мог уехать вместе с рефакторингом."""
    hit = [t for t in (PKG / "tests").rglob("test_*.py")
           if name in t.read_text(encoding="utf-8")]
    assert hit, f"{name} объявлен покрытым в {test_file}, но упоминаний в tests/ нет"


@pytest.mark.unit
def test_lists_cover_every_validator_without_uniform_seam():
    """Валидатор, не попавший ни в один список, остаётся без внешней проверки незамеченным."""
    from test_validator_contract import OTHER_SEAMS, UNIFORM_CHECK_VALIDATORS

    everything = {p.stem for p in (PKG / "validation").glob("validate_*.py")}
    listed = set(STANDALONE) | set(NEEDS_ARTIFACT) | set(UNIFORM_CHECK_VALIDATORS) | set(OTHER_SEAMS) | set(BESPOKE_ELSEWHERE)
    assert not (everything - listed), f"валидаторы вне всякого контракта: {sorted(everything - listed)}"


# ------------------------------------------------ справка не должна быть пустой ---

@pytest.mark.unit
@pytest.mark.parametrize("rel", sorted(
    [f"tools/{p.name}" for p in (PKG / "tools").glob("*.py")] +
    [f"validation/{p.name}" for p in (PKG / "validation").glob("*.py")] +
    ["installer/ai_ops.py"]))
def test_module_description_is_a_real_docstring(rel):
    """Описание модуля обязано быть ДОКСТРИНГОМ, а не строкой после `from __future__`.

    В 168 модулях строка-описание стояла после future-импорта и потому докстрингом не являлась:
    `__doc__` был None. 49 из них печатают `print(__doc__)` как справку — то есть на запрос
    помощи пользователь получал слово «None». Порядок «докстринг, затем from __future__» — ещё и
    единственно корректный для Python.
    """
    import ast

    path = PKG / rel
    src = path.read_text(encoding="utf-8")
    if '"""' not in src:
        pytest.skip(f"{rel}: без строкового описания")
    assert ast.get_docstring(ast.parse(src)) is not None, (
        f"{rel}: описание не является докстрингом (__doc__ = None) — "
        f"перенеси его ВЫШЕ `from __future__ import annotations`")
