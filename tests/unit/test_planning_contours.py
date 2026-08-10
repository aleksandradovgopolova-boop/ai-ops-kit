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


def test_signal_search_ignores_kit_internals_and_vendor_dirs(tmp_path):
    """ОБКАТКА НА ВТОРОМ РЕПОЗИТОРИИ (wow-repo, стек node/react/astro): гейт не сработал НИ РАЗУ на
    8 коммитах, включая коммит на 54 файла «Build WowRepo MVP engine, design system». Разбор дал
    дефект хуже шума: контур system_architecture заявлял `not_changed`, потому что поиск сигнала
    находил Dockerfile внутри `.ai/runtime/backups/3.27.6/.ai/managed/containers/` — бэкапа
    СОБСТВЕННОГО managed-слоя кита.

    Это подмена признания утверждением в обратную сторону: честный ответ был `unknown` («не умею
    видеть этот контур здесь»), а кит говорил «сигнальные пути есть и не затронуты». Тот же класс,
    что доказательства, указывавшие внутрь `.claude/worktrees/*` — кит принимал свои внутренности за
    факт о продукте.
    """
    # Только внутренности кита и вендор — сигнальных путей ПРОДУКТА нет.
    for rel in (".ai/runtime/backups/3.27.6/.ai/managed/containers/Dockerfile",
                "node_modules/some-pkg/Dockerfile",
                "dist/Dockerfile",
                ".ai/managed/schemas/x.json"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    der = C.derive_affects(tmp_path, ["src/pages/index.astro"], MODEL, overrides={})
    assert der["system_architecture"]["state"] == C.UNKNOWN, \
        "Dockerfile в бэкапе кита не является сигнальным путём продукта"
    assert der["data_contracts"]["state"] == C.UNKNOWN, \
        "схема внутри .ai/managed не является схемой продукта"

    # А настоящий Dockerfile продукта контур видит.
    (tmp_path / "Dockerfile").write_text("FROM node", encoding="utf-8")
    der2 = C.derive_affects(tmp_path, ["src/pages/index.astro"], MODEL, overrides={})
    assert der2["system_architecture"]["state"] == C.NOT_CHANGED


def test_signal_search_does_not_descend_into_non_product_dirs(tmp_path):
    """ОБКАТКА НА ТРЕТЬЕМ РЕПОЗИТОРИИ (niti, Next.js, 488 коммитов): один вызов гейта тратил
    12 СЕКУНД только на поиск сигнальных путей, а гейт зовут на КАЖДОМ прогоне конвейера.

    Предыдущая правка (исключение внутренностей кита) это УСУГУБИЛА: до неё `rglob` останавливался
    на первом попадании — часто внутри `node_modules` — а после стал обходить дерево ЦЕЛИКОМ, чтобы
    отфильтровать исключённое. Правильно не фильтровать после обхода, а НЕ ЗАХОДИТЬ.

    Проверяется механизм, а не время: время зависит от машины и размера вендора, а «не заходить»
    — свойство, которое либо есть, либо нет.
    """
    for rel in ("node_modules/pkg/deep/models/x.py", "dist/models/y.py",
                ".ai/managed/schemas/z.json", ".git/objects/aa/bb",
                "src/api/models/order.py"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    visited = [str(d) for d in C._product_dirs(tmp_path)]
    for bad in ("node_modules", "dist", ".ai/managed", ".git"):
        assert not any(bad in v for v in visited), f"обход зашёл в {bad}: {visited}"
    assert any("src" in v for v in visited), "обход не дошёл до кода продукта"
    # И результат по существу верен: сигнал есть, потому что есть src/api/models продукта.
    assert C._repo_has_signal(tmp_path, ["**/models/**"]) is True


def test_signal_search_ignores_vendor_only_matches(tmp_path):
    """Совпадение ТОЛЬКО в вендоре сигналом не является: иначе `unknown` снова станет `not_changed`."""
    p = tmp_path / "node_modules" / "pkg" / "models" / "x.py"
    p.parent.mkdir(parents=True)
    p.write_text("x", encoding="utf-8")
    assert C._repo_has_signal(tmp_path, ["**/models/**"]) is False


def test_fsd_entities_layer_is_not_a_data_model(tmp_path):
    """ОБКАТКА (niti, Next.js, 186 продуктовых коммитов): паттерн `**/entities/**` дал 6 находок из
    9 — и все ложные. niti построена по Feature-Sliced Design, где `src/entities/` это СЛОЙ
    ИНТЕРФЕЙСА (внутри `ui/`, `lib/`, `index.ts`), а не модель данных. Конвенция распространённая,
    поэтому сигнал был ложным не только здесь.

    Однозначные сигналы контура данных остаются: миграции, ORM-модели, openapi/proto/graphql/prisma
    — их имя означает контракт данных, а не слой приложения.
    """
    fsd = tmp_path / "apps" / "web" / "src" / "entities" / "concept" / "ui"
    fsd.mkdir(parents=True)
    (fsd / "ConceptCard.tsx").write_text("export const C = () => null\n", encoding="utf-8")
    der = C.derive_affects(tmp_path, ["apps/web/src/entities/concept/ui/ConceptCard.tsx"],
                           MODEL, overrides={})
    assert der["data_contracts"]["state"] != C.CHANGED, \
        "слой entities из FSD не является моделью данных"

    # А настоящая миграция контур меняет.
    (tmp_path / "supabase" / "migrations").mkdir(parents=True)
    (tmp_path / "supabase" / "migrations" / "0001.sql").write_text("select 1;", encoding="utf-8")
    der2 = C.derive_affects(tmp_path, ["supabase/migrations/0001.sql"], MODEL, overrides={})
    assert der2["data_contracts"]["state"] == C.CHANGED


def test_source_of_truth_declared_as_signal_makes_contour_self_satisfying(tmp_path):
    """ОБКАТКА НА niti: замер дал 0 находок на 186 коммитах — и это был ЛОЖНЫЙ ноль, полученный
    самим замеряющим. Объявив `supabase/migrations/` источником истины контура данных, любое
    изменение схемы стало трогать «свою истину»: контур самоудовлетворяющийся, гейт не срабатывает
    НИКОГДА, и отчёт выглядит как «всё согласовано».

    Истина — ОПИСАНИЕ (openapi, DataMap); схемы и миграции — сигнал. Тест держит разницу: при
    сужении истины до описания находка возвращается.
    """
    (tmp_path / "supabase" / "migrations").mkdir(parents=True)
    (tmp_path / "supabase" / "migrations" / "0006.sql").write_text("alter table;", encoding="utf-8")
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "openapi.yaml").write_text("openapi: 3.0.0", encoding="utf-8")
    files = ["supabase/migrations/0006.sql"]

    # Истина = описание. Схема изменилась, описание нет -> находка ЕСТЬ.
    (tmp_path / ".ai-ops.yaml").write_text(
        "product_operating_model:\n  contours:\n    data_contracts:\n"
        "      source_of_truth: [docs/openapi.yaml]\n", encoding="utf-8")
    rep = C.reconcile(tmp_path, {"data_contracts": True}, files, MODEL)
    assert [f for f in rep["findings"] if f["id"] == "declared_not_updated"], \
        "изменение схемы без обновления описания обязано быть находкой"

    # Истина = сами миграции. Контур самоудовлетворяющийся -> находки НЕТ, и это ложный зелёный.
    (tmp_path / ".ai-ops.yaml").write_text(
        "product_operating_model:\n  contours:\n    data_contracts:\n"
        "      source_of_truth: [docs/openapi.yaml, supabase/migrations/]\n", encoding="utf-8")
    rep2 = C.reconcile(tmp_path, {"data_contracts": True}, files, MODEL)
    assert not [f for f in rep2["findings"] if f["id"] == "declared_not_updated"]


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
