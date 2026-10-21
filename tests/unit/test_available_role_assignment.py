"""Назначение API-роли использует допуск и локальные предпосылки, не online health."""
from __future__ import annotations

import copy
import json

import pytest

from ai_ops_kit.engine import ai_ops_run, ai_ops_run_lifecycle as lifecycle, ai_ops_run_exec
from ai_ops_kit.engine.run_context import RunContext
from ai_ops_kit.providers import model_router as router, provider_endpoints as endpoints, orchestrator


def _registry():
    roles = {'roles': {r: {'preferred_class': 'balanced'} for r in router.ALL_ROLES},
             'role_constraints': {'integration_judge': {'must_differ_from': 'implementation'}}}
    specs = [('cheap', 'deepseek', 1), ('writer', 'qwen', 2), ('judge', 'kimi', 3)]
    models = {mid: {'classes': ['balanced'], 'provider': provider, 'cost_class': 'low'}
              for mid, provider, _ in specs}
    quals = [{'role': role, 'status': 'qualified', 'model_id': mid, 'provider': provider,
              'revision': 'r1', 'corpus_version': 'fixture',
              'metrics': {'false_green': 0, 'success_rate': cost / 4},
              'economics': {'total_cost_per_verified_change': cost, 'currency': 'USD'}}
             for role in router.ALL_ROLES for mid, provider, cost in specs
             if role == 'implementation' or mid == 'judge']
    return roles, quals, models


def _ctx(root, *, model=None, provider='openai-compatible'):
    return RunContext.from_run_args(task_text='bounded task', signals={'task_type': 'QUICK', 'risk': 'low'},
        child_root=root, features_dir=root / 'features', feature='work', provider_name=provider,
        model=model, runtime='pipeline', sandbox=False, baseline_diff=False, require_fix=False,
        author=False, review=False, open_pr=False, write_scope=None, max_steps=4, base=None)


def _runtime(monkeypatch, tmp_path, *, keys=('qwen', 'kimi'), trust=True):
    cfg = _registry()
    monkeypatch.setattr(router, '_load', lambda: copy.deepcopy(cfg))
    for item in endpoints.PROVIDER_ENDPOINTS.values():
        monkeypatch.delenv(item['key_env'], raising=False)
        if item.get('key_env_fallback'):
            monkeypatch.delenv(item['key_env_fallback'], raising=False)
    for provider in keys:
        monkeypatch.setenv(endpoints.PROVIDER_ENDPOINTS[provider]['key_env'], 'fixture-not-a-real-key')
    monkeypatch.setattr(ai_ops_run, '_load_klp_by_env', lambda *a: {})
    trusted, built, calls = [], [], []

    def check(provider, *args):
        trusted.append(provider)
        return {'ready': trust, 'reason': 'fixture trust denied' if not trust else None,
                'preflight': {'ready': trust, 'blocks': [] if trust else ['fixture trust denied']}}

    def make(model, base_url, key_env):
        built.append((model, base_url, key_env))
        def invoke(prompt):
            calls.append(model)
            (tmp_path / 'actual-provider-call').write_text(model)
            return json.dumps({'done': True, 'summary': 'controlled offline callback'})
        return invoke

    monkeypatch.setattr(ai_ops_run, '_provider_trust', check)
    monkeypatch.setattr(orchestrator, 'make_openai_provider', make)
    monkeypatch.setattr(orchestrator, 'make_provider', lambda *a, **k: pytest.fail('implicit passthrough reached'))
    return _ctx(tmp_path), trusted, built, calls


def test_runtime_selects_available_qualified_candidate_and_invokes_its_bound_provider(tmp_path, monkeypatch):
    ctx, trusted, built, calls = _runtime(monkeypatch, tmp_path)
    assert lifecycle._resolve_models(ctx) is None
    assert ctx.writer_model == 'writer', 'missing cheap credential must not hide available qualified writer'
    assert ctx.rev_model == 'judge' and ctx.model_resolution['reviewer']['independent_by_model']
    assert 'deepseek' not in trusted
    ai_ops_run_exec._build_run_proposers(ctx, None, None, None)
    action = ctx.prop('controlled bounded task')
    assert action['done'] is True
    assert calls == ['writer'] and (tmp_path / 'actual-provider-call').read_text() == 'writer'
    assert built[0][2] == 'QWEN_API_KEY'
    assert ctx.model_resolution['provider_availability']['online_health'] is None
    assert 'fixture-not-a-real-key' not in json.dumps(ctx.model_resolution)


