"""Селфтест retrieval_bench, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from retrieval_bench import (  # noqa: F401 — имена, которые использует тело
    Path,
    run_bench,
)


@pytest.mark.slow
def test_retrieval_bench_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "repo").mkdir()
        # расширенный корпус (>= 15 golden кейсов): keyword / зависимость-без-слова / редкий термин /
        # RU/EN / multi-file / noise. TS/React и внешние доки — НЕ здесь (repo_graph/full-text
        # покрывают только Python); кросс-языковая квалификация — v3.6.6 на реальных child-репо.
        fixture = {
            "pricing.py": '"""apply discount pricing."""\ndef apply_discount(a):\n    return a*0.9\ndef total(a):\n    return a\n',
            "checkout.py": 'import pricing\n\ndef checkout(a):\n    return pricing.total(a)\n',   # зависит от pricing, без 'discount'
            "order.py": 'import checkout\n\ndef place():\n    return checkout.checkout(1)\n',
            "rebate.py": '"""rebate calculation."""\ndef rebate(a):\n    return a\n',            # редкий термин
            "auth.py": '"""authentication login token handling."""\ndef login(u, p):\n    return True\n',
            "session.py": 'import auth\n\ndef session():\n    return auth.login("a", "b")\n',      # зависит от auth, без 'login'
            "catalog.py": '"""product catalog listing."""\ndef list_items():\n    return []\n',
            "report.py": '"""weekly report generation."""\ndef report():\n    return {}\n',
            "skidka.py": '"""расчёт скидки на заказ (RU)."""\ndef primenit_skidku(s):\n    return s\n',  # RU термин 'скидк'
            "legacy.py": '"""DEPRECATED устаревшее решение по ценам."""\ndef old_pricing():\n    pass\n',
            "noise.py": 'def f():\n    return f()\ndef g():\n    return g()\n',
        }
        for name, content in fixture.items():
            (root / "repo" / name).write_text(content, encoding="utf-8")

        golden = [
            {"query": "discount", "relevant": ["repo/pricing.py", "repo/checkout.py"]},   # dep: checkout
            {"query": "pricing", "relevant": ["repo/pricing.py"]},
            {"query": "checkout", "relevant": ["repo/checkout.py"]},
            {"query": "total", "relevant": ["repo/pricing.py"]},
            {"query": "rebate", "relevant": ["repo/rebate.py"]},                            # редкий термин
            {"query": "login", "relevant": ["repo/auth.py"]},
            {"query": "token", "relevant": ["repo/auth.py"]},
            {"query": "session", "relevant": ["repo/session.py", "repo/auth.py"]},          # dep: auth
            {"query": "authentication", "relevant": ["repo/auth.py"]},
            {"query": "catalog", "relevant": ["repo/catalog.py"]},
            {"query": "report", "relevant": ["repo/report.py"]},
            {"query": "скидк", "relevant": ["repo/skidka.py"]},                             # RU
            {"query": "устаревшее", "relevant": ["repo/legacy.py"]},                        # RU deprecated
            {"query": "deprecated", "relevant": ["repo/legacy.py"]},                        # EN deprecated
            {"query": "order place", "relevant": ["repo/order.py"]},
            {"query": "quantum", "relevant": []},                                           # noise: нет релевантных
        ]

        rep = run_bench(root, golden, ("repo",))
        ft = rep["strategies"]["fulltext"]
        ga = rep["strategies"]["graph_augmented"]
        sm = rep["strategies"]["semantic_lite"]
        expect("корпус >= 15 кейсов (не smoke)", len(golden) >= 15)
        expect("все 3 стратегии: метрики в [0,1]",
               all(0 <= s["precision"] <= 1 and 0 <= s["recall"] <= 1 and 0 <= s["f1"] <= 1
                   for s in (ft, ga, sm)))
        expect("graph_augmented macro-recall >= fulltext (граф помогает на dep-кейсах)",
               ga["recall"] >= ft["recall"])
        # spot: dep-кейс 'discount' — граф находит checkout, full-text нет
        q0_ft = ft["per_query"][0]["retrieved"]
        q0_ga = ga["per_query"][0]["retrieved"]
        expect("dep-кейс: graph находит checkout.py, full-text — нет",
               "repo/checkout.py" in q0_ga and "repo/checkout.py" not in q0_ft)
        # spot: rebate — semantic_lite находит редкий термин
        q_reb = next(q for q in sm["per_query"] if q["query"] == "rebate")
        expect("редкий термин 'rebate' -> semantic_lite recall=1", q_reb["recall"] == 1.0)
        # spot: RU 'скидк' находит skidka.py хоть одной стратегией
        expect("RU-запрос 'скидк' -> найден skidka.py",
               any("repo/skidka.py" in q["retrieved"]
                   for s in (ft, ga, sm) for q in s["per_query"] if q["query"] == "скидк"))
        # spot: noise 'quantum' -> ничего релевантного (recall определён как 0 при пустом relevant)
        expect("noise 'quantum' -> все стратегии не выдают ложных релевантных",
               all(next(q for q in s["per_query"] if q["query"] == "quantum")["recall"] == 0.0
                   for s in (ft, ga, sm)))
        expect("best_by_f1 определён среди трёх стратегий",
               rep["best_by_f1"] in ("fulltext", "graph_augmented", "semantic_lite"))

    assert ok, "перенесённый селфтест retrieval_bench: см. строки FAIL в выводе"
