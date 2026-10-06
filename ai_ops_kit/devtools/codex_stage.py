"""Opt-in текстовая PRODUCT.specification через native Codex; гейты принадлежат киту."""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from ai_ops_kit.gates import gate_executor
from ai_ops_kit.devtools.codex_stage_hook import hook_config
from ai_ops_kit.providers.orchestrator import build_role_prompt
from ai_ops_kit.providers.skill_context import audit_events, context_response, digest

PKG = Path(__file__).resolve().parents[2]
HOOK_TRUST_NOTICE = ('`--dangerously-bypass-hook-trust` is enabled. '
                     'Enabled hooks may run without review for this invocation.')


def prepare(task, published, package_root):
    if not isinstance(task, str) or not task.strip():
        raise ValueError('задача пуста')
    if (not isinstance(published, dict) or set(published) != {'intake', 'requirements'}
            or any(not isinstance(v, str) or not v.strip() for v in published.values())):
        raise ValueError('требуются опубликованные intake и requirements')
    root = Path(package_root)
    workflows = yaml.safe_load((root / 'registry/workflows.yaml').read_text())['workflows']
    stage = next(s for s in workflows['PRODUCT']['stages'] if s['id'] == 'specification')
    if (stage.get('owner') != 'solution-architect' or stage.get('review_mode') != 'writer'
            or stage.get('writer') != stage.get('owner')):
        raise ValueError('контракт PRODUCT.specification изменился; нужна квалификация')
    output, receipt = context_response('codex', stage, root)
    agents = yaml.safe_load((root / 'registry/agents.yaml').read_text())['agents']
    prompt = build_role_prompt(stage, stage['owner'], {a['id']: a for a in agents},
                               task, published, skill_bodies={})
    prompt += '\nВерни только текст specification. Не вызывай инструменты и не читай файлы.\n'
    return prompt, output, receipt


def command(binary, model, control):
    args = [str(binary), 'exec', '--ignore-user-config', '--ephemeral',
            '--dangerously-bypass-hook-trust', '--skip-git-repo-check',
            '--sandbox', 'read-only', '--json', '--model', model,
            '--output-last-message', str(control / 'answer.txt')]
    for flag in ('shell_tool', 'multi_agent', 'apps', 'remote_plugin', 'memories'):
        args += ['--disable', flag]
    for setting in ('web_search="disabled"', 'approval_policy="never"',
                    'shell_environment_policy.inherit="none"', 'model_reasoning_effort="low"'):
        args += ['-c', setting]
    return args + ['-']


def launch(prompt, output, binary, model, auth_file, timeout, runner):
    with tempfile.TemporaryDirectory(prefix='aiops-codex-stage-') as temp:
        base = Path(temp)
        control, workspace, home = (base / name for name in ('control', 'workspace', 'home'))
        for path in (control, workspace, home):
            path.mkdir(mode=0o700)
        shutil.copyfile(auth_file, home / 'auth.json')
        (home / 'auth.json').chmod(0o600)
        (control / 'context.json').write_text(json.dumps(output, ensure_ascii=False))
        (control / 'hook.py').write_text(
            'import sys\nsys.path.insert(0, sys.argv.pop(1))\n'
            'from ai_ops_kit.devtools.codex_stage_hook import main\nmain()\n')
        (home / 'hooks.json').write_text(json.dumps(hook_config(control, PKG)))
        # Документированный state root только для дочернего native процесса.
        env = {k: v for k, v in os.environ.items()
               if k in ('PATH', 'HOME', 'TMPDIR', 'SYSTEMROOT', 'LANG')}
        env['CODEX_HOME'] = str(home)
        proc = runner(command(binary, model, control), input=prompt, cwd=workspace,
                      env=env, capture_output=True, text=True, timeout=timeout)
        return inspect_result(proc, control, workspace, output)


