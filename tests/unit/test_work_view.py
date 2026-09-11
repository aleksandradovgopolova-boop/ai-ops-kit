"""Поведенческие тесты для lifecycle/work_view.project_work (issue #549).

Проверяем ЧЕТЫРЕ обязательства проекции:
  1. сводит четыре источника (заявка/реестр идущих работ/граф пакетов/план) в один dict по id;
  2. отсутствие источника -> связанные поля пустые/None И источник НЕ попадает в `sources`;
  3. проекция READ-ONLY: ни один файл не создаётся и не меняется;
  4. presenter.from_work_view говорит продуктовым языком (без сырого id сессии/областей записи).
"""
from __future__ import annotations

import yaml
import pytest

from ai_ops_kit.lifecycle import work_view
from ai_ops_kit.ui import presenter


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _four_source_repo(root, wid="arch-01"):
    """Собрать дочку со ВСЕМИ четырьмя источниками для одной работы."""
    # 1. заявка (workitem)
    _write(root / "features" / wid / "workitem.yaml", {
        "schema_version": 1, "kind": "workitem", "id": wid, "task": "спроектировать ядро",
        "workflow": "engineering", "status": "in_progress", "lifecycle_intent": "implementation",
        "human_approval_required": False,
        "paths": {"blueprint": f"features/{wid}/blueprint.yaml",
                  "run_state": f".ai/runtime/workitems/{wid}/TaskState.yaml",
                  "workitem": f"features/{wid}/workitem.yaml"}})
    # blueprint реально существует (для artifacts)
    (root / "features" / wid / "blueprint.yaml").write_text("kind: blueprint\n", encoding="utf-8")
    # 2. реестр идущих работ (active-work)
    _write(root / ".ai" / "runtime" / "active-work.yaml", {
        "schema_version": 1, "kind": "active-work",
        "active": [{"id": wid, "branch": "feat/arch-01", "status": "in-progress",
                    "affected_areas": ["context/system/"], "depends_on": ["arch-00"],
                    "shared_contracts": ["OrderContract"],
                    "owner_session": "sess-abc-123", "started_at": "2026-09-07T10:00:00Z"}]})
    # 3. граф пакетов (work-graph)
    _write(root / "work-graph.yaml", {
        "schema_version": 1, "kind": "WorkGraph", "id": "WG-001", "feature": wid,
        "execution_mode": "single",
        "packages": [{"id": wid, "depends_on": ["dep-pkg"],
                      "write_scope": ["src/core/**"], "shared_contracts": ["CoreContract"]}],
        "integration_order": [wid], "aggregate_verification": ["tests_passed"]})
    # 4. план продукта (plan)
    _write(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan",
        "work": [{"id": wid, "title": "Спроектировать ядро", "type": "architecture",
                  "goal": "goal-1", "status": "in_progress", "owner_role": "architect",
                  "value": "high", "write_scope": ["context/system/"]}]})
    return wid


@pytest.mark.unit
class TestProjectWorkMergesFourSources:
    def test_all_four_sources_merge_into_one_object(self, tmp_path):
        """Четыре источника сводятся в один dict по id; поля берутся из соответствующих источников."""
        wid = _four_source_repo(tmp_path)
        view = work_view.project_work(wid, tmp_path)
        assert set(view["sources"]) == {"workitem", "active_work", "work_graph", "plan"}
        assert view["id"] == wid
        assert view["title"] == "Спроектировать ядро"                 # из плана
        assert view["status"] == "in_progress"                        # факт заявки
        assert view["lifecycle_intent"] == "implementation"           # из заявки
        assert view["branch"] == "feat/arch-01"                       # из реестра идущих работ
        assert view["current_agent"] == "sess-abc-123"                # owner_session — единств. источник

    def test_scope_fields_are_union_across_sources(self, tmp_path):
        """write_scope/depends_on/shared_contracts — union графа + реестра + плана (без дублей)."""
        wid = _four_source_repo(tmp_path)
        view = work_view.project_work(wid, tmp_path)
        # write_scope: граф (src/core/**) + affected_areas реестра/плана (context/system/)
        assert "src/core/**" in view["write_scope"]
        assert "context/system/" in view["write_scope"]
        # depends_on: граф (dep-pkg) + реестр (arch-00)
        assert set(view["depends_on"]) == {"dep-pkg", "arch-00"}
        # shared_contracts: граф (CoreContract) + реестр (OrderContract)
        assert set(view["shared_contracts"]) == {"CoreContract", "OrderContract"}

    def test_participants_from_owner_session_and_owner_role(self, tmp_path):
        """participants собирается из уже записанного: owner_session (реестр) + owner_role (план)."""
        wid = _four_source_repo(tmp_path)
        view = work_view.project_work(wid, tmp_path)
        assert set(view["participants"]) == {"sess-abc-123", "architect"}

    def test_artifacts_only_existing_paths(self, tmp_path):
        """В artifacts попадают только реально существующие пути + ветка; обещанный путь — нет."""
        wid = _four_source_repo(tmp_path)
        view = work_view.project_work(wid, tmp_path)
        kinds = {a.get("kind") for a in view["artifacts"]}
        # blueprint и workitem существуют, run_state (TaskState.yaml) НЕ создан -> его нет
        assert "blueprint" in kinds and "workitem" in kinds
        assert "run_state" not in kinds
        assert "branch" in kinds


