"""Unit tests for tools/ai_ops_cli.py — превью и разрешение флагов (preview/dispatch core).

Здесь живёт машинерия предпросмотра: реестр INTENTS, resolve_flags, build_preview,
классификация задачи, требование человеческого одобрения и видимость деградации контекста.
Прямые действия команд (main/onboard/run/resume) вынесены в `test_ai_ops_cli_main.py`,
владельческие read-only команды (explain/inbox) — в `test_ai_ops_cli_owner_queue.py`.
Разрез #819: файл упирался в потолок анти-монолит-гейта (837/850).
"""
from __future__ import annotations

import subprocess

import pytest

from ai_ops_kit.cli import ai_ops_cli


# ОБЪЯВЛЕННАЯ ПОВЕРХНОСТЬ ИНТЕНТОВ — ОДИН ИСТОЧНИК (сведено 19.08.2026).
#
# Прежде один и тот же список жил в ТРЁХ местах: число 16 в `test_intents_count`, набор имён в
# `test_intents_contain_expected` и копия обоих в `tests/unit/test_ai_ops_cli_selftest.py`.
# Поэтому добавление ОДНОГО интента (`session`, перенесён из установщика в CLI, чтобы работать из
# установленной дочки) покрасило ТРИ теста, и ни один из них не сказал ничего нового: они
# проверяли одно утверждение трижды, а стоили тройного сопровождения.
#
# Здесь список один, а число выводится из него. Контракт не ослаб: набор по-прежнему пинится
# поимённо, и новый интент по-прежнему обязан быть объявлен ЗДЕСЬ, а не появиться молча.
# Когда лента B соберёт `docs/api/public-surface.md`, источником станет он, а этот список —
# его проверкой.
EXPECTED_INTENTS = {
    "new", "onboard", "discuss", "specify", "plan", "run",
    "do", "advise", "resume", "review", "status", "health",
    # v3.35 Product Operating Model: план продукта и понимание репозитория.
    "next", "model",
    # #539: владельческая карточка одной задачи — «что с моей задачей прямо сейчас» (read-only).
    "explain",
    # #540: единая владельческая очередь «что ждёт моего решения» — решения/остановки/подтверждения/
    # обзор/предупреждения о выпуске одним списком (read-only).
    "inbox",
    # #545 (outcome-loop): `readout` — ЕДИНЫЙ пост-релизный путь одним вызовом: PRR ->
    # verify_analytics_runtime -> outcome-проекция -> один вердикт (read-only). Проводит в контур
    # event_arrival.verify_analytics_runtime и validate_post_release_readout/validate_product_objects.
    "readout",
    # v3.35.2 (тир 4): BOOTSTRAP был строкой в реестре — стал командой.
    "bootstrap",
    # 2026-08-17: канал наблюдений о ките из дочки — данные, а не пересказ.
    "feedback",
    # 2026-08-19 (session-command-reaches-the-child): `session` переехал из установщика в CLI —
    # установщик в поставку не едет, поэтому из дочки команда была недостижима.
    "session",
    # 2026-08-19 (аудит): `doctor` силами самой дочки. Полная проверка живёт в установщике, а он
    # в поставку не едет — в дочке без клона кита команда отвечала «исходник рядом не найден».
    "doctor",
    # 2026-08-20 (лента 4, Фаза 3): roadmap Now/Next/Later и delivery-план из backlog. Подключены
    # командами CLI, модули убраны из UNWIRED_MODULES.
    "roadmap", "delivery",
    # 2026-08-20 (лента 3, Фаза 2): Backlog Intelligence — `backlog classify|dedup|prioritize|graph`
    # над GitHub Issues дочки. Был только модулями (`python3 -m ...`), стал командой движка.
    "backlog",
    # 2026-08-24 (Product Contract, срез 1): единый объект продукта поверх подсистем. `contract`
    # агрегирует идентичность/стандарт/артефакты/контуры/здоровье и даёт один вердикт. Делает
    # product_contract достижимым (иначе модуль ехал бы мёртвым грузом — capability-reachability).
    "contract",
    # 2026-08-24 (Product Contract, срез 2): флит-вид. `products` даёт сводный вердикт по ВСЕМ
    # продуктам реестра флота — «увидеть состояние всех продуктов разом». Делает product_registry
    # достижимым.
    "products",
    # 2026-08-25 (Фаза 4, закрытие острова): `team` — статус команды (health×3+риски+блокеры+задачи);
    # `governance` — политика/журнал решений AI/переопределения (только чтение). Делают достижимыми
    # team_sync и governance-тройку (последний кусок «мёртвого острова» аудита).
    "team",
    "governance",
    # 2026-08-25 (Product Contract): `inspect <id>` — карточка одного продукта флота по id без cd в
    # его репозиторий.
    "inspect",
    # 2026-08-31 (Фаза 5, капстоун): `replan` — автономное перепланирование. Цикл сам сводит
    # приоритеты плана к реальности (--apply — записать), структурные изменения — предложением.
    # Делает достижимым intelligence/replan_loop.
    "replan",
    # #549: `work show <id>` — единая машинная ПРОЕКЦИЯ работы по id (read-only): сводит четыре
    # источника (заявка/реестр идущих работ/граф пакетов/план) в одну карточку. Делает достижимым
    # lifecycle/work_view.
    "work",
    # knowledge-graph-query: `graph build|trace <feature>|gaps` — Knowledge Graph как ЗАПРАШИВАЕМАЯ
    # технология поверх registry/entities.yaml + validate_knowledge_graph. Собирает один граф из
    # plan.yaml + FL-*.yaml + feature blueprints. Делает достижимым intelligence/knowledge_graph.
    "graph",
    # voluntary-child-registration: `reach register|decline|forget|status|summary|coverage` —
    # добровольная отметка о подключении и охват БЕЗ телеметрии. Делает достижимым
    # engops/child_registry (opt-in, рукой владельца, без сети).
    "reach",
}


