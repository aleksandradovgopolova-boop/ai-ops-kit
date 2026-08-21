# -*- coding: utf-8 -*-
"""Локальная заявка на работу честна о своей досягаемости.

РЕШЕНИЕ ВЛАДЕЛЬЦА 18.08.2026 (ep-2026-08-18-claim-medium-hybrid): реестр заявок живёт локально,
публикация — только по явному включению. УСЛОВИЕ 3, которое здесь и проверяется: пока публикация
выключена, кит обязан говорить, что видит только свою машину, а НЕ подавать пересечения как
координацию команды. Это ровно тот ложный green, против которого стоит контур.

ПАРА, а не один прогон (приёмка из работы): выключено -> «вижу только эту машину»;
включено -> «вижу заявки команды». Одна половина без второй ничего не доказывает.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

pytestmark = pytest.mark.unit


@pytest.fixture
def aw():
    from ai_ops_kit.lifecycle import active_work
    return active_work


@pytest.fixture
def presenter():
    from ai_ops_kit.ui import presenter as p
    return p


def _write_config(root: Path, publish):
    cfg = {"schema_version": 1, "kind": "ai-ops-child-config"}
    if publish is not None:
        cfg["team_coordination"] = {"publish": publish}
    (root / ".ai-ops.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")


# ---------------------------------------------------------- досягаемость: пара

def test_publication_off_by_default(aw, tmp_path):
    """Дефолт — локально. Самый безопасный: НИКОГДА не выдаёт локальное за координацию команды."""
    assert aw.publication_enabled(tmp_path) is False           # нет файла вовсе
    _write_config(tmp_path, None)                              # файл есть, секции нет
    assert aw.publication_enabled(tmp_path) is False
    _write_config(tmp_path, False)                             # явно выключено
    assert aw.publication_enabled(tmp_path) is False


def test_publication_on_only_when_explicitly_enabled(aw, tmp_path):
    _write_config(tmp_path, True)
    assert aw.publication_enabled(tmp_path) is True


def test_broken_config_reads_as_local(aw, tmp_path):
    """Любая неоднозначность — «не опубликовано»: то же соображение безопасности."""
    (tmp_path / ".ai-ops.yaml").write_text("team_coordination: {publish: [unterminated", encoding="utf-8")
    assert aw.publication_enabled(tmp_path) is False


def test_reach_note_distinguishes_the_two_states(aw):
    off = aw.reach_note(False)
    on = aw.reach_note(True)
    assert "только этой машины" in off.lower() or "только эту машину" in off.lower()
    assert off != on
    assert "других машин" in on or "команды" in on


# ---------------------------------------------------------- register/list честны

def test_register_prints_reach_when_local(aw, tmp_path, capsys):
    reg = tmp_path / "active-work.yaml"
    aw.register(reg, "w1", "feature/w1", ["core"], "sess-1", published=False)
    out = capsys.readouterr().out
    assert "только этой машины" in out.lower() or "только эту машину" in out.lower(), out


def test_list_empty_still_names_reach(aw, tmp_path, capsys):
    """«Активных работ нет» на локальном реестре — это про одну машину, и это надо сказать."""
    reg = tmp_path / "active-work.yaml"
    aw.list_cmd(reg, published=False)
    out = capsys.readouterr().out
    assert "нет" in out
    assert "только этой машины" in out.lower() or "только эту машину" in out.lower(), out


def test_json_list_carries_reach(aw, tmp_path, capsys):
    reg = tmp_path / "active-work.yaml"
    aw.register(reg, "w1", "feature/w1", ["core"], "sess-1", published=False)
    capsys.readouterr()
    aw.list_cmd(reg, as_json=True, published=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["published"] is True, "досягаемость обязана быть и в JSON, не только в тексте"


# ---------------------------------------------------------- заявка обогащена

def test_claim_records_who_where_when(aw, tmp_path):
    """Заявка = кто (сессия) + где (машина) + когда (время) + что (ветка). Без «где/когда»
    инцидент параллельных сессий не разобрать (заявка #150: атрибуция была невозможна)."""
    reg = tmp_path / "active-work.yaml"
    aw.register(reg, "w1", "feature/w1", ["core"], "sess-1", published=False)
    entry = [w for w in aw.load(reg)["active"] if w["id"] == "w1"][0]
    assert entry["owner_session"] == "sess-1"
    assert entry.get("machine"), "заявка без машины — «кто держит» без «где»"
    assert entry.get("started_at"), "заявка без времени — инцидент не выстроить по порядку"
    assert entry["branch"] == "feature/w1"


def test_explicit_at_is_respected(aw, tmp_path):
    reg = tmp_path / "active-work.yaml"
    aw.register(reg, "w1", "feature/w1", ["core"], "sess-1", at="2026-08-18T09:00:00+00:00")
    entry = [w for w in aw.load(reg)["active"] if w["id"] == "w1"][0]
    assert entry["started_at"] == "2026-08-18T09:00:00+00:00"


# ---------------------------------------------------------- презентер честен: пара

def test_presenter_local_says_this_machine(presenter):
    rep = {"active": [{"id": "w1", "status": "in-progress", "branch": "b", "affected_areas": ["core"]}]}
    msg = presenter.from_active_work(rep, published=False)
    text = json.dumps(msg, ensure_ascii=False).lower()
    assert "эту машину" in text or "этой машине" in text or "эта машина" in text, text
    assert "не про команду" in text or "не попадают" in text or "координация команды" in text


def test_presenter_published_speaks_of_team(presenter):
    rep = {"active": [{"id": "w1", "status": "in-progress", "branch": "b", "affected_areas": ["core"]}]}
    msg = presenter.from_active_work(rep, published=True)
    text = json.dumps(msg, ensure_ascii=False).lower()
    assert "команд" in text, text


def test_presenter_empty_local_is_about_this_machine(presenter):
    """«Ничего не идёт» на локальном реестре — не факт о команде."""
    msg = presenter.from_active_work({"active": []}, published=False)
    text = json.dumps(msg, ensure_ascii=False).lower()
    assert "эту машину" in text or "этой машин" in text or "эта машина" in text, text


# ---------------------------------------------------------- ШОВ: status спрашивает публикацию

def _make_repo(root: Path, publish):
    (root / ".ai" / "runtime").mkdir(parents=True)
    _write_config(root, publish)
    reg = root / ".ai" / "runtime" / "active-work.yaml"
    reg.write_text(yaml.safe_dump({
        "schema_version": 1, "kind": "active-work",
        "active": [{"id": "w1", "status": "in-progress", "branch": "feature/w1",
                    "affected_areas": ["core"], "owner_session": "s1"}]},
        allow_unicode=True), encoding="utf-8")


def test_status_output_depends_on_publication(tmp_path, capsys):
    """ПРОБА ШВА: честная фраза доходит до человека, только если `status` реально СПРАШИВАЕТ
    публикацию и проводит её в презентер. Подмена живого вызова на константу (мутация
    reach-honesty-seam-status-asks-publication) обязана уронить этот тест: ответ перестаёт
    зависеть от конфигурации.
    """
    from ai_ops_kit.cli import ai_ops_cli

    pub_repo = tmp_path / "published"
    _make_repo(pub_repo, True)
    capsys.readouterr()
    ai_ops_cli.main(["status", str(pub_repo)])
    published_out = capsys.readouterr().out.lower()

    loc_repo = tmp_path / "local"
    _make_repo(loc_repo, False)
    capsys.readouterr()
    ai_ops_cli.main(["status", str(loc_repo)])
    local_out = capsys.readouterr().out.lower()

    assert published_out != local_out, (
        "ответ status не зависит от team_coordination.publish — шов разорван, "
        "публикацию не спросили или не провели в презентер")
    assert "команд" in published_out, published_out
    assert "эту машину" in local_out or "этой машин" in local_out or "эта машина" in local_out, local_out
