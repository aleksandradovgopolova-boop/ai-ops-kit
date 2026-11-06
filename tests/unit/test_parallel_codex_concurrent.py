"""#1434: Codex runtime передаётся в управляемую конкурентную оркестрацию пакетов.

Offline callbacks независимых пакетов идут одновременно через governed concurrent-путь
(`parallel_live.run_live_concurrent`, отдельный клон на пакет, fan-in на свежем integration-SHA), а
исполнитель прокидывается в КАЖДЫЙ пакетный прогон. Три поведения — по инженерному циклу:
  - positive: диспетч несёт runtime=codex + provider=codex-app-server в run_options каждого пакета;
  - side-effect proof: конкурентный прогон не портит общий checkout (HEAD на base, дерево чистое),
    пакеты изолированы по клонам, конфликтов нет;
  - fail-closed: native-провайдер Codex без подтверждённой среды НЕ возвращает тихий текст, а падает
    отказом среды (готовность/доверие/модель остаются обязательными per-работа), и такой пакет
    помечается fail, доставка не открывается.
Native turns текущего Codex adapter сериализованы общим workspace lock; live concurrency не доказана.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from threading import Barrier

import pytest

from ai_ops_kit.engine import parallel_live_dispatch as dsp
from ai_ops_kit.engine.parallel_live import _git, run_live_concurrent
from ai_ops_kit.providers import codex_native, provider_calls
from ai_ops_kit.providers.provider_errors import ProviderEnvUnavailableError


def _setup_repo(td):
    _git(td, "init", "-q")
    _git(td, "config", "user.email", "t@t")
    _git(td, "config", "user.name", "t")
    (Path(td) / "pyproject.toml").write_text(
        "[project]\nname='t'\nversion='0.1.0'\n[tool.pytest.ini_options]\npythonpath=['.']\n",
        encoding="utf-8")
    Path(td, "tests").mkdir()
    (Path(td) / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    _git(td, "add", "-A")
    _git(td, "commit", "-qm", "seed")
    return _git(td, "rev-parse", "HEAD").stdout.strip()


def _two_disjoint_packages():
    return {"schema_version": 1, "kind": "WorkGraph", "id": "WG-CODEX", "feature": "f",
            "execution_mode": "hybrid",
            "packages": [{"id": "aa", "depends_on": [], "write_scope": ["aa.py"]},
                         {"id": "bb", "depends_on": [], "write_scope": ["bb.py"]}]}


@pytest.mark.unit
class TestCodexExecutorReachesGovernedParallel:
    def test_dispatch_carries_runtime_and_provider_per_package(self, tmp_path, monkeypatch):
        """Диспетч `--parallel` для Codex: run_options КАЖДОГО пакета несёт исполнителя и провайдера.

        Без запуска клонов/провайдера — проверяем ровно шов проводки (инъектированный runner).
        """
        monkeypatch.setattr(dsp.atomic_planner, "decompose", lambda *a, **k: {
            "should_decompose": True,
            "work_packages": [
                {"id": "p1", "title": "t1", "depends_on": [], "write_scope": ["a/**"]},
                {"id": "p2", "title": "t2", "depends_on": [], "write_scope": ["b/**"]},
            ]})
        monkeypatch.setattr(dsp.gitio, "resolve_base", lambda *a: {
            "resolved": True, "base_ref": "main", "base_sha": "f" * 40})
        captured = {}

        def fake_runner(wg, child_root, base_sha, task_map, signals, run_fn, **kw):
            captured.update(kw)
            return {"proceed": True, "execution_concurrency": "concurrent",
                    "delivery": {"open_pr": True}, "integration_sha": "c" * 40}

        rec = dsp.run_parallel_live("сделать X", {"task_text": "сделать X"}, tmp_path,
                                    feature="WG-9", provider="codex-app-server", runtime="codex",
                                    runner=fake_runner, run_fn=lambda *a, **k: None)
        assert rec["parallel"] is True
        opts = captured["run_options"]
        assert opts["provider_name"] == "codex-app-server"
        assert opts["runtime"] == "codex"
        assert (tmp_path / "features/WG-9/parallel-report.json").is_file()

    def test_default_runtime_preserved_when_not_codex(self, tmp_path, monkeypatch):
        """Регресс: без явного рантайма пакеты остаются claude-code (дефолт не сдвинут)."""
        monkeypatch.setattr(dsp.atomic_planner, "decompose", lambda *a, **k: {
            "should_decompose": True,
            "work_packages": [
                {"id": "p1", "depends_on": [], "write_scope": ["a/**"]},
                {"id": "p2", "depends_on": [], "write_scope": ["b/**"]},
            ]})
        monkeypatch.setattr(dsp.gitio, "resolve_base", lambda *a: {
            "resolved": True, "base_ref": "main", "base_sha": "f" * 40})
        captured = {}
        dsp.run_parallel_live("t", {"task_text": "t"}, tmp_path, feature="WG-9", provider="mock",
                              runner=lambda *a, **k: captured.update(k) or {"proceed": True},
                              run_fn=lambda *a, **k: None)
        assert captured["run_options"]["runtime"] == "claude-code"
        assert (tmp_path / "features/WG-9/parallel-report.json").is_file()


@pytest.mark.unit
class TestCodexConcurrentNoCheckoutDamage:
    def _codex_commit_run(self, observed, overlap):
        """Фейковый run_fn: фиксирует исполнителя/провайдера, которые получил пакет, и коммитит в
        СВОЙ клон (как сделал бы реальный прогон writer'а)."""
        def run(task, sig, root, **kw):
            overlap.wait(timeout=30)  # последовательные callbacks не могут пройти этот барьер
            observed.append({"feature": kw["feature"], "runtime": kw.get("runtime"),
                             "provider_name": kw.get("provider_name")})
            pid = kw["feature"]
            _git(root, "config", "user.email", "t@t")
            _git(root, "config", "user.name", "t")
            _git(root, "checkout", "-q", "-B", f"ai-ops/{pid}")
            (Path(root) / f"{pid}.py").write_text(f"def {pid}():\n    return 1\n", encoding="utf-8")
            _git(root, "add", "-A")
            _git(root, "commit", "-qm", f"pkg {pid}")
            return {"ready_for_pr": True, "commit": {"sha": _git(root, "rev-parse", "HEAD").stdout.strip()}}
        return run

    def test_independent_codex_packages_run_concurrently_without_touching_main_checkout(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as cdir:
            base = _setup_repo(td)
            observed = []
            rec = run_live_concurrent(
                _two_disjoint_packages(), td, base, {"aa": "t", "bb": "t"}, {"task_type": "QUICK"},
                self._codex_commit_run(observed, Barrier(2)), cdir,
                run_options={"provider_name": "codex-app-server", "runtime": "codex"})
            # Барьер внутри callbacks доказывает их перекрытие, а не только метку результата.
            assert rec["proceed"] is True
            results = rec["package_results"]
            assert set(results) == {"aa", "bb"}
            for pid, result in results.items():
                assert result["status"] == "pass"
                assert result["sha"] != base
                clone = Path(cdir) / pid
                assert _git(clone, "diff", "--name-only", base, result["sha"]).stdout.strip() == f"{pid}.py"
                assert _git(clone, "show", f"{result['sha']}:{pid}.py").stdout == f"def {pid}():\n    return 1\n"
            assert rec.get("execution_concurrency") == "concurrent"
            assert rec.get("isolation") == "per-package-clone"
            assert {o["feature"] for o in observed} == {"aa", "bb"}
            # исполнитель и провайдер дошли до КАЖДОГО пакета, а не потерялись по дороге
            assert all(o["runtime"] == "codex" for o in observed)
            assert all(o["provider_name"] == "codex-app-server" for o in observed)
            # governed fan-in: конфликтов нет, пакеты и интеграция изолированы по клонам
            assert (rec.get("aggregate") or {}).get("conflicts") == 0
            assert all((Path(cdir) / p).is_dir() for p in ("aa", "bb", "_integration"))
            # side-effect proof: общий checkout НЕ тронут — HEAD на base, в рабочем дереве нет кода
            # модели. `.ai/` — это governed-артефакты пути (usage receipt), а не порча checkout: та же
            # граница, что у preflight_disposable (`_is_ai_churn`). Коммитов/веток кода в main нет.
            assert _git(td, "rev-parse", "HEAD").stdout.strip() == base
            dirty = [ln for ln in _git(td, "status", "--porcelain").stdout.splitlines()
                     if ln.strip() and ".ai" not in ln]
            assert dirty == []
            assert not (Path(td) / "aa.py").exists() and not (Path(td) / "bb.py").exists()


@pytest.mark.unit
class TestCodexParallelFailsClosed:
    def test_native_codex_provider_does_not_return_silent_text(self, tmp_path, monkeypatch):
        """Fail-closed per-работа: без подтверждённой native-среды Codex провайдер ПАДАЕТ отказом
        среды, а не возвращает тихий «успех». Проводка в параллель этого не ослабляет."""
        # Неготовность задаётся явно: установленный/авторизованный Codex на машине
        # не должен превращать unit-тест в живой вызов или писать в рабочий checkout.
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(codex_native.hook.tempfile, "gettempdir", lambda: str(tmp_path))
        attempts = []

        def unavailable_transport(command, directory, timeout):
            attempts.append((command, directory))
            raise codex_native.NativeError("offline transport unavailable")

        def forbidden_answer(*args, **kwargs):
            pytest.fail("неподтверждённая native-среда не должна запускать turn")

        monkeypatch.setattr(codex_native, "RPC", unavailable_transport)
        monkeypatch.setattr(codex_native, "answer", forbidden_answer)
        provider = provider_calls.make_provider("codex-app-server")
        with pytest.raises(ProviderEnvUnavailableError, match="offline transport unavailable"):
            provider("любой непустой промпт для попытки turn")
        assert len(attempts) == 1
        assert attempts[0][0][:3] == ["codex", "app-server", "--stdio"]
        assert Path(attempts[0][1]).is_relative_to(tmp_path)

    def test_unready_codex_package_marked_fail_and_no_delivery(self):
        """Пакет, чей codex-прогон не подтвердил готовность (как при fail-closed провайдере), помечается
        fail и НЕ проходит в доставку — молчаливого зелёного нет."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as cdir:
            base = _setup_repo(td)

            def unready_run(task, sig, root, **kw):
                # исполнитель Codex, но среда не подтвердила готовность -> работа не готова (не коммитит)
                return {"ready_for_pr": False, "commit": {}}

            rec = run_live_concurrent(
                _two_disjoint_packages(), td, base, {"aa": "t", "bb": "t"}, {"task_type": "QUICK"},
                unready_run, cdir,
                run_options={"provider_name": "codex-app-server", "runtime": "codex"})
            results = rec.get("package_results") or {}
            assert results and all(r.get("status") == "fail" for r in results.values())
            assert rec.get("delivery", {}).get("open_pr") is not True
            # общий checkout по-прежнему цел
            assert _git(td, "rev-parse", "HEAD").stdout.strip() == base
