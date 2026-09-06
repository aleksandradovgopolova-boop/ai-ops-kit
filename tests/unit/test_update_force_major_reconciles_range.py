#!/usr/bin/env python3
"""Форс-мажорное обновление согласует allowed_version_range, а doctor краснеет на installed ∉ allowed.

ПОВОД — ЗАМЕР ПОЛЯ (дочка cockpit, `ai-ops update --force` 3.39.0 -> 4.0.0, 06.09.2026).
`cmd_update` при форсированном переходе через границу мажора поднимал `parent.installed_version`
до 4.0.0, но `parent.allowed_version_range` оставлял прежним ('>=3.0.0 <4.0.0'). В итоге
installed=4.0.0 оказывалась ВНЕ своего же диапазона: `version_in_range('4.0.0', '>=3.0.0 <4.0.0')`
== False. Следствие связкой:
  * следующий ШТАТНЫЙ in-range апдейт молча «пропускался» как несовместимый (см. `cmd_update`:
    soft-skip при target ∉ allowed) — тихая заморозка обновлений;
  * `cmd_doctor` этого не проверял и рапортовал «версии: ✓» и «всё в порядке» — инструмент, который
    для этого и существует, о заморозке молчал.

Две проверяемые способности:
  * форс-мажор расширяет диапазон так, что installed СНОВА ∈ allowed (и штатный in-range путь его
    НЕ трогает);
  * doctor краснеет на installed ∉ allowed и зелен на installed ∈ allowed.

Обновление зовём с `--in-place`: предмет — механика согласования диапазона, а не политика доставки
(без флага путь ушёл бы в отложенный режим и проверял бы не то, что обещано в имени).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from _installer_helpers import _isolated_env, _run_cli

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"

pytestmark = pytest.mark.unit


def _load_installer():
    """Импортировать installer/ai_ops.py как модуль (он не пакет — грузим по пути)."""
    spec = importlib.util.spec_from_file_location("installer_ai_ops_range_under_test", INSTALLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_cfg(root: Path) -> dict:
    return yaml.safe_load((root / ".ai-ops.yaml").read_text(encoding="utf-8"))


def _set_parent(root: Path, *, installed: str, allowed: str) -> None:
    """Переписать installed_version и allowed_version_range БЕЗ пересборки файла (re.sub, как кит).

    Пишем ровно ту раскладку, что кладёт `init` (диапазон в кавычках) — чтобы тест мерил механику
    согласования, а не терпимость к переформатированию конфига.
    """
    import re
    p = root / ".ai-ops.yaml"
    text = p.read_text(encoding="utf-8")
    text = re.sub(r"(installed_version:\s*)\S+", rf"\g<1>{installed}", text, count=1)
    text = re.sub(r'(allowed_version_range:\s*)"[^"]*"', rf'\g<1>"{allowed}"', text, count=1)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- часть 1: cmd_update


def test_forced_major_update_widens_range_so_installed_is_in_range_again(installed_copy):
    """positive: форс-мажор расширяет диапазон — installed СНОВА попадает в allowed_version_range.

    Воспроизводим замер cockpit: installed=3.39.0, allowed='>=3.0.0 <4.0.0', пакет 4.0.0 (VERSION).
    После `update --force --in-place` диапазон обязан расшириться под новый мажор, а не остаться
    прежним — иначе installed=4.0.0 вне своего же диапазона.
    """
    mod = _load_installer()
    target = mod.pkg_version()  # актуальный мажор кита (в этом репозитории — 4.0.0)
    old_major = mod.parse_version(target)[0] - 1
    assert old_major >= 1, "тесту нужен пакет с мажором >= 2, чтобы «предыдущий мажор» существовал"
    old_range = f">={old_major}.0.0 <{old_major + 1}.0.0"

    _set_parent(installed_copy, installed=f"{old_major}.39.0", allowed=old_range)
    # предпосылка: ЦЕЛЬ (новый мажор) вне прежнего диапазона — потому переход и форсированный;
    # именно после подъёма installed до цели без расширения диапазона installed окажется вне него.
    assert not mod.version_in_range(target, old_range)

    r = _run_cli(installed_copy, "update", "--force", "--in-place")
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]

    after = _read_cfg(installed_copy)["parent"]
    expected = mod.compatible_range_for(target)
    assert after["allowed_version_range"] == expected, (
        f"диапазон не расширен под новый мажор: {after['allowed_version_range']!r} != {expected!r}")
    assert str(after["installed_version"]) == target
    assert mod.version_in_range(str(after["installed_version"]), after["allowed_version_range"]), (
        "installed после форс-мажора всё ещё вне своего же диапазона — тихая заморозка осталась")
    # названо человеку, а не сделано молча
    assert "allowed_version_range расширен" in (r.stdout + r.stderr), (r.stdout + r.stderr)[-2000:]


def test_in_range_update_does_not_touch_the_range(installed_copy):
    """fail-closed: штатный in-range апдейт диапазон НЕ трогает — расширение только на форс-мажоре.

    Свежая установка стоит на актуальном мажоре и в своём диапазоне. Повторный `update --in-place`
    (без --force) — штатный путь: диапазон обязан остаться байт-в-байт прежним, иначе кит молча
    переписывал бы решение владельца при каждом обновлении.
    """
    before = _read_cfg(installed_copy)["parent"]["allowed_version_range"]
    r = _run_cli(installed_copy, "update", "--in-place")
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    after = _read_cfg(installed_copy)["parent"]["allowed_version_range"]
    assert after == before, f"штатный in-range апдейт тронул диапазон: {before!r} -> {after!r}"
    assert "allowed_version_range расширен" not in (r.stdout + r.stderr)


def test_widen_allowed_range_is_a_noop_when_field_is_absent(tmp_path, monkeypatch):
    """Обратная сторона: нет поля allowed_version_range — расширять нечего, возвращаем None и молчим.

    Гарантирует, что helper не роняет конфиг владельца без диапазона (например, дочку, где поле
    задаётся дефолтом) и не выдумывает поле, которого не было.
    """
    mod = _load_installer()
    cfg = tmp_path / ".ai-ops.yaml"
    cfg.write_text("parent:\n  installed_version: 3.39.0\n", encoding="utf-8")
    monkeypatch.setattr(mod, "CHILD_CONFIG", cfg)
    assert mod.widen_allowed_range("4.0.0") is None
    assert "allowed_version_range" not in cfg.read_text(encoding="utf-8")


# ---------------------------------------------------------------- часть 2: cmd_doctor


def test_doctor_flags_installed_out_of_allowed_range(installed_copy, tmp_path):
    """doctor краснеет (`✗`), когда installed вне allowed_version_range — иначе тихая заморозка.

    Ставим installed вне диапазона (тот самый след cockpit) и требуем, чтобы doctor НАЗВАЛ проблему
    и её последствие, а не отрапортовал «в порядке». Окружение изолировано (см. `_isolated_env`),
    иначе тест мерил бы чистоту site-packages разработчика."""
    _set_parent(installed_copy, installed="4.0.0", allowed=">=3.0.0 <4.0.0")
    env = _isolated_env(tmp_path)
    r = _run_cli(installed_copy, "doctor", env=env)
    out = r.stdout + r.stderr
    assert "Traceback" not in out
    assert "диапазон версий: ✗" in out, f"doctor не заметил installed вне диапазона: {out[-2000:]}"
    assert "молча пропустится" in out, "doctor не назвал последствие (тихая заморозка обновлений)"
    # вердикт следует за худшей строкой: `✗` не может соседствовать с «всё в порядке»
    assert "Всё в порядке" not in out, out[-2000:]


def test_doctor_green_on_installed_in_allowed_range(installed_copy, tmp_path):
    """Пара к тесту выше: та же установка, диапазон покрывает installed — doctor зелен по этой строке.

    Единственное отличие от красного случая — согласованный диапазон, значит красным doctor делает
    именно рассогласование, а не что-то ещё."""
    _set_parent(installed_copy, installed="4.0.0", allowed=">=4.0.0 <5.0.0")
    env = _isolated_env(tmp_path)
    r = _run_cli(installed_copy, "doctor", env=env)
    out = r.stdout + r.stderr
    assert "Traceback" not in out
    assert "диапазон версий: ✓" in out, f"doctor не подтвердил согласованный диапазон: {out[-2000:]}"
    assert "диапазон версий: ✗" not in out, out[-2000:]
