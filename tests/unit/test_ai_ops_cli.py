"""Unit tests for tools/ai_ops_cli.py — CLI entry point and intent dispatch.

Tests resolve_flags, build_preview, INTENTS registry, and the main() CLI
entry point. Complements the selftest wrapper with granular assertions.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

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


@pytest.mark.critical_path
@pytest.mark.unit
@pytest.mark.slow   # тяжёлая обёртка селфтеста: в быстрый профиль не входит
class TestMainCLI:
    """Tests for main() — CLI entry point."""
    # test_main_selftest удалён: тело переехало в tests/unit/test_ai_ops_cli_selftest.py

    def test_main_preview_returns_zero(self, child_root, monkeypatch):
        """main(['preview', 'plan', ...]) should return 0 (preview only)."""
        monkeypatch.chdir(child_root)
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)

        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(child_root)
            rc = ai_ops_cli.main(["preview", "plan", "test task", str(child_root)])
            assert rc == 0
        finally:
            os.chdir(old_cwd)


@pytest.mark.critical_path
@pytest.mark.unit
class TestOnboardIntent:
    """Tests for onboard intent — repository profile detection."""

    def test_onboard_writes_profile(self, child_root):
        """onboard intent should write .ai/repository-profile.yaml."""
        subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=child_root, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=child_root, capture_output=True)
        (child_root / "package.json").write_text('{"name": "test"}')
        subprocess.run(["git", "add", "."], cwd=child_root, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=child_root, capture_output=True)

        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(child_root)
            rc = ai_ops_cli.main(["onboard", str(child_root)])
            assert rc == 0
            profile = child_root / ".ai" / "repository-profile.yaml"
            assert profile.is_file()
        finally:
            os.chdir(old_cwd)


def _run_main(argv):
    """Прогнать main(argv), захватив stdout. -> (rc, output). Мирроринг `_run` из монолита."""
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ai_ops_cli.main(argv)
    return rc, buf.getvalue()


@pytest.mark.unit
class TestDirectIntentActions:
    """Перенос из монолита: настоящие действия команд (не превью) — артефакты и коды возврата.

    Плоский root с package.json, без git — ровно как первый tempdir-блок монолита, где эти
    команды и проверялись.
    """

    @pytest.fixture
    def cli_root(self, tmp_path):
        root = tmp_path / "cli-root"
        root.mkdir()
        (root / "package.json").write_text('{"dependencies":{"react":"^18"}}', encoding="utf-8")
        return root

    def test_new_creates_workitem_and_spec(self, cli_root):
        """v2.112 new: РЕАЛЬНО создаёт features/nf/{workitem,spec}.yaml, rc==0."""
        rc, _ = _run_main(["new", str(cli_root), "--feature", "nf",
                           "--signals", '{"task_type":"ENGINEERING","affected_areas":["core"]}'])
        assert rc == 0
        assert (cli_root / "features" / "nf" / "workitem.yaml").is_file()
        assert (cli_root / "features" / "nf" / "spec.yaml").is_file()

    def test_plan_writes_plan_artifacts(self, cli_root):
        """v2.112 plan: РЕАЛЬНО пишет run-plan.yaml + work-package.yaml, rc==0."""
        rc, _ = _run_main(["plan", "сделать X", str(cli_root), "--feature", "pf",
                           "--signals", '{"affected_areas":["core"]}'])
        assert rc == 0
        assert (cli_root / "features" / "pf" / "run-plan.yaml").is_file()
        assert (cli_root / "features" / "pf" / "work-package.yaml").is_file()

    def test_discuss_creates_discovery_draft(self, cli_root):
        """v2.112 discuss: РЕАЛЬНО создаёт features/df/discovery-draft.md, rc==0."""
        rc, _ = _run_main(["discuss", "идея", str(cli_root), "--feature", "df"])
        assert rc == 0
        assert (cli_root / "features" / "df" / "discovery-draft.md").is_file()

    def test_status_returns_zero(self, cli_root):
        """v2.112 status: реальное чтение active-work (не превью), rc==0."""
        rc, _ = _run_main(["status", str(cli_root)])
        assert rc == 0

    def test_health_without_metrics_is_honest_refusal(self, cli_root):
        """v2.112 health: без метрик — честный отказ (rc==1, «не знаю» / «по пустому месту»), не фабрикует score."""
        rc, out = _run_main(["health", str(cli_root)])
        assert rc == 1
        assert "не знаю" in out
        assert "по пустому месту" in out

    def test_preview_onboard_does_not_execute(self, cli_root):
        """preview onboard НЕ выполняет действие: профиль репозитория не создаётся."""
        rc, _ = _run_main(["preview", "onboard", str(cli_root)])
        assert rc == 0
        assert not (cli_root / ".ai" / "repository-profile.yaml").is_file()

    def test_review_without_branch_is_honest_no_branch(self, cli_root):
        """v2.116 review: без ветки честный no-branch (rc!=0, «Проверять нечего», НЕ «можно вливать»)."""
        rc, out = _run_main(["review", "поревьюить", str(cli_root), "--feature", "nope-wid"])
        assert rc != 0
        assert "Проверять нечего" in out
        assert "можно вливать" not in out


@pytest.mark.unit
@pytest.mark.slow
class TestRunExecuteWiresModel:
    """v2.120 CLI: run --execute проводит --model до движка (не mock-хардкод)."""

    def test_model_wired_into_run_report(self, tmp_path):
        import json as _json

        groot = tmp_path / "grepo"
        groot.mkdir()
        (groot / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        for aa in (("init", "-q"), ("config", "user.email", "t@t"), ("config", "user.name", "t"),
                   ("add", "-A"), ("commit", "-q", "-m", "i")):
            subprocess.run(["git", "-C", str(groot), *aa], capture_output=True)

        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            ai_ops_cli.main(["run", "добавить x", str(groot), "--execute", "--feature", "wiref",
                             "--model", "marker-model-xyz",
                             "--signals",
                             '{"task_type":"QUICK","size":"small","risk":"low","affected_areas":["core"]}'])
        rep_p = groot / "features" / "wiref" / "run-report.json"
        assert rep_p.is_file()
        assert _json.loads(rep_p.read_text(encoding="utf-8")).get("model") == "marker-model-xyz"


@pytest.mark.unit
class TestResumePositionalRoot:
    """`ai-ops resume . <feature>` — форма из подсказки движка.

    Живой прогон на child-репозитории (2026-08-14): подсказка после блокирующих гейтов предлагала
    ровно эту строку, а intent-CLI разбирал "." как текст задачи -> workitem_id "." ->
    ValueError со стеком вместо ответа. Каталог в ХВОСТЕ разбирался, в голове — нет.
    """

    def _capture(self, monkeypatch):
        from ai_ops_kit.engine import ai_ops_run
        seen = {}

        def _fake_main(argv):
            seen["argv"] = argv
            return 0

        monkeypatch.setattr(ai_ops_run, "main", _fake_main)
        return seen

    def test_leading_dir_is_root_not_task(self, child_root, monkeypatch):
        seen = self._capture(monkeypatch)
        rc = ai_ops_cli.main(["resume", str(child_root), "describe-planning-execution"])
        assert rc == 0
        argv = seen["argv"]
        assert argv[1] == str(child_root), "каталог репозитория не распознан в первой позиции"
        assert argv[2] == "describe-planning-execution", \
            f"workitem_id взят не из второго позиционного: {argv[2]!r}"

    def test_task_text_still_wins_without_second_positional(self, child_root, monkeypatch):
        """Обычный `resume "текст"` не задет: без второго позиционного текст остаётся текстом."""
        seen = self._capture(monkeypatch)
        ai_ops_cli.main(["resume", "продолжить работу", str(child_root)])
        argv = seen["argv"]
        assert argv[1] == str(child_root)
        assert argv[2] == "продолжить работу"

    def test_resume_forwards_open_pr_and_takeover(self, child_root, monkeypatch):
        """#695: resume доводит готовую-на-ветке работу до ОТКРЫТОГО PR и снимает утёкшую заявку —
        значит --open-pr и --takeover обязаны доехать до движка. Раньше argv2 их терял, и готовая
        работа не открывала PR (owner-led прогон ii-sreda), а брошенную заявку нельзя было снять."""
        seen = self._capture(monkeypatch)
        ai_ops_cli.main(["resume", str(child_root), "wi-x", "--execute", "--open-pr",
                         "--takeover", "--takeover-reason", "утёкшая заявка"])
        argv = seen["argv"]
        assert "--open-pr" in argv, "resume не пробросил --open-pr — PR не откроется"
        assert "--takeover" in argv, "resume не пробросил --takeover — утёкшую заявку не снять"
        assert "утёкшая заявка" in argv

    def test_resume_deliver_only_forwards_reevaluate_only(self, child_root, monkeypatch):
        """#403: --deliver-only доставляет уже готовый READY-коммит без перезапуска писателя —
        интент обязан пробросить существующий режим reevaluate-only в движок. Иначе resume снова
        переавторит и плодит evidence-коммиты при сбое доставки после READY."""
        seen = self._capture(monkeypatch)
        ai_ops_cli.main(["resume", str(child_root), "wi-x", "--execute", "--open-pr", "--deliver-only"])
        assert "--reevaluate-only" in seen["argv"], "--deliver-only не пробросил reevaluate-only в движок"

    def test_resume_without_deliver_only_reauthors(self, child_root, monkeypatch):
        """Без --deliver-only resume идёт обычным путём (переавторинг) — reevaluate-only не появляется."""
        seen = self._capture(monkeypatch)
        ai_ops_cli.main(["resume", str(child_root), "wi-x", "--execute", "--open-pr"])
        assert "--reevaluate-only" not in seen["argv"]


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


# ── #539: ai-ops explain — владельческая карточка «что с моей задачей прямо сейчас» ──────────────
# Проверяем ТРИ обязательства команды: (1) карточка собирается из состояния; (2) для аудитории
# product внутренняя лексика/статусы скрыты, а блокер назван последствием, а не гейтом; (3) путь
# «активной работы нет» отвечает, а не падает и не молчит успехом.
import os

from ai_ops_kit.cli import ai_ops_cli_intents as _intents
from ai_ops_kit.ui import presenter as _presenter


def _explain_run(argv, cwd):
    old = os.getcwd()
    try:
        os.chdir(cwd)
        return ai_ops_cli.main(argv)
    finally:
        os.chdir(old)


def _focus_state(status="in_progress", conflicts=None, cost=None):
    return {"registry_ok": True, "active_count": 1,
            "focus": {"wid": "w-1", "task": "добавить экспорт в CSV",
                      "workflow": "ENGINEERING", "status": status,
                      "branch": "ai-ops/w-1", "human_approval": status == "needs_human_decision"},
            "conflicts": conflicts or [],
            "cost": cost or {"measured": True, "cost_usd": 0.42, "cost_complete": True,
                             "calls": 3, "tokens": 1000},
            "gates": 5, "living_status": {"managed": True, "fresh_today": True}}


@pytest.mark.unit
class TestExplainIntent:
    """`ai-ops explain` — карточка задачи для владельца."""

    def test_explain_is_registered_and_direct(self):
        """Интент объявлен, исполняется (не превью), и его обработчик достижим."""
        assert "explain" in ai_ops_cli.INTENTS
        assert "explain" in ai_ops_cli.DIRECT_INTENTS
        assert "explain" in ai_ops_cli._INTENT_HANDLERS

    def test_card_assembles_from_focus_state(self):
        """Карточка собирает задачу, стадию, стоимость и следующий шаг из снимка состояния."""
        msg = _intents._explain_message(_focus_state())
        out = _presenter.render(msg, audience="product")
        assert "добавить экспорт в CSV" in out         # какая задача
        assert "в работе" in out                       # стадия
        assert "$0.42" in out                          # оценка стоимости
        assert "Дальше:" in out                        # следующий шаг

    def test_cost_unmeasured_is_honest_not_zero(self):
        """Неизмеренная стоимость называется прямо, а не показывается нулём."""
        out = _presenter.render(
            _intents._explain_message(_focus_state(cost={"measured": False})),
            audience="product")
        assert "не измерена" in out
        assert "$0.00" not in out

    def test_blocker_is_a_consequence_not_a_gate_id(self):
        """Блокер назван последствием простыми словами — без имени гейта/трейсбека."""
        msg = _intents._explain_message(_focus_state(status="blocked"))
        out = _presenter.render(msg, audience="product")
        assert "Что мешает" in out
        assert "не проверено" in out or "не готова" in out
        assert msg["status"] == "blocked"
        low = out.lower()
        assert "gate" not in low and "code_review" not in low and "traceback" not in low

    def test_needs_human_decision_asks_for_decision(self):
        """Работа, ждущая человека, просит решение (статус needs_input, не blocked)."""
        msg = _intents._explain_message(_focus_state(status="needs_human_decision"))
        assert msg["status"] == "needs_input"
        out = _presenter.render(msg, audience="product")
        assert "реш" in out.lower()                     # «жду твоего решения» / «подтверди»

    def test_scope_conflict_becomes_a_blocker(self):
        """Пересечение области записи — тоже причина остановиться, названная последствием."""
        line = _intents._explain_blocker("in_progress", False, ["ai-ops/other"])
        assert line is not None
        assert "перепишут одно место" in line
        assert "ai-ops/other" in line

    def test_product_audience_suppresses_jargon(self):
        """Для product внутренний статус/workflow скрыты; на technical — доступны."""
        msg = _intents._explain_message(_focus_state())
        prod = _presenter.render(msg, audience="product")
        tech = _presenter.render(msg, audience="technical")
        assert "in_progress" not in prod and "ENGINEERING" not in prod
        assert "in_progress" in tech                    # тот же факт доступен технической аудитории

    def test_no_active_work_is_graceful(self, tmp_path, capsys):
        """Чистый репозиторий без идущих работ отвечает карточкой, а не падает и не молчит успехом."""
        rc = _explain_run(["explain", str(tmp_path)], tmp_path)
        out = capsys.readouterr().out
        assert rc == 0
        assert "ничего не идёт" in out.lower()
        assert "дальше" in out.lower()

    def test_corrupt_registry_says_it_does_not_know(self, tmp_path):
        """Битый реестр идущих работ -> «не знаю, что идёт» и код 1, а не ложное «ничего»."""
        awp = tmp_path / ".ai" / "runtime" / "active-work.yaml"
        awp.parent.mkdir(parents=True)
        awp.write_text("kind: active-work\nactive: [ this: is: broken\n", encoding="utf-8")
        rc = _explain_run(["explain", str(tmp_path)], tmp_path)
        assert rc == 1


# ── #540: ai-ops inbox — единая владельческая очередь «что ждёт моего решения» ────────────────────
# Проверяем ЧЕТЫРЕ обязательства: (1) очередь агрегирует из источников (решения с карточкой
# что/варианты/рекомендация, остановки, подтверждения, обзор, предупреждения о выпуске); (2) пустая
# очередь честна — «ничего не ждёт», а не выдуманный список; (3) для аудитории product скрыты
# идентификаторы работ/решений (жаргон), а на technical — доступны; (4) битый реестр -> «не знаю,
# что ждёт» и код 1, а не ложное «ничего».
import yaml as _yaml


def _make_queue(decisions=None, blocked=None, reviews=None, insight=None, warnings=None,
                registry_ok=True):
    d = decisions or []
    b = blocked or []
    r = reviews or []
    w = warnings or []
    total = len(d) + len(b) + len(r) + (1 if insight else 0) + len(w)
    return {"registry_ok": registry_ok, "total": total, "decisions": d, "blocked": b,
            "reviews": r, "insight": insight, "warnings": w}


@pytest.mark.unit
class TestInboxIntent:
    """`ai-ops inbox` — очередь всего, что ждёт решения владельца."""

    def test_inbox_is_registered_and_direct(self):
        """Интент объявлен, исполняется (не превью), и его обработчик достижим."""
        assert "inbox" in ai_ops_cli.INTENTS
        assert "inbox" in ai_ops_cli.DIRECT_INTENTS
        assert "inbox" in ai_ops_cli._INTENT_HANDLERS

    def test_reads_only_pending_decisions_with_card(self, tmp_path):
        """Источник решений: берутся только pending, с полями что/варианты/рекомендация."""
        ddir = tmp_path / ".ai" / "project" / "decisions"
        ddir.mkdir(parents=True)
        (ddir / "2026-09-06-d1.yaml").write_text(_yaml.safe_dump(
            {"id": "d1", "status": "pending", "proposal": "поднять таймаут доставки",
             "options": ["30s", "60s"], "recommendation": "60s"}, allow_unicode=True),
            encoding="utf-8")
        (ddir / "2026-09-05-d0.yaml").write_text(_yaml.safe_dump(
            {"id": "d0", "status": "approved", "proposal": "уже решено"}, allow_unicode=True),
            encoding="utf-8")
        got = _intents._inbox_decisions(tmp_path)
        assert [x["id"] for x in got] == ["d1"]                 # approved не попал
        assert got[0]["options"] == ["30s", "60s"]
        assert got[0]["recommendation"] == "60s"

    def test_decisions_dir_is_not_created_on_read(self, tmp_path):
        """Чтение решений НЕ создаёт каталог: inbox только читает (в отличие от list_decisions)."""
        assert _intents._inbox_decisions(tmp_path) == []
        assert not (tmp_path / ".ai" / "project" / "decisions").exists()

    def test_render_aggregates_all_buckets(self):
        """Очередь показывает решения (карточкой), остановки, подтверждения, обзор и предупреждения."""
        q = _make_queue(
            decisions=[{"id": "d1", "what": "поднять таймаут", "options": ["30s", "60s"],
                        "recommendation": "60s"}],
            blocked=[{"wid": "w-1", "task": "экспорт в CSV", "why": "проверка не пройдена"}],
            reviews=[{"wid": "w-2", "task": "смена схемы", "why": "жду подтверждения"}],
            insight={"what": "ночной обзор изменений", "path": "x"},
            warnings=[{"what": "здоровье продукта красное — выпускать рискованно", "why": "тесты"}])
        out = _intents._inbox_render(q, "product")
        assert "поднять таймаут" in out                         # решение
        assert "варианты:" in out and "60s" in out              # карточка: варианты+рекомендация
        assert "рекомендую" in out
        assert "экспорт в CSV" in out                           # остановленная работа
        assert "смена схемы" in out                             # ждёт подтверждения
        assert "ночной обзор" in out                            # свежий обзор
        assert "выпускать рискованно" in out                    # предупреждение о выпуске

    def test_empty_queue_is_honest(self):
        """Пустая очередь говорит «ничего не ждёт», а не показывает выдуманный список."""
        out = _intents._inbox_render(_make_queue(), "product")
        assert "Ничего не ждёт твоего решения." in out

    def test_empty_on_clean_repo_returns_zero(self, tmp_path, capsys):
        """Чистый репозиторий: команда отвечает пустой очередью и кодом 0, а не падает."""
        rc = _explain_run(["inbox", str(tmp_path)], tmp_path)
        out = capsys.readouterr().out
        assert rc == 0
        assert "ничего не ждёт" in out.lower()

    def test_product_audience_suppresses_ids(self):
        """Для product идентификаторы работ/решений скрыты; на technical — доступны."""
        q = _make_queue(blocked=[{"wid": "w-42", "task": "экспорт в CSV",
                                   "why": "проверка не пройдена"}])
        prod = _intents._inbox_render(q, "product")
        tech = _intents._inbox_render(q, "technical")
        assert "w-42" not in prod                               # идентификатор скрыт от владельца
        assert "экспорт в CSV" in prod                          # но сама задача названа
        assert "w-42" in tech                                   # тот же факт доступен технической

    def test_status_reflects_queue(self):
        """Статус контракта: решения -> нужно решение; только остановки -> заблокировано; пусто -> ок."""
        assert _intents._inbox_status(_make_queue(
            decisions=[{"id": "d", "what": "x", "options": [], "recommendation": ""}])) == "needs_input"
        assert _intents._inbox_status(_make_queue(
            blocked=[{"wid": "w", "task": "t", "why": "y"}])) == "blocked"
        assert _intents._inbox_status(_make_queue()) == "ok"
        assert _intents._inbox_status(_make_queue(registry_ok=False)) == "degraded"

    def test_release_warning_from_red_health(self, tmp_path, monkeypatch):
        """Предупреждение о выпуске выводится из красного здоровья продукта (read-only источник)."""
        monkeypatch.setattr(_intents, "_product_health_report",
                            lambda root: {"band": "red", "reasons": ["CI красный"]})
        warns = _intents._inbox_release_warnings(tmp_path)
        assert len(warns) == 1
        assert "рискованно" in warns[0]["what"]
        # Зелёное/нет данных -> предупреждения нет (не выдумываем).
        monkeypatch.setattr(_intents, "_product_health_report", lambda root: {"band": "green"})
        assert _intents._inbox_release_warnings(tmp_path) == []
        monkeypatch.setattr(_intents, "_product_health_report", lambda root: None)
        assert _intents._inbox_release_warnings(tmp_path) == []

    def test_corrupt_registry_says_it_does_not_know(self, tmp_path):
        """Битый реестр идущих работ -> «не знаю, что ждёт» и код 1, а не ложное «ничего»."""
        awp = tmp_path / ".ai" / "runtime" / "active-work.yaml"
        awp.parent.mkdir(parents=True)
        awp.write_text("kind: active-work\nactive: [ this: is: broken\n", encoding="utf-8")
        q = _intents._inbox_collect(tmp_path)
        assert q["registry_ok"] is False
        out = _intents._inbox_render(q, "product")
        assert "Не знаю, что ждёт" in out
        rc = _explain_run(["inbox", str(tmp_path)], tmp_path)
        assert rc == 1