@pytest.mark.unit
class TestMissingSourceIsHonest:
    def test_missing_source_absent_from_sources_and_fields_empty(self, tmp_path):
        """Есть только план: остальные три источника отсутствуют -> их нет в sources, поля пустые."""
        wid = "solo-01"
        _write(tmp_path / "planning" / "plan.yaml", {
            "schema_version": 1, "kind": "delivery-plan",
            "work": [{"id": wid, "title": "Одинокая работа", "status": "todo",
                      "owner_role": "architect", "write_scope": ["src/x/"]}]})
        view = work_view.project_work(wid, tmp_path)
        assert view["sources"] == ["plan"]                            # только план найден
        assert "active_work" not in view["sources"]
        assert "work_graph" not in view["sources"]
        assert "workitem" not in view["sources"]
        assert view["current_agent"] is None                         # owner_session нет -> None
        assert view["shared_contracts"] == []                        # источников нет
        assert view["depends_on"] == []
        assert view["lifecycle_intent"] is None
        # write_scope всё же есть — план его несёт
        assert view["write_scope"] == ["src/x/"]

    def test_unknown_id_yields_no_sources(self, tmp_path):
        """Работа, которой нет ни в одном источнике: sources пуст (не выдуманная карточка)."""
        view = work_view.project_work("ghost", tmp_path)
        assert view["sources"] == []
        assert view["participants"] == [] and view["artifacts"] == []
        assert view["current_agent"] is None

    def test_template_plan_is_not_read_as_work(self, tmp_path):
        """Заготовка плана (template: true) НЕ считается планом — иначе пример выдаётся за работу."""
        _write(tmp_path / "planning" / "plan.yaml", {
            "schema_version": 1, "kind": "delivery-plan", "template": True,
            "work": [{"id": "arch-01", "title": "пример"}]})
        view = work_view.project_work("arch-01", tmp_path)
        assert "plan" not in view["sources"]


@pytest.mark.unit
class TestReadOnly:
    def test_projection_writes_nothing(self, tmp_path):
        """READ-ONLY: проекция не создаёт и не меняет ни одного файла (снимок дерева до/после)."""
        wid = _four_source_repo(tmp_path)

        def snapshot():
            return {p: p.stat().st_mtime_ns for p in sorted(tmp_path.rglob("*")) if p.is_file()}

        before = snapshot()
        work_view.project_work(wid, tmp_path)
        after = snapshot()
        assert before == after                                       # ни новых файлов, ни изменений

    def test_reading_absent_repo_creates_no_dirs(self, tmp_path):
        """Чтение по несуществующей работе не создаёт каталогов (.ai/runtime и т.п.)."""
        work_view.project_work("nope", tmp_path)
        assert list(tmp_path.iterdir()) == []


@pytest.mark.unit
class TestDecisionsLinked:
    def test_related_decisions_are_picked_by_id_mention(self, tmp_path):
        """Связанные решения — эпизоды реестра, упоминающие id работы; несвязанные не берутся."""
        wid = _four_source_repo(tmp_path)
        _write(tmp_path / "decisions" / "registry.yaml", {
            "schema_version": 1, "kind": "decisions-registry",
            "episodes": [
                {"id": "ep-1", "actor": "ai", "question": f"как делать {wid}",
                 "decision": "так", "reason": "r", "reversibility": "two-way",
                 "date": "2026-09-07", "data": "d"},
                {"id": "ep-2", "actor": "human", "question": "несвязанное",
                 "decision": "иное", "reason": "r", "reversibility": "two-way",
                 "date": "2026-09-07"}]})
        view = work_view.project_work(wid, tmp_path)
        ids = {d["id"] for d in view["decisions"]}
        assert "ep-1" in ids and "ep-2" not in ids


@pytest.mark.unit
class TestPresenterSpeaksProduct:
    def test_product_card_hides_raw_session_and_scope(self, tmp_path):
        """Продуктовая карточка не выводит сырой id сессии/области записи — они в техдеталях."""
        wid = _four_source_repo(tmp_path)
        view = work_view.project_work(wid, tmp_path)
        out = presenter.render(presenter.from_work_view(view), audience="product")
        assert "sess-abc-123" not in out                             # id сессии — жаргон, скрыт
        assert "src/core/**" not in out                              # область записи — жаргон, скрыт
        assert "Спроектировать ядро" in out                          # заголовок работы виден
        # тот же факт доступен технической аудитории
        tech = presenter.render(presenter.from_work_view(view), audience="technical")
        assert "sess-abc-123" in tech

    def test_unknown_work_is_degraded_not_empty(self, tmp_path):
        """Ненайденная работа -> честное degraded «такой работы не вижу», а не пустая карточка."""
        msg = presenter.from_work_view(work_view.project_work("ghost", tmp_path))
        assert msg["status"] == "degraded"
        out = presenter.render(msg, audience="product")
        assert "не вижу" in out.lower()
