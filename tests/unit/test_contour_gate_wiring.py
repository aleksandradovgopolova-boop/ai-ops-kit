"""Гейт связности контуров ДОЛЖЕН БЫТЬ ВЫЗВАН — и его удаление обязано краснеть.

МУТАЦИОННОЕ РЕВЮ: тело вызова гейта в `execution_pipeline` было заменено на `pass`, и весь контур
остался зелёным (1678 passed). Головная находка релиза 3.35 — «гейт объявлен, а `reconcile` не
вызывается нигде» — была закрыта БЕЗ теста, то есть Proof of Fix на самом серьёзном дефекте не
исполнен. `grep contour_consistency tests/` давал одно попадание, и то в тесте presenter.

Здесь три уровня защиты:
  * присутствие — вызов есть в конвейере и evidence попадает в `gate_ev`;
  * поведение   — producer различает «описание отстало», «сверять нечего» и «инструмент недоступен»;
  * причина     — недостоверность реестра НЕ выдаётся за «изменений не предъявлено».
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_gate_is_actually_called_in_the_pipeline():
    """Вызов обязан присутствовать в `execution_pipeline` и писать evidence гейта.

    Проверяем не строкой в файле, а РАЗБОРОМ: есть вызов `contour_consistency_evidence` и есть
    присваивание в `gate_ev["contour_consistency"]`. Замена тела на `pass` краснеет здесь.
    """
    src = (PKG / "ai_ops_kit" / "engine" / "execution_pipeline.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "contour_consistency_evidence" in called, \
        "гейт связности контуров не вызывается в конвейере — его удаление прошло бы молча"
    assert 'gate_ev["contour_consistency"]' in src, \
        "evidence гейта не попадает в gate_ev, значит гейт не оценивается"


@pytest.mark.unit
def test_findings_reach_the_human_in_the_run_output():
    """ГЕЙТ, ЧЬИ НАХОДКИ НЕ ВИДНЫ, — ЭТО ГЕЙТ, КОТОРОГО НЕТ.

    Гейт исполнялся, считал находки и писал их в evidence, а вывод прогона о них молчал: «описание
    продукта отстало от кода» жило только в yaml-артефакте, который человек не открывает. Проверяем
    ПОВЕДЕНИЕ печати, а не наличие строки в файле.
    """
    from ai_ops_kit.engine import ai_ops_run
    import io
    import contextlib as _cl

    rep = {"kind": "execution-pipeline", "child_root": ".", "contour_consistency": {
        "status": "warn", "report": {
            "comparable": True, "derived": {},
            "findings": [{"id": "source_of_truth_behind", "contour": "data_contracts",
                          "severity": "major", "detail": "схема изменилась, openapi нет"}]}}}
    buf = io.StringIO()
    with _cl.redirect_stdout(buf):
        ai_ops_run._print_contour_consistency(rep)
    out = buf.getvalue()
    assert out.strip(), "находки гейта не напечатаны — человек о них не узнает"
    assert "описание" in out.lower(), out
    assert "source_of_truth_behind" not in out, "наружу вышло внутреннее имя находки"

    # Согласованный прогон отдельным блоком не шумит: вердикт прогона уже всё сказал.
    quiet = io.StringIO()
    with _cl.redirect_stdout(quiet):
        ai_ops_run._print_contour_consistency({"kind": "execution-pipeline", "child_root": ".",
                                               "contour_consistency": {"status": "pass", "report": {
                                                   "comparable": True, "derived": {}, "findings": []}}})
    assert quiet.getvalue().strip() == ""

    # Гейт не исполнялся — тишина (evidence уже сказал `warn`), но и не выдумываем «согласовано».
    none = io.StringIO()
    with _cl.redirect_stdout(none):
        ai_ops_run._print_contour_consistency({"kind": "execution-pipeline"})
    assert none.getvalue() == ""


@pytest.mark.unit
def test_pipeline_report_carries_the_findings():
    """Находки обязаны быть В ОТЧЁТЕ, иначе печатать нечего: разводка проверяется разбором."""
    src = (PKG / "ai_ops_kit" / "engine" / "execution_pipeline.py").read_text(encoding="utf-8")
    assert '"contour_consistency": contour_consistency' in src, \
        "полный отчёт гейта не попадает в отчёт прогона — до человека ему не дойти"
    # Печать вывода прогона вынесена из god-модуля ai_ops_run в ai_ops_run_print (v3.x):
    # разводку ищем там, где теперь живёт человекочитаемый вывод.
    printer = (PKG / "ai_ops_kit" / "engine" / "ai_ops_run_print.py").read_text(encoding="utf-8")
    tree = ast.parse(printer)
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_print_contour_consistency" in called, "печать находок не вызывается из вывода прогона"


@pytest.mark.unit
def test_gate_is_declared_where_it_is_counted():
    """Гейт объявлен в реестре и посчитан в публичном числе — иначе он существует только в коде."""
    import yaml
    gates = yaml.safe_load((PKG / "quality" / "gates.yaml").read_text(encoding="utf-8"))["gates"]
    assert "contour_consistency" in gates
    g = gates["contour_consistency"]
    assert g["blocking"] is False, "перевод в blocking — отдельное решение по данным обкаток"
    assert set(g["findings"]) >= {"source_of_truth_behind", "unknown_contour"}


@pytest.mark.unit
def test_producer_distinguishes_behind_from_nothing_to_compare(tmp_path):
    """`warn` при отставании описания, `warn` при отсутствии диффа, `pass` только когда сверено и сошлось."""
    from ai_ops_kit.engine import pipeline_evidence as PE
    (tmp_path / "context" / "system").mkdir(parents=True)
    (tmp_path / "context" / "system" / "DataMap.md").write_text("# д", encoding="utf-8")
    (tmp_path / "supabase" / "migrations").mkdir(parents=True)
    (tmp_path / "supabase" / "migrations" / "0006.sql").write_text("alter;", encoding="utf-8")

    behind = PE.contour_consistency_evidence(tmp_path, "w1", ["supabase/migrations/0006.sql"])
    assert behind["status"] == "warn"
    assert any("описание" in x or "source_of_truth_behind" in x for x in behind["evidence"])

    nothing = PE.contour_consistency_evidence(tmp_path, "w1", [])
    assert nothing["status"] == "warn", "«сверять нечего» — это не «согласовано»"

    together = PE.contour_consistency_evidence(
        tmp_path, "w1", ["supabase/migrations/0006.sql", "context/system/DataMap.md"])
    assert together["status"] == "pass"


@pytest.mark.unit
def test_failed_subprocess_is_not_reported_as_empty_diff(tmp_path, monkeypatch):
    """НАХОДКА РЕВЬЮ: producer звал подпроцесс с `check=False` и НЕ смотрел код возврата. При
    недостоверном реестре (`ModelCorrupt` внутри подпроцесса) он сообщал «изменений не
    предъявлено» — при том что файлы изменены. Битый реестр становился неотличим от пустого диффа:
    признание подменялось утверждением, ровно то, против чего вся модель.
    """
    import subprocess as sp
    from ai_ops_kit.engine import pipeline_evidence as PE

    class _Failed:
        returncode = 1
        stdout = ""
        stderr = "ОШИБКА: модель контуров не найдена"

    monkeypatch.setattr(PE.subprocess if hasattr(PE, "subprocess") else sp, "run",
                        lambda *a, **k: _Failed())
    ev = PE.contour_consistency_evidence(tmp_path, "w1", ["src/a.py"])
    assert ev["status"] == "warn"
    assert ev["report"] is None
    joined = " ".join(ev["evidence"]).lower()
    assert "не проведена" in joined, ev["evidence"]
    assert "изменений не предъявлено" not in joined, "сбой проверки выдан за пустой дифф"
