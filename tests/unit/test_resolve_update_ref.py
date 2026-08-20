"""Обновление берёт ревизию по каналу, а канал ЗАРАБАТЫВАЕТСЯ.

ПОВОД — ЗАМЕР (аудит 19.08.2026). `templates/ci/ai-ops-update.yml` делал `git clone --depth 1`, то
есть брал HEAD ветки по умолчанию — канал `edge`, — тогда как дочка объявляет `update_channel` в
`.ai-ops.yaml`. Объявление и источник не были связаны ничем: репозиторий просил `stable` и каждую
ночь получал предложение обновиться до последнего коммита `main`.

Наивное лечение («новейший тег с channel: stable») дало бы дефект ХУЖЕ исходного, и это замерено:
теги v3.36.7…v3.36.10 объявляют `stable` при пустом `field_evidence` и БЕЗ раздела `channels`
вовсе — раздел появился в v3.36.11 вместе с правилом «канал зарабатывается» (F-030), и тогда же
версия честно опустилась до `qualification`. То есть дочку с 3.36.12 отправили бы НАЗАД, на выпуск,
чья `stable` и была тем самообъявлением, ради которого правило вводили.

Отсюда три свойства, каждое проверяется ниже:
  * объявление тега проверяется ЕГО ЖЕ требованиями (`channels.<канал>.requires`);
  * тег, который своих требований не несёт, проверить нечем — потолок `qualification`;
  * понижение версии обновлением не является — отказ с причиной, а не тихий откат на ветку.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "installer"))

import ai_ops as installer  # noqa: E402 — путь ставится выше

CHANNELS_VOCAB = {
    "edge": {"requires": []},
    "qualification": {"requires": ["own_ci_green"]},
    "stable": {"requires": ["own_ci_green", "field_evidence"], "field_evidence_min_repos": 2},
}


def _claims(version, channel, *, with_vocab=True, evidence=()):
    d = {"schema_version": 1, "version": version, "channel": channel,
         "field_evidence": [{"repo": r} for r in evidence]}
    if with_vocab:
        d["channels"] = CHANNELS_VOCAB
    return d


def _repo(tmp_path, tags):
    """Git-репозиторий с тегами; в каждом теге свой release-claims.yaml."""
    root = tmp_path / "kit"
    (root / "registry").mkdir(parents=True)
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], capture_output=True, check=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    run("config", "user.email", "t@t.t")
    run("config", "user.name", "t")
    for tag, claims in tags:
        (root / "registry" / "release-claims.yaml").write_text(
            yaml.safe_dump(claims, allow_unicode=True), encoding="utf-8")
        (root / "VERSION").write_text(str(claims.get("version", "0")) + "\n", encoding="utf-8")
        run("add", "-A")
        run("commit", "-qm", tag)
        run("tag", tag)
    return root


@pytest.fixture()
def no_installed(monkeypatch):
    """По умолчанию считаем, что установленной версии нет — пол понижения не мешает проверкам."""
    monkeypatch.setattr(installer, "installed_version", lambda: None)


@pytest.mark.unit
def test_earned_channel_demotes_a_declaration_without_field_evidence():
    assert installer.earned_channel(_claims("1.0.0", "stable")) == "qualification"
    assert installer.earned_channel(
        _claims("1.0.0", "stable", evidence=("a", "b"))) == "stable"


@pytest.mark.unit
def test_a_tag_without_its_own_requirements_cannot_prove_stable():
    """Тег без раздела `channels` — ровно случай v3.36.7…v3.36.10."""
    assert installer.earned_channel(_claims("1.0.0", "stable", with_vocab=False)) == "qualification"


@pytest.mark.unit
def test_stable_is_refused_when_no_tag_earned_it(tmp_path, no_installed):
    repo = _repo(tmp_path, [
        ("v1.0.0", _claims("1.0.0", "stable", with_vocab=False)),   # самообъявление
        ("v1.1.0", _claims("1.1.0", "qualification")),
    ])
    res = installer.resolve_update_ref("stable", repo)
    assert res["ref"] is None, res
    assert "stable" in res["reason"] and "выполняется" in res["reason"].lower(), res["reason"]


@pytest.mark.unit
def test_stable_is_taken_when_a_tag_really_earned_it(tmp_path, no_installed):
    repo = _repo(tmp_path, [
        ("v1.0.0", _claims("1.0.0", "qualification")),
        ("v1.1.0", _claims("1.1.0", "stable", evidence=("child-a", "child-b"))),
    ])
    res = installer.resolve_update_ref("stable", repo)
    assert res["ref"] == "v1.1.0", res
    assert res["kind"] == "tag"


@pytest.mark.unit
def test_a_stronger_channel_satisfies_a_weaker_request(tmp_path, no_installed):
    repo = _repo(tmp_path, [("v1.0.0", _claims("1.0.0", "stable", evidence=("a", "b")))])
    assert installer.resolve_update_ref("qualification", repo)["ref"] == "v1.0.0"


@pytest.mark.unit
def test_edge_stays_on_the_default_branch(tmp_path, no_installed):
    repo = _repo(tmp_path, [("v1.0.0", _claims("1.0.0", "qualification"))])
    res = installer.resolve_update_ref("edge", repo)
    assert res["ref"] is None and res["kind"] == "branch"


@pytest.mark.unit
def test_a_downgrade_is_refused_by_name(tmp_path, monkeypatch):
    """Понижение обновлением не является — то же правило, что у `doctor` (B2-16)."""
    monkeypatch.setattr(installer, "installed_version", lambda: "2.0.0")
    repo = _repo(tmp_path, [("v1.0.0", _claims("1.0.0", "stable", evidence=("a", "b")))])
    res = installer.resolve_update_ref("stable", repo)
    assert res["ref"] is None, res
    assert "понижение" in res["reason"], res["reason"]


@pytest.mark.unit
def test_unknown_channel_is_refused_not_guessed(tmp_path, no_installed):
    repo = _repo(tmp_path, [("v1.0.0", _claims("1.0.0", "qualification"))])
    res = installer.resolve_update_ref("beta", repo)
    assert res["ref"] is None and "вне словаря" in res["reason"]


@pytest.mark.unit
def test_the_real_repository_never_claims_an_unearned_stable():
    """На настоящих тегах кита: `stable` не выдаётся, потому что не заработан ни одним выпуском.

    Это не пожелание, а сегодняшний факт: `field_evidence` пуст во всех тегах. Тест станет зелёным
    иначе ровно тогда, когда полевые доказательства появятся, — и это правильный момент.
    """
    res = installer.resolve_update_ref("stable", PKG_ROOT)
    if res["ref"] is not None:
        claims = yaml.safe_load(subprocess.run(
            ["git", "-C", str(PKG_ROOT), "show", f"{res['ref']}:registry/release-claims.yaml"],
            capture_output=True, text=True).stdout) or {}
        assert installer.earned_channel(claims) == "stable", (
            f"{res['ref']} выдан как stable, но своих требований не выполняет")


@pytest.mark.unit
def test_a_refusal_names_the_way_out(tmp_path, no_installed):
    """Правильный «нет», после которого человек застрял, — половина работы.

    ЗАМЕР 20.08.2026, живой репозиторий `ai-ops-cockpit`. Дочка объявляла `stable`, ни один тег
    `stable` не заработал — и отказ был верным. Но `stable` зарабатывается полевыми
    доказательствами, а те берутся из дочек, которые обновились; дочка на `stable` обновиться не
    может. Круг. Разрывает его роль раннего получателя (`qualification`), и пока отказ об этом
    молчит, владелец видит тупик и идёт чинить теги, в которых всё в порядке.
    """
    repo = _repo(tmp_path, [("v1.0.0", _claims("1.0.0", "qualification")),
                            ("v1.1.0", _claims("1.1.0", "qualification"))])
    res = installer.resolve_update_ref("stable", repo)
    assert res["ref"] is None
    assert res["best_earned"] == "qualification", res
    assert "update_channel: qualification" in res["reason"], res["reason"]
    assert "ранним получателем" in res["reason"]


@pytest.mark.unit
def test_no_way_out_is_invented_when_there_is_none(tmp_path, no_installed):
    """Обратная сторона: тегов нет вовсе — предлагать «поставьте qualification» НЕЧЕГО.

    Совет, который не сработает, хуже молчания: он тратит попытку и подрывает доверие к следующему.
    """
    empty = tmp_path / "kit-empty"
    empty.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(empty)], check=True)
    res = installer.resolve_update_ref("stable", empty)
    assert res["best_earned"] is None
    assert "ранним получателем" not in res["reason"], res["reason"]
