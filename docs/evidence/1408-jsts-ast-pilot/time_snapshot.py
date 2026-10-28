"""Ограниченное парное измерение build_graph с fail-closed допуском ресурса.

Никаких consumer-команд, новых snapshots, установки пакетов или остановки процессов.
Порог шума задан ДО измерений: последние два top-отсчёта <=15% aggregate CPU,
load1/logicalcpu <=0.5, memory_pressure free >=20%, без swap I/O, >=10 GiB диска.
Это консервативное условие данного пилота, не общая политика host-slot Kit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time

from ai_ops_kit.context import repo_graph
from ai_ops_kit.devtools import host_resource_cli as resources
from compare_snapshot import snapshot_hash


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError(f'{argv[0]} exited {result.returncode}: {result.stderr.strip()}')
    return result.stdout


def noise():
    cpu_count = int(command(['/usr/sbin/sysctl', '-n', 'hw.logicalcpu']).strip())
    pressure = command(['/usr/bin/memory_pressure', '-Q'])
    swap = command(['/usr/sbin/sysctl', 'vm.swapusage'])
    top = command(['/usr/bin/top', '-l', '3', '-s', '1', '-n', '1', '-stats', 'pid,cpu,mem'])
    cpu = [float(user) + float(system) for user, system in re.findall(
        r'CPU usage: ([\d.]+)% user, ([\d.]+)% sys,', top)][-2:]
    free = re.search(r'System-wide memory free percentage:\s*(\d+)%', pressure)
    swapio = []
    for match in re.finditer(r'\d+\((\d+)\) swapins, \d+\((\d+)\) swapouts', top):
        swapio.append((int(match.group(1)), int(match.group(2))))
    load = os.getloadavg()
    disk_free = shutil.disk_usage(Path.cwd()).free
    reasons = []
    if len(cpu) != 2 or max(cpu) > 15:
        reasons.append('aggregate CPU is unmeasured or above 15%')
    if load[0] / cpu_count > 0.5:
        reasons.append('load1/logicalcpu above 0.5')
    if free is None or int(free.group(1)) < 20:
        reasons.append('memory pressure unmeasured or free percentage below 20%')
    if len(swapio) < 3 or any(ins or outs for ins, outs in swapio[-2:]):
        reasons.append('swap activity unmeasured or nonzero')
    if disk_free < 10 * 1024**3:
        reasons.append('less than 10 GiB disk free')
    return {'at_utc': datetime.now(timezone.utc).isoformat(), 'logicalcpu': cpu_count,
            'load_average': load, 'aggregate_cpu_percent_last_two': cpu,
            'memory_pressure': pressure, 'swap': swap, 'swap_io': swapio,
            'disk_free_bytes': disk_free, 'top': top, 'blocked_reasons': reasons}


def graph_digest(graph):
    return hashlib.sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest()


def validate_graph(graph, backend, comparison):
    if graph['file_count'] != comparison['source']['selected_files']:
        raise RuntimeError('file_count differs from pinned comparison')
    edge_key = 'regex_edges' if backend == 'regex' else 'ast_edges'
    for record in comparison['records']:
        path = record['path']
        if graph['import_edges'][path] != record[edge_key]:
            raise RuntimeError(f'import edges differ: {path}')
        if backend != 'regex' and graph['js_analysis'][path] != record['analysis']:
            raise RuntimeError(f'AST diagnostics differ: {path}')


def run(args):
    comparison = json.loads(args.comparison.read_text())
    paths = [entry['path'] for entry in comparison['manifest']]
    for entry in comparison['manifest']:
        target = args.snapshot / entry['path']
        if target.is_symlink() or sha(target) != entry['sha256']:
            raise RuntimeError('snapshot entry mismatch')
    before = snapshot_hash(args.snapshot, paths)
    if before != comparison['snapshot_sha256_after']:
        raise RuntimeError('snapshot digest mismatch')
    receipt = {'status': 'NOT_RUN', 'at_utc': datetime.now(timezone.utc).isoformat(),
               'command': sys.argv, 'environment': {'python': sys.version,
                   'executable': sys.executable, 'platform': platform.platform(),
                   'packages': {p: version(p) for p in ('tree-sitter', 'tree-sitter-javascript',
                                                       'tree-sitter-typescript')}},
               'bindings': {'engine_sha256': sha(Path(repo_graph.__file__)),
                            'harness_sha256': sha(Path(__file__)),
                            'comparison_sha256': sha(args.comparison), 'snapshot_sha256_before': before},
               'protocol': {'pairs': args.pairs, 'order': 'AB,BA alternating; A=regex B=tree-sitter',
                            'warmup_pairs': 1, 'timed': 'build_graph: file I/O, parse, graph, per-build parser init',
                            'excluded': 'process start, initial imports (warmup), input hashing, validation, noise probes',
                            'cache': 'warm process and OS file cache; no cache purge or cold-start claim',
                            'thresholds': {'aggregate_cpu_max_percent': 15, 'load_per_logicalcpu_max': 0.5,
                                           'memory_pressure_free_min_percent': 20, 'swap_io_max': 0,
                                           'disk_free_min_gib': 10}},
               'slot': {'path': str(resources.DEFAULT_LOCK), 'owner': 'p0-1408-jsts-ast-pilot',
                        'acquired': False, 'released': False}, 'observations': [], 'samples': []}
    expected = {}
    try:
        # Штатный путь и nonblocking flock. Чужой lock не удаляется и не освобождается.
        with resources.host_slot('p0-1408-jsts-ast-pilot', 'local'):
            receipt['slot']['acquired'] = True
            matched = resources.heavy_processes()
            busy = resources.busy_heavy_processes(matched)
            receipt['heavy_processes'] = {'matched': matched, 'busy': busy}
            if busy:
                raise resources.ResourceBlocked('stock busy_heavy_processes reports other load')
            initial = noise()
            receipt['observations'].append(initial)
            if initial['blocked_reasons']:
                raise resources.ResourceBlocked('; '.join(initial['blocked_reasons']))
            if args.preflight_only:
                receipt['reason'] = 'preflight-only: benchmark not requested'
                return receipt
            for backend in ('regex', 'tree-sitter'):
                graph = repo_graph.build_graph(args.snapshot, subdirs=None, js_analyzer=backend)
                validate_graph(graph, backend, comparison)
                expected[backend] = graph_digest(graph)
            for pair in range(args.pairs):
                observation = noise()
                receipt['observations'].append(observation)
                if observation['blocked_reasons']:
                    raise resources.ResourceBlocked('; '.join(observation['blocked_reasons']))
                order = ('regex', 'tree-sitter') if pair % 2 == 0 else ('tree-sitter', 'regex')
                for backend in order:
                    wall_start, cpu_start = time.perf_counter_ns(), time.process_time_ns()
                    graph = repo_graph.build_graph(args.snapshot, subdirs=None, js_analyzer=backend)
                    cpu_ns, wall_ns = time.process_time_ns() - cpu_start, time.perf_counter_ns() - wall_start
                    validate_graph(graph, backend, comparison)
                    if graph_digest(graph) != expected[backend]:
                        raise RuntimeError('semantic graph changed between repetitions')
                    receipt['samples'].append({'pair': pair, 'backend': backend,
                                               'wall_ns': wall_ns, 'process_cpu_ns': cpu_ns})
            final = noise()
            receipt['observations'].append(final)
            if final['blocked_reasons']:
                raise resources.ResourceBlocked('; '.join(final['blocked_reasons']))
            receipt['status'] = 'COMPLETED'
            receipt['summary'] = {backend: {'wall_ms_median': statistics.median(
                s['wall_ns'] / 1e6 for s in receipt['samples'] if s['backend'] == backend),
                'wall_ms_range': [func(s['wall_ns'] / 1e6 for s in receipt['samples']
                                       if s['backend'] == backend) for func in (min, max)]}
                for backend in ('regex', 'tree-sitter')}
    except (resources.ResourceBlocked, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        receipt['status'] = 'INVALID_PARTIAL' if receipt['samples'] else 'NOT_RUN'
        receipt['reason'] = str(exc)
    finally:
        receipt['slot']['released'] = receipt['slot']['acquired']
        receipt['bindings']['snapshot_sha256_after'] = snapshot_hash(args.snapshot, paths)
        if receipt['bindings']['snapshot_sha256_after'] != before:
            raise RuntimeError('snapshot modified during probe or measurement')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--comparison', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pairs', type=int, default=7, choices=range(3, 11))
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args()
    result = run(args)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'reason': result.get('reason'),
                      'samples': len(result['samples']), 'slot': result['slot']}, ensure_ascii=False))
    raise SystemExit(0 if result['status'] == 'COMPLETED' else 2)
