"""Канал `stable` честен: либо достижим захватом field_evidence, либо ЯВНО «не предлагается».

ПОВОД — АУДИТ P1. `field_evidence` (записи «версия доехала до дочки и работает») НИКТО не пишет
автоматически: его вносит владелец руками по доверенному подтверждению. Значит при пустом или
неполном списке `stable` практически НЕДОСТИЖИМ. Раньше это было МОЛЧАЛИВО — дочка видела
объявленный канал stable, до которого нечем добраться, и не понимала, чего не хватает. `earned_channel`
тихо откатывал на qualification, не называя ЧЕГО не хватает.

Здесь проверяется, что недостижимость stable названа ЯВНО и с числами, а не подменена тишиной:
  (а) field_evidence < min_repos -> `stable_field_evidence_status.offered == False`, причина
      называет требование и ТЕКУЩИЙ счётчик; человеко-вывод (`channel_gap`) при запросе stable несёт
      тот же явный дефицит;
  (б) при достаточном field_evidence (>= min_repos валидных записей) stable ПРЕДЛАГАЕТСЯ;
  (в) FAIL-CLOSED: пустой field_evidence НЕ даёт stable (не регрессировали в фейк-stable).

★Функция только ЧИТАЕТ факт и объясняет дефицит; она не фабрикует field_evidence из слабого сигнала
(«прогон прошёл» ≠ «доехало до дочки и работает») — автозапись stable была бы F-002/F-005.★
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "installer"))

import ai_ops as installer  # noqa: E402 — путь ставится выше


def _pkg(tmp_path, *, version="1.2.0", evidence=(), min_repos=2):
    """Синтетический пакет с release-claims: channel=qualification (честно), но словарь channels
    объявляет stable с требованием field_evidence. Записи `evidence` — (repo, version, outcome)."""
    root = tmp_path / "kit"
    (root / "registry").mkdir(parents=True)
    doc = {
        "schema_version": 1,
        "registry_type": "release-claims",
        "version": version,
        "channel": "qualification",
        "channels": {
            "edge": {"requires": []},
            "qualification": {"requires": ["own_ci_green"]},
            "stable": {"requires": ["own_ci_green", "field_evidence"],
                       "field_evidence_min_repos": min_repos},
        },
        "field_evidence": [{"repo": r, "version": v, "outcome": o} for (r, v, o) in evidence],
    }
    (root / "registry" / "release-claims.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return root


# ── (в) FAIL-CLOSED: пустой field_evidence НЕ даёт stable ────────────────────────────────────────
@pytest.mark.unit
def test_empty_field_evidence_does_not_offer_stable(tmp_path):
    st = installer.stable_field_evidence_status(_pkg(tmp_path, evidence=()))
    assert st is not None
    assert st["offered"] is False
    assert st["have"] == 0
    # причина НАЗЫВАЕТ требование и текущий счётчик, а не молчит
    assert "не предлагается" in st["reason"].lower()
    assert "ни одного" in st["reason"]
    assert str(st["need"]) in st["reason"]


# ── (а) недостаточно (1 < 2): явный дефицит с текущим счётчиком ───────────────────────────────────
@pytest.mark.unit
def test_partial_field_evidence_names_the_deficit_with_counts(tmp_path):
    pkg = _pkg(tmp_path, version="1.2.3", evidence=[("child-a", "1.2.0", "ok")], min_repos=2)
    st = installer.stable_field_evidence_status(pkg)
    assert st["offered"] is False
    assert st["have"] == 1 and st["need"] == 2
    assert st["repos"] == ["child-a"]
    assert "child-a" in st["reason"] and "2" in st["reason"]
    # минор наследуется: 1.2.3 засчитывает обкатку 1.2.0
    assert st["minor"] == "1.2"


@pytest.mark.unit
def test_wrong_minor_or_bad_outcome_do_not_count(tmp_path):
    """Обкатка другого минора и запись с outcome != ok в счёт stable НЕ идут (fail-closed)."""
    pkg = _pkg(tmp_path, version="1.2.0", min_repos=2, evidence=[
        ("child-a", "1.1.0", "ok"),      # другой минор — не считается
        ("child-b", "1.2.0", "fail"),    # плохой исход — не считается
        ("child-c", "1.2.0", "ok"),      # засчитывается ровно один
    ])
    st = installer.stable_field_evidence_status(pkg)
    assert st["offered"] is False
    assert st["repos"] == ["child-c"] and st["have"] == 1


# ── (б) достаточно (>= min_repos): stable ПРЕДЛАГАЕТСЯ ───────────────────────────────────────────
@pytest.mark.unit
def test_sufficient_field_evidence_offers_stable(tmp_path):
    pkg = _pkg(tmp_path, version="1.2.1", min_repos=2, evidence=[
        ("child-a", "1.2.0", "ok"),
        ("child-b", "1.2.5", "ok"),
    ])
    st = installer.stable_field_evidence_status(pkg)
    assert st["offered"] is True
    assert st["have"] == 2 and sorted(st["repos"]) == ["child-a", "child-b"]
    assert "предлагается" in st["reason"].lower()


@pytest.mark.unit
def test_two_records_on_one_repo_are_one_proof(tmp_path):
    """Два прогона на ОДНОЙ дочке — одно доказательство, а не два: stable не заработан."""
    pkg = _pkg(tmp_path, version="1.2.0", min_repos=2, evidence=[
        ("child-a", "1.2.0", "ok"),
        ("child-a", "1.2.1", "ok"),
    ])
    st = installer.stable_field_evidence_status(pkg)
    assert st["offered"] is False and st["have"] == 1


# ── человеко-вывод: channel_gap при запросе stable несёт явный дефицит ───────────────────────────
@pytest.mark.unit
def test_channel_gap_surfaces_the_stable_deficit_to_a_human(tmp_path, monkeypatch):
    pkg = _pkg(tmp_path, version="1.2.0", min_repos=2, evidence=[("child-a", "1.2.0", "ok")])
    monkeypatch.setattr(installer, "child_update_channel", lambda: "stable")
    gap = installer.channel_gap(pkg)
    assert gap["satisfied"] is False
    # обобщённого «пакет заработал только qualification» уже недостаточно — назван и дефицит field_evidence
    assert "не предлагается" in gap["message"].lower()
    assert "child-a" in gap["message"]


@pytest.mark.unit
def test_channel_gap_stays_quiet_about_deficit_when_stable_is_earned(tmp_path, monkeypatch):
    """Если stable ЗАРАБОТАН, package_channel всё равно qualification (channel в реестре не поднят),
    но дочка на qualification удовлетворена — дефицит stable не приплетается не к месту."""
    pkg = _pkg(tmp_path, version="1.2.0", min_repos=2, evidence=[
        ("child-a", "1.2.0", "ok"), ("child-b", "1.2.0", "ok")])
    monkeypatch.setattr(installer, "child_update_channel", lambda: "qualification")
    gap = installer.channel_gap(pkg)
    assert gap["satisfied"] is True
    assert "не предлагается" not in gap["message"].lower()


# ── без требования field_evidence объяснять нечего -> None ───────────────────────────────────────
@pytest.mark.unit
def test_no_field_evidence_requirement_returns_none(tmp_path):
    root = tmp_path / "kit"
    (root / "registry").mkdir(parents=True)
    (root / "registry" / "release-claims.yaml").write_text(yaml.safe_dump({
        "registry_type": "release-claims", "version": "1.0.0", "channel": "edge",
        "channels": {"stable": {"requires": ["own_ci_green"]}},
    }, allow_unicode=True), encoding="utf-8")
    assert installer.stable_field_evidence_status(root) is None


# ── настоящий пакет кита: stable сегодня НЕ предлагается, и это названо явно (не тишина) ──────────
@pytest.mark.unit
def test_the_real_kit_states_stable_is_not_offered_explicitly():
    st = installer.stable_field_evidence_status(PKG_ROOT)
    # у настоящего кита stable требует field_evidence; статус обязан быть не-None и объяснимым
    assert st is not None
    assert isinstance(st["offered"], bool)
    assert st["need"] >= 1
    assert "минор" in st["reason"]
