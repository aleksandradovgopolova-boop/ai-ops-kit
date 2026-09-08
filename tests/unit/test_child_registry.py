"""voluntary-child-registration: добровольная регистрация дочек — охват БЕЗ телеметрии.

Кит ставится локально и НИКУДА не сообщает о себе (инвариант приватности). Эта работа даёт владельцу
честно оценить охват через ДОБРОВОЛЬНЫЙ (opt-in) механизм: владелец дочки сам решает поделиться
записью. Тесты держат инварианты, без которых механизм превращается в телеметрию:

  * согласие ЯВНОЕ (без «да» записи нет; поведение по умолчанию — не отмечаться);
  * отказ БЕЗОПАСЕН (ничего не создаётся, онбординг проходит);
  * СЕТИ НЕТ (capability-декларация «не звонит домой» подтверждена исходником);
  * ПРИВАТНОСТЬ состава (имя проекта есть; абсолютных путей / e-mail / кода нет);
  * ИДЕМПОТЕНТНОСТЬ (повторный онбординг не переспрашивает);
  * ОХВАТ считается из НАБОРА файлов реестра и оговаривается «нижняя граница»;
  * ПРОДУКТОВЫЙ СТАТУС переносится из Product Passport как есть (пробел -> пробел, не выдумка).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.engops import child_registry as cr

pytestmark = pytest.mark.unit


@pytest.fixture
def child(tmp_path):
    root = tmp_path / "some-product"
    root.mkdir()
    (root / "VERSION").write_text("4.1.0\n", encoding="utf-8")
    # git с одним коммитом -> анонимный id детерминирован (хэш первого коммита), а не случаен.
    for args in (["init"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                 ["add", "."], ["commit", "-m", "init"]):
        subprocess.run(["git", *args], cwd=root, capture_output=True)
    return root


# ── Согласие явное / поведение по умолчанию ──────────────────────────────────────────────────────

def test_default_is_not_registered_no_record_without_yes(child):
    """Без явного «да» записи нет — по умолчанию дочка НЕ отмечена."""
    assert cr.read_registration(child) == (None, None)
    assert cr.registration_state(child)["registered"] is False
    assert cr.has_decided(child) is False


def test_register_is_the_only_thing_that_creates_a_record(child):
    """Запись появляется ТОЛЬКО на явный register — и решение фиксируется."""
    p, created, rec = cr.register(child)
    assert created is True and p.is_file()
    assert cr.registration_state(child)["registered"] is True
    assert cr.read_decision(child)[0]["decision"] == "registered"


# ── Отказ безопасен ──────────────────────────────────────────────────────────────────────────────

def test_decline_creates_nothing_and_is_safe(child):
    """«Нет» ничего не создаёт: регистрации нет, но решение принято (онбординг не переспросит)."""
    cr.decline(child)
    assert not cr.registration_path(child).is_file()
    assert cr.registration_state(child)["registered"] is False
    assert cr.has_decided(child) is True  # решение есть -> идемпотентность


def test_onboard_offer_is_silent_and_creates_nothing(monkeypatch, tmp_path):
    """Онбординг с предложением отметиться проходит полностью и НИЧЕГО не создаёт (отказ безопасен).

    Гоняем сам интент onboard: он пишет профиль репозитория и печатает предложение, но записи-
    регистрации не создаёт — согласие только по отдельной команде.
    """
    from ai_ops_kit.cli import ai_ops_cli
    root = tmp_path / "calc"
    root.mkdir()
    (root / "package.json").write_text('{"name":"calc"}', encoding="utf-8")
    rc = ai_ops_cli.main(["onboard", str(root)])
    assert rc == 0
    assert (root / ".ai" / "repository-profile.yaml").is_file()  # онбординг прошёл
    assert not cr.registration_path(root).is_file()              # но отметки нет
    assert not cr.decision_path(root).is_file()                  # и решение не навязано


# ── Идемпотентность ──────────────────────────────────────────────────────────────────────────────

def test_repeated_register_does_not_duplicate_and_keeps_id(child):
    """Повторный register не плодит вторую запись и сохраняет анонимный id (стабильность охвата)."""
    _p, created1, rec1 = cr.register(child)
    _p, created2, rec2 = cr.register(child)
    assert created1 is True and created2 is False
    assert rec1["id"] == rec2["id"]


def test_has_decided_makes_onboarding_stop_asking(child):
    """Как только решение принято — has_decided=True: онбординг больше не предлагает (идемпотентность)."""
    assert cr.has_decided(child) is False
    cr.register(child)
    assert cr.has_decided(child) is True


def test_forget_revokes_consent_and_reopens_offer(child):
    """forget удаляет запись И решение — согласие отозвано, онбординг снова вправе предложить."""
    cr.register(child)
    removed = cr.forget(child)
    assert len(removed) == 2
    assert not cr.registration_path(child).is_file()
    assert cr.has_decided(child) is False


# ── Приватность состава записи ───────────────────────────────────────────────────────────────────

def test_registration_composition_has_name_but_no_path_email_or_code(child):
    """СОСТАВ записи: имя проекта есть; абсолютных путей, e-mail и содержимого кода нет."""
    (child / "secret.py").write_text("API_KEY = 'sekret-code-content'\n", encoding="utf-8")
    rec = cr.build_registration(child)
    # что ДОЛЖНО быть
    assert rec["project"] == "some-product"
    assert rec["kit_version"] == "4.1.0"
    assert rec["registered_at"] and rec["id"].startswith("proj-")
    # чего быть НЕ ДОЛЖНО — проверяем по всему сериализованному документу
    blob = yaml.safe_dump(rec, allow_unicode=True)
    assert str(child.resolve()) not in blob, "абсолютный путь просочился в запись"
    assert "/" not in rec["id"] and "/" not in rec["project"], "id/имя не несут разделителей пути"
    assert "@" not in blob, "e-mail не должен попадать в запись"
    assert "sekret-code-content" not in blob, "содержимое кода не должно попадать в запись"


def test_anon_id_is_stable_across_calls(child):
    """Анонимный id стабилен между вызовами (иначе охват плодил бы дубли одного репозитория)."""
    assert cr.build_registration(child)["id"] == cr.register(child)[2]["id"]


# ── Нет сети / честная capability-декларация ─────────────────────────────────────────────────────

def test_module_declares_no_network_and_keeps_the_promise():
    """Декларация «не звонит домой» подтверждена исходником: ни сетевого импорта, ни вызова.

    Это и есть honesty-guard для фичи: CAPABILITIES.network=False обязан совпадать с тем, что в коде
    сетевых умений нет. Иначе декларация была бы обещанием на словах.
    """
    assert cr.CAPABILITIES["network"] is False
    assert cr.CAPABILITIES["sends"] is False
    src = Path(cr.__file__).read_text(encoding="utf-8")
    forbidden = ("import socket", "import urllib", "import http", "import requests",
                 "import ftplib", "import smtplib", "urlopen", "http://", "https://",
                 "socket.", "requests.", "httpx")
    hits = [t for t in forbidden if t in src]
    assert not hits, f"модуль объявил network=False, но в коде есть сетевое: {hits}"


# ── Охват считается и оговаривается «нижняя граница» ─────────────────────────────────────────────

def _seed_kit(kit_root, regs):
    d = kit_root / "registry" / "child-registrations"
    d.mkdir(parents=True)
    for r in regs:
        (d / f"{r['id']}.yaml").write_text(yaml.safe_dump(r, allow_unicode=True), encoding="utf-8")


def test_coverage_counts_from_the_set_of_files_and_says_lower_bound(tmp_path):
    """Охват = число файлов реестра (источник истины — набор файлов), с оговоркой «нижняя граница»."""
    kit = tmp_path / "kit"
    _seed_kit(kit, [
        {"schema_version": 1, "kind": "ChildRegistration", "id": "proj-a", "project": "alpha",
         "kit_version": "4.1.0", "registered_at": "2026-09-08"},
        {"schema_version": 1, "kind": "ChildRegistration", "id": "proj-b", "project": "beta",
         "kit_version": "4.0.0", "registered_at": "2026-09-08"},
    ])
    rep = cr.coverage(kit)
    assert rep["count"] == 2
    assert rep["by_version"] == {"4.1.0": 1, "4.0.0": 1}
    assert rep["is_lower_bound"] is True
    assert "нижняя граница" in rep["note"]
    assert "нижняя граница" in cr.render_coverage(rep).lower() or "НИЖНЯЯ ГРАНИЦА" in cr.render_coverage(rep)


def test_coverage_empty_registry_is_zero_not_error(tmp_path):
    """Пустой/отсутствующий реестр -> охват 0 (а не ошибка) с той же оговоркой."""
    rep = cr.coverage(tmp_path / "kit")
    assert rep["count"] == 0 and rep["is_lower_bound"] is True


# ── Продуктовый статус из паспорта: пробел остаётся пробелом ─────────────────────────────────────

def test_product_status_snapshot_keeps_unknown_and_does_not_invent():
    """Паспорт с пробелом (unknown) -> в снимке пробел, а НЕ выдуманное значение."""
    sections = {
        "Версия и последний релиз": {"state": "verified", "value": "Версия 4.1.0"},
        "Статус и зрелость": {"state": "unknown", "value": "_неизвестно — нет данных_"},
        # раздел «Здоровье…» намеренно отсутствует -> тоже должен стать unknown, а не пропуск
    }
    snap = cr.product_status_snapshot(sections)
    assert snap["version_release"]["state"] == "verified"
    assert snap["maturity"]["state"] == "unknown"
    assert snap["health"]["state"] == "unknown"       # отсутствующий раздел -> unknown
    assert snap["health"]["value"] is None            # ничего не выдумано


def test_summary_carries_passport_gap_as_gap(child):
    """Сводка с впрыснутым снимком-пробелом несёт пробел, а не правдоподобное значение."""
    snap = cr.product_status_snapshot({"Статус и зрелость": {"state": "unknown", "value": None}})
    rep = cr.build_summary(child, product_status=snap)
    assert rep["product_status"]["maturity"]["state"] == "unknown"
    # и в человеческом рендере пробел назван пробелом, а не числом/классом
    assert "_неизвестно_" in cr.render_summary(rep)


def test_summary_without_passport_is_honestly_unknown(child):
    """Без впрыснутого паспорта сводка честно unknown по всем полям (а не пропуск)."""
    rep = cr.build_summary(child)
    assert all(v["state"] == "unknown" for v in rep["product_status"].values())


# ── Локальная сводка использования ───────────────────────────────────────────────────────────────

def test_scan_usage_counts_runs_and_task_types_honestly(child):
    """Прогоны и типы задач считаются из фич; нет фич -> нули (а не выдуманная активность)."""
    assert cr.scan_usage(child) == {"runs": 0, "features": 0, "task_types": {}}
    fdir = child / "features" / "w1"
    fdir.mkdir(parents=True)
    (fdir / "run-plan.yaml").write_text(yaml.safe_dump({"base_workflow": "ENGINEERING"}), encoding="utf-8")
    (fdir / "lifecycle-journal.jsonl").write_text(
        '{"kind":"run_start","run_id":"w1"}\n{"kind":"run_end","status":"ok"}\n', encoding="utf-8")
    usage = cr.scan_usage(child)
    assert usage["features"] == 1 and usage["runs"] == 1
    assert usage["task_types"] == {"ENGINEERING": 1}


# ── Доставка (collect) — локальная, двусторонняя ─────────────────────────────────────────────────

def test_collect_gathers_only_registered_children(tmp_path):
    """collect берёт ТОЛЬКО отметившиеся дочки; неотмеченную честно пропускает (не собирает пустоту)."""
    kit = tmp_path / "kit"
    yes = tmp_path / "yes"; yes.mkdir(); (yes / "VERSION").write_text("4.1.0")
    no = tmp_path / "no"; no.mkdir(); (no / "VERSION").write_text("4.1.0")
    cr.register(yes)
    cr.decline(no)
    rep = cr.collect(kit, [yes, no])
    assert len(rep["collected"]) == 1 and rep["collected"][0]["project"] == "yes"
    assert len(rep["skipped"]) == 1
    assert cr.kit_path(kit, rep["collected"][0]["id"]).is_file()   # копия в ките
    # состояние вернулось в дочку (двусторонность канала)
    assert cr.read_registration(yes)[0]["state"] == "collected"
