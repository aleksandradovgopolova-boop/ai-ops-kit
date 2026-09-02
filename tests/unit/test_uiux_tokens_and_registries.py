"""UI/UX волна 2 (#418) — токены-контракт и реестры возможностей как данные + валидатор.

Валидатор `standards/uiux/scripts/validate-registries.py` — источник согласованности реестров и
токенов с Конституцией. Тесты, как и у волны 1:
  * positive     — закоммиченные токены/реестры валидатор признаёт согласованными (0 расхождений);
  * fail-closed  — на подделке КАЖДОГО класса (шкала, повисшая ссылка на правило/токен, пробел
                   каталога §16, сломанный трёхуровневый цвет) валидатор ДАЁТ РАСХОЖДЕНИЕ — не тавтология;
  * structural   — все файлы токенов §34 на месте, id токенов уникальны и валидны, реестры ссылаются
                   только на существующие правила/токены.

Изоляция подделок — на КОПИИ standards/uiux в tmp (валидатор самодостаточен под этим деревом),
реальный стандарт не трогаем.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
STD = REPO_ROOT / "standards" / "uiux"
TOKENS_DIR = STD / "design" / "tokens"
REG_DIR = STD / "registries"
VALIDATOR = STD / "scripts" / "validate-registries.py"

TOKEN_FILES = [
    "spacing.json", "radius.json", "layout.json", "colors.json",
    "typography.json", "shadows.json", "controls.json", "motion.json",
]


def _run(uiux_dir: Path):
    """Прогнать валидатор из скопированного дерева, вернуть разобранный JSON-отчёт."""
    script = uiux_dir / "scripts" / "validate-registries.py"
    r = subprocess.run([sys.executable, str(script), "--json"],
                       capture_output=True, text=True)
    assert r.returncode in (0, 1), "валидатор упал: " + (r.stderr or r.stdout)
    return json.loads(r.stdout)


def _copy(tmp: Path) -> Path:
    dst = tmp / "uiux"
    shutil.copytree(STD, dst)
    return dst


def _has(report, needle: str) -> bool:
    return any(needle in p for p in report.get("problems", []))


@pytest.mark.unit
def test_sources_present():
    """Токены §34, реестры, валидатор и схемы на месте."""
    assert VALIDATOR.is_file(), "нет validate-registries.py"
    for f in TOKEN_FILES:
        assert (TOKENS_DIR / f).is_file(), "нет токен-файла " + f
    assert (TOKENS_DIR / "README.md").is_file(), "нет контракта design/tokens/README.md"
    for f in ("components.yaml", "patterns.yaml", "templates.yaml"):
        assert (REG_DIR / f).is_file(), "нет реестра " + f
    for s in ("design-tokens.schema.json", "uiux-registry.schema.json"):
        assert (REPO_ROOT / "schemas" / s).is_file(), "нет схемы " + s


@pytest.mark.unit
def test_committed_state_is_consistent(tmp_path):
    """POSITIVE: закоммиченные токены и реестры согласованы с Конституцией (0 расхождений)."""
    report = _run(_copy(tmp_path))
    assert report["ok"] is True, "валидатор нашёл расхождения на согласованном дереве: " + json.dumps(
        report.get("problems", []), ensure_ascii=False)


@pytest.mark.unit
def test_fail_closed_scale_mismatch(tmp_path):
    """FAIL-CLOSED: правка значения шкалы в JSON расходится с таблицей Конституции."""
    uiux = _copy(tmp_path)
    p = uiux / "design" / "tokens" / "spacing.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    for e in data["tokens"]:
        if e["id"] == "spacing.4":
            e["value"] = 17  # значение вне шкалы
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    report = _run(uiux)
    assert report["ok"] is False and _has(report, "scale_mismatch"), (
        "валидатор не поймал расхождение шкалы токена с Конституцией")


@pytest.mark.unit
def test_fail_closed_dangling_rule_ref(tmp_path):
    """FAIL-CLOSED: ссылка записи реестра на несуществующее правило Конституции."""
    uiux = _copy(tmp_path)
    p = uiux / "registries" / "components.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    data["entries"][0]["constitution_refs"].append("UI-999")
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    report = _run(uiux)
    assert report["ok"] is False and _has(report, "dangling_rule_ref"), (
        "валидатор не поймал повисшую ссылку на правило")


@pytest.mark.unit
def test_fail_closed_dangling_token(tmp_path):
    """FAIL-CLOSED: ссылка записи реестра на несуществующий токен."""
    uiux = _copy(tmp_path)
    p = uiux / "registries" / "components.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    data["entries"][0]["tokens"].append("spacing.999")
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    report = _run(uiux)
    assert report["ok"] is False and _has(report, "dangling_token"), (
        "валидатор не поймал ссылку на несуществующий токен")


@pytest.mark.unit
def test_fail_closed_catalog_gap(tmp_path):
    """FAIL-CLOSED: паттерн из каталога §16 удалён из реестра -> пробел покрытия."""
    uiux = _copy(tmp_path)
    p = uiux / "registries" / "patterns.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    data["entries"] = [e for e in data["entries"] if e.get("catalog_key") != "поиск"]
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    report = _run(uiux)
    assert report["ok"] is False and _has(report, "catalog_gap"), (
        "валидатор не поймал незакрытый каталог §16")


@pytest.mark.unit
def test_fail_closed_broken_color_tier(tmp_path):
    """FAIL-CLOSED: semantic-цвет ссылается не на primitive и не на hex (нарушение §21)."""
    uiux = _copy(tmp_path)
    p = uiux / "design" / "tokens" / "colors.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["semantic"][0]["light"] = "neutral.404"  # нет такого primitive
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    report = _run(uiux)
    assert report["ok"] is False and _has(report, "broken_tier"), (
        "валидатор не поймал разрыв трёхуровневой архитектуры цвета")


@pytest.mark.unit
def test_token_ids_unique_and_wellformed():
    """STRUCTURAL: id токенов уникальны и имеют вид dot-path (stable id)."""
    ids = []
    pat = re.compile(r"^[a-z0-9]+(\.[A-Za-z0-9]+)*$")
    for f in TOKEN_FILES:
        data = json.loads((TOKENS_DIR / f).read_text(encoding="utf-8"))
        stack = [data]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                if isinstance(o.get("id"), str):
                    ids.append(o["id"])
                stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
    assert len(ids) == len(set(ids)), "дубли id токенов: " + str(sorted(i for i in ids if ids.count(i) > 1))
    bad = [i for i in ids if not pat.match(i)]
    assert not bad, "id токена не вида dot-path: " + str(bad)


@pytest.mark.unit
def test_registries_are_data_with_refs():
    """STRUCTURAL: реестры — данные; каждая запись несёт id и хотя бы одну ссылку на Конституцию."""
    for f in ("components.yaml", "patterns.yaml", "templates.yaml"):
        data = yaml.safe_load((REG_DIR / f).read_text(encoding="utf-8"))
        assert data.get("entries"), f + " без записей"
        for e in data["entries"]:
            assert e.get("id"), f + ": запись без id"
            assert e.get("constitution_refs"), f + "/" + str(e.get("id")) + ": нет constitution_refs"
