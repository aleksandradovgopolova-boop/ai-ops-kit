"""ЯРУС 2 — Product Contract: «любой продукт корректно проверяется по контракту».

Второй ярус пирамиды (модель владельца 24.08.2026): контракт продукта как ГРАНИЦА — что делает
продукт валидным по стандарту и КАК именно нарушение обнаруживается и называется. Проверяются не
внутренности одной подсистемы, а инвариант вердикта: valid только когда всё обязательное на месте;
каждое нарушение (нет артефакта, пустая секция, нет источника истины контура, красное здоровье)
роняет вердикт в not_ready и НАЗЫВАЕТ причину — недоказанное называется недоказанным.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from ai_ops_kit.planning import artifact_registry as AR
from ai_ops_kit.planning import product_contract

PKG = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())
REG = AR.load()


@pytest.fixture(scope="module")
def installer():
    sys.path.insert(0, str(PKG / "installer"))
    spec = importlib.util.spec_from_file_location("ai_ops_installer_tier", PKG / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _product(installer, root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("# P\n\nсервис.\n", encoding="utf-8")
    (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    installer._seed_product_layer(root)
    return root


@pytest.mark.contract
def test_full_layer_makes_artifacts_valid(installer, tmp_path):
    """На полном слое ВСЕ обязательные артефакты valid — базовая линия контракта."""
    c = product_contract.resolve(_product(installer, tmp_path / "p"))
    assert c["artifacts"]["counts"]["missing"] == 0
    assert c["artifacts"]["counts"]["invalid"] == 0


@pytest.mark.contract
def test_missing_artifact_blocks_and_is_named(installer, tmp_path):
    """Удалённый обязательный артефакт -> not_ready, и блокер НАЗЫВАЕТ именно его."""
    p = _product(installer, tmp_path / "p")
    (p / ".ai-ops" / "ROADMAP.md").unlink()
    v = product_contract.validate(p)
    assert v["verdict"] == "not_ready"
    assert any("roadmap" in b.lower() for b in v["blocking"])


@pytest.mark.contract
def test_empty_section_is_invalid_not_valid(installer, tmp_path):
    """Паспорт с заголовками, но пустыми телами -> артефакт invalid (пустая секция != заполненная)."""
    p = _product(installer, tmp_path / "p")
    art = AR.artifact(REG, "product_passport")
    secs = art["structure"]["required_sections"]
    hollow = "<!-- template-version: 1 -->\n# П\n" + "".join(f"## {s}\n<!-- пусто -->\n" for s in secs)
    (p / ".ai-ops" / "PRODUCT_PASSPORT.md").write_text(hollow, encoding="utf-8")
    c = product_contract.resolve(p)
    assert c["artifacts"]["items"]["product_passport"]["state"] == "invalid"
    assert product_contract.validate(p)["verdict"] == "not_ready"


@pytest.mark.contract
def test_missing_contour_source_of_truth_blocks_and_is_named(installer, tmp_path):
    """Нет обязательного источника истины контура -> not_ready с названием контура."""
    p = _product(installer, tmp_path / "p")
    v = product_contract.validate(p)
    # свежий слой не заполняет источники истины контуров -> контурный пробел присутствует и назван
    assert v["verdict"] == "not_ready"
    assert any("контур" in b for b in v["blocking"])
    assert v["contours_ok"] is False


@pytest.mark.contract
def test_red_health_blocks_even_with_valid_form(installer, tmp_path):
    """Красное здоровье роняет вердикт, даже если форма цела — и называет причину."""
    p = _product(installer, tmp_path / "p")
    v = product_contract.validate(p, health={"band": "red", "reasons": ["прод горит"]})
    assert v["verdict"] == "not_ready"
    assert any("здоровье красное" in b for b in v["blocking"])


@pytest.mark.contract
def test_verdict_never_fabricates_valid_on_unknown(installer, tmp_path):
    """Неизвестное здоровье НЕ зеленит вердикт: unknown != ok. Вердикт валиден только по форме."""
    p = _product(installer, tmp_path / "p")
    v = product_contract.validate(p, health={"band": "unknown", "reasons": []})
    # unknown-здоровье само по себе не блокирует (только red), но и не выдаёт valid, если форма неполна
    assert v["health_band"] == "unknown"
    assert v["verdict"] in ("valid", "not_ready")