def test_runtime_no_available_candidate_blocks_before_any_provider_callback(tmp_path, monkeypatch):
    ctx, trusted, built, calls = _runtime(monkeypatch, tmp_path, keys=())
    result = lifecycle._resolve_models(ctx)
    assert result and result['status'] == 'blocked-preflight'
    assert result['ready_for_pr'] is False
    assert built == calls == trusted == []
    assert not (tmp_path / 'actual-provider-call').exists()


def test_runtime_selected_primary_trust_denial_is_not_bypassed(tmp_path, monkeypatch):
    ctx, trusted, built, calls = _runtime(monkeypatch, tmp_path, trust=False)
    result = lifecycle._resolve_models(ctx)
    assert result and result['status'] == 'blocked-preflight'
    assert ctx.writer_model == 'writer'
    assert calls == [] and not (tmp_path / 'actual-provider-call').exists()
    assert trusted[0] == 'qwen'


def test_runtime_assignment_error_blocks_without_passthrough(tmp_path, monkeypatch):
    ctx, trusted, built, calls = _runtime(monkeypatch, tmp_path)
    def broken(*a, **k):
        raise ValueError('fixture malformed registry')
    monkeypatch.setattr(router, 'plan_run', broken)
    result = lifecycle._resolve_models(ctx)
    assert result and result['status'] == 'blocked-preflight'
    assert built == calls == trusted == []


def test_plan_filters_fallback_ladder_and_preserves_independence():
    rc, qs, ms = _registry()
    before = copy.deepcopy((rc, qs, ms))
    plan = router.plan_run(rc, qs, ms, available_providers={'qwen', 'kimi'})
    assert plan['implementation']['model_id'] == 'writer'
    assert plan['integration_judge']['model_id'] == 'judge'
    assert plan['independence']['independent'] is True
    for role in router.ALL_ROLES:
        row = plan[role]
        assert row['provider'] in {'qwen', 'kimi'}
        assert not row.get('fallback') or row['fallback']['provider'] in {'qwen', 'kimi'}
        assert all(r['provider'] in {'qwen', 'kimi'} for r in row['escalation_ladder'])
    assert (rc, qs, ms) == before


@pytest.mark.parametrize('available', [set(), {'unknown'}])
def test_plan_empty_or_unknown_provider_set_never_resolves(available):
    plan = router.plan_run(*_registry(), available_providers=available)
    assert all(not plan[r]['resolved'] for r in router.ALL_ROLES)


def test_availability_never_promotes_conditional_or_false_green_strict_judge():
    rc, qs, ms = _registry()
    for q in qs:
        if q['provider'] == 'qwen':
            q['status'] = 'conditional'
        elif q['provider'] == 'kimi':
            q['metrics']['false_green'] = 1
    plan = router.plan_run(rc, qs, ms, available_providers={'qwen', 'kimi'})
    assert not plan['security_review']['resolved'] and not plan['integration_judge']['resolved']
    assert plan['implementation']['model_id'] == 'writer'


def test_pure_plan_without_filter_and_explicit_model_keep_existing_selection(tmp_path, monkeypatch):
    assert router.plan_run(*_registry())['implementation']['model_id'] == 'cheap'
    ctx, trusted, built, calls = _runtime(monkeypatch, tmp_path, keys=())
    ctx.model = 'explicit-model'
    assert lifecycle._resolve_models(ctx) is None
    assert ctx.writer_model == 'explicit-model' and ctx.writer_prov is None
    assert ctx.model_resolution['mode'] == 'explicit-override'
    assert built == calls == trusted == []


