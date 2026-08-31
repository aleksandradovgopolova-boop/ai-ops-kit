"""UI/UX Constitution — источник; ui-ux.rules.md и rules.yaml генерируются из него (волна 1).

Тест-ЗЕРКАЛО: генерируемые представления обязаны совпадать с тем, что производит генератор из
UI_CONSTITUTION.md. Расхождение (ручная правка генерата или правка Конституции без пересборки)
краснит контур — как прочие зеркала кита (check-fast↔CI, layering).

Три теста на capability — positive, fail-closed, side-effect proof:
  * positive     — пересборка из источника воспроизводит закоммиченные генераты байт-в-байт;
  * fail-closed  — та же сверка-страж, что защищает генерат, ДАЁТ КРАСНОЕ на подделке (не тавтология);
  * side-effect  — генератор пишет только свои три файла и детерминирован (второй прогон идентичен).

Плюс независимый структурный якорь: число/множество правил считается ИЗ ИСТОЧНИКА своим разбором
(лениво, любой разделитель), а не доверяется счётчику генератора — иначе малформатный заголовок
тихо выпал бы из генерата, а `rules_total` остался бы честным на вид.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
STD = REPO_ROOT / "standards" / "uiux"
SRC = STD / "UI_CONSTITUTION.md"
GEN = STD / "scripts" / "build-rules.py"
RULES_MD = STD / "ui-ux.rules.md"
RULES_YAML = STD / "rules.yaml"


def _generate_into(tmp: Path) -> tuple[str, str]:
    """Прогнать генератор на копии Конституции в изолированном каталоге. -> (rules.yaml, rules.md)."""
    tmp.mkdir(parents=True, exist_ok=True)
    src = tmp / "UI_CONSTITUTION.md"
    src.write_text(SRC.read_text(encoding="utf-8"), encoding="utf-8")
    r = subprocess.run([sys.executable, str(GEN), str(src)], capture_output=True, text=True)
    assert r.returncode == 0, f"генератор упал: {r.stderr or r.stdout}"
    return (tmp / "rules.yaml").read_text(encoding="utf-8"), (tmp / "ui-ux.rules.md").read_text(encoding="utf-8")


def _mirror_ok(committed: str, regenerated: str) -> bool:
    """Сверка-страж: закоммиченный генерат совпадает с пересборкой из источника.

    Ровно эту функцию использует и positive-, и fail-closed-тест: fail-closed проверяет НЕ «строка
    != строки», а что САМ страж возвращает False на подделке. Иначе тест доказывал бы тавтологию."""
    return committed == regenerated


def _source_rule_ids() -> list[str]:
    """ID правил, посчитанные ИЗ ИСТОЧНИКА независимым (ленивым) разбором.

    Лениво к разделителю (`#{3,4}`, любой хвост после ID) намеренно: если правило добавят с
    двоеточием вместо ` · ` или четырьмя `#`, строгий парсер генератора его молча уронит, а этот
    счёт — нет, и множества разойдутся -> красное. Так закрывается путь «правило потеряно, но
    rules_total честен на вид»."""
    md = SRC.read_text(encoding="utf-8")
    headings = re.findall(r"(?m)^#{3,4}\s+(UI-\d+|AI-\d+)\b", md)
    forbidden = re.findall(r"(?m)^\|\s*\*\*(UI-FORBIDDEN-\d+)\*\*", md)
    return headings + forbidden


def _load_generator():
    """Импортировать генератор по пути (имя с дефисом нельзя импортировать обычным import)."""
    spec = importlib.util.spec_from_file_location("uiux_build_rules", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.unit
def test_source_and_generator_present():
    """Источник и генератор на месте — стандарт самодостаточен."""
    assert SRC.is_file(), "нет UI_CONSTITUTION.md — источника стандарта"
    assert GEN.is_file(), "нет scripts/build-rules.py — генератора"
    assert RULES_MD.is_file() and RULES_YAML.is_file(), "нет сгенерированных представлений"


@pytest.mark.unit
def test_generated_files_match_source(tmp_path):
    """POSITIVE: закоммиченные ui-ux.rules.md и rules.yaml == пересборке из Конституции."""
    got_yaml, got_md = _generate_into(tmp_path)
    assert _mirror_ok(RULES_YAML.read_text(encoding="utf-8"), got_yaml), (
        "rules.yaml разошёлся с генерацией из UI_CONSTITUTION.md — пересоберите: "
        "python standards/uiux/scripts/build-rules.py")
    assert _mirror_ok(RULES_MD.read_text(encoding="utf-8"), got_md), (
        "ui-ux.rules.md разошёлся с генерацией из UI_CONSTITUTION.md — пересоберите генератором")


@pytest.mark.unit
def test_mirror_guard_is_fail_closed(tmp_path):
    """FAIL-CLOSED: сам страж `_mirror_ok` даёт КРАСНОЕ на подделке, а не только на разных строках."""
    got_yaml, _ = _generate_into(tmp_path)
    # В синхронном состоянии страж зелёный...
    assert _mirror_ok(got_yaml, got_yaml) is True, "страж краснит синхронный генерат — ложное красное"
    # ...а на ручной правче генерата (одна строка) — обязан покраснеть.
    tampered = got_yaml.replace("severity: medium", "severity: low", 1)
    assert tampered != got_yaml, "мутация не изменила файл — тест бессилен"
    assert _mirror_ok(tampered, got_yaml) is False, (
        "страж НЕ ловит рассинхрон генерата с источником — зеркало дырявое")


@pytest.mark.unit
def test_all_source_rules_are_captured():
    """АНТИ-ТИХАЯ-ПОТЕРЯ: множество ID из источника == множеству ID в rules.yaml (обе стороны).

    Независимо от счётчика генератора: малформатное правило, которое строгий парсер уронил, здесь
    останется в source-множестве и разойдётся с реестром -> красное. Обратное (правило убрали из
    источника, но забыли из реестра) тоже краснеет."""
    source_ids = _source_rule_ids()
    d = yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))
    yaml_ids = [r["id"] for r in d["rules"]]
    assert set(source_ids) == set(yaml_ids), (
        f"источник и реестр разошлись — только в источнике: {sorted(set(source_ids) - set(yaml_ids))}; "
        f"только в реестре: {sorted(set(yaml_ids) - set(source_ids))}")
    assert d["rules_total"] == len(source_ids), (
        f"rules_total={d['rules_total']} не совпал с числом правил в источнике ({len(source_ids)})")


@pytest.mark.unit
def test_generation_is_deterministic(tmp_path):
    """SIDE-EFFECT: два прогона генератора дают идентичный результат."""
    a_yaml, a_md = _generate_into(tmp_path / "a")
    b_yaml, b_md = _generate_into(tmp_path / "b")
    assert a_yaml == b_yaml and a_md == b_md, "генерация недетерминирована — зеркало нестабильно"


@pytest.mark.unit
def test_generator_writes_only_its_three_files(tmp_path):
    """SIDE-EFFECT: генератор создаёт ровно источник + два представления, ничего лишнего."""
    _generate_into(tmp_path)
    produced = {p.name for p in tmp_path.iterdir()}
    assert produced == {"UI_CONSTITUTION.md", "rules.yaml", "ui-ux.rules.md"}, (
        f"генератор тронул посторонние файлы: {produced}")


@pytest.mark.unit
def test_rules_yaml_form_is_valid():
    """ФОРМА: реестр парсится, ID уникальны, уровни из замкнутого словаря."""
    d = yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))
    rules = d["rules"]
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids)), f"дубли ID правил: {sorted({i for i in ids if ids.count(i) > 1})}"
    assert {r["level"] for r in rules} <= {"MUST", "SHOULD", "MUST_NOT", "MAY"}, "level вне словаря"


@pytest.mark.unit
def test_generator_id_sets_reference_real_rules():
    """АНТИ-МЁРТВАЯ-ССЫЛКА: хардкод-множества severity/automated в генераторе ⊆ ID источника."""
    gen = _load_generator()
    source_ids = set(_source_rule_ids())
    for name in ("AUTOMATABLE", "CRITICAL", "HIGH", "AI_OPS_FORBIDDEN"):
        ids = getattr(gen, name)
        assert ids <= source_ids, f"{name} ссылается на ID вне Конституции (мёртвая ссылка): {ids - source_ids}"
