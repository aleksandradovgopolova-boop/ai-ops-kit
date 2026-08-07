"""Селфтест repo_graph, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from repo_graph import (  # noqa: F401 — имена, которые использует тело
    Path,
    affected_tests,
    build_graph,
    impact,
)


@pytest.mark.slow
def test_repo_graph_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # синтетический репо: b<-a, test_b импортирует b
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "tools").mkdir()
        (root / "tools" / "b.py").write_text("def foo():\n    return 1\nclass Bar:\n    pass\n", encoding="utf-8")
        (root / "tools" / "a.py").write_text("import b\n\ndef use():\n    return b.foo()\n", encoding="utf-8")
        (root / "tools" / "test_b.py").write_text("import b\n\ndef test_foo():\n    assert b.foo()==1\n", encoding="utf-8")
        g = build_graph(root, ("tools",))
        expect("symbols извлечены (foo, Bar в b.py)",
               set(g["files"]["tools/b.py"]["symbols"]) == {"foo", "Bar"})
        expect("symbol_index: foo -> b.py", g["symbol_index"]["foo"] == ["tools/b.py"])
        expect("import-ребро a.py -> b.py", g["import_edges"]["tools/a.py"] == ["tools/b.py"])
        expect("тест-файл распознан (test_b.py -> b.py)", g["tests"].get("tools/test_b.py") == ["tools/b.py"])
        imp = impact(g, "tools/b.py")
        expect("impact(b.py) включает a.py и test_b.py (обратные зависимости)",
               "tools/a.py" in imp and "tools/test_b.py" in imp)
        expect("impact(a.py) пуст (никто не импортит a)", impact(g, "tools/a.py") == [])
        # v3.26.0: affected_tests
        at = affected_tests(g, ["tools/b.py"])
        expect("affected_tests(b.py) включает test_b.py", "tools/test_b.py" in at)
        at2 = affected_tests(g, ["tools/a.py"])
        expect("affected_tests(a.py) пуст (нет тестов, импортирующих a)", at2 == [])

    # v3.26.0: JS/TS парсинг
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src").mkdir()
        (root / "src" / "utils.ts").write_text("export function helper() { return 1; }\n", encoding="utf-8")
        (root / "src" / "main.ts").write_text("import { helper } from './utils';\nconsole.log(helper());\n", encoding="utf-8")
        (root / "src" / "utils.test.ts").write_text("import { helper } from './utils';\ntest('helper', () => expect(helper()).toBe(1));\n", encoding="utf-8")
        g = build_graph(root, ("src",))
        expect("JS: symbols извлечены (helper в utils.ts)", "helper" in g["files"]["src/utils.ts"]["symbols"])
        expect("JS: import-ребро main.ts -> utils.ts", "src/utils.ts" in g["import_edges"].get("src/main.ts", []))
        expect("JS: тест-файл распознан", "src/utils.test.ts" in g["tests"])
        at = affected_tests(g, ["src/utils.ts"])
        expect("JS: affected_tests(utils.ts) включает utils.test.ts", "src/utils.test.ts" in at)

    # дог-фуд: реальный граф кита (tools+validation), стабильные факты
    real = build_graph()
    expect(f"реальный граф кита строится без ошибок ({real['file_count']} файлов)",
           real["file_count"] > 50 and isinstance(real["symbol_index"], dict))
    imp_gp = impact(real, "tools/gate_policy.py")
    expect("impact(gate_policy) включает execution_pipeline и bench_lite (реальные импортёры)",
           "tools/execution_pipeline.py" in imp_gp and "tools/bench_lite.py" in imp_gp)
    expect("symbol_index покрывает известный символ (build_graph)",
           "build_graph" in real["symbol_index"])

    assert ok, "перенесённый селфтест repo_graph: см. строки FAIL в выводе"
