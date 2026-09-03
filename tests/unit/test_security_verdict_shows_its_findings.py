"""Отчёт прогона показывает САМИ находки безопасности, а не только имена заблокированных доменов.

ЗАМЕР 18.08.2026 на 3.36.12 и на живом отчёте дочки ИИ-Среда от 17.08: в `run-report.json` писались
ровно четыре поля (`overall`, `applicable_domains`, `blocking`, `needs_review`), а `domain_results` —
где лежат САМИ находки (`path`, `line`, класс) и `applies_because` (почему домен вообще применён) —
не попадали ВОВСЕ. Проверено чтением настоящего отчёта: `domain_results` = None.

ПОЧЕМУ ЭТО ДЕФЕКТ, А НЕ ЭКОНОМИЯ МЕСТА: гейт говорит человеку «блокирующие домены (critical/high
находки)» и ОТПРАВЛЯЕТ ЕГО В ОТЧЁТ. Находок в отчёте нет — значит утверждение гейта непроверяемо из
того артефакта, на который он сам ссылается. Ровно отсюда родилась заявка «блокирует без единой
находки»: человек прочитал отчёт и находок не увидел.

ГРАНИЦА, КОТОРУЮ ЭТИ ТЕСТЫ ОХРАНЯЮТ С ДВУХ СТОРОН: находка это ПУТЬ, СТРОКА И КЛАСС — но никогда
значение. Отчёт лежит в репозитории и уезжает в PR, поэтому секрет в нём был бы вынесенным секретом.
Поэтому проверяется и «находки видны», и «значения секрета в отчёте нет ни в каком виде».
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from ai_ops_kit.engine import execution_pipeline
from ai_ops_kit.security import security_pack

# НЕ канонический пример AWS: `AKIAIOSFODNN7EXAMPLE` — документированный публичный
# образец, и с 19.08.2026 детектор его НЕ считает утечкой (он и не утечка). Позитивная
# фикстура обязана выглядеть как настоящий ключ, иначе она проверяет не то.
AWS_KEY = "AKIA" + "QRSTUVWX9012YZAB"


def _init_git(root: Path):
    subprocess.run(["git", "init", "-q"], cwd=root, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=root, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, capture_output=True)
    (root / "dummy.txt").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, capture_output=True)


# ─────────────────────── проекция: белый список полей ───────────────────────

def test_projection_carries_findings_and_reasons():
    """Находки и ОСНОВАНИЯ применимости домена доходят до отчёта — иначе вердикт непроверяем."""
    res = security_pack.run_pack(files_content={"src/leak.py": f'KEY = "{AWS_KEY}"\n'}, signals={})
    rep = security_pack.for_report(res)
    assert rep["overall"] == "blocked" and rep["blocking"]
    blocking = [d for d in rep["domain_results"] if d["domain"] in rep["blocking"]]
    assert blocking, rep["domain_results"]
    assert any(f.get("path") == "src/leak.py" and f.get("line") == 1
               for d in blocking for f in d["findings"]), blocking
    assert all(d["applies_because"] for d in blocking), "домен применён без названного основания"


def test_projection_never_carries_the_secret_value():
    """БЕЛЫЙ СПИСОК, а не «уберём лишнее»: поле со значением в отчёт не попадает само по себе."""
    res = security_pack.run_pack(files_content={"src/leak.py": f'KEY = "{AWS_KEY}"\n'}, signals={})
    for r in res["results"]:
        for f in r["findings"]:
            f["value"] = AWS_KEY          # будущее поле находки, принесшее значение
            f["snippet"] = f'KEY = "{AWS_KEY}"'
    rep = security_pack.for_report(res)
    dumped = json.dumps(rep, ensure_ascii=False)
    assert AWS_KEY not in dumped, "значение секрета уехало в проекцию отчёта"
    assert "snippet" not in dumped and "value" not in dumped


def test_projection_survives_degraded_verdict():
    """На путях деградации вердикт бывает формы {'overall': 'error'} — проекция доносит ЭТО, не падает."""
    rep = security_pack.for_report({"overall": "error"})
    assert rep["overall"] == "error"
    assert rep["domain_results"] == [] and rep["blocking"] == []
    assert security_pack.for_report(None) is None


def test_projection_names_the_scan_scope():
    """Охват рядом с вердиктом: «clear» по пустому дифу и «clear» по проверенному выглядят одинаково."""
    res = security_pack.run_pack(files_content={"a.py": "x = 1\n"}, signals={})
    assert security_pack.for_report(res)["scan_scope"] == res["scan_scope"]


# ─────────────────────── шов: отчёт прогона ───────────────────────

@pytest.mark.critical_path
def test_run_report_shows_the_findings_behind_the_block(tmp_path):
    """ШОВ: прогон с настоящим секретом -> в ОТЧЁТЕ видны находка (путь+строка) и основание домена.
    Прежде здесь были только имена заблокированных доменов, и вердикт нельзя было перепроверить."""
    root = tmp_path / "child"
    root.mkdir()
    _init_git(root)
    from ai_ops_kit.engine import tool_broker
    ops = iter([{"op": "write", "path": "src/leak.py", "content": f'KEY = "{AWS_KEY}"\n'}, {"done": True}])
    report = execution_pipeline.run_pipeline(
        task="secret test", signals={"task_type": "ENGINEERING", "size": "small",
                                     "risk": "medium", "affected_areas": ["core"]},
        child_root=root, proposer=lambda ctx: next(ops),
        policy=tool_broker.Policy(level="execution", write_scope=["src/"]),
        budget={"max_model_calls": 10}, feature="sec-findings", commit=True, isolate=True,
        install_deps=False)
    sec = report["security_scan"]
    assert sec is not None and "secrets" in sec["blocking"]
    blocking = [d for d in sec["domain_results"] if d["domain"] in sec["blocking"]]
    assert blocking, sec["domain_results"]
    assert any(f.get("path", "").endswith("src/leak.py") and f.get("line") == 1
               for d in blocking for f in d["findings"]), blocking
    assert all(d["applies_because"] for d in blocking)
    assert sec["scan_scope"]["mode"] == "diff", sec["scan_scope"]
    # и ни одного значения секрета во ВСЁМ отчёте — он уезжает в PR
    assert AWS_KEY not in json.dumps(report, ensure_ascii=False, default=str)


def test_gate_blocker_is_checkable_from_the_report(tmp_path):
    """Гейт называет блокирующие домены и посылает в отчёт — в отчёте по каждому из них есть находки."""
    root = tmp_path / "child"
    root.mkdir()
    _init_git(root)
    from ai_ops_kit.engine import tool_broker
    ops = iter([{"op": "write", "path": "src/leak.py", "content": f'TOKEN = "{AWS_KEY}"\n'}, {"done": True}])
    report = execution_pipeline.run_pipeline(
        task="secret gate", signals={"task_type": "ENGINEERING", "size": "small",
                                     "risk": "medium", "affected_areas": ["core"]},
        child_root=root, proposer=lambda ctx: next(ops),
        policy=tool_broker.Policy(level="execution", write_scope=["src/"]),
        budget={"max_model_calls": 10}, feature="sec-gate", commit=True, isolate=True,
        install_deps=False)
    assert "security" in report["gates"]["unmet"]
    sec = report["security_scan"]
    by_domain = {d["domain"]: d for d in sec["domain_results"]}
    for dom in sec["blocking"]:
        assert by_domain.get(dom, {}).get("findings"), f"домен {dom} блокирует, а находок в отчёте нет"


def test_sequential_aggregate_carries_the_findings_too(tmp_path):
    """ТА ЖЕ БОЛЕЗНЬ НА ПОСЛЕДОВАТЕЛЬНОМ ПУТИ: наружу уходил только `security_overall`, и человек,
    которому гейт назвал блокирующие домены, не мог увидеть ни одной находки. Проверяется на
    `_aggregate_verify` напрямую — это и есть место, где агрегатный вердикт становится ответом."""
    from ai_ops_kit.engine import workpackage_executor as wpe
    root = tmp_path / "child"
    root.mkdir()
    _init_git(root)
    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                              text=True).stdout.strip()
    (root / "src").mkdir()
    (root / "src" / "leak.py").write_text(f'KEY = "{AWS_KEY}"\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "работа пакета"], cwd=root, capture_output=True)
    final_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                               text=True).stdout.strip()

    agg = wpe._aggregate_verify(root, "seq-findings", False, final_sha, None, base_sha,
                                {"task_type": "ENGINEERING", "affected_areas": ["core"]},
                                None, False, False)
    assert agg["verified"] is True, agg
    assert agg["security_overall"] == "blocked", agg["security_overall"]
    sec = agg["security_scan"]
    assert sec is not None, "агрегатный вердикт снова без находок"
    assert "secrets" in sec["blocking"]
    assert any(f.get("path", "").endswith("src/leak.py")
               for d in sec["domain_results"] for f in d["findings"]), sec["domain_results"]
    assert AWS_KEY not in json.dumps(agg, ensure_ascii=False, default=str)
