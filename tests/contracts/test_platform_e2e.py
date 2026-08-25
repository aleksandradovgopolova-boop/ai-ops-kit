"""ЯРУС 1 — Platform E2E: «AI Ops действительно может обслужить продукт».

Верхний ярус пирамиды тестов (модель владельца 24.08.2026): не механизм по отдельности, а весь путь
платформы над одним продуктом — от материализации слоя до карточки во флоте. Если этот ярус зелёный,
значит цепочка register -> contract -> fleet -> inspect держится как единая система, а не как набор
модулей, зелёных поодиночке. Ловит именно ШВЫ между подсистемами (класс дефектов «механизм работает,
но конвейер его не зовёт»).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from ai_ops_kit.planning import artifact_registry as AR
from ai_ops_kit.planning import product_contract, product_registry

PKG = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())
REG = AR.load()


@pytest.fixture(scope="module")
def installer():
    sys.path.insert(0, str(PKG / "installer"))
    spec = importlib.util.spec_from_file_location("ai_ops_installer_e2e", PKG / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _product(installer, root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# Niti\n\nсервис.\n", encoding="utf-8")
    (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    installer._seed_product_layer(root)
    return root


@pytest.mark.contract
def test_platform_serves_a_product_end_to_end(installer, tmp_path):
    """Полный путь платформы над продуктом одним прогоном — шов за швом."""
    prod = _product(installer, tmp_path / "niti")

    # 1. Материализованный слой -> артефакты стандарта valid (product_templates видит содержимое).
    contract = product_contract.resolve(prod)
    assert contract["kind"] == "product-contract"
    assert contract["artifacts"]["counts"]["valid"] == len(AR.artifacts(REG))

    # 2. Вердикт выносится и он ЧЕСТНЫЙ (valid или not_ready с причинами — не молчание).
    verdict = product_contract.validate(prod)
    assert verdict["verdict"] in ("valid", "not_ready")
    if verdict["verdict"] == "not_ready":
        assert verdict["blocking"], "not_ready без причин — молчание, а не вердикт"

    # 3. Регистрация в реестр флота — идемпотентный upsert, файл читается обратно валидным.
    reg = tmp_path / "products.yaml"
    res = product_registry.register(reg, prod)
    assert res["status"] == "created"
    assert product_registry.validate_registry(product_registry.load(reg)) == []

    # 4. Флот видит продукт, и его вердикт совпадает с прямым (реестр — не вторая правда).
    fleet = product_registry.fleet(reg)
    row = next(r for r in fleet["products"] if r["id"] == "niti")
    assert row["status"] == "ok"
    assert row["verdict"] == verdict["verdict"]

    # 5. Карточка по id даёт тот же контракт — цепочка замкнулась.
    ins = product_registry.inspect(reg, "niti")
    assert ins["status"] == "ok"
    assert ins["contract"]["artifacts"]["counts"] == contract["artifacts"]["counts"]


@pytest.mark.contract
def test_platform_is_honest_about_an_unonboarded_product(installer, tmp_path):
    """Продукт БЕЗ слоя платформа обслуживает честно: not_ready с названными пробелами, не падение
    и не выдуманное valid."""
    bare = tmp_path / "bare"
    bare.mkdir()
    v = product_contract.validate(bare)
    assert v["verdict"] == "not_ready"
    assert v["worst_artifact_state"] == "missing"
    assert v["blocking"]
    # и во флоте такой продукт — строка, а не исключение
    reg = tmp_path / "products.yaml"
    product_registry.register(reg, bare, pid="bare")
    assert any(r["id"] == "bare" for r in product_registry.fleet(reg)["products"])
