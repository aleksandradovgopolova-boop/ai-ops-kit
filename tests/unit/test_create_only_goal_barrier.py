"""Create-only durable plan batches never replace foreign or uncertain artifacts."""
from __future__ import annotations

import os

import pytest

from ai_ops_kit.shared import lifecycle_store as store


def test_preflight_conflict_prevents_even_earlier_missing_document_creation(tmp_path):
    (tmp_path / 'foreign.yaml').write_text('foreign')
    result = store.durable_create_batch(tmp_path, {'missing/a.yaml': 'new', 'foreign.yaml': 'ours'})
    assert not result['ok'] and result['created'] == []
    assert not (tmp_path / 'missing').exists()
    assert (tmp_path / 'foreign.yaml').read_text() == 'foreign'


def test_exact_existing_bytes_reused_and_new_document_durable_readback(tmp_path):
    docs = {'features/a/one.yaml': 'один\n', 'features/a/graph.yaml': 'last\n'}
    first = store.durable_create_batch(tmp_path, docs)
    assert first['ok'] and first['created'] == list(docs)
    before = {k: (tmp_path / k).stat().st_ino for k in docs}
    again = store.durable_create_batch(tmp_path, docs)
    assert again == {'ok': True, 'created': []}
    assert {k: (tmp_path / k).stat().st_ino for k in docs} == before


@pytest.mark.parametrize('damage', ['ancestor', 'dangling-ancestor', 'leaf', 'dangling-leaf', 'hardlink', 'directory'])
def test_unsafe_existing_paths_never_follow_or_replace(tmp_path, damage):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'value.yaml').write_text('sentinel')
    if 'ancestor' in damage:
        (tmp_path / 'target').symlink_to(outside if damage == 'ancestor' else tmp_path / 'absent')
    else:
        (tmp_path / 'target').mkdir()
        p = tmp_path / 'target/value.yaml'
        if damage in ('leaf', 'dangling-leaf'):p.symlink_to(outside / ('value.yaml' if damage == 'leaf' else 'absent'))
        elif damage == 'hardlink':os.link(outside / 'value.yaml', p)
        else:p.mkdir()
    assert not store.durable_create_batch(tmp_path, {'target/value.yaml': 'sentinel'})['ok']
    assert (outside / 'value.yaml').read_text() == 'sentinel'
    assert not (tmp_path / 'absent').exists()


@pytest.mark.parametrize('name', ['../escape.yaml', '/escape.yaml', 'a//b.yaml', 'a/./b.yaml', ''])
def test_invalid_document_path_rejected_before_writes(tmp_path, name):
    assert not store.durable_create_batch(tmp_path, {name: 'text'})['ok']
    assert list(tmp_path.iterdir()) == []


def test_partial_failed_sync_can_complete_only_matching_already_written_bytes(tmp_path, monkeypatch):
    docs = {'one.yaml': 'first', 'graph.yaml': 'last'}
    sync = os.fsync
    def fail(fd):
        if (tmp_path / 'one.yaml').exists():raise OSError('controlled sync unavailable')
        return sync(fd)
    with monkeypatch.context() as patch:
        patch.setattr(store.os, 'fsync', fail)
        refused = store.durable_create_batch(tmp_path, docs)
    assert not refused['ok'] and refused['created'] == ['one.yaml']
    assert not (tmp_path / 'graph.yaml').exists()
    assert store.durable_create_batch(tmp_path, docs)['ok']
    assert (tmp_path / 'graph.yaml').read_text() == 'last'


def test_parent_replaced_by_symlink_between_preflight_and_create_is_refused(tmp_path, monkeypatch):
    parent = tmp_path / 'features'
    parent.mkdir()
    target = tmp_path / 'elsewhere'
    target.mkdir()
    original = store.os.open
    seen = []
    def raced(path, flags, *args, **kwargs):
        if path == 'features':
            seen.append(path)
            if len(seen) == 2:
                parent.rmdir();parent.symlink_to(target)
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(store.os, 'open', raced)
    result = store.durable_create_batch(tmp_path, {'features/value.yaml': 'must not escape'})
    assert not result['ok'] and list(target.iterdir()) == []


def test_retry_syncs_reused_directory_parent_after_uncertain_mkdir_sync(tmp_path, monkeypatch):
    documents = {'features/work/value.yaml': 'confirmed'}
    root_inode = tmp_path.stat().st_ino
    sync = store.os.fsync
    def fail_parent(fd):
        if os.fstat(fd).st_ino == root_inode and (tmp_path / 'features').exists():
            raise OSError('controlled mkdir parent sync unavailable')
        return sync(fd)
    with monkeypatch.context() as patch:
        patch.setattr(store.os, 'fsync', fail_parent)
        assert not store.durable_create_batch(tmp_path, documents)['ok']
    assert (tmp_path / 'features').is_dir()
    assert not (tmp_path / 'features/work/value.yaml').exists()
    observed = []
    def confirmed(fd):
        observed.append(os.fstat(fd).st_ino)
        return sync(fd)
    monkeypatch.setattr(store.os, 'fsync', confirmed)
    assert store.durable_create_batch(tmp_path, documents)['ok']
    assert root_inode in observed, 'reuse must reconfirm the ancestor directory entry'