def test_writer_reresolution_cannot_reintroduce_excluded_provider():
    rc, qs, ms = _registry()
    writer = next(q for q in qs if q['role'] == 'implementation' and q['model_id'] == 'writer')
    qs = [q for q in qs if q['role'] == 'implementation']
    qs += [dict(copy.deepcopy(writer), role=r) for r in router.ALL_ROLES if r != 'implementation']
    plan = router.plan_run(rc, qs, ms, available_providers={'qwen', 'kimi'})
    assert plan['implementation']['model_id'] == 'judge'
    assert plan['integration_judge']['model_id'] == 'writer'
    assert plan['independence']['independent'] is True


def test_key_loss_between_selection_and_application_blocks(tmp_path, monkeypatch):
    ctx, trusted, built, calls = _runtime(monkeypatch, tmp_path)
    original, seen = endpoints.key_available, {}
    def available(provider):
        seen[provider] = seen.get(provider, 0) + 1
        return original(provider) and not (provider == 'qwen' and seen[provider] > 1)
    monkeypatch.setattr(endpoints, 'key_available', available)
    result = lifecycle._resolve_models(ctx)
    assert result and result['status'] == 'blocked-preflight'
    assert built == calls == trusted == []


def test_single_available_writer_never_becomes_independent_judge(tmp_path, monkeypatch):
    ctx, trusted, built, calls = _runtime(monkeypatch, tmp_path, keys=('qwen',))
    assert lifecycle._resolve_models(ctx) is None
    assert ctx.writer_model == 'writer'
    assert ctx.model_resolution['reviewer']['independent_by_model'] is False
    assert ctx.sec_qualified is False
    assert calls == []


def test_full_run_uses_selected_provider_for_real_broker_write_and_commit(tmp_path, monkeypatch):
    from test_ai_ops_run_model_routing import _git_repo
    from ai_ops_kit.shared import gitio
    _git_repo(tmp_path)
    _, trusted, built, _ = _runtime(monkeypatch, tmp_path)
    calls, steps = [], {}
    def make(model, base_url, key_env):
        built.append((model, base_url, key_env))
        def invoke(prompt):
            calls.append(model)
            steps[model] = steps.get(model, 0) + 1
            return json.dumps({'op': 'write', 'path': 'src/assigned.py', 'content': 'ASSIGNED = True\n'}
                              if steps[model] == 1 else {'done': True})
        return invoke
    monkeypatch.setattr(orchestrator, 'make_openai_provider', make)
    result = ai_ops_run.run('add assigned marker', {'task_type': 'QUICK', 'size': 'small', 'risk': 'low',
        'affected_areas': ['src']}, tmp_path, engine='pipeline', provider_name='openai-compatible',
        model=None, feature='assigned', execute=True, author=False, review=False, install_deps=False,
        budget={'max_model_calls': 2})
    assert calls == ['writer', 'writer'], 'both real proposer callbacks use selected model, not default passthrough'
    sha = result['commit']['sha']
    assert sha and gitio.git(tmp_path, 'show', f'{sha}:src/assigned.py')[1] == 'ASSIGNED = True'
    assert result['model_resolution']['writer']['provider'] == 'qwen'
    assert result['model_resolution']['model_attempts'][0]['model'] == 'writer'
    assert result['budget']['model_calls'] == 2 and result['budget']['remaining_calls'] == 0
    assert 'deepseek' not in trusted, 'unavailable provider is never consulted or invoked'


def test_full_run_without_available_assignment_stops_before_worktree_or_provider(tmp_path, monkeypatch):
    from test_ai_ops_run_model_routing import _git_repo
    from ai_ops_kit.shared import gitio
    _git_repo(tmp_path)
    base = gitio.git(tmp_path, 'rev-parse', 'HEAD')[1]
    _, trusted, built, calls = _runtime(monkeypatch, tmp_path, keys=())
    result = ai_ops_run.run('bounded task', {'task_type': 'QUICK', 'size': 'small', 'risk': 'low'},
        tmp_path, engine='pipeline', provider_name='openai-compatible', model=None, feature='blocked', execute=True)
    assert result['status'] == 'blocked-preflight' and result['ready_for_pr'] is False
    assert built == calls == trusted == []
    assert not (tmp_path / '.ai/worktrees').exists()
    assert gitio.git(tmp_path, 'rev-parse', 'HEAD')[1] == base
