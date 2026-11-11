"""#1481: установленная копия кита несёт его условия — `.ai/managed/LICENSE`.

Повод (замер 10.11.2026, main 32fb285b): свежая установка клала в проект 699 файлов кита и ни
одного файла условий. С #1470 кит распространяется по PolyForm Noncommercial, а эти условия требуют,
чтобы получатель копии получил их текст или адрес и строки `Required Notice:`.

Проверяется ПОВЕДЕНЧЕСКИ, настоящими `init`/`update`/`status` в temp git-репо, а не чтением
манифеста глазами: файл на месте и побайтно равен исходному, записан в контрольные суммы, его правка
и удаление видны дрейфом, старая установка получает его обновлением, сбой обновления не оставляет
его при старом коде, а лицензия самого продукта не тронута.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit._installer_helpers import INSTALLER, KIT, _git, _make_child_repo, _run_cli

pytestmark = pytest.mark.unit

LICENSE_REL = "LICENSE"
KIT_LICENSE = KIT / LICENSE_REL
# Условия, действующие с #1470. Осознанная смена условий меняет и эти две строки.
TERMS_URL = b"<https://polyformproject.org/licenses/noncommercial/1.0.0>"
NOTICE_PREFIX = b"Required Notice:"
# CRLF намеренно: «не тронуто» доказывается побайтно, а не по тексту.
PRODUCT_LICENSE = b"Product terms: proprietary, all rights reserved.\r\nOwner bytes.\r\n"
OLD_TERMS = b"MIT License\n\nCopyright (c) 2026 Example\n\nPermission is hereby granted...\n"


def _installer():
    spec = importlib.util.spec_from_file_location("_inst_for_kit_license", INSTALLER)
    ai_ops = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ai_ops
    spec.loader.exec_module(ai_ops)
    return ai_ops


def _env():
    """Без CODEX_HOME: иначе update положил бы prompts в настоящий домашний каталог Codex."""
    env = {k: v for k, v in os.environ.items() if k != "CODEX_HOME"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(root: Path) -> dict:
    """Независимая перепись дерева проекта (без .git, backup и отчёта обновления)."""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if (rel.startswith(".git/") or rel.startswith(".ai/runtime/backups")
                or rel == ".ai/runtime/last-update-report.json" or not p.is_file()):
            continue
        out[rel] = _sha(p)
    return out


@pytest.fixture(scope="module")
def seed(tmp_path_factory) -> Path:
    """Одна настоящая установка в проект, у которого ЕСТЬ собственная лицензия."""
    root = _make_child_repo(tmp_path_factory.mktemp("kit_license") / "child")
    (root / LICENSE_REL).write_bytes(PRODUCT_LICENSE)
    _git(root, "config", "maintenance.auto", "false")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "product license")
    r = _run_cli(root, "init", ".", env=_env())
    assert r.returncode == 0, f"init упал:\n{r.stdout}\n{r.stderr}"
    return root


@pytest.fixture
def child(seed, tmp_path) -> Path:
    """Своя копия установки на тест — для проверок, которые её меняют."""
    root = tmp_path / "child"
    shutil.copytree(seed, root, ignore=shutil.ignore_patterns("maintenance.lock"))
    return root


def _make_legacy(root: Path) -> Path:
    """Установка «до #1481»: файла условий нет, и контрольные суммы о нём не знают."""
    managed = root / ".ai" / "managed"
    (managed / LICENSE_REL).unlink()
    _installer().write_checksums(managed)
    assert LICENSE_REL not in json.loads((managed / ".checksums.json").read_text())["files"]
    return managed


# ── состав поставки ──────────────────────────────────────────────────────────────────────────

def test_kit_license_is_in_the_delivery_set():
    """Условия кита входят в состав копии, и источник — корневой LICENSE кита, а не второй текст."""
    delivered = {rel: src for src, rel in _installer().managed_set()}
    assert LICENSE_REL in delivered, "LICENSE не входит в поставку — копии кита уйдут без условий"
    assert Path(delivered[LICENSE_REL]) == KIT_LICENSE


def test_license_ships_under_any_package_selection():
    """Файл не закреплён ни за одним пакетом: при выборе подмножества пакетов он всё равно едет."""
    ai_ops = _installer()
    ownership = ai_ops.package_ownership()
    assert LICENSE_REL not in ownership, (
        f"LICENSE отдан пакету {ownership.get(LICENSE_REL)!r} — проект без этого пакета его не получит")
    pairs = [(KIT_LICENSE, LICENSE_REL), (KIT / "registry" / "agents.yaml", "registry/agents.yaml")]
    kept = {rel for _, rel in ai_ops.filter_by_packages(pairs, ["ai-ops-quality"], ownership)}
    assert kept == {LICENSE_REL}, kept       # чужой пакет отсечён, условия остались


def test_license_text_is_delivered_untransformed():
    """Проекция поставки сжимает только Python движка; текст условий едет побайтно."""
    raw = KIT_LICENSE.read_bytes()
    assert _installer().managed_content(LICENSE_REL, raw) == raw


# ── positive: настоящая установка ────────────────────────────────────────────────────────────

def test_fresh_install_carries_byte_identical_kit_terms(seed):
    """После init условия лежат рядом с кодом кита, с адресом и строкой Required Notice."""
    installed = seed / ".ai" / "managed" / LICENSE_REL
    assert installed.is_file(), "после установки в проекте нет условий кита"
    data = installed.read_bytes()
    assert data == KIT_LICENSE.read_bytes()
    assert TERMS_URL in data
    assert any(line.startswith(NOTICE_PREFIX) for line in data.splitlines())


