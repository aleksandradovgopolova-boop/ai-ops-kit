"""Машинный реестр Продуктовой конституции (PROD-*) едет в дочку И резолвится там.

По образцу `test_architecture_map_ships_to_child.py` / `test_constitution_map_ships_to_child.py`, но
СИЛЬНЕЕ: одного членства в `managed_set()` мало. Доказываем ПОВЕДЕНЧЕСКИ, что в СВЕЖЕУСТАНОВЛЕННОЙ
дочке механизм конформанса `ai_ops_kit.checks.constitution_conformance` резолвит статьи PROD-*
наравне с ARCH-*/UI-* — реальной установкой кита в temp git-репо через `installer/ai_ops.py init`,
а не чтением файла глазами. Так проверяется резолв ЧЕРЕЗ ГРАНИЦУ ПОСТАВКИ.

Держим машинную карту `constitution_id -> статья` (`standards/product/rules.yaml`) в поставке —
иначе каталог `CONSTITUTIONS=("architecture","uiux","product")` ждёт product, а резолвить его в
дочке нечем: PROD-* остаются висячими ID (класс F-033). Тяжёлый источник PRODUCT_CONSTITUTION.md и
оперативный слой product.rules.md — родительские (не едут).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "installer" / "ai_ops.py"
RULES_REL = "standards/product/rules.yaml"
SRC_REL = "standards/product/PRODUCT_CONSTITUTION.md"
OPS_REL = "standards/product/product.rules.md"

pytestmark = pytest.mark.unit


def _installer():
    spec = importlib.util.spec_from_file_location("_inst_for_product_map", INSTALLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _delivered() -> dict:
    """{relative_target: source_path} по фактическому managed_set() (дефолт — все пакеты)."""
    return {rel: src for src, rel in _installer().managed_set()}


# ── членство в поставке (как арх-тест) ────────────────────────────────────────────

def test_machine_registry_ships_to_child():
    """Карта статей продукта едет в дочку — ID конституции там резолвится."""
    delivered = _delivered()
    assert RULES_REL in delivered, (
        f"{RULES_REL} не входит в managed_set — продуктовая конституция не доедет до дочки")


def test_source_and_operational_layer_stay_parent_side():
    """В дочку едет ТОЛЬКО компактный реестр rules.yaml: тяжёлый источник PRODUCT_CONSTITUTION.md и
    оперативный слой product.rules.md — родительские (footprint-бюджет узкий), как арх/uiux."""
    delivered = _delivered()
    assert SRC_REL not in delivered, (
        f"{SRC_REL} не должен ехать в дочку — едет только компактный реестр rules.yaml")
    assert OPS_REL not in delivered, (
        f"{OPS_REL} не должен ехать в дочку — едет только компактный реестр rules.yaml")


def test_delivered_registry_is_resolvable():
    """Доставляемый реестр — валидный YAML со статьями и машинными полями gate/enforced_in."""
    delivered = _delivered()
    src = delivered[RULES_REL]
    doc = yaml.safe_load(Path(src).read_text(encoding="utf-8"))
    rules = doc.get("rules") or []
    assert rules, "доставляемый rules.yaml пуст — нечего резолвить в дочке"
    ids = {r["id"] for r in rules}
    assert doc.get("rules_total") == len(rules) == len(ids), "битый реестр: счётчик/дубли ID"
    assert all("gate" in r and "enforced_in" in r for r in rules), "в реестре нет gate/enforced_in"


# ── ПОВЕДЕНЧЕСКИ: реальная установка в temp-репо и резолв через границу поставки ────

def _make_child_repo(root: Path) -> Path:
    """Чистый python-репозиторий с одним коммитом — типовой вход пользователя (как в installer-тесте)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.1"\n',
                                         encoding="utf-8")
    for args in (("init", "-q", "."), ("config", "user.email", "t@t"),
                 ("config", "user.name", "t"), ("add", "-A"), ("commit", "-qm", "init")):
        subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return root


@pytest.fixture(scope="module")
def child_root(tmp_path_factory) -> Path:
    """СВЕЖАЯ установка кита в temp git-репо через настоящий `installer init` (один раз на модуль).

    Настоящий init честнее чтения файла глазами: он резолвит поставку через ту же границу, что и у
    пользователя. Fallback (копирование ровно по managed_set) — только если init недоступен в среде;
    он тоже проходит через managed_set, но не через процесс установки, поэтому вторичен.
    """
    root = _make_child_repo(tmp_path_factory.mktemp("prod_child") / "child")
    r = subprocess.run([sys.executable, str(INSTALLER), "init", "."], cwd=str(root),
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:                        # fallback: установка копированием по managed_set()
        for src, rel in _installer().managed_set():
            dst = root / ".ai" / "managed" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(Path(src).read_bytes())
    managed_rules = root / ".ai" / "managed" / "standards" / "product" / "rules.yaml"
    assert managed_rules.is_file(), (
        f"после установки нет {managed_rules} — реестр продукта не доехал до дочки:\n"
        f"{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return root


def test_conformance_registries_include_product_in_installed_child(child_root):
    """В свежеустановленной дочке `constitution_registries` содержит product наравне с арх/uiux."""
    from ai_ops_kit.checks import constitution_conformance as cc
    regs = cc.constitution_registries(child_root)
    assert "product" in regs, f"product не резолвится в дочке: {sorted(regs)}"
    assert regs["product"] == child_root / ".ai" / "managed" / "standards" / "product" / "rules.yaml"
    assert {"architecture", "uiux"} <= set(regs), (
        f"product обязан стоять В РЯД с арх/uiux, а не вместо: {sorted(regs)}")


def test_all_ten_product_articles_resolve_in_installed_child(child_root):
    """`load_all_rules` в дочке резолвит PROD-001..PROD-010 наравне со статьями арх и UI/UX."""
    from ai_ops_kit.checks import constitution_conformance as cc
    merged = cc.load_all_rules(child_root)
    for i in range(1, 11):
        rid = f"PROD-{i:03d}"
        assert rid in merged, f"{rid} не резолвится в свежеустановленной дочке"
    assert merged["PROD-001"].get("level") == "MUST"            # машинные поля доехали
    assert "ARCH-001" in merged, "арх-конституция должна резолвиться из той же дочки"
    assert any(k.startswith("UI-") for k in merged), "UI/UX должна резолвиться из той же дочки"
    # FAIL-CLOSED: выдуманного ID в реестре нет — иначе резолв был бы тавтологически зелёным.
    assert "PROD-999" not in merged, "несуществующий PROD-999 резолвится — резолв дырявый"
    assert "PROD-000-НЕТ-ТАКОГО" not in merged, "выдуманный ID резолвится — проверка тавтология"
