"""#542: opt-in `--parallel` РЕАЛЬНО достигает run_live_concurrent, а дефолт (single-path) неизменен.

Маршрутизация проверяется без запуска настоящих клонов/провайдера: тяжёлое исполнение подменяется
инъекцией `runner`/`run_fn`. Проверяем ровно шов проводки:
  - мультипакетный план -> вызов dispatch-runner (run_live_concurrent) с построенным WorkGraph;
  - атомарная задача -> None (вызыватель делает обычный прогон — дефолт не меняется);
  - CLI объявляет флаг `--parallel` и по умолчанию он ВЫКЛ.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.engine import parallel_live_dispatch as dsp


@pytest.mark.unit
class TestBuildWorkGraph:
    def test_multi_package_builds_graph(self, monkeypatch):
        monkeypatch.setattr(
            dsp.atomic_planner, "decompose",
            lambda signals, wid=None, child_root=None, **kw: {
                "should_decompose": True,
                "work_packages": [
                    {"id": f"{wid}-pkg-1", "title": "часть 1", "depends_on": [], "write_scope": ["a/**"]},
                    {"id": f"{wid}-pkg-2", "title": "часть 2", "depends_on": [], "write_scope": ["b/**"]},
                ]})
        wg, task_map = dsp.build_work_graph({"task_text": "сделать X"}, "WG-1", ".")
        assert wg["kind"] == "WorkGraph"
        assert [p["id"] for p in wg["packages"]] == ["WG-1-pkg-1", "WG-1-pkg-2"]
        # каждый пакет несёт СВОЙ текст (общая задача + подзадача пакета)
        assert set(task_map) == {"WG-1-pkg-1", "WG-1-pkg-2"}
        assert "сделать X" in task_map["WG-1-pkg-1"]
        assert "WG-1-pkg-1" in task_map["WG-1-pkg-1"]

    def test_atomic_returns_none(self, monkeypatch):
        monkeypatch.setattr(dsp.atomic_planner, "decompose",
                            lambda *a, **k: {"should_decompose": False, "work_packages": []})
        assert dsp.build_work_graph({"task_text": "t"}, "WG", ".") == (None, None)

    def test_single_package_is_not_parallelized(self, monkeypatch):
        monkeypatch.setattr(dsp.atomic_planner, "decompose", lambda *a, **k: {
            "should_decompose": True,
            "work_packages": [{"id": "only", "depends_on": [], "write_scope": ["a/**"]}]})
        assert dsp.build_work_graph({"task_text": "t"}, "WG", ".") == (None, None)


@pytest.mark.unit
class TestOptInReachesRunLiveConcurrent:
    def test_dispatch_calls_run_live_concurrent(self, monkeypatch):
        """Опт-ин достигает run_live_concurrent: инъектированный runner получает построенный WorkGraph."""
        monkeypatch.setattr(dsp.atomic_planner, "decompose", lambda *a, **k: {
            "should_decompose": True,
            "work_packages": [
                {"id": "p1", "title": "t1", "depends_on": [], "write_scope": ["a/**"]},
                {"id": "p2", "title": "t2", "depends_on": [], "write_scope": ["b/**"]},
            ]})
        # база-SHA нужна run_parallel_live — не зовём git, стабим _base_sha
        monkeypatch.setattr(dsp, "_base_sha", lambda root: "f" * 40)
        captured = {}

        def fake_runner(wg, child_root, base_sha, task_map, signals, run_fn, **kw):
            captured.update(wg=wg, base_sha=base_sha, task_map=task_map, run_fn=run_fn, kw=kw)
            return {"proceed": True, "execution_concurrency": "concurrent",
                    "delivery": {"open_pr": True}, "integration_sha": "c" * 40}

        # run_fn НЕ вызывается (fake_runner его не дергает) — реальные клоны не создаются
        rec = dsp.run_parallel_live("сделать X", {"task_text": "сделать X"}, ".",
                                    feature="WG-9", runner=fake_runner, run_fn=lambda *a, **k: None)
        assert rec["parallel"] is True
        assert captured["base_sha"] == "f" * 40
        assert [p["id"] for p in captured["wg"]["packages"]] == ["p1", "p2"]
        assert set(captured["task_map"]) == {"p1", "p2"}
        # реальный дефолтный runner — это именно run_live_concurrent
        from ai_ops_kit.engine import parallel_live
        assert dsp.parallel_live.run_live_concurrent is parallel_live.run_live_concurrent

    def test_atomic_task_falls_back_to_none(self, monkeypatch):
        """Атомарная задача -> None: вызыватель уходит в обычный (single-path) прогон, дефолт цел."""
        monkeypatch.setattr(dsp.atomic_planner, "decompose",
                            lambda *a, **k: {"should_decompose": False, "work_packages": []})
        called = {"runner": False}

        def fake_runner(*a, **k):
            called["runner"] = True
            return {}

        rec = dsp.run_parallel_live("t", {"task_text": "t"}, ".", runner=fake_runner)
        assert rec is None
        assert called["runner"] is False

    def test_no_base_sha_refuses_without_touching_runner(self, monkeypatch):
        monkeypatch.setattr(dsp.atomic_planner, "decompose", lambda *a, **k: {
            "should_decompose": True,
            "work_packages": [
                {"id": "p1", "depends_on": [], "write_scope": ["a/**"]},
                {"id": "p2", "depends_on": [], "write_scope": ["b/**"]},
            ]})
        monkeypatch.setattr(dsp, "_base_sha", lambda root: None)
        called = {"runner": False}
        rec = dsp.run_parallel_live("t", {"task_text": "t"}, ".",
                                    runner=lambda *a, **k: called.__setitem__("runner", True))
        assert rec["proceed"] is False
        assert rec["stage"] == "preflight"
        assert called["runner"] is False


@pytest.mark.unit
class TestExitAndPrint:
    def test_exit_code_green_delivery(self):
        assert dsp.exit_code({"proceed": True, "delivery": {"open_pr": True}}) == 0

    def test_exit_code_not_ready(self):
        assert dsp.exit_code({"proceed": False, "stage": "fan-in"}) == 1

    def test_exit_code_blocked(self):
        assert dsp.exit_code({"proceed": False, "stage": "preflight"}) == 2

    def test_print_does_not_raise(self, capsys):
        dsp.print_parallel({"proceed": True, "id": "WG", "execution_concurrency": "concurrent",
                            "isolation": "per-package-clone", "integration_sha": "c" * 40,
                            "aggregate": {"conflicts": 0}, "delivery_plan": {"ready": True},
                            "package_results": {"p1": {"status": "pass", "sha": "a" * 40}}})
        assert "PARALLEL" in capsys.readouterr().out


@pytest.mark.unit
class TestCliDeclaresFlag:
    def test_parallel_flag_default_off(self):
        """CLI объявляет --parallel и по умолчанию он ВЫКЛ (дефолтный run — single-path)."""
        from ai_ops_kit.cli import ai_ops_cli
        ap = ai_ops_cli._build_cli_arg_parser()
        ns = ap.parse_args(["run", "задача"])
        assert getattr(ns, "parallel", False) is False
        ns2 = ap.parse_args(["run", "задача", "--parallel"])
        assert ns2.parallel is True


def test_smoke_module_imports():
    with tempfile.TemporaryDirectory():
        assert callable(dsp.run_parallel_live)
        assert callable(dsp.build_work_graph)
