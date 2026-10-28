"""Проверка запрета запуска evidence-harness; benchmark здесь НЕ исполняется."""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def harness(tmp_path, monkeypatch):
    folder = Path(__file__).parents[2] / 'docs/evidence/1408-jsts-ast-pilot'
    monkeypatch.syspath_prepend(str(folder))
    spec = importlib.util.spec_from_file_location('ast1408_time_harness', folder / 'time_snapshot.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    snapshot = tmp_path / 'snapshot'
    snapshot.mkdir()
    source = snapshot / 'a.ts'
    source.write_text('export const value = 1;')
    comparison = tmp_path / 'comparison.json'
    digest = module.snapshot_hash(snapshot, ['a.ts'])
    comparison.write_text(json.dumps({'manifest': [{'path': 'a.ts',
        'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}],
        'snapshot_sha256_after': digest}))
    monkeypatch.setattr(module, 'version', lambda _name: 'test-double')
    @contextmanager
    def slot(*_args):
        yield
    monkeypatch.setattr(module.resources, 'host_slot', slot)
    monkeypatch.setattr(module.resources, 'heavy_processes', lambda: [])
    monkeypatch.setattr(module.resources, 'busy_heavy_processes', lambda _matched: [])
    def forbidden(*_args, **_kwargs):
        raise AssertionError('no graph build, warmup or timing is allowed in this test')
    monkeypatch.setattr(module.repo_graph, 'build_graph', forbidden)
    monkeypatch.setattr(module.time, 'perf_counter_ns', forbidden)
    args = argparse.Namespace(snapshot=snapshot, comparison=comparison, pairs=7, preflight_only=False)
    return module, args


def test_preflight_only_never_enters_benchmark_even_on_clean_host(harness, monkeypatch):
    module, args = harness
    args.preflight_only = True
    monkeypatch.setattr(module, 'noise', lambda: {'blocked_reasons': []})
    receipt = module.run(args)
    assert receipt['status'] == 'NOT_RUN'
    assert receipt['reason'] == 'preflight-only: benchmark not requested'
    assert receipt['samples'] == []
    assert receipt['slot']['released'] is True
    assert receipt['bindings']['snapshot_sha256_before'] == receipt['bindings']['snapshot_sha256_after']


def test_noisy_host_never_enters_benchmark(harness, monkeypatch):
    module, args = harness
    monkeypatch.setattr(module, 'noise', lambda: {'blocked_reasons': ['CPU noise']})
    receipt = module.run(args)
    assert receipt['status'] == 'NOT_RUN'
    assert receipt['reason'] == 'CPU noise'
    assert receipt['samples'] == []
    assert receipt['slot']['released'] is True


def test_busy_heavy_process_never_enters_noise_probe_or_benchmark(harness, monkeypatch):
    module, args = harness
    monkeypatch.setattr(module.resources, 'busy_heavy_processes', lambda _matched: [{'pid': 42}])
    def forbidden():
        raise AssertionError('busy resource must stop before noise probe')
    monkeypatch.setattr(module, 'noise', forbidden)
    receipt = module.run(args)
    assert receipt['status'] == 'NOT_RUN'
    assert receipt['reason'] == 'stock busy_heavy_processes reports other load'
    assert receipt['samples'] == []
    assert receipt['slot']['released'] is True


def test_unavailable_slot_never_probes_or_builds(harness, monkeypatch):
    module, args = harness
    @contextmanager
    def unavailable(*_args):
        raise module.resources.ResourceBlocked('slot held by another task')
        yield  # Contextmanager protocol; unreachable because acquisition failed.
    monkeypatch.setattr(module.resources, 'host_slot', unavailable)
    receipt = module.run(args)
    assert receipt['status'] == 'NOT_RUN'
    assert receipt['reason'] == 'slot held by another task'
    assert receipt['samples'] == []
    assert receipt['slot']['acquired'] is False
    assert receipt['slot']['released'] is False
