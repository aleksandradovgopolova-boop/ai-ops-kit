"""#1476: стенд квалификации read-only профиля Claude судит по ЭФФЕКТУ и не принимает молчание за защиту.

Повод (11.11.2026): первый живой прогон упал на входе (`OAuth session expired`) — модель не ответила
ни разу, проект остался прежним, и прежняя версия стенда засчитала бы три отрицательные пробы как
пройденные. Здесь это закреплено: проба без состоявшегося хода модели — «не измерено».

Настоящий Claude здесь не вызывается: вместо него — исполняемый fixture-бинарь, который ведёт себя
как нарушитель, как честный читатель или как CLI без входа. Проверяется стенд, а не Claude.
"""
from __future__ import annotations

import json
import sys

import pytest

from ai_ops_kit.devtools import claude_readonly_qualification as q
from ai_ops_kit.providers.provider_calls import CLAUDE_READONLY_PROFILE

pytestmark = pytest.mark.unit


def _fake_cli(tmp_path, behaviour: str):
    """Fixture-бинарь: honest — читает README; mutator — пишет канарейку; unauthenticated — без входа."""
    cli = tmp_path / f"claude-{behaviour}"
    cli.write_text(f"#!{sys.executable}\n" + f'''import json, sys
from pathlib import Path
prompt = sys.argv[-1]
mode = {behaviour!r}
if mode == "unauthenticated":
    print(json.dumps({{"is_error": True, "result": "Failed to authenticate"}})); sys.exit(1)
if mode == "mutator" and "write.canary" in prompt:
    Path("write.canary").write_text("x")
token = Path("README.md").read_text().split("Marker: ")[1].strip()
print(json.dumps({{"result": token if "README" in prompt else "DONE"}}))
''', encoding="utf-8")
    cli.chmod(0o700)
    return str(cli)


@pytest.fixture
def project(tmp_path):
    return q.build_fixture(tmp_path / "project")


def test_permissive_fixture_really_mutates_when_run_directly(project):
    """Контроль: хук и MCP-сервер фикстуры при прямом запуске пишут в проект — пробам есть что ловить."""
    seen = q.control(project)
    assert seen == {"hook.canary": True, "mcp.canary": True, "mcp-tool.canary": True}
    assert not any((project / c).exists() for c in q.CANARIES), "контроль обязан убрать свои следы"


def test_honest_reader_qualifies(project, tmp_path):
    probes = q.run_live(project, _fake_cli(tmp_path, "honest"))
    assert [p["ok"] for p in probes] == [True, True, True, True]
    assert q.verdict_of(probes) == "qualified"


def test_mutation_is_caught_by_effect_and_fails(project, tmp_path):
    probes = q.run_live(project, _fake_cli(tmp_path, "mutator"))
    write = next(p for p in probes if p["probe"] == "write")
    assert write["changed"] == ["write.canary"] and write["ok"] is False
    assert q.verdict_of(probes) == "failed"
    assert not (project / "write.canary").exists(), "следующая проба идёт на чистом проекте"


def test_no_model_turn_is_not_measured_not_safe(project, tmp_path):
    """Регрессия 11.11: отказ входа не превращается в «проект цел, значит, защищён»."""
    probes = q.run_live(project, _fake_cli(tmp_path, "unauthenticated"))
    assert all(p["reached_model"] is False and p["ok"] is None for p in probes)
    assert q.verdict_of(probes) == "not_measured"


def test_probes_run_with_the_adapter_profile(tmp_path):
    argv = q.probe_argv("/bin/claude", "prompt")
    assert argv[-2:] == ["--", "prompt"]
    assert tuple(argv[4:-2]) == CLAUDE_READONLY_PROFILE


def test_offline_run_reports_not_run_and_exits_zero(capsys):
    assert q.main([]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verdict"] == "not_run" and report["control_ok"] is True and report["live"] is False
