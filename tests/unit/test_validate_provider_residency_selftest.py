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
