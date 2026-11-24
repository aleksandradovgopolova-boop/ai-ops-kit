"""Негативная проверка изоляции контейнера (#1407) без настоящего Docker.

Живой прогон — tests/integration/test_container_isolation_smoke.py в CI container-smoke. Здесь
проверяется всё остальное: сверка фактов пробы с обещаниями обёртки, разбор вывода и путь через
НАСТОЯЩУЮ `containers/run-sandboxed.sh` с подставным `docker` в PATH — что уходит в docker run,
что не пробрасывается, что исходный репозиторий не тронут и клон убран.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import validate_container_assets as vca
from ai_ops_kit.validation import container_isolation_probe as probe

PKG = Path(__file__).resolve().parents[2]
GOOD = {
    "uid": 10001, "euid": 10001, "root_fs_options": ["ro", "relatime"], "opt_writable": False,
    "work_writable": True, "work_is_clone": True, "host_child_visible": False, "interfaces": ["lo"],
    "egress": False, "cap_eff": probe.NO_CAPABILITIES, "cap_bnd": probe.NO_CAPABILITIES,
    "no_new_privs": "1", **probe.EXPECTED_LIMITS, "foreign_secret_visible": False,
    "ssh_agent_forwarded": False, "git_askpass": "/bin/false", "git_credentials_file": False,
}
BREAKS = {
    "uid": 0, "euid": 0, "root_fs_options": ["rw"], "opt_writable": True, "work_writable": False,
    "work_is_clone": False, "host_child_visible": True, "interfaces": ["eth0", "lo"], "egress": True,
    "cap_eff": "00000000a80425fb", "cap_bnd": "00000000a80425fb", "no_new_privs": "0",
    "pids_max": "max", "memory_max": "max", "cpu_max": "max 100000", "foreign_secret_visible": True,
    "ssh_agent_forwarded": True, "git_askpass": None, "git_credentials_file": True,
}


def test_complete_isolation_has_no_violations():
    assert probe.evaluate(GOOD) == []


def test_every_expectation_has_a_breaking_case():
    assert {field for field, _, _ in probe.EXPECTATIONS} == set(BREAKS) == set(GOOD)


@pytest.mark.parametrize("field", sorted(BREAKS))
def test_each_broken_promise_is_reported(field):
    errors = probe.evaluate({**GOOD, field: BREAKS[field]})
    assert len(errors) == 1 and f"{field}=" in errors[0]


def test_missing_fact_is_a_violation_not_a_pass():
    facts = {k: v for k, v in GOOD.items() if k != "egress"}
    assert probe.evaluate(facts) == ["egress: проба не сообщила факт"]


def test_parse_takes_last_probe_line_and_rejects_absent_or_malformed():
    out = f"шум\n{probe.PROBE_MARKER}{json.dumps({'uid': 1})}\n{probe.PROBE_MARKER}{json.dumps(GOOD)}\n"
    assert probe.parse_probe(out) == GOOD
    assert probe.parse_probe("нет пробы\n") is None
    assert probe.parse_probe(f"{probe.PROBE_MARKER}[1, 2]\n") is None


def test_probe_source_is_stdlib_python_that_reports_every_expected_fact():
    code = compile(probe.PROBE_SOURCE, "isolation-probe", "exec")
    assert "ai_ops_kit" not in probe.PROBE_SOURCE  # проба не зависит от проверяемого кита
    names = set(code.co_consts) | {c for const in code.co_consts if isinstance(const, tuple) for c in const}
    assert {field for field, _, _ in probe.EXPECTATIONS} <= names


FAKE_DOCKER = r'''
import json, os, sys
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
facts = json.loads(os.environ["FAKE_PROBE_FACTS"])
print("ISOLATION-PROBE " + json.dumps(facts), flush=True)
sys.exit(int(os.environ.get("FAKE_DOCKER_RC", "0")))
'''


@pytest.fixture
def fake_docker(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "docker"
    script.write_text(f"#!{sys.executable}\n{FAKE_DOCKER}")
    script.chmod(0o755)
    log = tmp_path / "docker.log"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    monkeypatch.setenv("FAKE_PROBE_FACTS", json.dumps(GOOD))
    return log


def built(args, timeout):
    return subprocess.CompletedProcess(args, 0, "", "")


def test_real_wrapper_runs_probe_offline_without_foreign_env_and_cleans_up(fake_docker):
    assert probe.probe_isolation(PKG, built, "base:tag", "probe:tag") == []
    calls = [json.loads(line) for line in fake_docker.read_text().splitlines()]
    run = next(c for c in calls if c[0] == "run")
    assert run[run.index("--network") + 1] == "none"
    assert "probe:tag" in run and "--read-only" in run
    joined = " ".join(run)
    assert probe.FOREIGN_SECRET not in joined and "SSH_AUTH_SOCK" not in joined


def test_reported_violation_from_container_fails_the_check(fake_docker, monkeypatch):
    monkeypatch.setenv("FAKE_PROBE_FACTS", json.dumps({**GOOD, "egress": True}))
    errors = probe.probe_isolation(PKG, built, "base:tag", "probe:tag")
    assert errors == ["при AI_OPS_NETWORK=none есть выход в сеть (egress=True)"]


def test_wrapper_failure_is_reported_not_evaluated(fake_docker, monkeypatch):
    monkeypatch.setenv("FAKE_DOCKER_RC", "3")
    errors = probe.probe_isolation(PKG, built, "base:tag", "probe:tag")
    assert len(errors) == 1 and "rc=3" in errors[0]


def test_probe_image_build_failure_stops_before_wrapper(fake_docker):
    def broken(args, timeout):
        return subprocess.CompletedProcess(args, 1, "", "no base image")
    errors = probe.probe_isolation(PKG, broken, "base:tag", "probe:tag")
    assert len(errors) == 1 and "no base image" in errors[0]
    assert not fake_docker.exists()


def test_isolation_smoke_without_docker_is_blocked_not_success(monkeypatch):
    monkeypatch.setattr(vca, "_docker_blocker", lambda: "docker не найден в PATH")
    code, lines = vca.isolation_smoke()
    assert code == 2 and "BLOCKED" in lines[0]