def inspect_result(proc, control, workspace, output):
    if proc.returncode:
        raise ValueError('native Codex завершился с ошибкой; результат не опубликован')
    events = [json.loads(line) for line in (control / 'events.jsonl').read_text().splitlines()]
    audit = audit_events('codex', events)
    ack = json.loads((control / 'ack.json').read_text())
    if not isinstance(ack, dict) or ack.get('output_sha256') != digest(output) or audit['gaps']:
        raise ValueError('доставка hook или native audit не подтверждены')
    if any(e.get('hook_event_name') != 'SessionStart' for e in events):
        raise ValueError('text-only стадия попыталась вызвать инструмент')
    stream = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    if any(not isinstance(e, dict) or ('item' in e and not isinstance(e['item'], dict)) for e in stream):
        raise ValueError('native stream имеет неверную форму')
    allowed = {'thread.started', 'turn.started', 'item.started', 'item.updated',
               'item.completed', 'turn.completed'}
    if (not stream or not any(e.get('type') == 'turn.completed' for e in stream)
            or any(e.get('type') not in allowed for e in stream)
            or any(not accepted_item(e.get('item', {}))
                   for e in stream if e.get('type', '').startswith('item.'))):
        raise ValueError('native stream содержит отказ, неизвестное событие или инструмент')
    sessions = [e.get('thread_id') for e in stream if e.get('type') == 'thread.started']
    if sessions != [audit['records'][0]['session_id']]:
        raise ValueError('native stream и hook принадлежат разным сессиям')
    if any(workspace.iterdir()):
        raise ValueError('native workspace изменён вопреки text-only контракту')
    answer_file = control / 'answer.txt'
    if answer_file.is_symlink():
        raise ValueError('native ответ не может быть симлинком')
    answer = answer_file.read_text(encoding='utf-8')
    if not answer.strip():
        raise ValueError('native ответ пуст')
    return answer, audit, [e['usage'] for e in stream if 'usage' in e]


def accepted_item(item):
    return (item.get('type') in ('agent_message', 'reasoning')
            or (item.get('type') == 'error' and item.get('message') == HOOK_TRUST_NOTICE))


def run_specification(task, published, output_dir, *, model, binary='codex', auth_file=None,
                      timeout=120, package_root=PKG, runner=subprocess.run):
    """Новая директория результата обязательна; ни resume, ни workflow completion не заявляются."""
    if (not isinstance(model, str) or not model.strip() or isinstance(timeout, bool)
            or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError('требуются model и положительный конечный timeout')
    prompt, context, receipt = prepare(task, published, package_root)
    destination = Path(output_dir)
    if destination.exists():
        raise ValueError('директория результата уже существует; перезапись запрещена')
    auth = Path(auth_file) if auth_file else Path.home() / '.codex/auth.json'
    if not auth.is_file():
        raise ValueError('native auth.json не найден; API-key fallback запрещён')
    answer, audit, usage = launch(prompt, context, binary, model, auth, timeout, runner)
    gates = gate_executor.evaluate('PRODUCT', {})
    report = {'scope': 'bounded-native-stage', 'workflow': 'PRODUCT', 'stage': 'specification',
              'stage_status': 'artifact_created', 'workflow_status': 'blocked',
              'context_receipt': receipt, 'audit': audit, 'usage': usage,
              'model': model, 'gate_report': 'GateReport.json',
              'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
              'provenance': {'kind': 'REASONING', 'actor': 'solution-architect',
                             'sha256': hashlib.sha256(answer.encode()).hexdigest()}}
    publish(destination, answer, report, gates)
    return report


def publish(destination, answer, report, gates):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.codex-stage-', dir=destination.parent) as temp:
        prepared = Path(temp)
        (prepared / 'stage-specification.md').write_text(answer, encoding='utf-8')
        for name, value in (('NativeStageReport.json', report), ('GateReport.json', gates)):
            (prepared / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        # Резервируем только НОВОЕ имя: конкурирующий результат не перезаписывается.
        destination.mkdir(mode=0o700)
        try:
            os.replace(prepared, destination)  # единый комплект вместо пустого собственного placeholder
        except OSError:
            destination.rmdir()
            raise
