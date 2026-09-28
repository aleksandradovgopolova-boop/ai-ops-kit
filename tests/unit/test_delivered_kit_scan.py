"""Кит меряет себя тем же сканером, которым его меряет дочка (#1157).

ПОВОД. В дочке сканер выносит флаги на установленную копию кита (`.ai/managed/`) в раздел
«адресат — сопровождающий кита», и до кита этот раздел не доходил. Замер на свежей установке
(имитация дочки: `managed_set()` под `.ai/managed/`): 4 адреса — `shell=True` в `tool_broker`,
два в `regression_evidence` и реестр правил `security/security-domains.yaml`, где имя правила
стоит значением. Стало 1.

ОСТАВШИЙСЯ АДРЕС — ПРАВДА, А НЕ ШУМ. Ветка оболочки `tool_broker` исполняет команды модели с
конвейерами и перенаправлениями — это объявленная возможность op `shell` со своим контуром
(политика, скраб окружения, таймаут, сторож путей). Спрятать её от сканера было бы подгонкой
замера. Поэтому ожидаемое множество объявлено ПОИМЁННО с причиной: новый адрес в поставке
краснеет здесь, в ките, а не всплывает у дочки.

Раздел тела PR обновления кита (путь 2 issue) сторожится здесь же: пустой список — явное
«ничего», сбой скана — «проверить не удалось», а не молчание.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from ai_ops_kit.security import security_scan

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
PREFIX = ".ai/managed/"

# Объявленная поверхность поставки: (путь в ките, правило) -> почему это не шум.
DECLARED_SURFACE = {
    ("ai_ops_kit/engine/tool_broker.py", "subprocess_shell_true"):
        "op shell исполняет конвейеры/перенаправления модели; контур — Policy.decide, scrub_env, "
        "timeout, сторож путей; команды без синтаксиса оболочки идут списком",
}


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def delivered_flags():
    """Флаги сканера на поставке так, как её видит дочка на свежей установке."""
    files = {}
    for src, rel in _load("_inst_1157", "installer/ai_ops.py").managed_set():
        raw = src.read_bytes()
        if b"\x00" not in raw[:8192]:
            files[PREFIX + rel] = raw.decode("utf-8", errors="ignore")
    return security_scan.scan_injection(files)


def test_fresh_install_delivery_section_holds_only_the_declared_surface(delivered_flags):
    got = {(f["path"].removeprefix(PREFIX), f["id"]) for f in delivered_flags}
    assert got == set(DECLARED_SURFACE), (
        "раздел поставки на свежей установке изменился — новый адрес уедет в каждую дочку:\n"
        + "\n".join(f"  {f['id']} — {f['path']}:{f['line']}" for f in delivered_flags))


def test_every_delivered_flag_lands_in_the_vendor_section(delivered_flags):
    """Всё, что сканер нашёл на поставке, дочка видит в разделе кита, а не в своём коде."""
    assert delivered_flags and all(f["area"] == "vendor" for f in delivered_flags)


def test_declared_surface_has_exactly_one_address_per_entry(delivered_flags):
    """Объявление покрывает одно место, а не весь файл: второй `shell=True` рядом краснеет."""
    for key in DECLARED_SURFACE:
        hits = [f for f in delivered_flags if (f["path"].removeprefix(PREFIX), f["id"]) == key]
        assert len(hits) == 1, (key, hits)


def test_rules_registry_is_read_as_detector_material_in_the_child():
    """Реестр правил в дочке — материал детектора, а не код: имена правил там значения."""
    rel = "security/security-domains.yaml"
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert security_scan.scan_injection({"проба.yaml": text}), "реестр перестал называть правила"
    assert security_scan.scan_injection({PREFIX + rel: text}) == []
    assert security_scan.scan_injection({rel: text}) == []


# ─── путь 2: раздел тела PR обновления кита ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def update_ops():
    _load("_inst_1157_hub", "installer/ai_ops.py")
    return _load("_update_ops_1157", "installer/update_ops.py")


def test_update_section_says_nothing_explicitly(update_ops):
    text = update_ops.security_surface_section(".", [], scan=lambda root, changed: [])
    assert "Что этот выпуск привозит по безопасности" in text
    assert "ничего" in text


def test_update_section_names_what_arrived(update_ops):
    flags = [{"id": "subprocess_shell_true", "path": ".ai/managed/ai_ops_kit/x.py", "line": 7,
              "arrived": True},
             {"id": "eval_or_exec", "path": ".ai/managed/ai_ops_kit/y.py", "line": 3,
              "arrived": False}]
    text = update_ops.security_surface_section(".", [], scan=lambda root, changed: flags)
    assert "НОВОЕ subprocess_shell_true — .ai/managed/ai_ops_kit/x.py:7" in text
    assert "eval_or_exec" not in text, "бывшее раньше не новость — свёрнуто числом"
    assert "в прежней версии: 1" in text
    assert "ничего" not in text


def test_update_section_scan_failure_is_not_nothing(update_ops):
    def boom(root, changed):
        raise RuntimeError("сканер упал")
    text = update_ops.security_surface_section(".", [], scan=boom)
    assert "НЕ УДАЛОСЬ" in text and "ничего:" not in text


def test_delivered_surface_marks_arrivals_against_base(tmp_path):
    """Настоящий скан поставки против прежней версии: приехавший адрес отмечен, бывший — нет."""
    import subprocess

    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], capture_output=True, check=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    old = tmp_path / ".ai/managed/ai_ops_kit/old.py"
    old.parent.mkdir(parents=True)
    опасно = "subprocess.run(cmd, " + "shell=True)\n"
    old.write_text(опасно, encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "старый кит")
    new = tmp_path / ".ai/managed/ai_ops_kit/new.py"
    new.write_text(опасно, encoding="utf-8")
    (tmp_path / "app.py").write_text(опасно, encoding="utf-8")   # код продукта — не поставка
    old.write_text("# правка\n" + опасно, encoding="utf-8")
    changed = [".ai/managed/ai_ops_kit/new.py", ".ai/managed/ai_ops_kit/old.py", "app.py"]
    flags = security_scan.delivered_surface(tmp_path, changed, base="HEAD")
    by_path = {f["path"]: f["arrived"] for f in flags}
    assert by_path == {".ai/managed/ai_ops_kit/new.py": True,
                       ".ai/managed/ai_ops_kit/old.py": False}