@pytest.mark.critical_path
@pytest.mark.unit


class TestIntentsRegistry:
    """Tests for INTENTS — the intent registry."""

    def test_intents_count(self):
        """Число интентов совпадает с объявленным набором — считается, а не вписывается рукой."""
        assert len(ai_ops_cli.INTENTS) == len(EXPECTED_INTENTS)

    def test_intents_contain_expected(self):
        """INTENTS should contain all expected intent names."""
        assert set(ai_ops_cli.INTENTS.keys()) == EXPECTED_INTENTS

    def test_each_intent_has_required_fields(self):
        """Each intent should have (description, action, needs_task_text)."""
        for name, entry in ai_ops_cli.INTENTS.items():
            assert len(entry) == 3, f"Intent {name} should have 3 fields"
            desc, action, needs_task = entry
            assert isinstance(desc, str)
            assert isinstance(action, str)
            assert isinstance(needs_task, bool)


@pytest.mark.critical_path
@pytest.mark.unit
class TestResolveFlags:
    """Tests for resolve_flags — preset flag resolution from signals."""

    def test_quick_flags(self):
        """QUICK task should have sandbox + baseline_diff ON, review + author OFF."""
        signals = {"task_type": "QUICK"}
        flags = ai_ops_cli.resolve_flags(signals)
        assert flags["sandbox"] is True
        assert flags["baseline_diff"] is True
        assert flags["review"] is False
        assert flags["author"] is False

    def test_engineering_flags(self):
        """ENGINEERING task should have review + author ON."""
        signals = {"task_type": "ENGINEERING"}
        flags = ai_ops_cli.resolve_flags(signals)
        assert flags["review"] is True
        assert flags["author"] is True

    def test_engine_is_always_pipeline(self):
        """engine should always be 'pipeline'."""
        signals = {"task_type": "QUICK"}
        flags = ai_ops_cli.resolve_flags(signals)
        assert flags["engine"] == "pipeline"