def test_installed_terms_are_under_checksum_control(seed):
    """Файл записан в контрольные суммы, и целая установка дрейфа не показывает."""
    managed = seed / ".ai" / "managed"
    recorded = json.loads((managed / ".checksums.json").read_text())["files"]
    assert recorded.get(LICENSE_REL) == _sha(managed / LICENSE_REL)
    assert _installer().detect_drift(managed) == []


def test_product_license_is_not_replaced_by_install(seed):
    """Side-effect proof: лицензия самого продукта после установки побайтно прежняя."""
    assert (seed / LICENSE_REL).read_bytes() == PRODUCT_LICENSE
    assert (seed / LICENSE_REL).read_bytes() != (seed / ".ai" / "managed" / LICENSE_REL).read_bytes()


# ── fail-closed: правка и удаление не выглядят целой установкой ───────────────────────────────

def test_changed_terms_are_reported_as_drift_and_reinstall_refuses(child):
    managed = child / ".ai" / "managed"
    (managed / LICENSE_REL).write_bytes(OLD_TERMS)
    drift = _installer().detect_drift(managed)
    assert [(d["path"], d["kind"]) for d in drift] == [(LICENSE_REL, "changed")]
    status = _run_cli(child, "status", env=_env())
    assert status.returncode != 0 and "ДРИФТ" in status.stdout, status.stdout + status.stderr
    again = _run_cli(child, "init", ".", env=_env())
    assert again.returncode != 0, "init поверх изменённых условий отчитался успехом"
    assert (managed / LICENSE_REL).read_bytes() == OLD_TERMS   # молча не перезаписано


def test_removed_terms_are_reported_as_drift(child):
    managed = child / ".ai" / "managed"
    (managed / LICENSE_REL).unlink()
    drift = _installer().detect_drift(managed)
    assert [(d["path"], d["kind"]) for d in drift] == [(LICENSE_REL, "removed")]
    status = _run_cli(child, "status", env=_env())
    assert status.returncode != 0 and "ДРИФТ" in status.stdout, status.stdout + status.stderr


# ── обновление ───────────────────────────────────────────────────────────────────────────────

def test_legacy_install_gets_terms_on_update_and_product_license_survives(child):
    """Установка без файла условий получает его обновлением; повторное сравнение пустое."""
    managed = _make_legacy(child)
    diff = _run_cli(child, "diff", env=_env())
    assert f".ai/managed/{LICENSE_REL}" in diff.stdout and "add" in diff.stdout, diff.stdout
    assert not (managed / LICENSE_REL).exists()          # diff ничего не пишет

    upd = _run_cli(child, "update", "--in-place", timeout=240, env=_env())
    assert upd.returncode == 0, upd.stdout + upd.stderr
    assert (managed / LICENSE_REL).read_bytes() == KIT_LICENSE.read_bytes()
    recorded = json.loads((managed / ".checksums.json").read_text())["files"]
    assert recorded.get(LICENSE_REL) == _sha(managed / LICENSE_REL)
    assert (child / LICENSE_REL).read_bytes() == PRODUCT_LICENSE
    second = _run_cli(child, "diff", env=_env())
    assert "diff пуст" in second.stdout, second.stdout


def test_terms_follow_the_version_being_installed(seed, tmp_path, monkeypatch):
    """Условия идут за версией: иной текст в источнике приходит как replace ровно одного файла.

    Так копия, поставленная под прежними условиями, получает новые только вместе с новым кодом —
    и наоборот, прежний выпуск со своим текстом ставит свой текст, а не вписанный в код.
    """
    ai_ops = _installer()
    other = tmp_path / "LICENSE-other-version"
    other.write_bytes(OLD_TERMS)
    pairs = [(other if rel == LICENSE_REL else src, rel) for src, rel in ai_ops.managed_set()]
    monkeypatch.setattr(ai_ops, "MANAGED", seed / ".ai" / "managed")
    monkeypatch.setattr(ai_ops._core()._load("delivery_ops"), "managed_set", lambda: pairs)
    changes = ai_ops.build_diff()
    assert [(c["path"], c["action"]) for c in changes] == [(f".ai/managed/{LICENSE_REL}", "replace")]


_FAILING_UPDATE = r'''
import importlib.util, sys
spec = importlib.util.spec_from_file_location("_inst_license_rollback", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
raise SystemExit(mod._update_ops().cmd_update(in_place=True, smoke_checks=[[sys.argv[2]]]))
'''


def test_failed_update_does_not_leave_terms_with_old_copy(child, tmp_path):
    """Сбой после доставки откатывает и файл условий: дерево проекта побайтно прежнее."""
    managed = _make_legacy(child)
    observed = tmp_path / "observed"
    probe = tmp_path / "smoke.py"
    probe.write_text(
        "from pathlib import Path\n"
        f"assert (Path.cwd() / '.ai/managed/{LICENSE_REL}').is_file()\n"   # доставка ПРОИЗОШЛА
        f"Path({str(observed)!r}).write_text('delivered')\n"
        "raise SystemExit(1)\n", encoding="utf-8")
    before = _tree(child)
    proc = subprocess.run([sys.executable, "-c", _FAILING_UPDATE, str(INSTALLER), str(probe)],
                          cwd=child, env=_env(), capture_output=True, text=True, timeout=240)
    report = json.loads((child / ".ai/runtime/last-update-report.json").read_text())
    assert observed.is_file(), proc.stdout + proc.stderr
    assert proc.returncode == 1 and report["status"] == "rolled_back", report
    assert not (managed / LICENSE_REL).exists()
    after = _tree(child)
    assert after == before, sorted(p for p in before.keys() | after.keys()
                                   if before.get(p) != after.get(p))
