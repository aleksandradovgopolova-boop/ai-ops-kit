#!/usr/bin/env python3
"""Проверка research-артефактов против схем (stdlib+pyyaml).

Заготовка validate_research_artifacts.py для v0.2 (в репо пойдёт с selftest).
Покрывает: required/const/enum/pattern/minLength/minItems/types/additionalProperties,
if/then (DP: confidence=high -> review; EV: inference -> derived_from),
кросс-ссылки evidence_ids/derived_from -> файлы EV в том же наборе.
"""
import json, glob, re, sys, os
import yaml

def check(instance, schema, path='.'):
    errs = []
    t = schema.get('type')
    tlist = t if isinstance(t, list) else ([t] if t else None)
    if 'const' in schema and instance != schema['const']:
        errs.append(f'{path}: const {schema["const"]!r} != {instance!r}')
    if 'enum' in schema and instance not in schema['enum']:
        errs.append(f'{path}: {instance!r} not in enum')
    if 'pattern' in schema and isinstance(instance, str) and not re.search(schema['pattern'], instance):
        errs.append(f'{path}: {instance!r} !~ {schema["pattern"]}')
    if 'minLength' in schema and isinstance(instance, str) and len(instance) < schema['minLength']:
        errs.append(f'{path}: shorter than minLength ({schema["minLength"]})')
    if tlist and instance is not None:
        pymap = {'object': dict, 'array': list, 'string': str, 'boolean': bool}
        if 'null' not in tlist and not any(isinstance(instance, pymap.get(x, object)) for x in tlist):
            errs.append(f'{path}: type mismatch ({tlist})')
    if isinstance(instance, dict) and ('properties' in schema or schema.get('required')):
        for req in schema.get('required', []):
            if req not in instance:
                errs.append(f'{path}: missing required {req!r}')
        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False:
            for k in instance:
                if k not in props:
                    errs.append(f'{path}: unexpected key {k!r}')
        for k, v in instance.items():
            if k in props:
                errs.extend(check(v, props[k], f'{path}.{k}'))
    if isinstance(instance, list) and 'items' in schema:
        if 'minItems' in schema and len(instance) < schema['minItems']:
            errs.append(f'{path}: fewer than minItems')
        for i, item in enumerate(instance):
            errs.extend(check(item, schema['items'], f'{path}[{i}]'))
    # упрощённый if/then: единственный properties-const в if
    if 'if' in schema and 'then' in schema and isinstance(instance, dict):
        cond = True
        for k, sub in schema['if'].get('properties', {}).items():
            v = instance.get(k)
            if 'const' in sub and v != sub['const']:
                cond = False
            if 'properties' in sub and isinstance(v, dict):
                for k2, sub2 in sub['properties'].items():
                    if 'const' in sub2 and v.get(k2) != sub2['const']:
                        cond = False
        if cond:
            for req in schema['then'].get('required', []):
                if not isinstance(instance.get(req), (dict, list, str)):
                    errs.append(f'{path}: if/then — требуется {req!r}')
    return errs

def run(root, sets):
    ok = True
    for label, pairs in sets.items():
        ev_ids = set()
        for sp, g in pairs:
            schema = json.load(open(os.path.join(root, sp)))
            targets = [(f, yaml.safe_load(open(f))) for f in sorted(glob.glob(os.path.join(root, g)))]
            if g == '@examples':
                targets = [(f'{sp} example[{i}]', ex) for i, ex in enumerate(schema.get('examples', []))]
            for name, inst in targets:
                errs = check(inst, schema)
                if inst.get('kind') == 'research.evidence':
                    ev_ids.add(inst.get('id'))
                    for ref in inst.get('derived_from', []) or []:
                        if ref not in ev_ids and not glob.glob(os.path.join(root, os.path.dirname(g), f'{ref}.yaml')):
                            errs.append(f'derived_from без файла: {ref}')
                if inst.get('kind') == 'research.decision-package' and not name.endswith(']'):
                    missing = [e for e in inst.get('evidence_ids', []) if e not in ev_ids]
                    if missing:
                        errs.append(f'evidence_ids без файлов: {missing}')
                print(('FAIL ' + name + ': ' + '; '.join(errs)) if errs else ('PASS ' + name))
                ok = ok and not errs
    return ok

if __name__ == '__main__':
    root = sys.argv[1] if len(sys.argv) > 1 else '.'
    sets = {
        'live': [
            ('schemas/research-request.schema.json', '.research/requests/*.yaml'),
            ('schemas/research-evidence.schema.json', '.research/evidence/*.yaml'),
            ('schemas/decision-package.schema.json', '.research/decisions/*.yaml'),
        ],
        'demo': [
            ('schemas/research-request.schema.json', 'examples/research-demo/requests/*.yaml'),
            ('schemas/research-evidence.schema.json', 'examples/research-demo/evidence/*.yaml'),
            ('schemas/decision-package.schema.json', 'examples/research-demo/decisions/*.yaml'),
        ],
        'schema-examples': [
            ('schemas/research-request.schema.json', '@examples'),
            ('schemas/research-evidence.schema.json', '@examples'),
            ('schemas/decision-package.schema.json', '@examples'),
        ],
    }
    print('RESEARCH-OK' if run(root, sets) else 'RESEARCH-FAIL')
