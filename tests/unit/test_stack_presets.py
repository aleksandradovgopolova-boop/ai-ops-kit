"""Поставка профиля, навык и набор через настоящую точку входа установщика."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from tests.unit._installer_helpers import _make_child_repo

pytestmark = pytest.mark.unit
KIT = Path(__file__).resolve().parents[2]


def command(cwd, *args):
    env = dict(os.environ, AI_OPS_PYTHON=sys.executable, AI_OPS_HOME=str(KIT), PYTHONDONTWRITEBYTECODE='1')
    env.pop('CODEX_HOME', None)
    entry = cwd / 'ai-ops' if (cwd / 'ai-ops').is_file() else KIT / 'ai-ops'
    return subprocess.run([entry, *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=150)


def installed(root):
    return {p.parent.name for p in (root / '.claude/skills').glob('*/SKILL.md')}


def test_unknown_preset_fails_before_install(tmp_path):
    root = _make_child_repo(tmp_path / 'child')
    result = command(tmp_path, 'init', '--preset', 'missing', str(root))
    assert result.returncode == 2 and not (root / '.ai').exists()


@pytest.mark.slow
def test_installer_profile_add_and_stock_update(tmp_path):
    root = _make_child_repo(tmp_path / 'child')
    result = command(tmp_path, 'init', str(root), '--preset', 'dashboard')
    assert result.returncode == 0, result.stderr + result.stdout
    config = root / '.ai-ops.yaml'
    assert installed(root) == {'frontend-design', 'e2e-browser-testing', 'user-documentation',
                               'plain-language-communication'}
    conf_before = yaml.safe_load(config.read_bytes())
    assert conf_before['presets']['enabled'] == ['software-product', 'data-and-integrations']
    config.write_bytes(config.read_bytes() + b'# owner comment\n')
    prints = root / '.ai/runtime/skill-prints.json'
    prints.chmod(0o640)
    for kind, name in [('capability', 'repo-onboarding'), ('bundle', 'enterprise')]:
        result = command(root, kind, 'add', name)
        assert result.returncode == 0, result.stderr + result.stdout
        assert prints.stat().st_mode & 0o777 == 0o640
        before_retry = config.read_bytes()
        result = command(root, kind, 'add', name)
        assert result.returncode == 0 and config.read_bytes() == before_retry
    expected = installed(root)
    assert {'repo-onboarding', 'decision-support', 'system-constraint-analysis'} <= expected
    assert 'product-demo-video' not in expected
    config_after = yaml.safe_load(config.read_bytes())
    assert set(config_after['runtime_surface']['skills']['enabled']) == expected
    del config_after['runtime_surface'], conf_before['runtime_surface']
    assert config_after == conf_before and '# owner comment' in config.read_text()
    result = command(root, 'update', '--in-place')
    assert result.returncode == 0, result.stderr + result.stdout
    assert installed(root) == expected
    before_refusal = config.read_bytes()
    skill = root / '.claude/skills/repo-onboarding/SKILL.md'
    skill.write_text('owner')
    for kind, name in [('capability', 'repo-onboarding'), ('bundle', 'unknown')]:
        assert command(root, kind, 'add', name).returncode == 2
        assert config.read_bytes() == before_refusal and skill.read_text() == 'owner'


def test_all_catalog_members_reference_real_assets():
    kit_manifest = yaml.safe_load((KIT / 'manifest/ai-ops-manifest.yaml').read_text())
    skills = {s['id']: KIT / s['path'] for s in kit_manifest['skills']['shipped']}
    catalog = kit_manifest['skills']['installation_profiles']
    assert set(catalog['presets']) == {'react-product', 'python-backend', 'ai-product', 'dashboard', 'mobile'}
    assert set(catalog['bundles']) == {'product-team', 'enterprise', 'startup', 'govtech'}
    for preset in catalog['presets'].values():
        assert all((KIT / 'presets' / (name + '.yaml')).is_file() for name in preset['agents'])
    for members in [p['skills'] for p in catalog['presets'].values()] + list(catalog['bundles'].values()):
        assert members and len(set(members)) == len(members) and all(skills[name].is_file() for name in members)


def test_failed_skill_copy_can_be_retried(tmp_path, monkeypatch):
    from installer import managed_state
    src = tmp_path / 'source'
    src.mkdir()
    (src / 'SKILL.md').write_text('full skill')
    target = tmp_path / '.claude/skills/added'
    expected = managed_state._dir_signature(src)

    def interrupted(source, stage):
        stage.mkdir()
        (stage / 'SKILL.md').write_bytes(b'part')
        raise OSError('simulated interruption')

    with monkeypatch.context() as patch:
        patch.setattr(managed_state.shutil, 'copytree', interrupted)
        with pytest.raises(OSError, match='interruption'):
            managed_state._deliver_selected_skill(src, target, expected)
    assert not target.exists()
    managed_state._deliver_selected_skill(src, target, expected)
    assert managed_state._dir_signature(target) == expected


@pytest.mark.parametrize('conflict', ['owner-skill', 'shared-directory', 'file-in-place-of-skills'])
def test_init_profile_refuses_conflict_before_creating_managed(tmp_path, conflict):
    root = _make_child_repo(tmp_path / 'child')
    shared = tmp_path / 'shared'
    shared.mkdir()
    skills = root / '.claude/skills'
    skills.parent.mkdir()
    if conflict == 'shared-directory':
        skills.symlink_to(shared, target_is_directory=True)
    elif conflict == 'file-in-place-of-skills':
        skills.write_bytes(b'preserve')
    else:
        owner = skills / 'frontend-design'
        owner.mkdir(parents=True)
        (owner / 'SKILL.md').write_text('owner')
    result = command(tmp_path, 'init', str(root), '--preset', 'dashboard')
    assert result.returncode == 2
    assert not (root / '.ai').exists() and not (root / '.ai-ops.yaml').exists()
    assert not list(shared.iterdir())
    if conflict == 'file-in-place-of-skills':
        assert skills.read_bytes() == b'preserve'
    if conflict == 'owner-skill':
        assert (skills / 'frontend-design/SKILL.md').read_text() == 'owner'


def test_aliased_commands_cannot_be_changed_by_adding_skill():
    from installer.stack_profiles import _expanded
    with pytest.raises(ValueError, match='ссылки YAML'):
        _expanded('runtime_surface: {skills: &surface {enabled: []}, commands: *surface}', {'repo-onboarding'})


def test_update_and_add_share_an_exclusive_lock(tmp_path):
    from installer.stack_profiles import install_lock
    root = _make_child_repo(tmp_path / 'child')
    with install_lock(root):
        result = command(root, 'update', '--in-place')
    assert result.returncode == 2 and 'другая операция' in result.stdout
    assert not (root / '.ai').exists()


def test_selected_source_entry_must_be_a_regular_file(tmp_path):
    from installer.stack_profiles import verify_new_install
    root = tmp_path / 'project'
    root.mkdir()
    path = tmp_path / 'kit/skills/demo'
    path.mkdir(parents=True)
    with pytest.raises(ValueError, match='исходный файл'):
        verify_new_install(root, tmp_path / 'kit', {'skills': {'shipped': [
            {'id': 'demo', 'path': 'skills/demo/SKILL.md'}]}}, ['demo'])
    assert not list(root.iterdir())


def test_add_rejects_missing_source_before_expanding_configuration(tmp_path, monkeypatch):
    from installer import stack_profiles
    root = tmp_path / 'child'
    (root / '.ai/managed').mkdir(parents=True)
    (root / '.ai/managed/.checksums.json').write_text('{}')
    cfg = root / '.ai-ops.yaml'
    cfg.write_text('parent: {installed_version: 1.0.0}\nruntime_surface: {skills: {enabled: []}}\n')
    before = cfg.read_bytes()
    kit = tmp_path / 'kit'
    (kit / 'skills/x').mkdir(parents=True)
    manifest = {'skills': {'shipped': [{'id': 'x', 'path': 'skills/x/SKILL.md'}],
                           'installation_profiles': {'bundles': {'set': ['x']}}}}
    from types import SimpleNamespace
    monkeypatch.chdir(root)
    with pytest.raises(ValueError, match='исходный файл'):
        stack_profiles.add_cli(['add', 'set'], 'bundle', kit, SimpleNamespace(manifest=lambda: manifest))
    assert cfg.read_bytes() == before and not (root / '.claude').exists()

@pytest.mark.parametrize('state', ['exclusive', 'unfinished'])
def test_add_preserves_prepared_migration_window(tmp_path, state):
    from ai_ops_kit.lifecycle import session_migration_store as store
    from contextlib import nullcontext
    root = _make_child_repo(tmp_path / 'child').resolve()
    result = command(tmp_path, 'init', str(root), '--preset', 'dashboard')
    assert result.returncode == 0, result.stdout + result.stderr
    config = root / '.ai-ops.yaml'
    before = config.read_bytes()
    initial_skills = installed(root)
    window = store.barrier(root, exclusive=True) if state == 'exclusive' else nullcontext()
    if state == 'unfinished':
        store.create(root / store.AREA / ('a' * 64) / 'journal.json', {'phase': 'installing'})
    with window:
        result = command(root, 'capability', 'add', 'repo-onboarding')
    assert result.returncode == 2 and 'migration' in result.stdout
    assert config.read_bytes() == before and installed(root) == initial_skills
