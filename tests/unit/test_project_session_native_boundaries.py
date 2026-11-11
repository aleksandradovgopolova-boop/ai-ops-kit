"""Открытый агент не требует native provider; автономный отказ сохраняет задачу."""
import json

import pytest
import yaml

from ai_ops_kit.cli.project_session import hook
from ai_ops_kit.lifecycle import project_session as sessions
from test_project_session import complete_prepared_spec, fixture_producer, project as _project_fixture


@pytest.fixture
def project(tmp_path, monkeypatch):
    return _project_fixture.__wrapped__(tmp_path, monkeypatch)


@pytest.mark.parametrize("runtime", sessions.RUNTIMES)
def test_open_agent_gets_real_controller_plan_without_nested_provider(project, monkeypatch, runtime):
    from ai_ops_kit.cli import project_session as cli
    from ai_ops_kit.providers import codex_native
    def unexpected_native_readiness(_root):
        pytest.fail("current-session must not require a nested native provider")
    monkeypatch.setattr(codex_native, "readiness", unexpected_native_readiness)
    task = sessions.begin(project, runtime, "open-agent", "Проведи ресерч архитектуры", "turn-1")
    monkeypatch.chdir(project)
    args = ["run", "--runtime", runtime, "--session", "open-agent"]
    assert cli.main(args + ["--signals", '{"task_type":"research","size":"small","risk":"low"}']) == 1
    complete_prepared_spec(project, task)
    assert cli.main(args) == 1
    saved = sessions.load(project, runtime, "open-agent")
    assert saved["status"] == "running" and saved["execution"]["prepared"]
    assert saved["execution"]["mode"] == "current-session"
    command = saved["execution"]["command"]
    assert "--execute" not in command and "--provider" not in command
    feature = project / "features" / ("session-" + task["request_id"])
    workitem = yaml.safe_load((feature / "workitem.yaml").read_text())
    plan = yaml.safe_load((feature / "run-plan.yaml").read_text())
    assert workitem["task"] == task["prompt"] and plan["base_workflow"] == "RESEARCH"
    report = json.loads((feature / "run-report.json").read_text())
    assert report["execution"] == "planned" and plan["gates"]
    assert not sessions.verify(project, runtime, "open-agent")["accepted"]
    assert hook(runtime, {"cwd": str(project), "session_id": "open-agent", "hook_event_name": "Stop"})["continue"] is False
    before = (sessions.session_dir(project, runtime, "open-agent") / "process.stderr.log").read_bytes()
    # Реальная правка продукта/коммит ожидаема при исполнении текущим агентом.
    (project / "result.md").write_text("research result")
    sessions.git(project, "add", "result.md")
    sessions.git(project, "commit", "-qm", "research result")
    assert cli.main(args) == 1
    assert sessions.load(project, runtime, "open-agent")["request_id"] == task["request_id"]
    assert (sessions.session_dir(project, runtime, "open-agent") / "process.stderr.log").read_bytes() == before
    (feature / "run-plan.yaml").write_text("foreign plan")
    assert cli.main(args) == 2
    assert len(list(sessions.session_dir(project, runtime, "open-agent").glob("*.execution-claim"))) == 1


def test_native_lifecycle_blocker_survives_resume_without_claim_or_process(project, monkeypatch):
    from ai_ops_kit.cli import project_session as cli
    from ai_ops_kit.providers import codex_native
    fixture_producer(project)
    task=sessions.begin(project,'codex','lifecycle-gap','Используй готовое исследование')
    diagnostic={'ready':False,'provider':codex_native.NAME,'hook_trust':'confirmed',
                'blocker_code':'native-lifecycle-unconfirmed','reason':'SessionStart не подтверждён до turn/start',
                'next_step':codex_native.NativeLifecycleUnavailable.next_step}
    monkeypatch.setattr(codex_native,'readiness',lambda root:dict(diagnostic))
    monkeypatch.chdir(project)
    args=['run','--autonomous','--runtime','codex','--session','lifecycle-gap']
    assert cli.main(args+['--signals','{"task_type":"quick","size":"small","risk":"low"}'])==1
    assert cli.main(args)==1  # signals/request переиспользуются, запуск не продвигается мимо blocker
    saved=sessions.load(project,'codex','lifecycle-gap')
    assert saved['request_id']==task['request_id'] and saved['status']=='pending'
    assert saved['provider_preparation']['blocker_code']==diagnostic['blocker_code']
    assert saved['provider_preparation']['hook_trust']=='confirmed'
    assert saved['next_step']==diagnostic['next_step'] and saved['provider_preparation']['signals']['size']=='small'
    context=hook('codex',{'cwd':str(project),'session_id':'lifecycle-gap','hook_event_name':'SessionStart'})
    assert diagnostic['next_step'] in context['hookSpecificOutput']['additionalContext']
    assert not list(sessions.session_dir(project,'codex','lifecycle-gap').glob('*.execution-claim'))
    assert not (project/'.ai/runtime/process-observed').exists()


