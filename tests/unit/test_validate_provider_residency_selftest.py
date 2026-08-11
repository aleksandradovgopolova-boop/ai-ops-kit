"""Селфтест validate_provider_residency, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_provider_residency import (  # noqa: F401 — имена, которые использует тело
    DEMO,
    SCHEMA,
    _load,
    _provider_classes,
    check,
    json,
    route_allowed,
)


@pytest.mark.slow
def test_validate_provider_residency_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    ex = json.loads(SCHEMA.read_text(encoding="utf-8"))["examples"][0]
    expect("пример из схемы валиден", check(ex) == [])
    if DEMO.is_dir():
        expect("реальный examples/residency-demo целостен",
               all(check(_load(f)) == [] for f in sorted(DEMO.glob("PRP-*.yaml"))))

    def _mut(dc, **over):
        rules = [dict(r) for r in ex["rules"]]
        for r in rules:
            if r["data_class"] == dc:
                r.update(over)
        return {**ex, "rules": rules}

    expect("secret в облако -> ошибка",
           any("секреты не в облако" in x for x in check(_mut("secret", allowed_provider_classes=["external-cloud"]))))
    expect("secret retention != zero -> ошибка",
           any("secret требует max_retention=zero" in x for x in check(_mut("secret",
               allowed_provider_classes=["on-premise"], max_retention="ephemeral"))))
    expect("confidential в external-cloud -> ошибка",
           any("external-cloud" in x for x in check(_mut("confidential",
               allowed_provider_classes=["external-cloud", "ru-cloud"]))))
    expect("confidential retention=standard -> ошибка",
           any("ephemeral" in x for x in check(_mut("confidential", max_retention="standard"))))
    expect("default_deny=false -> ошибка",
           any("default_deny" in x for x in check({**ex, "default_deny": False})))
    expect("класс без правила -> ошибка",
           any("нет правила residency" in x for x in check({**ex, "rules": ex["rules"][:3]})))

    # route_allowed
    expect("route: confidential -> external-cloud запрещён",
           route_allowed(ex, "confidential", "external-cloud") is False)
    expect("route: confidential -> on-premise разрешён",
           route_allowed(ex, "confidential", "on-premise") is True)
    expect("route: secret -> ru-cloud запрещён", route_allowed(ex, "secret", "ru-cloud") is False)

    # кросс-проверка против реального providers.yaml: ни один external-cloud провайдер не принимает secret
    pcs = _provider_classes()
    if pcs:
        bad = [pid for pid, cc in pcs.items()
               if cc != "on-premise" and route_allowed(ex, "secret", cc)]
        expect(f"реальные провайдеры: ни один не-on-premise не принимает secret ({len(pcs)} провайдеров)",
               bad == [])
        ext = [pid for pid, cc in pcs.items() if cc == "external-cloud"]
        expect(f"реальные external-cloud провайдеры не принимают confidential ({len(ext)})",
               all(route_allowed(ex, "confidential", pcs[p]) is False for p in ext))

    assert ok, "перенесённый селфтест validate_provider_residency: см. строки FAIL в выводе"


def _policy(secret_allowed=("on-premise",)):
    """Минимальная валидная PRP с настраиваемым allowed для класса secret."""
    return {
        "schema_version": 1, "kind": "ProviderResidencyPolicy", "id": "PRP-900",
        "default_deny": True,
        "rules": [
            {"data_class": "public", "allowed_provider_classes": ["external-cloud"],
             "max_retention": "standard"},
            {"data_class": "internal", "allowed_provider_classes": ["ru-cloud"],
             "max_retention": "standard"},
            {"data_class": "confidential", "allowed_provider_classes": ["on-premise"],
             "max_retention": "ephemeral"},
            {"data_class": "secret", "allowed_provider_classes": list(secret_allowed),
             "max_retention": "zero"},
        ],
    }


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
            "при неизвестном реестре проверка сделала вид, что выполнилась")

    def test_real_registry_is_readable(self):
        """`_provider_classes()` на реальном реестре отдаёт словарь, а не None."""
        pcs = _provider_classes()
        assert isinstance(pcs, dict) and pcs, f"реестр провайдеров не прочитан: {pcs!r}"
