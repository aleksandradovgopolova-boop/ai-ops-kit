"""F-030: канал релиза зарабатывается, а не объявляется.

НАХОДКА (внешнее ревью 12.08.2026). Поле `channel` в `registry/release-claims.yaml` было
самообъявлением: его не проверял никто, и слово `stable` стоило ровно столько, сколько стоит слово.

Цена замерена в тот же день. Тег v3.36.9 вышел как `stable` и содержал P1 — F-022, политика
обновлений не исполнялась, — исправленный через час после релиза. Дочки при этом получают ИМЕННО тег,
а не `main`, то есть публичный статус «stable» был утверждением о том, чего не проверяли.

Теперь критерии каналов машиночитаемы (`channels`), а `stable` требует полевых доказательств на
нескольких РАЗНЫХ дочках для той же версии. Пустое `field_evidence` на свежем патче — нормальное
состояние и честный `qualification`.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
CLAIMS = KIT / "registry" / "release-claims.yaml"

sys.path.insert(0, str(KIT / "ai_ops_kit" / "validation"))
import validate_release_claims as vrc  # noqa: E402 — путь к валидатору кладём выше


def _data():
    return yaml.safe_load(CLAIMS.read_text(encoding="utf-8"))


def _with(**over):
    d = copy.deepcopy(_data())
    d.update(over)
    return d


# ─── fail-closed: stable без основания не проходит ───────────────────────────────────────────────
@pytest.mark.unit
def test_stable_without_field_evidence_is_rejected():
    errs = vrc.channel_errors(_with(channel="stable", field_evidence=[]))
    assert errs, "канал stable прошёл без полевых доказательств — вернулось самообъявление"
    assert "не заработан" in errs[0], errs
    assert "3.36" in errs[0] or _data()["version"] in errs[0], (
        "в ошибке нет версии — читающий не поймёт, для чего именно нужны доказательства")


@pytest.mark.unit
def test_one_repo_is_not_enough_when_two_required():
    """Два прогона на одной дочке — это ОДНО доказательство, а не два."""
    ver = _data()["version"]
    twice_same = [{"repo": "ii-sreda", "version": ver, "outcome": "ok"},
                  {"repo": "ii-sreda", "version": ver, "outcome": "ok"}]
    errs = vrc.channel_errors(_with(channel="stable", field_evidence=twice_same))
    assert errs and "ii-sreda" in errs[0], errs


@pytest.mark.unit
def test_evidence_for_another_version_does_not_count():
    """Обкатка ДРУГОГО минора не делает stable новую — иначе канал наследовался бы молча."""
    old = [{"repo": "ii-sreda", "version": "3.0.0", "outcome": "ok"},
           {"repo": "niti", "version": "3.0.0", "outcome": "ok"}]
    assert vrc.channel_errors(_with(channel="stable", field_evidence=old)), (
        "доказательства другого минора зачлись текущему")


@pytest.mark.unit
def test_evidence_from_an_earlier_patch_of_the_same_minor_counts():
    """Патч НАСЛЕДУЕТ обкатку своего минора: доказательства на X.Y.0 засчитываются для X.Y.Z —
    иначе каждый патч обнулял бы счётчик и stable был бы беговой дорожкой. РАЗВОДКА: при точной
    сверке по версии (дефект) этот тест краснел бы, ведь X.Y.0 != X.Y.Z."""
    ver = _data()["version"]
    mj, mn, *_rest = ver.split(".")
    earlier = f"{mj}.{mn}.0" if not ver.endswith(".0") else f"{mj}.{mn}.1"
    rows = [{"repo": "ii-sreda", "version": earlier, "outcome": "ok"},
            {"repo": "niti", "version": earlier, "outcome": "ok"}]
    assert vrc.channel_errors(_with(channel="stable", version=ver, field_evidence=rows)) == [], (
        "доказательства другого патча ТОГО ЖЕ минора обязаны засчитываться")


@pytest.mark.unit
def test_inheritance_is_bounded_to_the_minor():
    """Наследование — только ВНУТРИ минора: соседний минор X.(Y±1) для X.Y не годится (fail-closed)."""
    ver = _data()["version"]
    mj, mn, *_rest = ver.split(".")
    other = f"{mj}.{int(mn) - 1}.9" if int(mn) > 0 else f"{mj}.{int(mn) + 1}.9"
    rows = [{"repo": "a", "version": other, "outcome": "ok"},
            {"repo": "b", "version": other, "outcome": "ok"}]
    assert vrc.channel_errors(_with(channel="stable", version=ver, field_evidence=rows)), (
        "доказательства ДРУГОГО минора не должны зарабатывать stable")


@pytest.mark.unit
def test_failed_run_is_not_evidence():
    ver = _data()["version"]
    bad = [{"repo": "a", "version": ver, "outcome": "failed"},
           {"repo": "b", "version": ver, "outcome": "failed"}]
    assert vrc.channel_errors(_with(channel="stable", field_evidence=bad)), (
        "неудачный прогон зачтён как доказательство обкатки")


@pytest.mark.unit
def test_incomplete_evidence_row_is_named():
    """Запись без обязательного поля — не доказательство, и об этом надо сказать."""
    ver = _data()["version"]
    rows = [{"repo": "a", "version": ver, "outcome": "ok"}, {"repo": "b", "version": ver}]
    errs = vrc.channel_errors(_with(channel="stable", field_evidence=rows))
    assert any("outcome" in x for x in errs), errs


@pytest.mark.unit
def test_unknown_channel_is_rejected():
    assert vrc.channel_errors(_with(channel="ГОТОВО-НАВЕРНОЕ")), "непонятный канал прошёл молча"


@pytest.mark.unit
def test_channel_without_criteria_block_is_rejected():
    d = _data()
    d.pop("channels", None)
    assert vrc.channel_errors(d), "канал без объявленных критериев проверить нельзя — но прошёл"


# ─── positive: заработанный канал проходит ───────────────────────────────────────────────────────
@pytest.mark.unit
def test_two_distinct_repos_earn_stable(tmp_path, monkeypatch):
    # Канал stable теперь требует И полевые доказательства, И product_layer_ready — все 5 целей
    # Product OS достигнуты (ep-2026-08-20-stable-includes-product-operating-layer). Этот тест
    # проверяет ПОЛЕВУЮ половину, поэтому product-слой изолируем синтетическим планом со всеми целями
    # `achieved` (сам product-слой покрыт tests/contracts/test_stable_gate_includes_product_layer.py).
    # Иначе тест мерил бы обе половины сразу и падал бы из-за реального плана, где цели ещё не достигнуты.
    goals = ["product-operating-layer", "backlog-intelligence", "roadmap-and-delivery",
             "ai-product-operations", "autonomous-product-loop"]
    (tmp_path / "planning").mkdir()
    (tmp_path / "planning" / "plan.yaml").write_text(
        yaml.dump({"goals": [{"id": g, "status": "achieved"} for g in goals]}), encoding="utf-8")
    monkeypatch.setattr(vrc, "PKG", tmp_path)
    ver = _data()["version"]
    good = [{"repo": "ii-sreda", "version": ver, "outcome": "ok", "date": "2026-08-12"},
            {"repo": "niti", "version": ver, "outcome": "ok", "date": "2026-08-12"}]
    assert vrc.channel_errors(_with(channel="stable", field_evidence=good)) == []


@pytest.mark.unit
def test_qualification_does_not_require_field_evidence():
    """Иначе свежий патч нельзя было бы объявить честно вообще никак."""
    assert vrc.channel_errors(_with(channel="qualification", field_evidence=[])) == []


# ─── состояние репозитория: заявление совпадает с фактом ─────────────────────────────────────────
@pytest.mark.unit
def test_repository_claim_matches_its_own_criteria():
    assert vrc.channel_errors(_data()) == [], (
        "релизные заявления репозитория не выполняют собственные критерии канала")


@pytest.mark.unit
def test_docs_declare_the_actual_channel_not_a_hardcoded_word():
    """Шаблоны сверки версии берут канал из реестра, а не зашивают слово.

    Первое честное понижение канала до `qualification` сделало обе проверки слепыми — валидатор сам
    это и сказал. Зашитое слово в регулярке дублировало реестр; дубль стоил слепоты.
    """
    rules = _data().get("authoritative_version") or []
    assert rules, "правила сверки объявления версии исчезли"
    for r in rules:
        assert "{channel}" in r["pattern"], (
            f"в шаблоне {r['file']} канал зашит вместо подстановки из реестра: {r['pattern']}")
    assert vrc.authoritative_version_errors(_data(), KIT) == []