@pytest.mark.critical_path
@pytest.mark.unit
class TestBuildPreview:
    """Tests for build_preview — execution preview generation."""

    def test_preview_kind(self, child_root):
        """build_preview should return kind=ExecutionPreview."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        (child_root / "package.json").write_text('{"name": "test"}')

        preview = ai_ops_cli.build_preview(
            intent="plan",
            task="implement feature X",
            child_root=child_root,
            signals={"task_type": "ENGINEERING"},
        )
        assert preview["kind"] == "ExecutionPreview"
        assert preview["schema_version"] == 1

    def test_preview_contains_understood(self, child_root):
        """Preview should contain 'understood' section with task type."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)

        preview = ai_ops_cli.build_preview(
            intent="plan",
            task="fix a bug",
            child_root=child_root,
            signals={"task_type": "QUICK"},
        )
        assert "understood" in preview
        assert preview["understood"]["task_type"] == "QUICK"

    def test_preview_contains_will_do(self, child_root):
        """Preview should contain 'will_do' section with stages."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)

        preview = ai_ops_cli.build_preview(
            intent="run",
            task="test task",
            child_root=child_root,
            signals={"task_type": "QUICK"},
        )
        assert "will_do" in preview
        assert "stages" in preview["will_do"]

    def test_preview_contains_approvals(self, child_root):
        """Preview should contain 'approvals_needed' list."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)

        preview = ai_ops_cli.build_preview(
            intent="run",
            task="test task",
            child_root=child_root,
            signals={"task_type": "QUICK"},
        )
        assert "approvals_needed" in preview
        assert isinstance(preview["approvals_needed"], list)


@pytest.mark.critical_path
@pytest.mark.unit
class TestCriticalApproval:
    """Tests for CRITICAL task — requires human approval."""

    def test_critical_task_needs_approval(self, child_root):
        """CRITICAL task should produce human-approval requirement."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)

        preview = ai_ops_cli.build_preview(
            intent="run",
            task="critical change",
            child_root=child_root,
            signals={"task_type": "CRITICAL"},
        )
        assert len(preview["approvals_needed"]) > 0

    def test_critical_approval_names_human(self, child_root):
        """CRITICAL: хотя бы одно требование одобрения адресовано ЧЕЛОВЕКУ (не абстрактный список)."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        preview = ai_ops_cli.build_preview(
            intent="run",
            task="миграция схемы",
            child_root=child_root,
            signals={"task_type": "CRITICAL", "risk": "critical", "affected_areas": ["db"]},
        )
        assert any("человек" in a for a in preview["approvals_needed"])


