"""Канал обновлений ЧИТАЕТСЯ, а не только объявляется.

ПОВОД — ЗАМЕР (аудит 19.08.2026). `parent.update_channel` обязателен по
`schemas/child-config.schema.json`, `ai-ops init` писал его в КАЖДУЮ дочку со значением `stable`
— и не читала ни одна строка кода: `grep -rn update_channel` по всему репозиторию давал только
схему и пример. Одновременно `templates/ci/ai-ops-update.yml` делает `git clone --depth 1` ветки
по умолчанию, то есть приносит канал `edge`. Дочка объявляла самый строгий канал, получала самый
слабый, и никто ей об этом не говорил.

Класс тот же, что F-022 (`update_policy` обязателен, объявлен «silent_update: forbidden», обещан
владельцу вслух — и не читался): обязательное поле конфига без единого читателя.

Отдельно проверяется СЛОВАРЬ: до правки схема знала `[stable, beta]`, а
`registry/release-claims.yaml` — `edge | qualification | stable`. Слова `beta` не существовало
нигде, кроме перечисления в схеме. Две правды об одном вопросе — то же, что ни одной.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "installer"))

import ai_ops as installer  # noqa: E402 — путь ставится выше


@pytest.fixture()
def child(tmp_path, monkeypatch):
    """Дочка с конфигом, который можно переписывать по одному полю."""
    cfg = tmp_path / ".ai-ops.yaml"
    monkeypatch.setattr(installer, "CHILD_CONFIG", cfg, raising=False)

    def write(channel="stable"):
        body = {"schema_version": 1, "kind": "ai-ops-child-config",
                "parent": {"source": "git+https://example.invalid/kit.git",
                           "installed_version": "3.36.12", "update_channel": channel,
                           "update_policy": "pr"}}
        if channel is None:
            body["parent"].pop("update_channel")
        cfg.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
        return cfg
    return write


def _pkg_with_channel(tmp_path, channel):
    root = tmp_path / "pkg"
    (root / "registry").mkdir(parents=True, exist_ok=True)
    (root / "registry" / "release-claims.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "channel": channel}), encoding="utf-8")
    return root


@pytest.mark.unit
def test_vocabulary_is_one(tmp_path):
    """Схема дочки и реестр выпуска называют каналы ОДНИМИ словами."""
    schema = json.loads((PKG_ROOT / "schemas" / "child-config.schema.json").read_text(encoding="utf-8"))
    enum = schema["properties"]["parent"]["properties"]["update_channel"]["enum"]
    claims = yaml.safe_load((PKG_ROOT / "registry" / "release-claims.yaml").read_text(encoding="utf-8"))
    assert set(enum) == set(claims["channels"]), (
        f"словарь каналов разошёлся: схема {sorted(enum)}, реестр {sorted(claims['channels'])}")
    assert set(installer.CHANNEL_ORDER) == set(enum), "код знает не те каналы, что схема"


@pytest.mark.unit
def test_weaker_package_channel_is_named_not_swallowed(child, tmp_path):
    """Просили stable, пакет заработал qualification — это НАЗЫВАЕТСЯ, а не проходит молча."""
    child("stable")
    gap = installer.channel_gap(_pkg_with_channel(tmp_path, "qualification"))
    assert gap["satisfied"] is False
    assert "stable" in gap["message"] and "qualification" in gap["message"], gap["message"]


@pytest.mark.unit
def test_matching_channel_is_satisfied(child, tmp_path):
    child("qualification")
    assert installer.channel_gap(_pkg_with_channel(tmp_path, "qualification"))["satisfied"] is True


@pytest.mark.unit
def test_stronger_package_channel_satisfies_a_weaker_request(child, tmp_path):
    """Просили edge, дали stable — это не проблема: сильнее объявленного принять можно."""
    child("edge")
    assert installer.channel_gap(_pkg_with_channel(tmp_path, "stable"))["satisfied"] is True


@pytest.mark.unit
def test_unreadable_package_channel_is_unknown_not_ok(child, tmp_path):
    """«Не прочитали» — третье состояние, и оно не равно ни «подходит», ни «не подходит»."""
    child("stable")
    empty = tmp_path / "nopkg"
    empty.mkdir()
    gap = installer.channel_gap(empty)
    assert gap["satisfied"] is None, "непрочитанный реестр выдан за ответ"
    assert gap["offers"] is None
    assert "не знаю" in gap["message"] or "прочитать не удалось" in gap["message"]


@pytest.mark.unit
def test_missing_field_reads_as_the_strictest_channel(child, tmp_path):
    """Конфиг без обязательного поля — подозрительное состояние, а не разрешение на слабый канал."""
    child(None)
    assert installer.child_update_channel() == "stable"


@pytest.mark.unit
def test_the_shipped_example_declares_a_channel_the_package_can_give():
    """Заготовка не обещает того, чего пакет не отдаёт.

    Прежде в примере стоял `stable` и попадал в каждую установку, тогда как пакет объявлял
    `qualification`; владелец получал объявление строже реальности.
    """
    example = yaml.safe_load(
        (PKG_ROOT / "examples" / "child-config.example.yaml").read_text(encoding="utf-8"))
    asked = (example.get("parent") or {}).get("update_channel")
    offers = installer.package_channel(PKG_ROOT)
    assert asked in installer.CHANNEL_ORDER, f"в примере канал '{asked}' вне словаря"
    assert offers is not None, "канал пакета не прочитан"
    assert installer.CHANNEL_ORDER.index(offers) >= installer.CHANNEL_ORDER.index(asked), (
        f"заготовка просит '{asked}', а пакет заработал только '{offers}' — установка по этой "
        f"заготовке сразу даёт замечание, которое владелец не создавал")
