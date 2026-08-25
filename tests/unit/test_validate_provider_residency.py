"""Гранулярные тесты validate_provider_residency (миграция из селфтеста v3.30)."""
from __future__ import annotations

import pytest

from validate_provider_residency import (  # noqa: F401
    DEMO,
    SCHEMA,
    _load,
    _provider_classes,
    check,
    json,
    route_allowed,
)


@pytest.fixture
def example_prp():
    """Пример из схемы."""
    return json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]


def _mut(ex, dc, **over):
    """Мутировать правило для указанного data_class."""
    rules = [dict(r) for r in ex["rules"]]
    for r in rules:
        if r["data_class"] == dc:
            r.update(over)
    return {**ex, "rules": rules}


@pytest.mark.unit
def test_schema_example_is_valid(example_prp):
    """Пример из схемы валиден."""
    assert check(example_prp) == []


@pytest.mark.unit
def test_real_residency_demo_is_consistent():
    """Реальный examples/residency-demo целостен."""
    if DEMO.is_dir():
        for f in sorted(DEMO.glob("PRP-*.yaml")):
            assert check(_load(f)) == [], f


@pytest.mark.unit
def test_secret_in_cloud_is_error(example_prp):
    """secret в облако -> ошибка."""
    errs = check(_mut(example_prp, "secret", allowed_provider_classes=["external-cloud"]))
    assert any("секреты не в облако" in x for x in errs), errs


@pytest.mark.unit
def test_secret_retention_not_zero_is_error(example_prp):
    """secret retention != zero -> ошибка."""
    errs = check(
        _mut(
            example_prp,
            "secret",
            allowed_provider_classes=["on-premise"],
            max_retention="ephemeral",
        )
    )
    assert any("secret требует max_retention=zero" in x for x in errs), errs


@pytest.mark.unit
def test_confidential_in_external_cloud_is_error(example_prp):
    """confidential в external-cloud -> ошибка."""
    errs = check(
        _mut(
            example_prp,
            "confidential",
            allowed_provider_classes=["external-cloud", "ru-cloud"],
        )
    )
    assert any("external-cloud" in x for x in errs), errs


@pytest.mark.unit
def test_confidential_retention_standard_is_error(example_prp):
    """confidential retention=standard -> ошибка."""
    errs = check(_mut(example_prp, "confidential", max_retention="standard"))
    assert any("ephemeral" in x for x in errs), errs


@pytest.mark.unit
def test_default_deny_false_is_error(example_prp):
    """default_deny=false -> ошибка."""
    errs = check({**example_prp, "default_deny": False})
    assert any("default_deny" in x for x in errs), errs


@pytest.mark.unit
def test_class_without_rule_is_error(example_prp):
    """Класс без правила -> ошибка."""
    errs = check({**example_prp, "rules": example_prp["rules"][:3]})
    assert any("нет правила residency" in x for x in errs), errs


# ── route_allowed ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_route_confidential_to_external_cloud_forbidden(example_prp):
    """route: confidential -> external-cloud запрещён."""
    assert route_allowed(example_prp, "confidential", "external-cloud") is False


@pytest.mark.unit
def test_route_confidential_to_on_premise_allowed(example_prp):
    """route: confidential -> on-premise разрешён."""
    assert route_allowed(example_prp, "confidential", "on-premise") is True


@pytest.mark.unit
def test_route_secret_to_ru_cloud_forbidden(example_prp):
    """route: secret -> ru-cloud запрещён."""
    assert route_allowed(example_prp, "secret", "ru-cloud") is False


# ── кросс-проверка против реальных провайдеров ───────────────────────────────────────────────────


@pytest.mark.unit
def test_real_providers_no_external_cloud_accepts_secret(example_prp):
    """Ни один external-cloud провайдер не принимает secret."""
    pcs = _provider_classes()
    if pcs:
        bad = [pid for pid, cc in pcs.items() if cc != "on-premise" and route_allowed(example_prp, "secret", cc)]
        assert bad == [], bad


@pytest.mark.unit
def test_real_external_cloud_providers_dont_accept_confidential(example_prp):
    """Реальные external-cloud провайдеры не принимают confidential."""
    pcs = _provider_classes()
    if pcs:
        ext = [pid for pid, cc in pcs.items() if cc == "external-cloud"]
        assert all(route_allowed(example_prp, "confidential", pcs[p]) is False for p in ext)


# ── TestDeclaredCrossCheckActuallyRuns ───────────────────────────────────────────────────────────


def _policy(secret_allowed=("on-premise",)):
    """Минимальная валидная PRP с настраиваемым allowed для класса secret."""
    return {
        "schema_version": 1,
        "kind": "ProviderResidencyPolicy",
        "id": "PRP-900",
        "default_deny": True,
        "rules": [
            {"data_class": "public", "allowed_provider_classes": ["external-cloud"], "max_retention": "standard"},
            {"data_class": "internal", "allowed_provider_classes": ["ru-cloud"], "max_retention": "standard"},
            {"data_class": "confidential", "allowed_provider_classes": ["on-premise"], "max_retention": "ephemeral"},
            {"data_class": "secret", "allowed_provider_classes": list(secret_allowed), "max_retention": "zero"},
        ],
    }


@pytest.mark.unit
class TestDeclaredCrossCheckActuallyRuns:
    """Проверка №5 из докстроки ИСПОЛНЯЕТСЯ валидатором, а не только селфтестом.

    Ревизия 2026-08-12: `route_allowed` и `_provider_classes` были написаны и объявлены пятым
    пунктом валидатора, но `check`/`main` их не звали — звал только этот файл. Заявленная проверка
    существовала как код и не исполнялась ни на одном прогоне.
    """

    def test_policy_with_no_routable_provider_is_caught(self):
        """Политика, не оставляющая классу ни одного провайдера, — неисполнима."""
        registry = {"anthropic": "external-cloud", "local": "on-premise"}
        # secret разрешён только в ru-cloud, а такого провайдера в реестре нет.
        errs = check(_policy(secret_allowed=["ru-cloud"]), provider_classes=registry)
        assert any("неисполнима" in x and "secret" in x for x in errs), errs

    def test_policy_with_routable_provider_passes(self):
        """Обратная сторона: пригодный провайдер есть -> нарушения нет."""
        registry = {"anthropic": "external-cloud", "local": "on-premise", "gigachat": "ru-cloud"}
        errs = check(_policy(), provider_classes=registry)
        assert not [x for x in errs if "неисполнима" in x], errs

    def test_unknown_registry_skips_check_instead_of_passing_it(self):
        """`None` — «реестр неизвестен»: проверка пропускается, а не объявляется пройденной.

        Прежде `_provider_classes()` отдавал `{}` на нечитаемом реестре, и кросс-проверка молча
        «не находила нарушений». Пустое и неизвестное — разные ответы.
        """
        errs = check(_policy(secret_allowed=["ru-cloud"]), provider_classes=None)
        assert not [x for x in errs if "неисполнима" in x], (
            "при неизвестном реестре проверка сделала вид, что выполнилась"
        )

    def test_real_registry_is_readable(self):
        """`_provider_classes()` на реальном реестре отдаёт словарь, а не None."""
        pcs = _provider_classes()
        assert isinstance(pcs, dict) and pcs, f"реестр провайдеров не прочитан: {pcs!r}"
