"""Названное меню стратегий обновления: резолвер называет выбор владельца и fail-closed на неизвестном.

ПОВОД (исход `products_pick_update_strategy_from_a_named_menu` + `delivery_modes_beyond_pr_and_manual_exist`).
До этого выбор доставки обновления жил в `update_policy: pr|manual` — два режима без имени и описания.
Теперь набор стратегий ОБЪЯВЛЕН в реестре (release-claims.yaml -> update_strategies) с описанием
каждой, а `resolve_update_strategy` читает выбор дочки и НАЗЫВАЕТ его. Проверяется:
  (positive) каждая стратегия из меню распознаётся резолвером;
  (fail-closed) неизвестная стратегия -> ошибка, НЕ тихий дефолт; auto-stable без stable-канала или
    без явного opt-in -> сообщается как НЕДОСТУПНАЯ (никакого применения);
  (side-effect) выбранная стратегия видна резолверу как человеко-сообщение (то же читает doctor).

★Резолвер только ЧИТАЕТ и называет — он не применяет обновление к репозиторию. auto-stable объявлена
свойством (требует stable + явный opt-in), а не поведением.★
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "installer"))

import version_ops as installer  # noqa: E402 — стратегии обновления переехали в под-хаб хаба


def _pkg(tmp_path, *, channel="qualification"):
    """Синтетический пакет с меню стратегий, повторяющим доставляемую декларацию."""
    root = tmp_path / "kit"
    (root / "registry").mkdir(parents=True)
    doc = {
        "schema_version": 1,
        "registry_type": "release-claims",
        "version": "1.0.0",
        "channel": channel,
        "channels": {"edge": {"requires": []}, "qualification": {"requires": []},
                     "stable": {"requires": []}},
        "update_strategies": {
            "pr": {"what": "PR на ревью владельца", "default": True},
            "manual": {"what": "владелец применяет сам"},
            "scheduled-batch": {"what": "группируются, один PR по расписанию"},
            "auto-stable": {"what": "автоприменение из stable",
                            "requires_channel": "stable", "enabled": False},
        },
    }
    (root / "registry" / "release-claims.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return root


def _choose(monkeypatch, name, *, opt_in=False):
    monkeypatch.setattr(installer, "child_update_strategy", lambda: name)
    monkeypatch.setattr(installer, "_child_strategy_opt_in", lambda: opt_in)


# ── positive: каждая стратегия из меню распознаётся ──────────────────────────────────────────────
@pytest.mark.unit
@pytest.mark.parametrize("name", ["pr", "manual", "scheduled-batch"])
def test_each_menu_strategy_is_recognized(tmp_path, monkeypatch, name):
    _choose(monkeypatch, name)
    r = installer.resolve_update_strategy(_pkg(tmp_path))
    assert r["known"] is True and r["available"] is True
    assert r["error"] is None
    assert r["what"] and name in r["message"]


@pytest.mark.unit
def test_auto_stable_is_a_known_menu_strategy(tmp_path, monkeypatch):
    # Даже когда недоступна, она РАСПОЗНАНА как часть меню (known), а не отвергнута как неизвестная.
    _choose(monkeypatch, "auto-stable")
    r = installer.resolve_update_strategy(_pkg(tmp_path, channel="stable"))
    assert r["known"] is True
    assert r["requires_channel"] == "stable"


# ── fail-closed: неизвестная стратегия -> ошибка, НЕ тихий дефолт ─────────────────────────────────
@pytest.mark.unit
def test_unknown_strategy_is_an_error_not_a_silent_default(tmp_path, monkeypatch):
    _choose(monkeypatch, "yolo-autopilot")
    r = installer.resolve_update_strategy(_pkg(tmp_path))
    assert r["known"] is False and r["available"] is False
    assert r["error"] and "yolo-autopilot" in r["error"]
    # НЕ подменилось на pr: имя осталось выбранным, доступные названы.
    assert r["name"] == "yolo-autopilot"
    assert "pr" in r["error"] and "manual" in r["error"]


@pytest.mark.unit
def test_unreadable_menu_is_unknown_not_default(tmp_path, monkeypatch):
    _choose(monkeypatch, "pr")
    empty = tmp_path / "no-registry"
    empty.mkdir()
    r = installer.resolve_update_strategy(empty)
    assert r["known"] is None and r["available"] is None
    assert "не прочитано" in r["message"]


# ── fail-closed: auto-stable недоступна без stable-канала или без явного opt-in ───────────────────
@pytest.mark.unit
def test_auto_stable_unavailable_without_stable_channel(tmp_path, monkeypatch):
    _choose(monkeypatch, "auto-stable", opt_in=True)   # даже с opt-in — канал слабее stable
    r = installer.resolve_update_strategy(_pkg(tmp_path, channel="qualification"))
    assert r["known"] is True and r["available"] is False
    assert "канал" in r["message"] and "stable" in r["message"]


@pytest.mark.unit
def test_auto_stable_unavailable_without_explicit_opt_in(tmp_path, monkeypatch):
    _choose(monkeypatch, "auto-stable", opt_in=False)  # канал stable, но нет явного включения
    r = installer.resolve_update_strategy(_pkg(tmp_path, channel="stable"))
    assert r["available"] is False
    assert "opt_in" in r["message"] or "включите" in r["message"]


@pytest.mark.unit
def test_auto_stable_available_only_on_stable_with_opt_in(tmp_path, monkeypatch):
    _choose(monkeypatch, "auto-stable", opt_in=True)
    r = installer.resolve_update_strategy(_pkg(tmp_path, channel="stable"))
    assert r["known"] is True and r["available"] is True


# ── side-effect: дефолт и видимость выбора ────────────────────────────────────────────────────────
@pytest.mark.unit
def test_missing_choice_reads_as_pr_default(monkeypatch, tmp_path):
    # Отсутствие parent.update_strategy -> 'pr' (совместимость + дефолт меню).
    monkeypatch.chdir(tmp_path)   # нет .ai-ops.yaml
    assert installer.child_update_strategy() == "pr"


@pytest.mark.unit
def test_resolved_strategy_is_visible_as_a_human_line(tmp_path, monkeypatch):
    _choose(monkeypatch, "scheduled-batch")
    r = installer.resolve_update_strategy(_pkg(tmp_path))
    # То же сообщение печатает doctor — стратегия видна человеку по имени.
    assert r["message"].startswith("стратегия обновления")
    assert "scheduled-batch" in r["message"]


# ── доставляемая декларация реальна: меню несёт все 4 стратегии ───────────────────────────────────
@pytest.mark.unit
def test_shipped_registry_declares_the_full_menu():
    menu = installer.update_strategy_menu(PKG_ROOT)
    assert set(menu) == {"pr", "manual", "scheduled-batch", "auto-stable"}
    assert menu["pr"].get("default") is True
    assert menu["auto-stable"].get("requires_channel") == "stable"
    assert menu["auto-stable"].get("enabled") is False
    for name, props in menu.items():
        assert str(props.get("what") or "").strip(), f"стратегия {name} без описания"
