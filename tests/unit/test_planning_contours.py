"""Связность контуров: `unknown` != `not_changed` (v3.35 Product Operating Model).

Главный инвариант среза и главный способ его подделать — свернуть «не умею видеть» в «не менялось».
Три теста на capability:
  * positive     — diff по сигнальному пути даёт `changed`; сигналы есть и не тронуты -> `not_changed`;
  * fail-closed  — контура без сигнальных путей -> `unknown`, и порча модели -> исключение;
  * side-effect  — заявленный `changed` без обновления источника истины даёт находку.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.planning import contours as C

MODEL = C.load_model()


def _repo(tmp_path):
    """Репозиторий, где сигнальные пути ЧАСТИ контуров существуют, а части — нет."""
    (tmp_path / "context" / "system").mkdir(parents=True)
    (tmp_path / "context" / "system" / "DataMap.md").write_text("# данные\n", encoding="utf-8")
    (tmp_path / "src" / "api").mkdir(parents=True)
    (tmp_path / "src" / "api" / "app.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


# ── positive ──────────────────────────────────────────────────────────────────────────────────

def test_signal_path_in_diff_is_changed(tmp_path):
    r = _repo(tmp_path)
    der = C.derive_affects(r, ["context/system/DataMap.md"], MODEL, overrides={})
    assert der["data_contracts"]["state"] == C.CHANGED
    assert der["data_contracts"]["matched"] == ["context/system/DataMap.md"]


def test_signals_present_but_untouched_is_not_changed(tmp_path):
    r = _repo(tmp_path)
    der = C.derive_affects(r, ["README.md"], MODEL, overrides={})
    assert der["data_contracts"]["state"] == C.NOT_CHANGED


def test_deep_glob_matches_nested_path(tmp_path):
    """`**/models/**` обязан ловить `src/api/models/user.py` — иначе модель данных «не менялась»."""
    r = _repo(tmp_path)
    der = C.derive_affects(r, ["src/api/models/user.py"], MODEL, overrides={})
    assert der["data_contracts"]["state"] == C.CHANGED


def test_exact_signal_beats_another_contours_glob(tmp_path):
    """Найдено при живой проверке гейта: `context/system/DataMap.md` — ЯВНЫЙ источник истины и
    явный сигнал контура данных, но он же попадает под glob `context/system/**` контура
    архитектуры. Правильное обновление модели данных давало ложную находку `undeclared_change` по
    архитектуре — а гейт, выдающий шум, перестают читать, и он становится хуже отсутствующего.

    Правило специфичности: точный путь сильнее чужого glob. Glob другого контура на этом файле не
    срабатывает; на СВОИХ путях (`docker-compose.yml`) архитектура срабатывает как раньше."""
    (tmp_path / "context" / "system").mkdir(parents=True)
    (tmp_path / "context" / "system" / "DataMap.md").write_text("# д", encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    der = C.derive_affects(tmp_path, ["context/system/DataMap.md"], MODEL, overrides={})
    assert der["data_contracts"]["state"] == C.CHANGED          # свой явный путь
    assert der["system_architecture"]["state"] != C.CHANGED     # чужой glob не срабатывает
    der2 = C.derive_affects(tmp_path, ["docker-compose.yml"], MODEL, overrides={})
    assert der2["system_architecture"]["state"] == C.CHANGED    # свой путь — срабатывает


def test_repo_override_teaches_kit_its_paths(tmp_path):
    """Доопределение в `.ai-ops.yaml` превращает `unknown` в проверяемое состояние."""
    r = _repo(tmp_path)
    before = C.derive_affects(r, ["src/telemetry/events.py"], MODEL, overrides={})
    assert before["analytics_learning"]["state"] == C.UNKNOWN
    after = C.derive_affects(r, ["src/telemetry/events.py"], MODEL,
                             overrides={"analytics_learning": ["src/telemetry/**"]})
    assert after["analytics_learning"]["state"] == C.CHANGED


# ── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_no_signal_paths_is_unknown_not_not_changed(tmp_path):
    """ГЛАВНЫЙ инвариант: «не умею видеть» никогда не выглядит как «не менялось»."""
    r = _repo(tmp_path)
    der = C.derive_affects(r, ["src/api/app.py"], MODEL, overrides={})
    an = der["analytics_learning"]
    assert an["state"] == C.UNKNOWN
    assert an["state"] != C.NOT_CHANGED
    assert "не найден" in an["reason"] or "нет сигнальных" in an["reason"]


def test_dot_paths_match_their_own_signals(tmp_path):
    """Находка ревью: `lstrip("./")` резал НАБОР символов, а не префикс, и `.ai-ops.yaml` терял
    ведущую точку. Следствие было тяжёлым: изменение исполняемой части контракта (protected_paths,
    approvals) и CI-конвейера проходило гейт связности как согласованное, потому что ни один
    dot-путь не совпадал со своим же сигнальным паттерном."""
    assert C._matches(".ai-ops.yaml", ".ai-ops.yaml")
    assert C._matches(".github/workflows/ci.yml", ".github/workflows/**")
    assert C._matches("./src/api/app.py", "src/api/**")     # префикс ./ обязан сниматься как префикс


def test_unanchored_pattern_does_not_make_every_repo_signalled(tmp_path):
    """Находка ревью: `rglob("**")` возвращает САМ корень, поэтому `_repo_has_signal` был истинен
    всегда, и `unknown` сворачивался в `not_changed` — главный инвариант среза нарушался в любом
    репозитории, где у контура есть паттерн вида `**/migrations/**`."""
    assert not C._repo_has_signal(tmp_path, ["**/migrations/**"])
    assert not C._repo_has_signal(tmp_path, ["**/models/**", "**/entities/**"])
    (tmp_path / "app" / "migrations").mkdir(parents=True)
    assert C._repo_has_signal(tmp_path, ["**/migrations/**"])   # а когда путь ЕСТЬ — истина


def test_repo_without_data_signals_is_unknown(tmp_path):
    """Тот же дефект через публичный вход: контур data_contracts в репозитории без схем, моделей и
    миграций обязан быть `unknown`, а не «не менялось»."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.js").write_text("var a = 1\n", encoding="utf-8")
    der = C.derive_affects(tmp_path, ["src/app.js"], MODEL, overrides={})
    assert der["data_contracts"]["state"] == C.UNKNOWN


