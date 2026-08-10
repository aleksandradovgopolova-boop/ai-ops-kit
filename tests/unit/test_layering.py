"""Границы пакетов имеют силу, а не только имена (v3.32.0).

Переезд в `ai_ops_kit/*` (3.31.0) дал модулям осмысленные имена, но направление зависимостей не
проверял никто: `gates` мог импортировать `engops`, `shared` — что угодно, и это прошло бы молча.
`validate_layering.py` считает граф по коду и сверяет с `packages/layering.yaml`.

Замер: 9 взаимных зависимостей и 31 цикл длиннее двух внутри ядра. Строгий DAG покраснел бы на
всём сразу — такое правило выключают. Поэтому запрещено то, что нарушено НЕ БЫВАЕТ сегодня и
должно остаться таким: security/ui выше фундамента, зависимости у `shared`, импорт `cli`/`devtools`.
А то, что разрешено внутри ядра, с v3.34 держит ПОТОЛОК: `ratchet_errors` не даёт числу расти.

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
    (("gates", "intelligence"), "ВВЕРХ"),    # инвариант колец: Kernel не зависит от Intelligence
    (("engine", "intelligence"), "ВВЕРХ"),
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


def test_intelligence_may_read_the_kernel(spec):
    """Кольцо Intelligence ЧИТАЕТ события ядра — вниз по слоям, это разрешено.

    Инвариант односторонний. Запретить обе стороны значило бы отрезать аналитику от данных,
    ради которых она существует, и правило перестало бы описывать реальную архитектуру.
    """
    # known_violations вычищаем: синтетический граф из одного ребра не содержит замороженных
    # нарушений, и проверка «исключение исчезло» иначе заглушила бы то, ради чего тест написан.
    rules_only = dict(spec, known_violations=[])
    assert not vl.check(rules_only, {("intelligence", "gates"): {"x -> y"}}), \
        "аналитике запрещено читать ядро — правило описывает не ту архитектуру"


def test_rings_invariant_is_declared_verified(spec):
    """Инвариант объявлен проверяемым — и это утверждение обязано быть правдой.

    До v3.33.2 он честно значился `unverifiable_today`, потому что `lifecycle` держал и ядро, и
    аналитику. Объявить его проверенным, не имея границы, было бы ровно той ложной декларацией,
    которую кит запрещает сам себе.
    """
    verified = {v["id"] for v in (spec.get("verified_invariants") or [])}
    assert "kernel-does-not-depend-on-intelligence" in verified
    assert not (spec.get("unverifiable_today") or []), \
        "остались непроверяемые утверждения — они должны быть перечислены, а не забыты"
    layers = {l["name"]: i for i, l in enumerate(spec["layers"])}
    assert layers["intelligence"] > layers["capabilities"], \
        "слой intelligence обязан стоять ВЫШЕ ядра, иначе инвариант не выражен"


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


def test_graph_sees_every_import_style(tmp_path):
    """side-effect: ребро появляется от ЛЮБОЙ формы импорта, которой связывают модули.

    v3.33: форма `from ai_ops_kit.<пакет> import <модуль>` даёт module из ДВУХ частей. Проверка
    требовала трёх — и после перевода импортов увидела 4 ребра вместо 49, оставшись зелёной.
    Проверка, ослепшая на новой форме, хуже отсутствующей: она подтверждает границы, которых
    больше не видит.
    """
    surface = tmp_path / "ai_ops_kit"
    (surface / "alpha").mkdir(parents=True)
    (surface / "beta").mkdir(parents=True)
    (surface / "beta" / "target.py").write_text("X = 1\n", encoding="utf-8")
    (surface / "alpha" / "flat.py").write_text("import target\n", encoding="utf-8")
    (surface / "alpha" / "deep.py").write_text(
        "from ai_ops_kit.beta.target import X\n", encoding="utf-8")
    (surface / "alpha" / "shallow.py").write_text(
        "from ai_ops_kit.beta import target\n", encoding="utf-8")

    who = vl.build_graph(surface).get(("alpha", "beta"), set())
    for style in ("flat", "deep", "shallow"):
        assert any(style in w for w in who), f"форма '{style}' не дала ребра: {sorted(who)}"


def test_ratchet_is_green_on_the_real_repository(spec):
    """positive: замер в реестре совпадает с кодом, потолок не превышен."""
    errors = vl.ratchet_errors(spec, vl.build_graph())
    assert not errors, "ратчет циклов:\n  " + "\n  ".join(errors)


def test_cycle_count_is_independent_of_traversal_order():
    """side-effect: считаются РАЗЛИЧНЫЕ циклы, а не обходы.

    Это и есть дефект, найденный в 3.34: baseline хранил 119 — число ротаций, то есть каждый цикл
    посчитан по разу с каждой своей вершины. На треугольнике такое даёт 3 вместо 1. Величина,
    зависящая от способа обхода, потолком быть не может: следующий замер посчитает иначе и получит
    другой ответ на неизменном коде.
    """
    triangle = {("a", "b"): {"x -> y"}, ("b", "c"): {"x -> y"}, ("c", "a"): {"x -> y"}}
    assert vl.cyclic_counts(triangle)["cycles_longer_than_two"] == 1
    assert vl.cyclic_counts(triangle)["mutual_pairs"] == 0

    # Цикл и обратный ему — разные связи в коде, оба обязаны считаться.
    both = {**triangle, ("b", "a"): {"x -> y"}, ("c", "b"): {"x -> y"},
            ("a", "c"): {"x -> y"}}
    counts = vl.cyclic_counts(both)
    assert counts["cycles_longer_than_two"] == 2, counts
    assert counts["mutual_pairs"] == 3, counts


def test_ratchet_sees_the_real_graph(spec):
    """side-effect: доказать, что счёт меняется от РЕАЛЬНОГО графа, ПРЕЖДЕ чем верить реакции.

    Без этого шага тест «потолок не превышен» зелёный и на сломанном счётчике, всегда
    возвращающем ноль.
    """
    edges = vl.build_graph()
    base = vl.cyclic_counts(edges)
    assert base["mutual_pairs"] > 0 and base["cycles_longer_than_two"] > 0, base

    without = {e: w for e, w in edges.items() if e != ("gates", "providers")}
    after = vl.cyclic_counts(without)
    assert after["mutual_pairs"] == base["mutual_pairs"] - 1, (
        f"снятие реального ребра не изменило замер: {base} -> {after}")
    assert after["cycles_longer_than_two"] < base["cycles_longer_than_two"]


@pytest.mark.parametrize("key", ["mutual_pairs", "cycles_longer_than_two"])
def test_ratchet_catches_a_new_cycle(spec, key):
    """fail-closed: новая взаимная связь внутри ядра краснеет, хотя слоями она разрешена.

    `check` о таких рёбрах молчит намеренно — они внутри `capabilities`. Именно поэтому нужен
    потолок: без него «не запрещено» читается как «расти можно».
    """
    tightened = dict(spec, baseline=dict(spec["baseline"], **{key: spec["baseline"][key] - 1}))
    errors = vl.ratchet_errors(tightened, vl.build_graph())
    assert any(f"ратчет {key}" in e and "при потолке" in e for e in errors), errors


@pytest.mark.parametrize("declared", [None, "31", True, {}])
def test_ratchet_without_a_number_is_not_green(spec, declared):
    """fail-closed: потолок без числа — не «ограничений нет», а нечем проверять.

    Пустой или испорченный baseline обязан краснеть. Иначе достаточно стереть ключ, чтобы ратчет
    молча перестал существовать — ровно так опустошение registry/tracks.yaml проходило до #39.
    """
    broken = dict(spec, baseline={k: v for k, v in spec["baseline"].items()
                                 if k != "mutual_pairs"})
    if declared is not None:
        broken["baseline"] = dict(broken["baseline"], mutual_pairs=declared)
    errors = vl.ratchet_errors(broken, vl.build_graph())
    assert any("нет числа" in e for e in errors), (declared, errors)


def test_graph_covers_the_real_repository():
    """Страховка от тихой слепоты: связей между пакетами заведомо больше горстки.

    Точное число — предмет рефакторинга, а вот обвал до единиц означает, что сломался разбор,
    а не что код стал чище. Порог намеренно грубый: он ловит поломку парсера, а не колебания.
    """
    edges = vl.build_graph()
    assert len(edges) >= 20, (
        f"межпакетных рёбер всего {len(edges)} — так не бывает при 95 модулях; "
        "скорее всего разбор импортов перестал понимать используемую форму")
