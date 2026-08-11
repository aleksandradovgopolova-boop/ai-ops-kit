"""Долг доказательства поставки: признание вместо подделки — и без лазейки.

ЛОВУШКА ОБНОВЛЕНИЯ, НАЙДЕННАЯ НА ИИ-СРЕДЕ. Правило «`released` требует SHA-verified
DeliveryReceipt» появилось в 3.27.4. Репозиторий, выпускавший функции раньше, при обновлении получает
красный CI, и закрыть его нечем: `sha_verified` ставится только сверкой записанного DeliveryIntent с
remote, а интента тогда не записывали. Подделать флаг нельзя — это переопределение проверенного
факта. У ии-среды так встали пять функций из восьми.

Решение: отсутствие доказательства признаётся ОТДЕЛЬНЫМ состоянием. Запись говорит «доказательства
нет», а не «доказательство есть»; находка перестаёт блокировать, но остаётся видимой.

Три обязательных теста на capability:
  * positive     — признанный долг не валит прогон и ВИДЕН в выводе;
  * fail-closed  — непризнанная функция по-прежнему ошибка; запись не является доказательством;
                   `planned`-строка, дописанная руками, долгом не считается (иначе это обход);
  * side-effect  — команда пишет только с `--apply`, повторный прогон не растит список сам,
                   а закрытый долг из списка уходит.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]

from ai_ops_kit.validation import validate_feature_blueprint as vfb  # noqa: E402

DEBT_REL = ".ai/project/delivery-proof-debt.yaml"


def _installer(root: Path):
    import os
    old = os.getcwd()
    os.chdir(root)
    try:
        spec = importlib.util.spec_from_file_location(
            f"inst_debt_{abs(hash(str(root)))}", KIT / "installer" / "ai_ops.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.chdir(old)


def _feature(root: Path, fid: str, status: str = "released"):
    d = root / "features" / fid
    (d / "discovery").mkdir(parents=True, exist_ok=True)
    (d / "discovery" / "problem.md").write_text("# проблема\n", encoding="utf-8")
    (d / "blueprint.yaml").write_text(yaml.safe_dump({
        "schema_version": 1, "kind": "feature-blueprint",
        "feature": {"id": fid, "name": fid, "title": fid, "status": status,
                    "current_stage": "discovery"},
        "artifacts": {"discovery": [{"path": "discovery/problem.md", "status": "done"}]},
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return d


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "child"
    (root / ".ai" / "project").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def _write_debt(root: Path, ids, status="released"):
    (root / ".ai" / "project").mkdir(parents=True, exist_ok=True)
    (root / DEBT_REL).write_text(yaml.safe_dump({
        "schema_version": 1, "kind": "DeliveryProofDebt",
        "reason": "released_before_delivery_receipts",
        "features": [{"id": i, "status_at_record": status} for i in ids],
    }, allow_unicode=True, sort_keys=False), encoding="utf-8")


# ── positive ──────────────────────────────────────────────────────────────────────────────────

def test_recognised_debt_does_not_block_but_stays_visible(repo):
    d = _feature(repo, "onboarding")
    _write_debt(repo, ["onboarding"])

    errors, debt = vfb.validate_dir_full(d)

    assert errors == [], f"признанный долг всё ещё блокирует: {errors}"
    assert debt, "долг исчез из вывода — невидимый долг перестаёт быть долгом"
    assert "признано долгом" in debt[0].lower()


def test_verified_receipt_removes_the_finding_entirely(repo):
    """Настоящее доказательство закрывает вопрос — долг тут не нужен."""
    d = _feature(repo, "shipped")
    (d / "delivery-receipt.yaml").write_text(yaml.safe_dump({
        "schema_version": 1, "kind": "DeliveryReceipt", "sha_verified": True,
        "commit_sha": "a" * 40}, allow_unicode=True), encoding="utf-8")

    errors, debt = vfb.validate_dir_full(d)
    assert errors == [] and debt == []


# ── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_unrecognised_feature_still_fails(repo):
    d = _feature(repo, "new-thing")
    _write_debt(repo, ["onboarding"])          # признан ДРУГОЙ

    errors, _ = vfb.validate_dir_full(d)
    assert errors, "функция без доказательства и без признания прошла молча"


def test_planned_entry_in_the_list_is_not_a_loophole(repo):
    """Дописанная руками строка про запланированную функцию долгом не считается.

    Иначе список превращается в способ обойти правило для новой работы: пометил — и проверка молчит.
    Признание истории и обход правила должны различаться механически, а не по доброй воле.
    """
    d = _feature(repo, "future-thing")
    _write_debt(repo, ["future-thing"], status="planned")

    errors, _ = vfb.validate_dir_full(d)
    assert errors, "строка со status_at_record: planned дала обход правила"


def test_broken_debt_file_is_not_an_excuse(repo):
    d = _feature(repo, "onboarding")
    (repo / DEBT_REL).write_text("не yaml: [[[", encoding="utf-8")

    errors, _ = vfb.validate_dir_full(d)
    assert errors, "нечитаемый файл долга прочитан как признание"


def test_debt_file_is_not_a_receipt(repo):
    """Файл долга не должен случайно удовлетворить проверку доказательства."""
    d = _feature(repo, "onboarding")
    _write_debt(repo, ["onboarding"])
    _, debt = vfb.validate_dir_full(d)
    assert debt, "долг должен остаться названным, а не превратиться в доказательство"
    body = (repo / DEBT_REL).read_text(encoding="utf-8")
    assert "DeliveryReceipt" not in body and "sha_verified" not in body, \
        "в записи долга появились поля доказательства — это подделка формы"


# ── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_dry_run_writes_nothing(repo, capsys):
    _feature(repo, "onboarding")
    inst = _installer(repo)

    rc = inst.cmd_delivery_proof(())

    assert rc == 0
    assert not (repo / DEBT_REL).exists(), "сухой прогон записал файл в чужой репозиторий"
    out = capsys.readouterr().out
    assert "Сухой прогон" in out and "--apply" in out


def test_apply_records_only_the_facts_of_today(repo, capsys):
    _feature(repo, "onboarding")
    _feature(repo, "library-view")
    _feature(repo, "in-work", status="in-progress")     # не released -> не долг
    inst = _installer(repo)

    inst.cmd_delivery_proof(("--apply",))

    data = yaml.safe_load((repo / DEBT_REL).read_text(encoding="utf-8"))
    assert data["kind"] == "DeliveryProofDebt"
    ids = {f["id"] for f in data["features"]}
    assert ids == {"onboarding", "library-view"}, ids
    assert all(f["status_at_record"] == "released" for f in data["features"])

    # Повторный прогон не растит список сам и не переписывает дату признания.
    before = (repo / DEBT_REL).read_text(encoding="utf-8")
    inst.cmd_delivery_proof(("--apply",))
    assert (repo / DEBT_REL).read_text(encoding="utf-8") == before, "повторный прогон изменил запись"


def test_closed_debt_leaves_the_list(repo):
    """Доказательство появилось — запись о долге уходит, иначе долг вечен на бумаге."""
    d = _feature(repo, "onboarding")
    inst = _installer(repo)
    inst.cmd_delivery_proof(("--apply",))
    assert "onboarding" in (repo / DEBT_REL).read_text(encoding="utf-8")

    (d / "delivery-receipt.yaml").write_text(yaml.safe_dump({
        "schema_version": 1, "kind": "DeliveryReceipt", "sha_verified": True,
        "commit_sha": "b" * 40}, allow_unicode=True), encoding="utf-8")
    inst.cmd_delivery_proof(("--apply",))

    data = yaml.safe_load((repo / DEBT_REL).read_text(encoding="utf-8"))
    assert [f["id"] for f in data["features"]] == [], "закрытый долг остался в списке"


def test_doctor_names_the_debt(repo):
    """Находка стала advisory — значит `doctor` обязан о ней говорить, иначе это тишина."""
    _feature(repo, "onboarding")
    inst = _installer(repo)
    unproven = inst._released_without_proof(repo)
    assert unproven == ["onboarding"]
    src = (KIT / "installer" / "ai_ops.py").read_text(encoding="utf-8")
    assert "_released_without_proof(REPO_ROOT)" in src, "doctor не считает долг"
    assert "поставка без доказательства" in src, "doctor не называет долг словами"
