# -*- coding: utf-8 -*-
"""Поведенческие тесты извлечения операций tRPC-роутера (TypeScript) — вид `api` (E16, W2).

tRPC-роутер живёт в TS, а stdlib ast к TS неприменим → разбор ТЕКСТОМ/паттерном по исходнику (не
полноценным TS-парсером, без исполнения) → confidence по умолчанию `inferred`, а НЕ `verified`
(честность силы = честность confidence). Это ТРЕТИЙ носитель вида `api` (после GraphQL SDL E8 и
gRPC .proto E11).

Тесты ПОВЕДЕНЧЕСКИЕ: гоняем публичный `extract_surfaces` над деревом-фикстурой (classify_file →
поведение), а не зовём приватный экстрактор напрямую. Общие хелперы и исходники-фикстуры — в
`_surface_extraction_helpers.py`. Прочие api-носители (GraphQL/gRPC) и серверные стеки — в
`test_surface_extraction_backend.py`.
"""
from __future__ import annotations

import re

from ai_ops_kit.checks.surface_extraction import extract_surfaces
from ai_ops_kit.validation.validate_feature_registry import DEFAULT_SCHEMA, load_schema
from ai_ops_kit.validation.validate_feature_registry import _check_object

from _surface_extraction_helpers import (
    _TRPC_BROKEN,
    _TRPC_CREATE_ROUTER,
    _TRPC_FOREIGN,
    _TRPC_ROUTER,
    _REACT_JSX,
    _EXPRESS,
    _api_ops,
    _screen_paths,
    _route_paths,
    _write,
)


def test_trpc_procedures_are_api_operations_inferred(tmp_path):
    """query/mutation/subscription-процедуры роутера — операции продукта вида api, всегда inferred."""
    _write(tmp_path, "server/router.ts", _TRPC_ROUTER)
    surfaces = extract_surfaces(tmp_path)
    ops = _api_ops(surfaces, "trpc-router")
    assert {"getOrders", "createOrder", "onOrderUpdate"} <= ops
    for s in surfaces:
        if s["extractor"] == "trpc-router":
            assert s["kind"] == "api"
            assert s["confidence"] == "inferred"   # текстовый разбор TS НИКОГДА не verified
            assert s["ref"].startswith("server/router.ts:")


def test_trpc_mutation_and_subscription_are_operations(tmp_path):
    """mutation и subscription — такие же операции, как query (все три builder'а)."""
    _write(tmp_path, "server/router.ts", _TRPC_ROUTER)
    ops = _api_ops(extract_surfaces(tmp_path), "trpc-router")
    assert "createOrder" in ops       # .mutation(
    assert "onOrderUpdate" in ops     # .subscription(


def test_trpc_plain_field_is_not_an_operation(tmp_path):
    """Обычное поле объекта (meta: значение без .query/.mutation/.subscription) — НЕ операция."""
    _write(tmp_path, "server/router.ts", _TRPC_ROUTER)
    ops = _api_ops(extract_surfaces(tmp_path), "trpc-router")
    assert "meta" not in ops


def test_trpc_nested_router_gives_namespace(tmp_path):
    """Вложенный роутер (orders: t.router({…})) даёт namespace-префикс процедурам, сам ключ — не операция."""
    _write(tmp_path, "server/router.ts", _TRPC_ROUTER)
    ops = _api_ops(extract_surfaces(tmp_path), "trpc-router")
    assert {"orders.list", "orders.remove"} <= ops
    assert "orders" not in ops        # сам ключ вложенного роутера операцией не считается


def test_trpc_comments_and_strings_give_no_false_operations(tmp_path):
    """Текст ".query(" в строковом литерале и `//`-комментарий не порождают ложных операций."""
    _write(tmp_path, "server/router.ts", _TRPC_ROUTER)
    ops = _api_ops(extract_surfaces(tmp_path), "trpc-router")
    # Ровно шесть операций: три верхних + две вложенных namespace'а. Ни строка внутри createOrder,
    # ни комментарий не добавляют лишнего.
    assert ops == {"getOrders", "createOrder", "onOrderUpdate", "orders.list", "orders.remove"}


def test_trpc_create_router_and_string_literal_key(tmp_path):
    """createTRPCRouter({…}) распознан; строковый литеральный ключ ("with-dash") — операция."""
    _write(tmp_path, "server/cat.ts", _TRPC_CREATE_ROUTER)
    ops = _api_ops(extract_surfaces(tmp_path), "trpc-router")
    assert {"getAll", "with-dash"} <= ops


def test_trpc_computed_key_is_skipped(tmp_path):
    """Вычисляемый ключ `[DYN]:` (динамика) — НЕ операция (нелитеральный ключ)."""
    _write(tmp_path, "server/cat.ts", _TRPC_CREATE_ROUTER)
    ops = _api_ops(extract_surfaces(tmp_path), "trpc-router")
    assert not any("runtime" in o for o in ops)
    assert ops == {"getAll", "with-dash"}


def test_trpc_foreign_ts_without_indicator_is_empty(tmp_path):
    """Чужой .ts без индикатора tRPC (поле `router`, вызов `.query()`) не даёт операций."""
    _write(tmp_path, "hooks/useData.ts", _TRPC_FOREIGN)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "trpc-router"] == []


def test_trpc_react_component_ts_is_empty(tmp_path):
    """Обычный React/JSX .ts без индикатора tRPC — сужение критично: пусто по trpc-router."""
    src = (
        "import React from 'react';\n"
        "export const Panel = () => {\n"
        "  const opts = { path: '/home', router: true, query: 'x' };\n"
        "  return null;\n"
        "};\n"
    )
    _write(tmp_path, "ui/Panel.ts", src)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "trpc-router"] == []


def test_trpc_isolated_from_broken_files(tmp_path):
    """Битый .ts (незакрытый объект роутера) не валит прогон и не даёт фантомной операции."""
    _write(tmp_path, "server/router.ts", _TRPC_ROUTER)
    _write(tmp_path, "server/broken.ts", _TRPC_BROKEN)
    ops = _api_ops(extract_surfaces(tmp_path), "trpc-router")
    assert "getOrders" in ops                       # валидный роутер разобран
    assert not any("vanish" in o for o in ops)      # незакрытый объект пропущен


def test_trpc_does_not_break_other_stacks(tmp_path):
    """tRPC-роутер рядом с react-экраном и express-маршрутом: прочие стеки целы, api — отдельно."""
    _write(tmp_path, "server/router.ts", _TRPC_ROUTER)
    _write(tmp_path, "src/App.jsx", _REACT_JSX)
    _write(tmp_path, "server/http.ts", _EXPRESS)
    surfaces = extract_surfaces(tmp_path)
    # react screen целы
    assert "/billing" in _screen_paths(surfaces, "react-router")
    # express route целы (в .ts тоже применим — inferred route)
    assert "/health" in _route_paths(surfaces, "express")
    # tRPC api — свой вид
    assert "getOrders" in _api_ops(surfaces, "trpc-router")
    # express-файл сам по себе не даёт tRPC-операций (нет индикатора tRPC)
    assert not any(s["extractor"] == "trpc-router" and s["ref"].startswith("server/http.ts:")
                   for s in surfaces)


def test_trpc_records_conform_to_surface_schema(tmp_path):
    """Записи trpc-router валидны по той же схеме surface, что судит реестр, и по паттерну ref."""
    _write(tmp_path, "server/router.ts", _TRPC_ROUTER)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "trpc-router"]
    assert surfaces
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])
