"""Селфтест semantic_lite, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from semantic_lite import (  # noqa: F401 — имена, которые использует тело
    Path,
    build_index,
    search,
)


@pytest.mark.slow
def test_semantic_lite_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "repo").mkdir()
        # 'return' — частый токен (во всех файлах); 'rebate' — редкий (только в relevant).
        (root / "repo" / "relevant.py").write_text(
            "def f():\n    rebate = 1\n    return rebate\n", encoding="utf-8")
        (root / "repo" / "noise.py").write_text(
            "def g():\n    return 0\n    return 0\n    return 0\n    return 0\n", encoding="utf-8")
        (root / "repo" / "other.py").write_text(
            "def h():\n    return 1\n", encoding="utf-8")
        idx = build_index(root, ("repo",))
        # запрос 'return rebate': наивный подсчёт вхождений вывел бы noise (4x 'return') вперёд;
        # TF-IDF понижает частое 'return' и повышает редкое 'rebate' -> relevant.py первым.
        res = search(idx, "return rebate", k=3)
        top = [r["file"] for r in res]
        expect("TF-IDF: 'return rebate' -> relevant.py первым (редкое rebate > частого return)",
               top and top[0] == "repo/relevant.py")
        expect("noise.py (только частое 'return') ранжирован НИЖЕ relevant",
               "repo/noise.py" not in top or top.index("repo/noise.py") > top.index("repo/relevant.py"))
        # запрос только по редкому слову -> только файл с ним
        r2 = [x["file"] for x in search(idx, "rebate", k=3)]
        expect("запрос 'rebate' находит только relevant.py", r2 == ["repo/relevant.py"])
        expect("scores в (0,1]", all(0 < r["score"] <= 1.0001 for r in res))

    # дог-фуд: реальный индекс кита строится, известный запрос находит релевантное
    real = build_index()
    expect(f"реальный TF-IDF индекс кита строится ({real['n']} docs)", real["n"] > 50)
    rr = search(real, "budget contract enforcement", k=5)
    expect("запрос 'budget contract' находит budget-related файлы",
           any("budget" in r["file"] for r in rr))

    assert ok, "перенесённый селфтест semantic_lite: см. строки FAIL в выводе"
