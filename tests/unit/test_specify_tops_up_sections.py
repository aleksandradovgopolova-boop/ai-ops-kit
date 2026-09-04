"""Повторный `specify` дописывает разделы под возросший уровень, а не отказывает про деньги.

ЗАМЕР, С КОТОРОГО НАЧАЛОСЬ (B2-26, третий прогон на втором brownfield 19.08.2026; ПОВТОР находки
15.08 — то есть класс жив уже второй раз). Прогон ENGINEERING остановился на `spec-prestage-failed`,
человек позвал `specify` заново с `size=medium`, и уровень описания НЕ поднялся: файл остался
`L0 QUICK` с шестью разделами. Причиной отказа кит назвал ЭКОНОМИЧЕСКИЙ ПОТОЛОК разбора.

ПОЧЕМУ ЭТО ДЕФЕКТ, А НЕ СРАБОТАВШИЙ ПОТОЛОК. Механизм дописывания разделов существует с F-029 и
работает — до него просто не доходило управление: процессный гейт возвращал код 2 РАНЬШЕ. И отказ
при этом врал по существу: человек читает про 100 тысяч токенов, а дело было в двадцати
недостающих разделах. Дописывание разделов не тратит НИЧЕГО — `specify` детерминированный и модель
не зовёт вовсе, — то есть повод для потолка отсутствует по построению.

ГРАНИЦА ПРАВКИ ОХРАНЯЕТСЯ С ОБЕИХ СТОРОН: потолок продолжает ловить то, ради чего заведён — разбор
по кругу без единой правки кода, — и освобождение действует ТОЛЬКО для `specify` и ТОЛЬКО когда
дописывать действительно есть что.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.cli import ai_ops_cli as cli
from ai_ops_kit.engops import process_spend, session_telemetry
from ai_ops_kit.gates import spec_levels

QUICK = {"task_type": "QUICK", "size": "small", "risk": "low"}
RAISED = {"task_type": "PRODUCT", "size": "medium", "risk": "medium"}


class _Args:
    def __init__(self, wid="w1", as_json=False):
        self.feature = wid
        self.json = as_json
        self.full_process = False
        self.spend_ok = False


@pytest.fixture()
def child(tmp_path):
    root = tmp_path / "child"
    root.mkdir()
    for c in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
              ["git", "config", "user.name", "T"]):
        subprocess.run(c, cwd=root, capture_output=True)
    (root / "a.txt").write_text("i\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=root, capture_output=True)
    return root


def _over_ceiling(root, wid, monkeypatch):
    """Расход сессии перевалил потолок владельца, кода никто не трогал — состояние из поля.

    Точка отсчёта и текущий замер — ОДНА живая сессия (`sess-1`): потолок мерит трату разбора в
    текущей сессии, и без общей личности сессии он бы (верно) не сработал — см. work-scoped-spend.
    """
    monkeypatch.setattr(session_telemetry, "snapshot",
                        lambda *a, **k: {"session_total_tokens": 200_000})
    monkeypatch.setattr(process_spend, "_session_id", lambda *a, **k: "sess-1")
    process_spend.record_step(root, wid, "specify", 100_000, session_id="sess-1")
    assert process_spend.assess(root, wid, "specify")["blocks"] is True, (
        "проба не дошла до дефекта: потолок не сработал, проверять было бы нечего")


# ─────────────── чистое чтение: чего не хватает под поднявшийся уровень ───────────────

def test_pending_sections_names_what_is_missing(child):
    spec_levels.create_spec(child, "w1", QUICK)
    p = spec_levels.pending_sections(child, "w1", RAISED)
    assert p["spec_exists"] and p["level_in_file"] == 0 and p["level_now"] == 2, p
    assert p["missing"], "уровень поднялся, а дописывать якобы нечего"
    assert "success_metrics" in p["missing"], p["missing"]


def test_pending_sections_writes_nothing(child):
    """Решение «применять ли потолок» не имеет права само менять артефакт."""
    sp, _, _ = spec_levels.create_spec(child, "w1", QUICK)
    before = sp.read_bytes()
    spec_levels.pending_sections(child, "w1", RAISED)
    assert sp.read_bytes() == before, "чтение изменило spec.yaml"


def test_pending_sections_is_empty_without_a_spec(child):
    """Контроль: первый разбор — не дописывание, освобождение к нему не относится."""
    assert spec_levels.pending_sections(child, "w1", RAISED)["missing"] == []


def test_pending_sections_is_empty_when_level_did_not_rise(child):
    """Контроль: уровень тот же — дописывать нечего, потолок работает как работал."""
    spec_levels.create_spec(child, "w1", QUICK)
    assert spec_levels.pending_sections(child, "w1", QUICK)["missing"] == []


# ─────────────── шов: процессный гейт перестал врать про деньги ───────────────

def test_ceiling_does_not_block_a_top_up(child, monkeypatch, capsys):
    """ШОВ, ровно тот прогон из поля: потолок пробит, уровень поднялся -> шаг делать МОЖНО."""
    spec_levels.create_spec(child, "w1", QUICK)
    _over_ceiling(child, "w1", monkeypatch)
    rc = cli._process_gate("specify", "поднять уровень", child, RAISED, _Args(), False)
    assert rc is None, f"процессный гейт всё ещё не пускает дописывание: код {rc}"
    out = capsys.readouterr().out
    assert "разделы" in out, f"человеку не сказали, что именно будет дописано: {out!r}"
    assert "потолок владельца" not in out, (
        f"отказ про деньги там, где дело в разделах, вернулся: {out!r}")


def test_specify_then_actually_raises_the_level(child, monkeypatch):
    """И это не разговор: после пропуска гейта разделы ДЕЙСТВИТЕЛЬНО дописываются, уровень растёт."""
    sp, _, _ = spec_levels.create_spec(child, "w1", QUICK)
    was = len(yaml.safe_load(sp.read_text(encoding="utf-8"))["sections"])
    _over_ceiling(child, "w1", monkeypatch)
    assert cli._process_gate("specify", "t", child, RAISED, _Args(), False) is None
    sp, created, rep = spec_levels.create_spec(child, "w1", RAISED)
    doc = yaml.safe_load(sp.read_text(encoding="utf-8"))
    assert created is False and rep["added"], rep
    assert doc["level"] == 2 and len(doc["sections"]) > was, (doc["level"], was)


# ─────────────── контроли: потолок ловит то, ради чего заведён ───────────────

def test_ceiling_still_blocks_a_description_loop(child, monkeypatch):
    """Контроль: разбор по кругу БЕЗ поднявшегося уровня потолок останавливает как раньше."""
    spec_levels.create_spec(child, "w1", QUICK)
    _over_ceiling(child, "w1", monkeypatch)
    assert cli._process_gate("specify", "ещё раз то же", child, QUICK, _Args(), False) == 2


def test_exemption_is_only_for_specify(child, monkeypatch):
    """Контроль: освобождение узкое. `discuss` при том же поднявшемся уровне потолок держит —
    он-то как раз и есть разбор, и стоит денег."""
    spec_levels.create_spec(child, "w1", QUICK)
    _over_ceiling(child, "w1", monkeypatch)
    assert cli._process_gate("discuss", "обсудим", child, RAISED, _Args(), False) == 2
