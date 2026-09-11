"""UI/UX волна 2 (#418) — контракт токенов (tokens.yaml) и capability-реестр (capabilities.yaml)
как ПРОВЕРЯЕМЫЕ ДАННЫЕ.

Исход роадмапа `tokens_contract_and_capability_registries_available`: реестры доступны как данные =
есть код, который их читает и валидирует, а не просто yaml лежит. Источник согласованности —
`standards/uiux/scripts/validate-registries.py`; он же гоняется здесь через CLI.

Три обязательных теста на capability (AGENTS.md):
  * positive     — валидатор ГРУЗИТ оба новых реестра и на закоммиченном дереве не находит расхождений;
  * fail-closed  — подделка КАЖДОГО нового класса (namespace, источник токенов, sample, повисшая
                   ссылка capability на правило/компонент) даёт РАСХОЖДЕНИЕ, а не проходит молча;
  * side-effect  — реестры реально ЧИТАЮТСЯ кодом (данные, не мёртвый файл): удаление namespace из
                   tokens.yaml роняет capability, что на него ссылалась — значит capabilities.yaml
                   валидируется ПРОТИВ tokens.yaml, оба прочитаны.

Подделки изолированы на КОПИИ standards/uiux в tmp; реальный стандарт не трогаем.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
STD = REPO_ROOT / "standards" / "uiux"
REG_DIR = STD / "registries"
TOKENS_YAML = REG_DIR / "tokens.yaml"
CAPS_YAML = REG_DIR / "capabilities.yaml"
COMPONENTS_YAML = REG_DIR / "components.yaml"
RULES_YAML = STD / "rules.yaml"

pytestmark = pytest.mark.unit


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


def _load(p: Path):
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _dump(p: Path, data) -> None:
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


# ─── positive ─────────────────────────────────────────────────────────────────────────────────────

def test_new_registries_present():
    """Оба новых реестра лежат рядом с существующими."""
    assert TOKENS_YAML.is_file(), "нет registries/tokens.yaml"
    assert CAPS_YAML.is_file(), "нет registries/capabilities.yaml"


def test_committed_state_is_consistent(tmp_path):
    """POSITIVE: валидатор грузит tokens.yaml + capabilities.yaml и не находит расхождений."""
    report = _run(_copy(tmp_path))
    assert report["ok"] is True, "валидатор нашёл расхождения: " + json.dumps(
        report.get("problems", []), ensure_ascii=False)


def test_kinds_are_declared():
    """STRUCTURAL: реестры объявляют свой kind (tokens/capabilities) — данные самоописаны."""
    assert _load(TOKENS_YAML).get("kind") == "tokens"
    assert _load(CAPS_YAML).get("kind") == "capabilities"


# ─── fail-closed: контракт токенов ──────────────────────────────────────────────────────────────

def test_fail_closed_tokens_empty_namespace(tmp_path):
    """FAIL-CLOSED: namespace контракта не покрывает ни одного реального токена."""
    uiux = _copy(tmp_path)
    p = uiux / "registries" / "tokens.yaml"
    data = _load(p)
    data["entries"][0]["namespace"] = "bogus"  # такого префикса нет в design/tokens
    _dump(p, data)
    report = _run(uiux)
    assert report["ok"] is False and _has(report, "empty_namespace"), (
        "валидатор не поймал namespace без токенов")


def test_fail_closed_tokens_missing_source(tmp_path):
    """FAIL-CLOSED: source указывает на несуществующий файл токенов."""
    uiux = _copy(tmp_path)
    p = uiux / "registries" / "tokens.yaml"
    data = _load(p)
    data["entries"][0]["source"] = "does-not-exist.json"
    _dump(p, data)
    report = _run(uiux)
    assert report["ok"] is False and _has(report, "missing_source"), (
        "валидатор не поймал битый source")


def test_fail_closed_tokens_dangling_sample(tmp_path):
    """FAIL-CLOSED: sample-id контракта не существует в design/tokens."""
    uiux = _copy(tmp_path)
    p = uiux / "registries" / "tokens.yaml"
    data = _load(p)
    data["entries"][0]["sample"].append("spacing.999")
    _dump(p, data)
    report = _run(uiux)
    assert report["ok"] is False and _has(report, "dangling_token"), (
        "валидатор не поймал sample на несуществующий токен")


# ─── fail-closed: capability ────────────────────────────────────────────────────────────────────

def test_fail_closed_capability_dangling_rule_ref(tmp_path):
    """FAIL-CLOSED: capability ссылается на несуществующее правило Конституции."""
    uiux = _copy(tmp_path)
    p = uiux / "registries" / "capabilities.yaml"
    data = _load(p)
    data["entries"][0]["constitution_refs"].append("UI-999")
    _dump(p, data)
    report = _run(uiux)
    assert report["ok"] is False and _has(report, "dangling_rule_ref"), (
        "валидатор не поймал повисшую ссылку capability на правило")


def test_fail_closed_capability_dangling_namespace(tmp_path):
    """FAIL-CLOSED: capability ссылается на namespace токенов, не объявленный в tokens.yaml."""
    uiux = _copy(tmp_path)
    p = uiux / "registries" / "capabilities.yaml"
    data = _load(p)
    data["entries"][0].setdefault("token_namespaces", []).append("bogus")
    _dump(p, data)
    report = _run(uiux)
    assert report["ok"] is False and _has(report, "dangling_namespace"), (
        "валидатор не поймал ссылку capability на необъявленный namespace")


def test_fail_closed_capability_dangling_backed_by(tmp_path):
    """FAIL-CLOSED: capability опирается на несуществующий компонент/паттерн."""
    uiux = _copy(tmp_path)
    p = uiux / "registries" / "capabilities.yaml"
    data = _load(p)
    data["entries"][0].setdefault("backed_by", []).append("comp.does-not-exist")
    _dump(p, data)
    report = _run(uiux)
    assert report["ok"] is False and _has(report, "dangling_local"), (
        "валидатор не поймал ссылку capability на несуществующий компонент")


# ─── честная градация статуса capability: проверяется данными, а не декларацией ──────────────────

CAP_STATUS_VOCAB = {"guaranteed_by_shipped_code", "required_by_standard", "planned"}


def test_committed_statuses_are_honest_gradation():
    """STRUCTURAL: каждый закоммиченный статус — из закрытого словаря честной градации, и ни одна
    запись не заявляет guaranteed_by_shipped_code (backing — каталожная спека, standards/uiux не едет)."""
    caps = _load(CAPS_YAML)
    entries = caps.get("entries", [])
    assert entries, "capabilities.yaml без записей"
    for e in entries:
        st = e.get("status")
        assert st in CAP_STATUS_VOCAB, e.get("id") + ": статус '" + str(st) + "' вне словаря"
        if st == "guaranteed_by_shipped_code":
            assert e.get("shipped_backing"), (
                e.get("id") + ": guaranteed_by_shipped_code без shipped_backing — завышение")


def test_fail_closed_capability_unknown_status(tmp_path):
    """FAIL-CLOSED: статус вне закрытого словаря ловится как unknown_status, а не проходит молча."""
    uiux = _copy(tmp_path)
    p = uiux / "registries" / "capabilities.yaml"
    data = _load(p)
    data["entries"][0]["status"] = "guaranteed"  # старое самодекларативное значение — теперь недопустимо
    _dump(p, data)
    report = _run(uiux)
    assert report["ok"] is False and _has(report, "unknown_status"), (
        "валидатор не поймал статус вне закрытого словаря")


def test_fail_closed_unsubstantiated_guarantee(tmp_path):
    """FAIL-CLOSED (проба краснеет на дефекте): guaranteed_by_shipped_code без доказанного backing
    (нет shipped_backing) → unsubstantiated_guarantee. Гарантия без едущего кода — красная."""
    uiux = _copy(tmp_path)
    p = uiux / "registries" / "capabilities.yaml"
    data = _load(p)
    data["entries"][0]["status"] = "guaranteed_by_shipped_code"  # без shipped_backing
    data["entries"][0].pop("shipped_backing", None)
    _dump(p, data)
    report = _run(uiux)
    assert report["ok"] is False and _has(report, "unsubstantiated_guarantee"), (
        "валидатор не покраснел на гарантии без доказанного shipped_backing")


def _copy_realdepth(tmp: Path) -> Path:
    """Копия с реальной глубиной repo/standards/uiux — валидатор вычисляет REPO_ROOT = parents[1],
    поэтому shipped_backing (repo-относительные пути) резолвятся как в настоящем дереве."""
    dst = tmp / "standards" / "uiux"
    shutil.copytree(STD, dst)
    return dst


def test_guarantee_backed_inside_standard_is_still_unsubstantiated(tmp_path):
    """FAIL-CLOSED: shipped_backing, указывающий ВНУТРЬ standards/uiux/** (дерево-стандарт в дочку
    не едет), не засчитывается за гарантию — по-прежнему unsubstantiated_guarantee."""
    uiux = _copy_realdepth(tmp_path)  # REPO_ROOT валидатора = tmp_path
    p = uiux / "registries" / "capabilities.yaml"
    data = _load(p)
    data["entries"][0]["status"] = "guaranteed_by_shipped_code"
    # путь СУЩЕСТВУЕТ (внутри скопированного стандарта), но лежит в standards/uiux — не едет в дочку
    data["entries"][0]["shipped_backing"] = ["standards/uiux/registries/capabilities.yaml"]
    _dump(p, data)
    report = _run(uiux)
    assert report["ok"] is False and _has(report, "unsubstantiated_guarantee"), (
        "backing внутри standards/uiux не должен считаться доказанной гарантией")


def test_substantiated_guarantee_is_green(tmp_path):
    """POSITIVE: guaranteed_by_shipped_code с shipped_backing на РЕАЛЬНЫЙ артефакт вне standards/uiux
    — не краснит. Доказывает, что зелень честная (проба зеленеет ровно при доказанном backing)."""
    uiux = _copy_realdepth(tmp_path)  # REPO_ROOT валидатора = tmp_path
    (tmp_path / "shipped_real_component.py").write_text("# едущий в дочку артефакт\n", encoding="utf-8")
    p = uiux / "registries" / "capabilities.yaml"
    data = _load(p)
    data["entries"][0]["status"] = "guaranteed_by_shipped_code"
    data["entries"][0]["shipped_backing"] = ["shipped_real_component.py"]
    _dump(p, data)
    report = _run(uiux)
    assert not _has(report, "unsubstantiated_guarantee"), (
        "доказанный shipped_backing не должен краснить: " + json.dumps(
            report.get("problems", []), ensure_ascii=False))


# ─── side-effect: реестры реально читаются как данные ───────────────────────────────────────────

def test_capabilities_validated_against_tokens_registry(tmp_path):
    """SIDE-EFFECT: удаление namespace из tokens.yaml роняет capability, что на него ссылалась —
    доказывает, что capabilities.yaml валидируется ПРОТИВ tokens.yaml (оба прочитаны как данные)."""
    uiux = _copy(tmp_path)
    tp = uiux / "registries" / "tokens.yaml"
    cp = uiux / "registries" / "capabilities.yaml"

    # выберем namespace, на который реально ссылается хотя бы одна capability
    caps = _load(cp)
    used_ns = set()
    for e in caps.get("entries", []):
        used_ns.update(e.get("token_namespaces", []))
    assert used_ns, "capabilities.yaml не ссылается ни на один namespace — тест бессмысленен"
    victim = sorted(used_ns)[0]

    # до правки — согласовано
    assert _run(uiux)["ok"] is True

    # убираем объявление namespace из контракта токенов
    tokens = _load(tp)
    tokens["entries"] = [e for e in tokens["entries"] if e.get("namespace") != victim]
    _dump(tp, tokens)

    report = _run(uiux)
    assert report["ok"] is False and _has(report, "dangling_namespace"), (
        "capability не проверяется против tokens.yaml — один из реестров не читается")


def test_capability_refs_resolve_in_real_data():
    """SIDE-EFFECT/STRUCTURAL: закоммиченный capabilities.yaml — живые данные: каждая запись несёт id
    и правило Конституции, а её backed_by указывают на реальные id из components/patterns/templates."""
    caps = _load(CAPS_YAML)
    assert caps.get("entries"), "capabilities.yaml без записей"

    rule_ids = {r["id"] for r in _load(RULES_YAML).get("rules", [])}
    local_ids = set()
    for f in ("components.yaml", "patterns.yaml", "templates.yaml"):
        for e in _load(REG_DIR / f).get("entries", []):
            local_ids.add(e.get("id"))

    seen = set()
    for e in caps["entries"]:
        cid = e.get("id")
        assert cid, "capability без id"
        assert cid not in seen, "дубль id capability: " + str(cid)
        seen.add(cid)
        refs = e.get("constitution_refs", [])
        assert refs, cid + ": нет constitution_refs"
        for r in refs:
            assert r in rule_ids, cid + " -> " + r + " нет в rules.yaml"
        for loc in e.get("backed_by", []):
            assert loc in local_ids, cid + " backed_by " + loc + " нет в реестрах"
