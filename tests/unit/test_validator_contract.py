"""Внешний контракт слоя валидаторов — рекомендация №6 внешнего ревью.

74 валидатора были продуктовым обещанием качества, но проверялись САМОАТТЕСТАЦИЕЙ: у каждого свой
`--selftest`, и валидатор подтверждал сам себя. Штучных тестов на все 70 (по три на capability =
210 штук) единовременно не написать, поэтому здесь закрывается класс: у большинства валидаторов
один и тот же шов `check(data) -> list[str]`, и от него можно требовать контракт.

Что проверяется для каждого:
  * positive     — контракт формы: check() возвращает СПИСОК строк, а не bool/None/исключение;
  * fail-closed  — на заведомо чужом артефакте список НЕ пуст (валидатор, который не умеет
                   сказать «нет», бесполезен как гейт);
  * side-effect  — сообщения непустые и осмысленной длины: «ошибка» без текста не даёт починить.

Список ЯВНЫЙ, а не собранный на лету: новый валидатор с тем же швом должен попасть под контракт
осознанно, иначе покрытие тихо разъезжается с реальностью (тот же принцип, что у исключений
пре-коммит-чеклиста). Расхождение списка с фактическим набором ловит отдельный тест.
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]

# Валидаторы со швом check(data) / check(data, pkg). Держать по алфавиту.
UNIFORM_CHECK_VALIDATORS = [
    "validate_acceptance_result",
    "validate_access_filter",
    "validate_architecture_decision",
    "validate_bootstrap_qualification",
    "validate_budget_contract",
    "validate_capability_scope",
    "validate_context_architecture",
    "validate_duties",
    "validate_feature_learning",
    "validate_integration_trace",
    "validate_key_lifecycle",
    "validate_loop_policy",
    "validate_loop_trace",
    "validate_memory_governance",
    "validate_model_qualification",
    "validate_model_roles",
    "validate_mutation_probes",
    "validate_plan_artifact",
    "validate_post_release_readout",
    "validate_product_model",
    "validate_product_objects",
    "validate_promotion_qualification",
    "validate_provider_residency",
    "validate_qualification",
    "validate_regression_corpus",
    "validate_release_claims",
    "validate_requirements_artifact",
    "validate_reviewer_result",
    "validate_sandbox_boundary",
    "validate_security_domains",
    "validate_spec_artifact",
    "validate_storybook_evidence",
    "validate_supply_chain",
]

# Иные швы — под общий контракт не подходят, перечислены с причиной (declared, not implicit).
OTHER_SEAMS = {
    "validate_decisions": "check() возвращает (errors, warnings) — иной контракт",
    "validate_event_catalog": "check() возвращает (errors, warnings) — иной контракт",
    "validate_security_posture": "check(data, root) — требует корень репозитория",
}

# Сессионные модули в engops/ — тот же шов check(data), но живут вне каталога validation/.
# ЗАЧЕМ ЭТОТ СПИСОК (session-ritual-validators-are-dead): замер 17.08 показал, что 5 модулей
# session_* имеют check(), но НИ ОДНА не вызывается из production-кода — только из собственных
# тестов. Включение в контракт делает их видимыми: новый session-модуль с check() обязан попасть
# в список осознанно, а пропажа — ловится тестом.
SESSION_CONTRACT_CHECKS = [
    "ai_ops_kit.engops.session_boundary",
    "ai_ops_kit.engops.session_guardrails",
    "ai_ops_kit.engops.session_handoff",
    "ai_ops_kit.engops.session_launcher",
    "ai_ops_kit.engops.session_telemetry",
    "ai_ops_kit.engops.session_telemetry_provider",
]

# Заведомо чужой артефакт: ни один валидатор не должен признать его своим.
ALIEN = {"kind": "совершенно-не-тот-артефакт", "registry_type": "мусор",
         "schema_version": 999, "нет": "ничего осмысленного"}


def _seam_of(path: Path):
    """('data', arity) для check() модуля, иначе None."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "check":
            args = [a.arg for a in n.args.args]
            return (args[0] if args else None), len(args)
    return None


def _check(name):
    """Импорт check() по имени модуля. Поддерживает плоские имена (validate_*) и полные пути."""
    if "." in name:
        # Полный путь: ai_ops_kit.engops.session_boundary — загрузка по файлу, без sys.path.
        parts = name.split(".")
        rel = Path(*parts[1:])  # от корня пакета: engops/session_boundary
        fpath = PKG / "ai_ops_kit" / (rel.with_suffix(".py"))
        spec = importlib.util.spec_from_file_location(name, fpath)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.check
    return importlib.import_module(name).check


