"""Воспроизводимое функциональное сравнение; намеренно БЕЗ замеров времени.

python compare_snapshot.py --repo /path/to/ii-sreda --snapshot /new/path --output results.json
Запуск из корня Kit с PYTHONPATH=. в экспериментальной venv.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
import subprocess

from ai_ops_kit.context import repo_graph

REVISION = '7b14b251acc65cdf50de4439ef3013c5f83858c1'
SUBTREES = ('src/', 'server/', 'e2e/', 'scripts/', 'eslint-rules/')
LIMIT = 160


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def regex_specifiers(text):
    # Точные три шаблона текущего _analyze_js, до преобразования specifier -> stem.
    found = set(re.findall(r'''\bimport\s*['"]([^'"]+)['"]''', text))
    found.update(re.findall(r'''\bfrom\s*['"]([^'"]+)['"]''', text))
    found.update(re.findall(r'''require\s*\(\s*['"]([^'"]+)['"]\s*\)''', text))
    return found


def snapshot_hash(snapshot, paths):
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.encode() + b'\0' + (snapshot / path).read_bytes() + b'\0')
    return digest.hexdigest()


def compare(repo, snapshot):
    # Исключительно git objects закреплённого revision; working tree не читается.
    entries = []
    for raw in git(repo, 'ls-tree', '-rz', REVISION).split(b'\0'):
        if not raw:
            continue
        header, raw_path = raw.split(b'\t', 1)
        mode, kind, blob = header.decode().split()
        path = raw_path.decode()
        if (mode == '100644' and kind == 'blob' and path.startswith(SUBTREES)
                and Path(path).suffix in repo_graph.JS_TS_EXTENSIONS):
            entries.append((path, blob))
    buckets = defaultdict(list)
    for entry in entries:
        path = entry[0]
        group = (path.split('/')[0], Path(path).suffix,
                 'test' if '.test.' in path or '.spec.' in path or '/__tests__/' in path else 'other')
        buckets[group].append(entry)
    queues = {key: deque(sorted(values, key=lambda x: hashlib.sha256(x[0].encode()).hexdigest()))
              for key, values in sorted(buckets.items())}
    selected = []
    while len(selected) < min(LIMIT, len(entries)):
        for queue in queues.values():
            if queue and len(selected) < LIMIT:
                selected.append(queue.popleft())
    selected.sort()
    snapshot.mkdir(parents=True, exist_ok=False)
    manifest = []
    for path, blob in selected:
        data = git(repo, 'cat-file', 'blob', blob)
        target = snapshot / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o444)
        manifest.append({'path': path, 'blob': blob, 'sha256': hashlib.sha256(data).hexdigest()})
    paths = [path for path, _ in selected]
    before = snapshot_hash(snapshot, paths)
    regex_graph = repo_graph.build_graph(snapshot, subdirs=None)
    ast_graph = repo_graph.build_graph(snapshot, subdirs=None, js_analyzer='tree-sitter')
    records = []
    for path in paths:
        content = (snapshot / path).read_text(encoding='utf-8')
        baseline = regex_specifiers(content)
        assert repo_graph._js_specifier_stems(baseline) == set(regex_graph['files'][path]['imports'])
        analysis = ast_graph['js_analysis'][path]
        ast = set(analysis.get('specifiers', []))
        errors = []
        if analysis.get('fallback') == 'syntax-error':
            source = content.encode('utf-8')
            root = repo_graph._load_js_parser(Path(path).suffix).parse(source).root_node
            stack = [root]
            while stack:
                node = stack.pop()
                stack.extend(reversed(node.named_children))
                if node.is_error or node.is_missing:
                    errors.append({'kind': node.type, 'line': node.start_point.row + 1,
                                   'column': node.start_point.column + 1})
        records.append({'path': path, 'regex_specifiers': sorted(baseline), 'syntax_errors': errors,
                        'analysis': analysis,
                        'ast_only': sorted(ast - baseline) if analysis['backend'] == 'tree-sitter' else None,
                        'regex_only': sorted(baseline - ast) if analysis['backend'] == 'tree-sitter' else None,
                        'regex_edges': regex_graph['import_edges'][path],
                        'ast_edges': ast_graph['import_edges'][path]})
    after = snapshot_hash(snapshot, paths)
    assert before == after
    actual = [record for record in records if record['analysis']['backend'] == 'tree-sitter']
    return {'source': {'repository': 'ii-sreda', 'revision': REVISION, 'eligible_files': len(entries),
                       'subtrees': SUBTREES, 'selection': 'round-robin(root, suffix, test/other); SHA256(path) order',
                       'limit': LIMIT, 'selected_files': len(paths),
                       'selected_groups': dict(sorted(Counter(
                           f"{Path(p).parts[0]}:{Path(p).suffix}" for p in paths).items()))},
            'environment': {name: version(name) for name in
                            ('tree-sitter', 'tree-sitter-javascript', 'tree-sitter-typescript')},
            'snapshot_sha256_before': before, 'snapshot_sha256_after': after,
            'timing': 'NOT_RUN: explicit resource window required; #1409 has priority',
            'summary': {'ast_success_files': len(actual), 'fallback_files': len(records) - len(actual),
                        'regex_specifier_pairs': sum(len(r['regex_specifiers']) for r in records),
                        'regex_pairs_on_ast_success_files': sum(len(r['regex_specifiers']) for r in actual),
                        'ast_specifier_pairs': sum(len(r['analysis']['specifiers']) for r in actual),
                        'ast_only_pairs': sum(len(r['ast_only']) for r in actual),
                        'regex_only_pairs': sum(len(r['regex_only']) for r in actual),
                        'unresolved_files': sum(r['analysis'].get('unresolved', False) for r in actual)},
            'limitations': ['No independent complete oracle; counts are not precision or recall.',
                            'Limited deterministic sample of one pinned repository; no generalization.',
                            'Stem graph is not Node/tsconfig/package resolution; all AST JS stays unbounded.',
                            'Literal strings only; escapes/computed imports unresolved; require binding not resolved.'],
            'manifest': manifest, 'records': records}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.repo, args.snapshot)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))
