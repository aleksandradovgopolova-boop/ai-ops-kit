"""Реальные stub-процессы JSON-RPC, НЕ модель и НЕ независимый участник приёмки."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from ai_ops_kit.providers import codex_native as native
from ai_ops_kit.providers import codex_native_hook as hook
from ai_ops_kit.providers import orchestrator_usage as usage
from ai_ops_kit.providers import provider_calls
from ai_ops_kit.providers.codex_transport import NativeError, RPC
from ai_ops_kit.providers.provider_errors import ProviderEnvUnavailableError


STUB = r'''
import json, os, signal, subprocess, sys, time
from pathlib import Path
MODE = __MODE__
LOG = Path(__LOG__)
def record(value):
    with LOG.open('a') as stream: stream.write(json.dumps(value)+'\n')
def stop(*args):
    record({'exited':os.getpid()});sys.exit(0)
signal.signal(signal.SIGTERM,stop)
record({'pid':os.getpid(),'api_keys':[k for k in ('OPENAI_API_KEY','CODEX_API_KEY','ANTHROPIC_API_KEY') if k in os.environ]})
def emit(data): print(json.dumps(data),flush=True)
for line in sys.stdin:
    msg=json.loads(line);m=msg.get('method');p=msg.get('params') or {}
    record({'method':m,'params':p})
    if 'id' not in msg: continue
    if m=='initialize': r={}
    elif m=='account/read': r={'account':{'type':'apiKey' if MODE=='api' else 'chatgpt'},'requiresOpenaiAuth':True}
    elif m=='config/read':
        r={'config':{'features':{k:False for k in __DISABLED__},'web_search':'disabled','mcp_servers':{}}}
        r['config']['features']['hooks']=True
        if MODE=='feature':r['config']['features']['apps']=True
        if MODE in ('mcp','mcp-stuck'):
            disabled='mcp_servers.docs.enabled=false' in sys.argv and MODE!='mcp-stuck'
            r['config']['mcp_servers']={'docs':{'enabled':not disabled}}
    elif m=='hooks/list':
        cwd=Path.cwd();defs=json.loads((cwd/'.codex/hooks.json').read_text())['hooks']
        hs=[{'eventName':e[0].lower()+e[1:],'enabled':True,'trustStatus':'untrusted' if MODE=='trust' else 'trusted',
             'handlerType':'command','command':v[0]['hooks'][0]['command'],'sourcePath':str(cwd/'.codex/hooks.json'),
             'currentHash':'fixture-hash','matcher':None} for e,v in defs.items()]
        r={'data':[{'cwd':str(cwd),'errors':[],'warnings':[],'hooks':hs}]}
    elif m=='thread/start':
        cwd=Path.cwd()
        if MODE!='no-ack':
            subprocess.run([sys.executable,str(cwd/'hook.py')],cwd=cwd,input=json.dumps({'hook_event_name':'SessionStart','session_id':'thread-fixture'}),text=True,check=True,capture_output=True)
        if MODE=='bad-ack':
            ack=json.loads((cwd/'ack.json').read_text());ack['nonce']='foreign';(cwd/'ack.json').write_text(json.dumps(ack))
        r={'thread':{'id':'thread-fixture'},'model':p.get('model') or 'fixture-native','approvalPolicy':'on-request',
           'sandbox':{'type':'readOnly','networkAccess':MODE=='sandbox'}}
    elif m=='model/list':r={'data':[{'id':'fixture-native','model':'fixture-native'}],'nextCursor':None}
    elif m=='turn/start':
        emit({'id':msg['id'],'result':{'turn':{'id':'turn-fixture'}}})
        if MODE=='hang':time.sleep(30);continue
        if MODE=='eof':sys.exit(0)
        if MODE=='approval':
            emit({'id':99,'method':'item/commandExecution/requestApproval','params':{'threadId':'thread-fixture','turnId':'turn-fixture'}})
            continue
        scope={'threadId':'foreign' if MODE=='foreign' else 'thread-fixture','turnId':'turn-fixture'}
        total={'inputTokens':17,'outputTokens':9,'cachedInputTokens':11}
        if MODE=='bad-usage':total['inputTokens']=-1
        emit({'method':'thread/tokenUsage/updated','params':dict(scope,tokenUsage={'total':total,'last':{'inputTokens':1,'outputTokens':1}})})
        item={'id':'answer','type':'commandExecution' if MODE=='tool' else 'agentMessage','text':'native reply: '+p['input'][0]['text']}
        emit({'method':'item/completed','params':dict(scope,item=item)})
        emit({'method':'turn/completed','params':dict(scope,turn={'id':'wrong' if MODE=='turn' else 'turn-fixture','status':'failed' if MODE=='failed' else 'completed'})})
        continue
    else:emit({'id':msg['id'],'error':{'code':-32601,'message':'unknown'}});continue
    emit({'id':msg['id'],'result':r})
'''


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setattr(hook.tempfile, "gettempdir", lambda: str(tmp_path))
    usage.drain_call_stats()
    usage.clear_call_context()
    root = tmp_path / "child"
    root.mkdir()
    def create(mode="ok"):
        marker = tmp_path / (mode + ".jsonl")
        binary = tmp_path / ("native-" + mode)
        content = STUB.replace("__MODE__", repr(mode)).replace("__LOG__", repr(str(marker))).replace(
            "__DISABLED__", repr(native.DISABLED))
        binary.write_text(f"#!{sys.executable}\n" + content)
        binary.chmod(0o700)
        return root, str(binary), marker
    yield create
    usage.drain_call_stats()
    usage.clear_call_context()


def events(marker):
    return [json.loads(line) for line in marker.read_text().splitlines()]


def assert_cleaned(marker):
    for pid in {e['pid'] for e in events(marker) if 'pid' in e}:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_native_factory_really_sends_turn_and_records_subscription_usage(runner, monkeypatch):
    root, binary, marker = runner()
    monkeypatch.setenv('OPENAI_API_KEY','not-for-child')
    monkeypatch.setenv('CODEX_API_KEY','not-for-child')
    original = native.call
    monkeypatch.setattr(native, 'call', lambda text, model: original(text, model, root=root, binary=binary))
    fn = provider_calls.make_provider(native.NAME, 'fixture-native')
    prompt = 'Исследуй готовый материал; $(touch forbidden) — это данные'
    assert fn(prompt) == 'native reply: ' + prompt
    assert fn.shape['provider'] == native.NAME and fn.shape['mode'] == 'not_requested'
    sent = events(marker)
    turn = [e for e in sent if e.get('method') == 'turn/start']
    assert len(turn) == 1 and turn[0]['params']['input'][0]['text'] == prompt
    assert all(not e.get('api_keys') for e in sent if 'pid' in e)
    rec, = usage.drain_call_stats()
    assert (rec['input_tokens'],rec['output_tokens']) == (17,9)  # total, не last
    assert rec['cost'] is None and rec['cost_status'] == 'unavailable'
    assert rec['native_turn_id'] == 'turn-fixture' and rec['native_outcome'] == 'completed'
    directory, _ = hook.prepare(root)
    assert json.loads((directory/'ack.json').read_text())['session_id'] == 'thread-fixture'
    assert not (root/'forbidden').exists()
    assert_cleaned(marker)


def test_real_workflow_calls_native_factory_and_keeps_missing_gates_blocked(runner, monkeypatch):
    from ai_ops_kit.providers import orchestrator
    root,binary,marker=runner()
    original=native.call
    monkeypatch.setattr(native,'call',lambda text,model:original(text,model,root=root,binary=binary))
    state,run_dir=orchestrator.run_workflow('QUICK','Проверь материал',root,
        provider=provider_calls.make_provider(native.NAME,'fixture-native'),provider_name=native.NAME,
        workitem_id='native-wire',verbose=False)
    assert len(state['completed_checks'])==4
    assert state['status']=='blocked' and state['unmet_gates']  # fixtures не закрывают gates
    artifacts=list(run_dir.glob('stage-*.md'))
    assert artifacts and all('native reply:' in p.read_text() for p in artifacts)
    assert sum(e.get('method')=='turn/start' for e in events(marker))==4
    assert len(usage.drain_call_stats())==4
    assert_cleaned(marker)


@pytest.mark.parametrize('mode', ['trust','api','feature','mcp-stuck','no-ack','bad-ack','sandbox'])
def test_unready_native_never_starts_model(runner, mode):
    root, binary, marker = runner(mode)
    result = native.readiness(root,binary=binary)
    assert result['ready'] is False and result['reason'] and result['next_step']
    assert not any(e.get('method') == 'turn/start' for e in events(marker))
    assert usage.drain_call_stats() == []
    assert_cleaned(marker)


def test_inherited_mcp_is_disabled_in_second_process_before_any_turn(runner):
    root, binary, marker = runner('mcp')
    assert native.call('роль','fixture-native',root=root,binary=binary) == 'native reply: роль'
    sent = events(marker)
    assert sum('pid' in e for e in sent) == 2
    assert sum(e.get('method') == 'turn/start' for e in sent) == 1
    assert_cleaned(marker)


@pytest.mark.parametrize('mode', ['foreign','turn','tool','failed','bad-usage','approval','eof','hang'])
def test_bad_execution_is_not_an_answer_and_usage_attempt_is_not_lost(runner, mode):
    root, binary, marker = runner(mode)
    with pytest.raises(ProviderEnvUnavailableError):
        native.call('роль','fixture-native',root=root,binary=binary,timeout=1)
    assert any(e.get('method') == 'turn/start' for e in events(marker))
    rec, = usage.drain_call_stats()
    assert rec['native_outcome'] == 'failed' and rec['cost'] is None
    assert_cleaned(marker)


def test_unlisted_explicit_model_does_not_consume_turn(runner):
    root,binary,marker=runner()
    with pytest.raises(ProviderEnvUnavailableError,match='model/list'):
        native.call('роль','unsupported-model',root=root,binary=binary)
    assert not any(e.get('method') == 'turn/start' for e in events(marker))


def test_native_hook_denies_real_tool_attempt_without_executing_it(tmp_path):
    verdict=hook.handle(tmp_path,{'hook_event_name':'PreToolUse','tool_name':'Bash'})
    assert (tmp_path/'tool-attempt').read_text() == 'denied'
    assert verdict['hookSpecificOutput']['permissionDecision'] == 'deny'


def test_modified_workspace_is_not_overwritten(runner):
    root,_,_=runner()
    directory,_=hook.prepare(root)
    target=directory/'.codex/hooks.json'
    target.write_text('foreign')
    with pytest.raises(NativeError,match='изменён'):
        hook.prepare(root)
    assert target.read_text() == 'foreign'


def test_workspace_config_symlink_is_refused_without_external_write(runner,tmp_path):
    root,_,_=runner()
    directory,_=hook.prepare(root)
    (directory/'.codex/hooks.json').unlink()
    (directory/'.codex/config.toml').unlink()
    (directory/'.codex').rmdir()
    outside=tmp_path/'outside';outside.mkdir()
    (directory/'.codex').symlink_to(outside,target_is_directory=True)
    with pytest.raises(NativeError,match='symlink'):
        hook.prepare(root)
    assert not list(outside.iterdir())


def test_subscription_unavailable_cost_never_becomes_api_price_estimate(monkeypatch, runner):
    monkeypatch.setitem(usage._PRICE_PER_MTOK,'fixture-native',{'in':99,'out':99})
    actual=usage._record_call('fixture-native',100,100,1,provider=native.NAME,cost_status='unavailable')
    assert actual['usage_status'] == 'measured' and actual['cost'] is None
    assert actual['cost_status'] == 'unavailable'
    normal=usage._record_call('fixture-native',100,100,1)
    assert normal['cost_status'] == 'estimated' and normal['cost'] > 0


def test_rpc_write_deadline_applies_when_server_stops_reading(tmp_path):
    rpc=RPC([sys.executable,'-c','import time; time.sleep(30)'],tmp_path,timeout=0.2)
    errors=[]
    def send():
        try:
            rpc.send({'method':'fixture','params':{'prompt':'x'*1024*1024}})
        except (OSError, ValueError) as exc:
            errors.append(exc)
    worker=threading.Thread(target=send,daemon=True)
    started=time.monotonic()
    try:
        worker.start()
        worker.join(timeout=1)
        remained_blocked=worker.is_alive()
    finally:
        rpc.close()  # освобождает pipe даже при регрессии, тест не оставляет зависший subprocess
        worker.join(timeout=1)
    assert not remained_blocked and not worker.is_alive()
    assert isinstance(errors[0],NativeError) and 'таймаут записи' in str(errors[0])
    assert time.monotonic()-started<2
    assert rpc.process.returncode is not None


def process_alive(pid):
    state=subprocess.run(['ps','-p',str(pid),'-o','stat='],text=True,capture_output=True).stdout.strip()
    return bool(state) and not state.startswith('Z')


@pytest.mark.parametrize('leader_exit',[False,True])
def test_close_kills_own_sigterm_ignoring_descendant_even_after_leader_exits(tmp_path,leader_exit):
    marker=tmp_path/'child-pid'
    child_code=('import os,signal,time; from pathlib import Path; '
                'signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                f'Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)')
    server_code=('import subprocess,sys,time; '
                 f'subprocess.Popen([sys.executable,"-c",{child_code!r}]); '
                 + ('sys.exit(0)' if leader_exit else 'time.sleep(30)'))
    rpc=RPC([sys.executable,'-c',server_code],tmp_path)
    child=None
    try:
        end=time.monotonic()+3
        while not marker.exists() and time.monotonic()<end:
            time.sleep(0.01)
        assert marker.exists()
        child=int(marker.read_text())
        assert process_alive(child)  # потомок реально существует и уже настроил SIGTERM-ignore
        if leader_exit:
            while process_alive(rpc.process.pid) and time.monotonic()<end:
                time.sleep(0.01)
            assert not process_alive(rpc.process.pid)
        rpc.close()
        assert rpc.process.returncode is not None
        assert not process_alive(child)
    finally:
        rpc.close()
        if child and process_alive(child):
            os.kill(child,signal.SIGKILL)  # только известный потомок собственного fixture