@pytest.mark.unit
def test_list_matches_reality():
    """Валидатор с тем же швом, не внесённый в список, остался бы вне контракта незамеченным."""
    discovered = set()
    for p in sorted((PKG / "ai_ops_kit" / "validation").glob("validate_*.py")):
        seam = _seam_of(p)
        if seam and seam[0] == "data" and seam[1] <= 2:
            discovered.add(p.stem)
    listed = set(UNIFORM_CHECK_VALIDATORS) | set(OTHER_SEAMS)
    missing = sorted(discovered - listed)
    stale = sorted(set(UNIFORM_CHECK_VALIDATORS) - discovered)
    assert not missing, f"валидаторы со швом check(data) вне контракта: {missing}"
    assert not stale, f"в списке есть исчезнувшие/сменившие шов: {stale}"


@pytest.mark.unit
def test_session_checks_match_reality():
    """Session-модуль с check() в engops/, не внесённый в список, остался бы вне контракта."""
    discovered = set()
    for p in sorted((PKG / "ai_ops_kit" / "engops").glob("session_*.py")):
        seam = _seam_of(p)
        if seam and seam[1] == 1:
            discovered.add(f"ai_ops_kit.engops.{p.stem}")
    listed = set(SESSION_CONTRACT_CHECKS)
    missing = sorted(discovered - listed)
    stale = sorted(listed - discovered)
    assert not missing, f"session-модули со швом check() вне контракта: {missing}"
    assert not stale, f"в списке есть исчезнувшие/сменившие шов: {stale}"


@pytest.mark.unit
@pytest.mark.parametrize("name", UNIFORM_CHECK_VALIDATORS)
class TestUniformCheckContract:

    def test_returns_list_of_strings(self, name):
        """Контракт формы: список строк. bool/None нельзя ни показать человеку, ни агрегировать."""
        out = _check(name)(dict(ALIEN))
        assert isinstance(out, list), f"{name}.check вернул {type(out).__name__}, ожидался list"
        assert all(isinstance(x, str) for x in out), f"{name}: в списке не только строки"

    def test_fail_closed_on_alien_artifact(self, name):
        """Валидатор, который молча принимает чужой артефакт, зеленит гейт вхолостую."""
        out = _check(name)(dict(ALIEN))
        assert out, f"{name}: чужой артефакт принят без единой ошибки"

    def test_messages_are_actionable(self, name):
        """Пустая строка вместо причины — та же тишина, только с ненулевым кодом возврата."""
        out = _check(name)(dict(ALIEN))
        assert all(len(x.strip()) >= 8 for x in out), f"{name}: есть пустые/обрывочные сообщения"


@pytest.mark.unit
@pytest.mark.parametrize("name,reason", sorted(OTHER_SEAMS.items()))
def test_other_seams_still_exist(name, reason):
    """Исключение на исчезнувший валидатор — мёртвая запись, она маскирует потерю покрытия."""
    assert (PKG / "ai_ops_kit" / "validation" / f"{name}.py").is_file(), f"{name} не найден ({reason})"


@pytest.mark.unit
@pytest.mark.parametrize("module_name", SESSION_CONTRACT_CHECKS)
class TestSessionCheckContract:
    """Контракт session check-функций — тот же шов, что у валидаторов (session-ritual-validators-are-dead)."""

    def test_returns_list_of_strings(self, module_name):
        """check() возвращает список строк — не bool/None/исключение."""
        out = _check(module_name)(dict(ALIEN))
        assert isinstance(out, list), f"{module_name}.check вернул {type(out).__name__}"
        assert all(isinstance(x, str) for x in out), f"{module_name}: в списке не только строки"

    def test_fail_closed_on_alien_artifact(self, module_name):
        """Session-модуль, молча принимающий чужой артефакт, зелёный вхолостую."""
        out = _check(module_name)(dict(ALIEN))
        assert out, f"{module_name}: чужой артефакт принят без единой ошибки"

    def test_messages_are_actionable(self, module_name):
        """Пустая строка вместо причины — тишина с ненулевым кодом."""
        out = _check(module_name)(dict(ALIEN))
        assert all(len(x.strip()) >= 8 for x in out), f"{module_name}: есть пустые/обрывочные сообщения"
