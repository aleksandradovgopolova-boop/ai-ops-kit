"""Гейт безопасности либо закрывается на уровне задачи, либо не блокирует её (B2-24, 19.08.2026).

ЗАМЕР, С КОТОРОГО НАЧАЛОСЬ. Третий прогон на втором brownfield дошёл до конца, сделал работу и
остановился на гейте `security` с `checks: []`, `evidence: []` и единственным блокером «нужен
независимый security-reviewer/человек». Диф — три файла, ни один из четырёх названных доменов им не
затронут: домены подняты СОВПАДЕНИЕМ ПО СОДЕРЖИМОМУ. На уровне QUICK судья выключен автоподбором
(`resolve_flags`), то есть закрыть требование было НЕЧЕМ: путь к `ready_for_pr` закрыт по
построению, а не по находке.

РАЗВИЛКА РЕШЕНА ЗАМЕРОМ НА 240 НАСТОЯЩИХ КОММИТАХ четырёх живых репозиториев (niti, ii-sreda,
msh_news_bot_v2, bolshe-ne-budu-menshe), а не вкусом:
  · «домен применим, находок ноль» — 184 прогона из 240;
  · из них в 148 КАЖДЫЙ такой домен поднят ТОЛЬКО содержимым — это 62% ВСЕХ прогонов;
  · вариант «поднимать судью на QUICK» стоил бы судьи на 7 из 10 мелких правок.
Выбран вариант «предупреждать, а не блокировать» — и обе половины названия работы закрыты:
  (1) НЕ БЛОКИРУЕТ: домен без находок, поднятый только содержимым, становится `advisory`;
  (2) ЗАКРЫВАЕТСЯ: домен, поднятый ПУТЁМ или СИГНАЛОМ, остаётся воротами, но теперь человеческое
      одобрение доступно и там, где судьи нет вовсе, — прежде ветка человека требовала `review`,
      которого на QUICK не бывает, и прогон падал в немой отказ.

ЧТО НЕ ОБСУЖДАЛОСЬ И ЗДЕСЬ ОХРАНЯЕТСЯ С ДВУХ СТОРОН: домен с находками critical/high блокирует
по-прежнему, а `advisory` — НЕ `clear`: «проверено чисто» и «проверять было нечего» обязаны
выглядеть по-разному, иначе цена правки превращается в ложный зелёный.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from ai_ops_kit.engine import execution_pipeline
from ai_ops_kit.security import security_pack

# НЕ канонический пример AWS: `AKIAIOSFODNN7EXAMPLE` — документированный публичный
# образец, и с 19.08.2026 детектор его НЕ считает утечкой (он и не утечка). Позитивная
# фикстура обязана выглядеть как настоящий ключ, иначе она проверяет не то.
AWS_KEY = "AKIA" + "QRSTUVWX9012YZAB"
# файл, чей ПУТЬ ни одному домену не соответствует, а содержимое ловится подстрокой
CONTENT_ONLY = {"src/reader.js": "const logger = console;\nconst route = '/x';\n"}


def _init_git(root: Path):
    subprocess.run(["git", "init", "-q"], cwd=root, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=root, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, capture_output=True)
    (root / "dummy.txt").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, capture_output=True)


# ─────────────── (1) не блокирует: догадка по подстроке — предупреждение ───────────────

def test_content_only_domain_without_findings_is_advisory():
    """Домен, поднятый ТОЛЬКО содержимым и без единой находки, уходит в `advisory`, не в ворота."""
    r = security_pack.run_pack(files_content=dict(CONTENT_ONLY), signals={})
    assert r["advisory"], f"ни один домен не стал предупреждением: {r}"
    assert r["needs_review"] == [], f"догадка по подстроке всё ещё держит ворота: {r['needs_review']}"
    assert r["blocking"] == [], r["blocking"]
    assert all(d["status"] == "advisory" for d in r["results"] if d["domain"] in r["advisory"])


def test_advisory_is_not_clear():
    """`advisory` — отдельный вердикт: иначе «проверено чисто» и «проверять было нечего» сольются."""
    r = security_pack.run_pack(files_content=dict(CONTENT_ONLY), signals={})
    assert r["overall"] == "advisory", r["overall"]
    clean = security_pack.run_pack(files_content={"README.txt": "hello\n"}, signals={})
    assert clean["overall"] == "clear" and clean["advisory"] == [], clean


def test_advisory_reaches_the_report():
    """Предупреждение обязано доехать до отчёта: не названное вслух — то же молчание."""
    r = security_pack.run_pack(files_content=dict(CONTENT_ONLY), signals={})
    rep = security_pack.for_report(r)
    assert rep["advisory"] == r["advisory"], rep
    by_domain = {d["domain"]: d for d in rep["domain_results"]}
    for dom in r["advisory"]:
        assert by_domain[dom]["status"] == "advisory"
        assert by_domain[dom]["applies_because"], "домен предупреждает без названного основания"


# ─────────────── контроли: настоящее основание воротами и осталось ───────────────

def test_path_raised_domain_is_still_a_gate():
    """Контроль: правка конвейера — основание НАСТОЯЩЕЕ, домен остаётся `needs_review`."""
    r = security_pack.run_pack(files_content={".github/workflows/deploy.yml": "on: push\n"}, signals={})
    assert "deployment_config" in r["needs_review"], r
    # `.get` намеренно: контроль обязан быть зелёным И ДО правки, иначе его краснота ничего не
    # говорит о поведении — она была бы про отсутствие нового ключа
    assert "deployment_config" not in r.get("advisory", []), "правка по пути ушла в предупреждения"


def test_signal_raised_domain_is_still_a_gate():
    """Контроль: домен, поднятый СИГНАЛОМ задачи, воротами и остаётся — сигнал не догадка."""
    r = security_pack.run_pack(files_content={"README.txt": "hello\n"},
                               signals={"auth_change": True, "authn_change": True,
                                        "secret_boundary_change": True, "deploy_change": True})
    assert r["needs_review"], f"сигнал перестал поднимать домен: {r}"
    assert r["overall"] in ("needs_review", "blocked"), r["overall"]


def test_findings_still_block_even_when_domain_was_raised_by_content():
    """ИНВАРИАНТ, который не обсуждался: находки critical/high блокируют независимо от основания."""
    r = security_pack.run_pack(files_content={"src/reader.js": f'const logger = "{AWS_KEY}";\n'},
                               signals={})
    assert r["blocking"], f"находка перестала блокировать: {r}"
    assert r["overall"] == "blocked", r["overall"]
    assert not (set(r["blocking"]) & set(r.get("advisory", []))), (
        "домен одновременно блокирует и предупреждает")


# ─────────────── шов: тот же выбор на настоящем прогоне QUICK ───────────────

def test_quick_run_is_not_closed_by_a_substring_guess(tmp_path):
    """ШОВ. Прогон QUICK, правка одного файла, домены подняты только содержимым, находок нет:
    гейт `security` больше НЕ в непройденных, а предупреждение названо в отчёте.

    Это ровно тот прогон, что упёрся в гейт 19.08: до правки здесь был `unmet: [security]`."""
    root = tmp_path / "child"
    root.mkdir()
    _init_git(root)
    from ai_ops_kit.engine import tool_broker
    ops = iter([{"op": "write", "path": "src/reader.js",
                 "content": "const logger = console;\nconst route = '/x';\n"}, {"done": True}])
    report = execution_pipeline.run_pipeline(
        task="проверка оглавления", signals={"task_type": "QUICK", "size": "small",
                                             "risk": "low", "affected_areas": ["core"]},
        child_root=root, proposer=lambda ctx: next(ops),
        policy=tool_broker.Policy(level="execution", write_scope=["src/"]),
        budget={"max_model_calls": 10}, feature="quick-advisory", commit=True, isolate=True,
        install_deps=False, review=False)
    sec = report["security_scan"]
    assert sec["overall"] == "advisory", sec["overall"]
    assert "security" not in report["gates"]["unmet"], report["gates"]["unmet"]
    assert sec["advisory"], "гейт пропустил, но предупреждение нигде не названо"


def test_quick_run_with_a_real_reason_says_how_to_close_it(tmp_path):
    """ШОВ второй половины. Домен поднят ПУТЁМ — ворота остаются, НО отказ называет,
    чем их закрыть, и говорит правду о судье.

    Прежде на QUICK ветка человеко-одобрения была недостижима (условие требовало `review`), и
    прогон падал в общий отказ без `pending_human` — человек читал «нужен независимый reviewer»
    и не имел ни одного способа его дать."""
    root = tmp_path / "child"
    root.mkdir()
    _init_git(root)
    from ai_ops_kit.engine import tool_broker
    ops = iter([{"op": "write", "path": ".github/workflows/deploy.yml",
                 "content": "on: push\njobs: {}\n"}, {"done": True}])
    report = execution_pipeline.run_pipeline(
        task="правка конвейера", signals={"task_type": "QUICK", "size": "small",
                                          "risk": "low", "affected_areas": ["core"]},
        child_root=root, proposer=lambda ctx: next(ops),
        policy=tool_broker.Policy(level="execution", write_scope=[".github/"]),
        budget={"max_model_calls": 10}, feature="quick-gate", commit=True, isolate=True,
        install_deps=False, review=False)
    assert "security" in report["gates"]["unmet"], report["gates"]["unmet"]
    sec_gate = next(g for g in (report["gates"]["gate_results"] or []) if g.get("gate") == "security")
    assert sec_gate["status"] == "fail", sec_gate
    text = json.dumps(sec_gate, ensure_ascii=False)
    # НАЗВАННАЯ КОМАНДА ОБЯЗАНА СУЩЕСТВОВАТЬ. Первая редакция этого отказа (PR #176) советовала
    # `ai-ops approve по домену` — такого intent в CLI НЕТ, и живой прогон 19.08 это показал. Совет,
    # которого нельзя выполнить, хуже отсутствия совета: человек считает, что путь есть.
    assert "approvals.py record" in text, f"отказ не называет, чем закрыть ворота: {text}"
    _named = re.search(r"python3 (\S+approvals\.py)", text)
    assert _named, text
    assert (PKG_ROOT / _named.group(1).replace(".ai/managed/", "")).is_file(), (
        f"отказ называет путь, которого нет: {_named.group(1)}")
    assert "выключен автоподбором" in text, (
        "причина отказа врёт про судью: на QUICK его не «нет квалифицированного», "
        f"его нет вовсе — {text}")
    # и это ИМЕННО ветка человека, а не общий отказ: общий говорил «нужен независимый
    # security-reviewer/человек» и не называл ни одного способа его дать
    assert "нужен независимый security-reviewer/человек по доменам" not in text, text
