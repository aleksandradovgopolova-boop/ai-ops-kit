"""Границы пакетов имеют силу, а не только имена (v3.32.0).

Переезд в `ai_ops_kit/*` (3.31.0) дал модулям осмысленные имена, но направление зависимостей не
проверял никто: `gates` мог импортировать `engops`, `shared` — что угодно, и это прошло бы молча.
`validate_layering.py` считает граф по коду и сверяет с `packages/layering.yaml`.

Замер на 3.31.1: 9 взаимных зависимостей и 119 циклов внутри ядра. Строгий DAG покраснел бы на
всём сразу — такое правило выключают. Поэтому запрещено то, что нарушено НЕ БЫВАЕТ сегодня и
должно остаться таким: security/ui выше фундамента, зависимости у `shared`, импорт `cli`/`devtools`.

Главный риск такой проверки — оказаться тавтологией: она зелёная, потому что запрещает лишь то,
чего и так нет. Поэтому большинство тестов ниже — про ЗУБЫ: подсунуть синтетический граф с
нарушением и убедиться, что оно поймано и названо.

Три обязательных теста на capability (AGENTS.md):
  * positive     — реальный граф репозитория чист по объявленным правилам;
  * fail-closed  — каждый класс нарушения ловится (вверх по слоям, shared-не-лист, импорт devtools,
                   пакет вне слоёв), и протухшее исключение из реестра тоже;
  * side-effect  — граф строится по РЕАЛЬНОМУ коду: и плоское имя, и пакетное дают ребро.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG / "validation"))

import validate_layering as vl  # noqa: E402


@pytest.fixture(scope="module")
def spec():
    return vl.load_spec()


def test_repository_graph_respects_declared_layers(spec):
    """positive: то, что есть в коде, укладывается в объявленные границы."""
    errors = vl.check(spec, vl.build_graph())
    assert not errors, "нарушения слоёв:\n  " + "\n  ".join(errors)


def test_every_package_is_placed_in_a_layer(spec):
    """Пакет без слоя — дыра в правиле: про него ничего нельзя ни запретить, ни разрешить."""
    declared = {p for layer in spec["layers"] for p in layer["packages"]}
    real = {d.name for d in (PKG / "ai_ops_kit").iterdir()
            if d.is_dir() and d.name != "__pycache__"}
    assert real == declared, f"вне слоёв: {sorted(real - declared)}; лишние: {sorted(declared - real)}"


@pytest.mark.parametrize("edge,expect", [
    (("security", "gates"), "ВВЕРХ"),        # primitives не вправе тянуть ядро
    (("ui", "engine"), "ВВЕРХ"),
    (("shared", "context"), "foundation-is-a-leaf"),
    (("gates", "devtools"), "no-product-depends-on-devtools"),
    (("engine", "cli"), "ВВЕРХ"),            # точку входа не импортирует никто
])
def test_forbidden_edge_is_caught(spec, edge, expect):
    """fail-closed: каждый класс нарушения обязан быть пойман и НАЗВАН."""
    errors = vl.check(spec, {edge: {"synthetic -> synthetic"}})
    assert errors, f"нарушение {edge[0]} -> {edge[1]} прошло молча — правило не работает"
    assert any(expect in e for e in errors), (
        f"нарушение поймано, но названо непонятно (ждали '{expect}'): {errors}")


def test_package_outside_layers_is_caught(spec):
    """fail-closed: новый пакет обязан быть объявлен, а не проскользнуть без правил."""
    errors = vl.check(spec, {("newpkg", "shared"): {"x -> y"}})
    assert any("вне слоёв" in e for e in errors), errors


def test_stale_known_violation_is_caught():
    """fail-closed: реестр исключений вправе только сокращаться.

    Разрешение, пережившее свою причину, — тихая ложь: следующий прочитает его как «так можно».
    """
    spec = dict(vl.load_spec())
    spec["known_violations"] = ["security -> gates: выдуманное, в коде такого нет"]
    errors = vl.check(spec, vl.build_graph())
    assert any("исчезло из кода" in e for e in errors), (
        "протухшее исключение не поймано — реестр превратится в кладбище")


def test_graph_sees_both_import_styles(tmp_path):
    """side-effect: ребро появляется и от плоского имени, и от пакетного.

    Переход на пакетные имена идёт отдельным срезом; проверка не вправе ослепнуть на полпути.
    """
    surface = tmp_path / "ai_ops_kit"
    (surface / "alpha").mkdir(parents=True)
    (surface / "beta").mkdir(parents=True)
    (surface / "beta" / "target.py").write_text("X = 1\n", encoding="utf-8")
    (surface / "alpha" / "flat.py").write_text("import target\n", encoding="utf-8")
    (surface / "alpha" / "qualified.py").write_text(
        "from ai_ops_kit.beta.target import X\n", encoding="utf-8")

    edges = vl.build_graph(surface)
    who = edges.get(("alpha", "beta"), set())
    assert any("flat" in w for w in who), f"плоский импорт не дал ребра: {edges}"
    assert any("qualified" in w for w in who), f"пакетный импорт не дал ребра: {edges}"