@pytest.mark.critical_path
@pytest.mark.unit
class TestPreviewClassificationAndData:
    """Перенос из монолита: понятый workflow, измеренные данные, названный результат, согласие с роутером."""

    def test_preview_understood_workflow_engineering(self, child_root):
        """ENGINEERING-сигналы -> preview.understood.workflow == 'ENGINEERING'."""
        (child_root / "package.json").write_text('{"dependencies":{"react":"^18"}}', encoding="utf-8")
        pv = ai_ops_cli.build_preview(
            "run", "добавить фильтр", child_root,
            {"task_type": "ENGINEERING", "risk": "medium", "affected_areas": ["core"]})
        assert pv["understood"]["workflow"] == "ENGINEERING"

    def test_preview_data_used_agents_and_tokens_measured(self, child_root):
        """data_used.agents — список, estimated_tokens измерены (не None) при собранном контексте."""
        (child_root / "package.json").write_text('{"dependencies":{"react":"^18"}}', encoding="utf-8")
        pv = ai_ops_cli.build_preview(
            "run", "добавить фильтр", child_root,
            {"task_type": "ENGINEERING", "risk": "medium", "affected_areas": ["core"]})
        assert isinstance(pv["data_used"]["agents"], list)
        assert pv["data_used"]["estimated_tokens"] is not None

    def test_preview_expected_result_named(self, child_root):
        """Ожидаемый результат назван (truthy)."""
        (child_root / "package.json").write_text('{"dependencies":{"react":"^18"}}', encoding="utf-8")
        pv = ai_ops_cli.build_preview(
            "run", "добавить фильтр", child_root,
            {"task_type": "ENGINEERING", "risk": "medium", "affected_areas": ["core"]})
        assert bool(pv["expected_result"])

    def test_preview_without_task_type_agrees_with_router(self, child_root):
        """v2.107: без task_type preset согласован с роутером (QUICK ИЛИ review&&author включены)."""
        (child_root / "package.json").write_text('{"dependencies":{"react":"^18"}}', encoding="utf-8")
        pv = ai_ops_cli.build_preview(
            "run", "поправить логику расчёта", child_root,
            {"affected_areas": ["core"], "risk": "medium"})  # без task_type
        wf = pv["understood"]["workflow"]
        af = pv["will_do"]["auto_flags"]
        assert wf == "QUICK" or (af["review"] and af["author"])


@pytest.mark.critical_path
@pytest.mark.unit
class TestDecompositionAdvice:
    """Tests for decomposition_advised — large task detection."""

    def test_large_task_decomposition_advised(self, child_root):
        """Large task with many affected areas should get decomposition_advised=True."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)

        preview = ai_ops_cli.build_preview(
            intent="run",
            task="large refactoring across many modules",
            child_root=child_root,
            signals={
                "task_type": "ENGINEERING",
                "size": "large",
                "affected_areas": ["auth", "api", "ui", "database", "tests", "docs"],
            },
        )
        assert preview["decomposition_advised"] is True


@pytest.mark.unit
class TestDegradedContextIsVisible:
    """Проглоченное исключение не должно выглядеть нормальным результатом.

    Внешнее ревью назвало этот случай поимённо среди 137 `except Exception`: сбой
    compile_bundle уходил в `bundle = None`, и превью печатало «агентов 0 · ~None ток.» — прогон
    с несобранным контекстом ничем не отличался от обычного.
    """

    def _broken_bundle(self, monkeypatch):
        from ai_ops_kit.context import context_compiler

        def _boom(*a, **kw):
            raise RuntimeError("реестр недоступен")

        monkeypatch.setattr(context_compiler, "compile_bundle", _boom)

    def test_preview_reports_context_failure(self, tmp_path, monkeypatch):
        self._broken_bundle(monkeypatch)
        pv = ai_ops_cli.build_preview("run", "задача", tmp_path, {"task_type": "QUICK"})
        assert "RuntimeError" in (pv["data_used"]["context_error"] or ""), \
            "сбой сборки контекста не виден машиночитаемому потребителю превью"

    def test_printed_preview_warns_loudly(self, tmp_path, monkeypatch, capsys):
        self._broken_bundle(monkeypatch)
        pv = ai_ops_cli.build_preview("run", "задача", tmp_path, {"task_type": "QUICK"})
        ai_ops_cli._print_preview(pv)
        out = capsys.readouterr().out
        assert "КОНТЕКСТ НЕ СОБРАН" in out
        assert "агентов 0" not in out, "деградация всё ещё показана как нормальные данные"

    def test_healthy_preview_has_no_error_and_prints_numbers(self, tmp_path, capsys):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='d'\n", encoding="utf-8")
        pv = ai_ops_cli.build_preview("run", "задача", tmp_path, {"task_type": "QUICK"})
        assert pv["data_used"]["context_error"] is None
        ai_ops_cli._print_preview(pv)
        out = capsys.readouterr().out
        assert "данные: агентов" in out and "КОНТЕКСТ НЕ СОБРАН" not in out
