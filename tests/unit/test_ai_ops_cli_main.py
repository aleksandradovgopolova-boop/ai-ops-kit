"""Unit tests for tools/ai_ops_cli.py — main() и прямые действия команд.

Здесь живут тесты входной точки CLI и РЕАЛЬНОГО исполнения команд (не превью): main(),
onboard, прямые интенты (new/plan/discuss/status/health/review), run --execute с проводкой
--model и разбор позиционного каталога в `resume`. Машинерия превью/флагов — в
`test_ai_ops_cli.py`, владельческие read-only команды (explain/inbox) — в
`test_ai_ops_cli_owner_queue.py`. Разрез #819 (файл упирался в потолок анти-монолит-гейта).
"""
from __future__ import annotations

import subprocess

import pytest

from ai_ops_kit.cli import ai_ops_cli


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
