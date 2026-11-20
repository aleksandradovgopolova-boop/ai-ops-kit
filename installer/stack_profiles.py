"""Профили установки из checkout. Навыки и правила поставляет штатный установщик."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile

import yaml


def _catalog(manifest):
    catalog = manifest['skills']['installation_profiles']
    skills = {item['id']: item for item in manifest['skills']['shipped']}
    return catalog, skills


def _members(catalog, kind, name, skills):
    table = {key: [key] for key in skills} if kind == 'capability' else catalog['bundles']
    if name not in table:
        raise ValueError(f'неизвестный {kind}: {name}')
    members = table[name]
    if not members or not set(members) <= skills.keys():
        raise ValueError(f'неизвестный навык в {kind} {name}')
    return set(members)


def init_cli(argv, kit, manifest, init):
    parser = argparse.ArgumentParser(prog='ai-ops init')
    parser.add_argument('project')
    parser.add_argument('--preset', required=True)
    args = parser.parse_args(argv)
    catalog, skills = _catalog(manifest)
    try:
        preset = catalog['presets'][args.preset]
    except KeyError:
        raise ValueError(f'неизвестный профиль: {args.preset}') from None
    if not set(preset['skills']) <= skills.keys() or not all(
            (kit / 'presets' / (name + '.yaml')).is_file() for name in preset['agents']):
        raise ValueError('профиль ссылается на отсутствующий компонент')
    selected = set(preset['skills']) | {key for key, item in skills.items() if item.get('opt_in') is False}
    return init(args.project, profile=(preset['agents'], sorted(selected)))


def _check_sources(kit, skills, selected):
    for name in selected:
        entry = kit / skills[name]['path']
        if not entry.is_file() or entry.is_symlink():
            raise ValueError(f'отсутствует исходный файл навыка {name}')


def verify_new_install(root, kit, manifest, selected):
    _check_sources(kit, {item['id']: item for item in manifest['skills']['shipped']}, selected)
    cfg = root / '.ai-ops.yaml'
    if cfg.exists() or cfg.is_symlink():
        raise ValueError('конфигурация проекта уже существует; профиль задаётся при новой установке')
    for path in (root / '.ai', root / '.claude', root / '.claude/skills'):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f'ожидался каталог проекта: {path.name}')
    for name in selected:
        dest = root / '.claude/skills' / name
        if dest.exists() or dest.is_symlink():
            raise ValueError(f'навык {name} уже существует в проекте')


def configure_template(text, profile):
    groups, skills = profile
    old = 'presets: {enabled: []}'
    if text.count(old) != 1 or 'runtime_surface' in yaml.safe_load(text):
        raise ValueError('шаблон конфигурации профиля изменился')
    return text.replace(old, 'presets: {enabled: ' + json.dumps(groups) + '}') + '\n' + yaml.safe_dump(
        {'runtime_surface': {'skills': {'enabled': skills}}}, sort_keys=False)


def _expanded(text, members):
    cfg = yaml.safe_load(text)
    branch = cfg
    for key in ('runtime_surface', 'skills'):
        branch = branch.get(key, {})
        if not isinstance(branch, dict):
            raise ValueError('ожидалась карта параметров ' + key)
    enabled = branch.get('enabled', 'all')
    if enabled == 'all':
        return text
    if not isinstance(enabled, list) or not all(isinstance(k, str) for k in enabled):
        raise ValueError('список runtime_surface.skills.enabled повреждён')
    extra = sorted(members.difference(enabled))
    if not extra:
        return text
    node = yaml.compose(text)
    for key in ('runtime_surface', 'skills', 'enabled'):
        entries = [v for k, v in node.value if k.value == key]
        if len(entries) != 1:
            raise ValueError('список навыков должен быть объявлен однозначно')
        node = entries[0]
    offset = node.start_mark.index
    if node.flow_style and text[offset] == '[':
        pos = offset + 1
        new = text[:pos] + ', '.join(extra) + (', ' if enabled else '') + text[pos:]
    else:
        indent = ' ' * node.start_mark.column
        new = text[:offset] + ''.join('- ' + value + '\n' + indent for value in extra) + text[offset:]
    expected = dict(cfg)
    surface = dict(cfg['runtime_surface'])
    surface['skills'] = dict(surface['skills'], enabled=extra + enabled)
    expected['runtime_surface'] = surface
    if yaml.safe_load(new) != expected:
        raise ValueError('ссылки YAML связывают список навыков с другими полями проекта')
    return new


def add_cli(argv, kind, kit, core):
    if len(argv) != 2 or argv[0] != 'add':
        raise ValueError(f'использование: ai-ops {kind} add <имя>')
    root = Path.cwd()
    config = root / '.ai-ops.yaml'
    if config.is_symlink() or not config.is_file() or not (root / '.ai/managed/.checksums.json').is_file():
        raise ValueError('команду нужно запустить в установленном дочернем проекте')
    catalog, skills = _catalog(core.manifest())
    members = _members(catalog, kind, argv[1], skills)
    _check_sources(kit, skills, members)
    with install_lock(root, required=True) as fd:
        before = config.read_bytes()
        cfg = yaml.safe_load(before)
        if not isinstance(cfg, dict) or not isinstance(cfg.get('parent'), dict):
            raise ValueError('некорректная конфигурация родительского пакета')
        if cfg['parent'].get('installed_version') != core.pkg_version():
            raise ValueError('сначала согласуйте версию установщика и установленного кита')
        destinations = [root / '.claude/skills' / name for name in members]
        for parent in (root / '.claude', root / '.claude/skills'):
            if parent.exists() and not parent.is_dir():
                raise ValueError(f'ожидался каталог проекта: {parent.name}')
        if core._footprint_symlink([config, root / '.ai/runtime/skill-prints.json',
                                   root / '.ai/runtime/backups/skills', *destinations]):
            raise ValueError('область поставки содержит символьную ссылку')
        # Existing owner edits to a selected skill need an explicit stock update.
        # Never replace a local customization for an additive command.
        for name in members:
            path = root / '.claude/skills' / name
            if path.exists() and core._dir_signature(path) != core._dir_signature((kit / skills[name]['path']).parent):
                raise ValueError(f'существующий навык {name} отличается от поставки')
        new = _expanded(before.decode('utf-8'), members).encode('utf-8')
        if before != new:
            with tempfile.NamedTemporaryFile(dir=root, delete=False) as out:
                tmp = Path(out.name)
                try:
                    out.write(new)
                    out.flush()
                    os.fchmod(out.fileno(), config.stat().st_mode & 0o777)
                    os.fsync(out.fileno())
                    if config.read_bytes() != before:
                        raise ValueError('конфигурация изменилась, добавление прервано')
                    os.replace(tmp, config)
                    os.fsync(fd)
                finally:
                    tmp.unlink(missing_ok=True)
        synced = core.sync_skills(root, selected=members)
        if set(synced) != members:
            raise ValueError('часть выбранных навыков не доставлена; повторите добавление после устранения ошибки')
        print('Доступны навыки: ' + ', '.join(sorted(members)))
        return 0



@contextmanager
def install_lock(root, *, required=False):
    """The directory inode survives a config rename; no stale lock file on crash."""
    try:
        import fcntl
    except ImportError:
        if required:
            raise ValueError('для согласованного добавления требуется файловая блокировка flock') from None
        yield None
        return
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fd
    finally:
        os.close(fd)