def test_writing_a_test_does_not_change_the_engineering_contour(tmp_path):
    """ОБКАТКА НА ЖИВОМ РЕПОЗИТОРИИ (ii-sreda, 44 продуктовых коммита): паттерн `**/*.test.*` дал
    28 находок из 41 — больше половины всего шума гейта из одного сигнала.

    Дефект модели, а не гейта. Источник истины контура Engineering/Quality/Security — ПРАВИЛА
    (DevelopmentProcess.md, .ai-ops.yaml), а не тесты. Написание теста — нормальная работа, оно не
    меняет тестовую стратегию и не обязано её переписывать. Требовать обновления правил на каждый
    тест — та самая бюрократия «восемь документов на задачу», которую модель запрещает прямо.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.test.ts").write_text("test('x', () => {})\n", encoding="utf-8")
    (tmp_path / "context" / "team").mkdir(parents=True)
    (tmp_path / "context" / "team" / "DevelopmentProcess.md").write_text("# правила", encoding="utf-8")
    der = C.derive_affects(tmp_path, ["src/auth.test.ts"], MODEL, overrides={})
    assert der["engineering_quality_security"]["state"] != C.CHANGED

    # А изменение самих ПРАВИЛ контур меняет — сигнал остался там, где ему место.
    der2 = C.derive_affects(tmp_path, ["context/team/DevelopmentProcess.md"], MODEL, overrides={})
    assert der2["engineering_quality_security"]["state"] == C.CHANGED


def test_repo_declares_where_its_truth_lives(tmp_path):
    """ОБКАТКА: ii-sreda держит ADR в `docs/architecture/decisions/`, а не в `decisions/registry.yaml`.
    Сигнал `**/ADR-*.md` контур ловил верно, но объявленного китом источника истины в репозитории нет
    — и `declared_not_updated` срабатывал ВЕЧНО на контуре, который поддерживается как надо (12
    находок из 41).

    Дыра была в дизайне: репозиторий мог доопределить `change_signals`, но НЕ `source_of_truth`.
    Кит знает типовые места, но где лежит правда ЭТОГО продукта, знает только владелец.
    """
    d = tmp_path / "docs" / "architecture" / "decisions"
    d.mkdir(parents=True)
    (d / "ADR-069-TYPECHECK.md").write_text("# решение", encoding="utf-8")
    (tmp_path / ".ai-ops.yaml").write_text(
        "product_operating_model:\n"
        "  contours:\n"
        "    research_decisions:\n"
        "      source_of_truth: [docs/architecture/decisions/]\n", encoding="utf-8")
    files = ["docs/architecture/decisions/ADR-069-TYPECHECK.md"]
    rep = C.reconcile(tmp_path, {"research_decisions": True}, files, MODEL)
    assert not [f for f in rep["findings"]
                if f["id"] == "declared_not_updated" and f["contour"] == "research_decisions"], \
        "обновление ADR в объявленном репозиторием месте не должно считаться необновлением истины"
    # Пробел контура тоже закрыт объявлением репозитория.
    st = C.sot_state(tmp_path, MODEL)
    assert st["research_decisions"]["ok"], "объявленный репозиторием источник истины не учтён"


def test_corrupt_model_raises(tmp_path):
    bad = tmp_path / "pom.yaml"
    bad.write_text("contours: []\n", encoding="utf-8")
    with pytest.raises(C.ModelCorrupt):
        C.load_model(bad)


def test_missing_model_raises(tmp_path):
    with pytest.raises(C.ModelCorrupt):
        C.load_model(tmp_path / "нет-такого.yaml")


def test_broken_repo_config_does_not_crash_overrides(tmp_path):
    """Битый `.ai-ops.yaml` — забота doctor'а: детект не обязан падать, но и врать не должен."""
    (tmp_path / ".ai-ops.yaml").write_text("communication: [\n bad", encoding="utf-8")
    assert C.repo_overrides(tmp_path) == {}


# ── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_declared_changed_without_sot_update_is_finding(tmp_path):
    """Ровно тот случай, ради которого модель существует: обновлён компонент, модель данных нет."""
    r = _repo(tmp_path)
    rep = C.reconcile(r, {"data_contracts": True}, ["src/ui/Dashboard.tsx"], MODEL, overrides={})
    ids = [f["id"] for f in rep["findings"]]
    assert "declared_not_updated" in ids
    assert rep["verdict"] == "inconsistent"


def test_undeclared_change_is_finding(tmp_path):
    r = _repo(tmp_path)
    rep = C.reconcile(r, {}, ["context/system/DataMap.md"], MODEL, overrides={})
    ids = [f["id"] for f in rep["findings"]]
    assert "undeclared_change" in ids


def test_sot_update_closes_declared_change(tmp_path):
    r = _repo(tmp_path)
    rep = C.reconcile(r, {"data_contracts": True}, ["context/system/DataMap.md"], MODEL,
                      overrides={})
    assert not [f for f in rep["findings"]
                if f["id"] == "declared_not_updated" and f["contour"] == "data_contracts"]


def test_no_diff_is_not_comparable_rather_than_ok(tmp_path):
    """Пустой diff не является доказательством согласованности — об этом сказано прямо."""
    r = _repo(tmp_path)
    rep = C.reconcile(r, {"data_contracts": True}, [], MODEL, overrides={})
    assert rep["comparable"] is False


def test_unknown_findings_are_info_not_major(tmp_path):
    """`unknown` — признание, а не провал: оно не обязано ронять вердикт."""
    r = _repo(tmp_path)
    rep = C.reconcile(r, {}, ["src/api/app.py"], MODEL, overrides={})
    unknown = [f for f in rep["findings"] if f["id"] == "unknown_contour"]
    assert unknown
    assert all(f["severity"] == "info" for f in unknown)


def test_sot_state_reports_required_gaps(tmp_path):
    r = _repo(tmp_path)
    st = C.sot_state(r, MODEL)
    assert st["data_contracts"]["ok"] is True          # DataMap.md на месте
    assert st["product_strategy"]["ok"] is False       # ProductOverview/Status/ROADMAP нет
    assert "ROADMAP.md" in st["product_strategy"]["required_missing"]
