"""Граф кода дочки — это ПРОДУКТ, а не кит в ней (F-022, корень; живой прогон niti 12.08).

ЧТО БЫЛО ВИДНО: в вывод прогона попадала строка `<unknown>:11: invalid escape sequence`. Источник
не назван даже интерпретатору, поэтому владелец не мог ни починить, ни осознанно пропустить.

ЧТО ОКАЗАЛОСЬ ПРИЧИНОЙ: предупреждение шло из СТАРОЙ копии самого кита —
`.ai/managed/tools/context_hybrid.py` версии 3.27.7, где докстринг ещё не был raw-строкой (свой
кит починил 08.08, коммитом 8f6aac4, но у дочки лежала копия ДО правки). Кит разбирал её как код
продукта, потому что `.ai/` не было в списке пропуска.

ЗАМЕР на niti (Next.js/Turborepo, собственного Python нет вовсе):
  Python  4094 файла в графе, из них 4094 внутри `.ai/` — 100%;
  JS/TS   2507 в графе, 1625 (64%) — копии дерева в `.ai/worktrees`, то есть каждый реальный файл
          продукта считался примерно трижды.
По этому графу считаются `impact()` и `affected_tests()` — «какие тесты задеты правкой».

Три обязательных теста на capability (AGENTS.md).
"""
from __future__ import annotations

import warnings

from repo_graph import _analyze, build_graph


def _child(tmp_path):
    """Дочка: свой код + область кита со всем, что там заводится на практике."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("import helper\n\n\ndef run():\n    pass\n",
                                                 encoding="utf-8")
    (tmp_path / "src" / "helper.py").write_text("def helped():\n    pass\n", encoding="utf-8")
    (tmp_path / "src" / "ui.ts").write_text("export const x = 1\n", encoding="utf-8")
    for rel in (".ai/managed/tools/context_hybrid.py",
                ".ai/runtime/backups/3.27.7/.ai/managed/tools/context_hybrid.py",
                ".ai/worktrees/fix-003/src/service.py"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('"""доставленная копия кита: v2 \\ v1"""\n\n\ndef delivered():\n    pass\n',
                     encoding="utf-8")
    w = tmp_path / ".ai" / "worktrees" / "fix-003" / "src" / "ui.ts"
    w.write_text("export const x = 1\n", encoding="utf-8")
    return tmp_path


def test_kit_area_is_not_product_code(tmp_path):
    """positive: ни один файл из `.ai/` не попадает в граф — ни Python, ни JS/TS."""
    graph = build_graph(_child(tmp_path), subdirs=None, include_js=True)
    # `graph["files"]` БЕЗ запасного пути: смена формы графа обязана уронить тест, а не
    # заставить его перебирать ключи верхнего уровня и проходить вхолостую.
    rels = list(graph["files"])
    inside = [r for r in rels if str(r).startswith(".ai/") or "/.ai/" in str(r)]
    assert not inside, f"область кита посчитана кодом продукта: {inside[:5]}"


def test_product_code_is_still_in_the_graph(tmp_path):
    """side-effect proof: исключили ЛИШНЕЕ, а не всё.

    Без этой проверки «починку» можно было бы получить, отфильтровав слишком широко: пустой граф
    тоже не содержит `.ai/`, и `affected_tests` на нём молчал бы — то есть ложное «ничего не
    задето» вместо шума. Пустой ответ опаснее шумного: он выглядит как проверенный.
    """
    graph = build_graph(_child(tmp_path), subdirs=None, include_js=True)
    rels = {str(r) for r in graph["files"]}
    assert any(r.endswith("src/service.py") for r in rels), f"код продукта потерян: {sorted(rels)}"
    assert any(r.endswith("src/helper.py") for r in rels), "второй модуль продукта потерян"
    assert any(r.endswith("src/ui.ts") for r in rels), "JS/TS продукта потерян"


def test_parse_warning_names_the_file(tmp_path):
    """границы: предупреждение интерпретатора называет ФАЙЛ, а не `<unknown>`.

    Это вторая половина находки и она нужна отдельно: даже когда разбирается законный файл продукта,
    сообщение обязано быть адресуемым. Глушить предупреждения нельзя — тогда пропали бы и настоящие.
    """
    bad = tmp_path / "legacy_tool.py"
    bad.write_text('"""путь c:\\ и разностью a \\ b"""\n', encoding="utf-8")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _analyze(bad)

    assert caught, "предупреждение исчезло — значит его заглушили, а не адресовали"
    named = [str(c.filename) for c in caught]
    assert all("<unknown>" not in n for n in named), f"источник не назван: {named}"
    assert any(str(bad) in n for n in named), f"назван не тот файл: {named}"
