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


# --------------------------------------------------- product-аудитория: без внутренних id (#708)

def test_product_audience_hides_internal_ids(aw, tmp_path, capsys):
    """На product человеку не нужны wi-…/сессия/машина/ветка старта — только суть: работа началась
    в отдельной копии, main не тронут. id-насыщенная строка ACTIVE-WORK здесь не печатается."""
    reg = tmp_path / "active-work.yaml"
    aw.register(reg, "wi-abc123", "ai-ops/wi-abc123", ["core"], "session:deadbeef",
                published=False, audience="product")
    out = capsys.readouterr().out
    assert "отдельной копии" in out and "main не трогаю" in out, out
    assert "ACTIVE-WORK" not in out, "внутренний заголовок координации на product утёк: " + out
    assert "wi-abc123" not in out and "session:deadbeef" not in out, "id утёк на product: " + out
    assert "ai-ops/wi-abc123" not in out, "имя ветки утекло на product: " + out


def test_technical_audience_still_names_the_claim(aw, tmp_path, capsys):
    """Умолчание (technical) — полная координационная форма с id: пара к product, одна без другой
    ничего не доказывает."""
    reg = tmp_path / "active-work.yaml"
    aw.register(reg, "wi-abc123", "ai-ops/wi-abc123", ["core"], "session:deadbeef", published=False)
    out = capsys.readouterr().out
    assert "ACTIVE-WORK: зарегистрирована работа 'wi-abc123'" in out, out
    assert "только этой машины" in out.lower() or "только эту машину" in out.lower(), out


def test_finish_product_hides_id_keeps_reason(aw, tmp_path, capsys):
    """finish на product: без wi-…/жаргона «ACTIVE-WORK», но ПРИЧИНА остановки сохраняется —
    человек должен понять, почему работа не доведена."""
    reg = tmp_path / "active-work.yaml"
    aw.register(reg, "wi-abc123", "ai-ops/wi-abc123", ["core"], "sess-1", published=False)
    capsys.readouterr()
    aw.finish_cmd(reg, "wi-abc123", status="blocked",
                  reason="код не написан — правок 0", audience="product")
    out = capsys.readouterr().out
    assert "код не написан" in out, out
    assert "ACTIVE-WORK" not in out and "wi-abc123" not in out, "id/жаргон утёк на product: " + out


def test_finish_product_done_without_reason_is_silent(aw, tmp_path, capsys):
    """Успех без причины на product — молчим: итог «готово» уже сказан отчётом, дубль не нужен."""
    reg = tmp_path / "active-work.yaml"
    aw.register(reg, "wi-abc123", "ai-ops/wi-abc123", ["core"], "sess-1", published=False)
    capsys.readouterr()
    aw.finish_cmd(reg, "wi-abc123", status="done", child_root=tmp_path, audience="product")
    out = capsys.readouterr().out
    assert out.strip() == "", "на product успешный finish не должен дублировать отчёт: " + out


def test_finish_technical_still_names_id(aw, tmp_path, capsys):
    """Умолчание (technical) — полная форма с id (пара к product)."""
    reg = tmp_path / "active-work.yaml"
    aw.register(reg, "wi-abc123", "ai-ops/wi-abc123", ["core"], "sess-1", published=False)
    capsys.readouterr()
    aw.finish_cmd(reg, "wi-abc123", status="done", child_root=tmp_path)
    out = capsys.readouterr().out
    assert "ACTIVE-WORK: работа 'wi-abc123' помечена done" in out, out


def test_product_audience_still_surfaces_publication(aw, tmp_path, capsys):
    """Публикация ОТПРАВЛЯЕТ данные с машины — это не «шум про выключенную фичу», а факт, который
    человек должен видеть и на product (честность важнее краткости)."""
    reg = tmp_path / "active-work.yaml"
    aw.register(reg, "wi-abc123", "ai-ops/wi-abc123", ["core"], "session:deadbeef",
                child_root=tmp_path, published=True, audience="product")
    out = capsys.readouterr().out
    assert ".ai/claims/" in out, "на product скрыли, что заявка публикуется наружу: " + out


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


# ------------------------------------------ status говорит продуктом, а не заявками/ветками (#958)

def test_status_product_output_speaks_product_not_branches(presenter):
    """Человеко-обращённый вывод `status` (audience=product) НЕ сыплет внутренней кухней: ни имени
    ветки (`ai-ops/…`), ни слова «заявк», ни «рабочих копи»/«worktree», ни внутреннего id работы.
    Сырьё (ветка/id/рабочая копия) при этом обязано остаться в технических деталях."""
    rep = {"active": [
        {"id": "wi-7cf4f63f098d", "workitem": "wi-7cf4f63f098d", "title": "Показывать номер версии",
         "status": "in_progress", "branch": "ai-ops/calm-top-bar",
         "worktree": "/tmp/wt/calm-top-bar", "affected_areas": ["src/settings/"]}]}
    msg = presenter.from_active_work(rep, published=True)
    prod = presenter.render(msg, audience="product")
    low = prod.lower()
    for leak in ("ai-ops/", "заявк", "worktree", "рабочих копи", "рабочая копи",
                 "wi-7cf4f63f098d", "calm-top-bar"):
        assert leak not in low, f"внутренняя кухня «{leak}» просочилась в product:\n{prod}"
    assert "Показывать номер версии" in prod, "человек не видит, ЧТО идёт: " + prod
    tech = presenter.render(msg, audience="technical")
    assert "ai-ops/calm-top-bar" in tech and "wi-7cf4f63f098d" in tech, \
        "ветка/id обязаны остаться в технических деталях: " + tech


def test_status_divergence_names_it_without_the_word_claim(presenter):
    """Расхождение плана с реальной работой называется человеку СЛЕДСТВИЕМ, без слова «заявк»."""
    msg = presenter.from_active_work(
        {"active": []},
        crosscheck={"plan_exists": True, "registry_exists": True, "registry_count": 0,
                    "declared": [{"id": "wi-1", "title": "Тёмная тема"}],
                    "only_in_plan": [{"id": "wi-1", "title": "Тёмная тема"}]})
    prod = presenter.render(msg, audience="product")
    assert "расход" in prod.lower(), "расхождение не названо: " + prod
    assert "заявк" not in prod.lower(), "слово «заявк» в лице человека: " + prod
    assert "wi-1" not in prod, "внутренний id в лице человека: " + prod


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
