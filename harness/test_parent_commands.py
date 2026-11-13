"""Offline A1 regressions; these tests are run only by the orchestrator.

Reuse the isolated publisher Git fixture explicitly. The transport seam fakes
the connector/native publisher; offline_child still runs the real transport
module, frame parser, READY protocol and durable receipts in a real subprocess.
"""
import base64
import copy
import fcntl
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from harness import git_publish as native, git_transport as transport, parent_commands as parent, storage
from harness.test_git_publish import (isolated_storage_environment, prepared, to_pr, pr_data,
                                      rows_for, cleanup_pr_data, HEAD, MERGE, TEST_MERGE)
from harness.test_git_transport import seam, durable, RUN, REQUEST, NEXT


RESPONSE = transport.encode({'text': '한글 🐈'})


@pytest.fixture
def parent_seam(seam, monkeypatch):
    directory, calls = seam
    for key in ('READ_ONLY', 'GIT', 'TAVERN_WORKFLOW_DEMO', 'TAVERN_NO_GIT'):
        monkeypatch.delenv(key, raising=False)
    durable(directory / 'github.json', {'run_id': RUN, 'step': 'repository',
                                       'status': 'awaiting_connector', 'config': {'enabled': True},
                                       'deadline': time.time() + 1800})
    durable(directory / 'report.json', {'run_id': RUN, 'simulated': False, 'read_only': False,
                                       'changed_files': ['fixture.py']})
    response_dir = directory / 'parent-responses'
    response_dir.mkdir(mode=0o700)
    response = response_dir / 'response.json'
    response.write_bytes(RESPONSE)
    response.chmod(0o600)
    return directory, calls, response


# Test-only bootstrap: production never creates a launcher or edits a ledger.
# It imports the real transport and installs only the isolated native seam.
CHILD = r'''
import contextlib, io, json, os, sys
from pathlib import Path
from harness import git_publish as n, git_transport as t, storage
root, mode = Path(sys.argv[1]), sys.argv[2]
n.ROOT = root
n.REPORTS = root / 'logs/harness/workflows'
n.storage_policy = lambda: storage.resolve_storage(root, env={})
def fake(args):
    d = n.REPORTS / args[2]
    source = Path(args[6])
    assert isinstance(t.parse(source.read_bytes()), (dict, list))
    (d / 'fixture-received.json').write_bytes(source.read_bytes())
    os.chmod(str(d / 'fixture-received.json'), 0o600)
    if mode == 'native_failure':
        print(json.dumps({'status': 'failed', 'error_type': 'ValueError'}))
        return 7
    ledger = json.loads((d / 'github.json').read_text())
    if mode in ('failed_pending_read', 'failed_pending_write'):
        ledger['status'] = 'needs_reconciliation' if mode == 'failed_pending_write' else 'failed'
        ledger['pending_write'] = mode == 'failed_pending_write'
        (d / 'github.json').write_bytes(t.encode(ledger))
        print(json.dumps({'run_id': d.name, 'github': {'status': ledger['status']}, 'request': None}))
        return 1
    ledger['pending_request_id'] = '2' * 64
    if mode == 'write_missing_deadline':
        ledger.pop('deadline')
    if mode == 'write_bad_deadline':
        ledger['deadline'] = True
    if mode == 'awaiting_ci':
        ledger.pop('pending_request_id')
        ledger['status'] = 'awaiting_ci'
    with (d / 'github.json').open('wb') as out:
        out.write(t.encode(ledger))
    os.chmod(str(d / 'github.json'), 0o600)
    job = None if mode == 'awaiting_ci' else {
        'request_id': '2' * 64, 'tool': n.TOOLS['fetch'], 'arguments': {'url': 'fixture'}}
    if mode == 'large':
        job['arguments']['text'] = '한글 🐈' * 7000
    if mode in ('write', 'large_write', 'write_missing_deadline', 'write_bad_deadline'):
        job['tool'] = n.TOOLS['create_tree']
        if mode == 'large_write':
            job['arguments']['text'] = '한글 🐈' * 21000
    if mode == 'merge':
        job['tool'] = n.TOOLS['merge_pull_request']
    payload = {'run_id': d.name, 'github': {'status': ledger['status']},
               'request': job, 'poll_after_seconds': 10 if mode == 'awaiting_ci' else 0}
    print(json.dumps(payload, ensure_ascii=False))
    return 0
n.main = fake
captured = io.StringIO()
with contextlib.redirect_stdout(captured):
    code = t.main(sys.argv[3:])
raw = captured.getvalue()
if mode == 'missing_ready': raw = raw.split('\n', 1)[1]
if mode == 'extra_ready': raw = t.READY + '\n' + raw
if mode == 'extra_json': raw += '{}\n'
if mode == 'truncated': raw = raw[:-10]
if mode == 'wrong_ready': raw = raw.replace(t.READY, 'wrong-ready', 1)
sys.stdout.write(raw)
sys.stdout.flush()
if mode == 'signal': os.kill(os.getpid(), 9)
raise SystemExit(code)
'''


@pytest.fixture
def offline_child(parent_seam, monkeypatch):
    real_popen = subprocess.Popen
    directory, _, _ = parent_seam
    settings = {'mode': 'normal', 'calls': []}

    def spawn(args, **kwargs):
        settings['calls'].append(args)
        assert args == [sys.executable, '-m', 'harness.git_transport', 'accept', '--run-id', RUN,
                        '--request-id', REQUEST, '--stdin-base64']
        assert kwargs['shell'] is False and kwargs['close_fds'] is True
        assert 'env' not in kwargs
        frame = kwargs['stdin']
        assert stat.S_ISREG(os.fstat(frame.fileno()).st_mode)
        assert stat.S_IMODE(os.fstat(frame.fileno()).st_mode) == 0o600
        assert frame.tell() == 0
        raw = os.pread(frame.fileno(), os.fstat(frame.fileno()).st_size, 0)
        assert raw.endswith(b'\n.\n') or settings['mode'] == 'partial_frame'
        assert all(len(line) <= 2048 for line in raw.splitlines())
        return real_popen([sys.executable, '-c', CHILD, str(directory.parents[3]),
                           settings['mode']] + args[3:], **kwargs)

    monkeypatch.setattr(parent.subprocess, 'Popen', spawn)
    return settings


def accept(response, request=REQUEST, raw=RESPONSE):
    return parent.execute('agent-git-accept-file', RUN, request_id=request,
                          response_file=str(response), sha256=transport.digest(raw))


def no_frame(directory):
    assert not list(directory.glob('.parent-input-*'))


def test_next_accept_next_uses_exact_returned_request_and_no_reissue(parent_seam, offline_child):
    directory, calls, response = parent_seam
    first = parent.execute('agent-git-next', RUN)
    assert first['status'] == 'awaiting_connector' and first['native_exit_code'] == 0
    assert first['native']['request']['request_id'] == REQUEST
    assert first['next_action']['then']['required_arguments']['request_id'] == REQUEST
    second = accept(response)
    assert second['status'] == 'awaiting_connector' and second['executed'] is True
    assert second['native']['request']['request_id'] == NEXT
    assert second['next_action']['request_id'] == NEXT
    stopped = parent.execute('agent-git-next', RUN)
    assert stopped['status'] == 'needs_reconciliation' and stopped['code'] == 'existing_result_no_redispatch'
    assert stopped['next_action']['action'] == 'stop' and 'native' not in stopped
    assert len(calls) == len(offline_child['calls']) == 1
    temporary = [name for name in second['side_effects']['created'] if name.startswith('.parent-input-')]
    assert temporary == second['side_effects']['removed']
    assert (directory / ('parent-accept-' + parent.operation('accept', RUN, REQUEST) + '.json')).exists()
    no_frame(directory)
    assert response.read_bytes() == RESPONSE
    op = parent.operation('accept', RUN, REQUEST)
    assert (directory / 'transport' / (op + '.response.json')).read_bytes() == RESPONSE
    assert (directory / 'transport' / (op + '.complete.json')).exists()


def test_multiline_file_stdin_has_2048_character_lines_and_exact_response(parent_seam, offline_child):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    raw = transport.encode({'text': '한글 🐈' * 600})
    response.write_bytes(raw)
    result = accept(response, raw=raw)
    assert result['status'] == 'awaiting_connector'
    saved = directory / 'transport' / (parent.operation('accept', RUN, REQUEST) + '.response.json')
    assert saved.read_bytes() == raw and response.read_bytes() == raw
    no_frame(directory)


@pytest.mark.parametrize('different', [False, True])
def test_duplicate_response_never_reaccepts(parent_seam, offline_child, different):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    assert accept(response)['native_exit_code'] == 0
    raw = transport.encode({'other': True}) if different else RESPONSE
    response.write_bytes(raw)
    result = accept(response, raw=raw)
    assert result['code'] == ('conflicting_response' if different else 'duplicate_response')
    assert result['executed'] is False and len(offline_child['calls']) == 1
    no_frame(directory)


def test_stale_request_does_not_spawn(parent_seam, offline_child):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    result = accept(response, '3' * 64)
    assert result['code'] == 'stale_request_id'
    assert result['next_action']['action'] == 'stop' and not offline_child['calls']
    no_frame(directory)


@pytest.mark.parametrize('mode', ['native_failure', 'nonzero', 'merge'])
def test_pending_id_cannot_continue_failed_or_merge_result(parent_seam, offline_child, monkeypatch, mode):
    directory, _, response = parent_seam

    def pending(args):
        ledger = json.loads((directory / 'github.json').read_text())
        ledger['pending_request_id'] = REQUEST
        durable(directory / 'github.json', ledger)
        if mode == 'native_failure':
            print(json.dumps({'status': 'failed', 'error_type': 'ValueError'}))
        else:
            print(json.dumps({'run_id': RUN, 'github': {'status': 'awaiting_connector'},
                              'request': {'request_id': REQUEST, 'arguments': {},
                                          'tool': native.TOOLS['merge_pull_request' if mode == 'merge' else 'fetch']}}))
        return 0 if mode == 'merge' else 7

    monkeypatch.setattr(native, 'main', pending)
    first = parent.execute('agent-git-next', RUN)
    assert first['status'] == ('awaiting_approval' if mode == 'merge' else 'failed')
    assert first['native_exit_code'] == (0 if mode == 'merge' else 7)
    assert first['next_action']['action'] == 'stop'
    before = {p.name: p.read_bytes() for p in (directory / 'transport').iterdir()}
    result = accept(response)
    assert result['code'] == ('a2_or_merge_requires_approval' if mode == 'merge' else 'native_result_requires_stop')
    assert result['status'] == ('needs_reconciliation' if mode == 'merge' else 'failed')
    assert result['native_exit_code'] == (None if mode == 'merge' else 7)
    assert not result['executed']
    assert result['side_effects']['created'] == [] and not offline_child['calls']
    assert {p.name: p.read_bytes() for p in (directory / 'transport').iterdir()} == before
    assert response.read_bytes() == RESPONSE
    no_frame(directory)


def test_request_tool_and_pending_write_disagreement_blocks_export(parent_seam, offline_child, monkeypatch):
    directory, calls, response = parent_seam
    original = native.main

    def mismatch(args):
        code = original(args)
        ledger = json.loads((directory / 'github.json').read_text())
        ledger['pending_write'] = True  # The recorded request is a read-only fetch.
        durable(directory / 'github.json', ledger)
        return code

    monkeypatch.setattr(native, 'main', mismatch)
    result = parent.execute('agent-git-next', RUN)
    assert result['code'] == 'pending_write_mismatch' and result['executed']
    assert result['status'] == 'needs_reconciliation' and 'native' not in result
    assert result['next_action']['action'] == 'stop'
    again = accept(response)
    assert again['code'] == 'pending_write_mismatch' and not again['executed']
    assert len(calls) == 1 and not offline_child['calls']
    assert response.read_bytes() == RESPONSE
    no_frame(directory)


@pytest.mark.parametrize('marker', ['inflight.json', 'head.next', 'orphan.begin.json'])
def test_uncertain_native_evidence_never_dispatches(parent_seam, offline_child, marker):
    directory, calls, response = parent_seam
    parent.execute('agent-git-next', RUN)
    marker = ('3' * 64 + '.begin.json') if marker == 'orphan.begin.json' else marker
    durable(directory / 'transport' / marker, {'run_id': RUN})
    for result in (parent.execute('agent-git-next', RUN), accept(response)):
        assert result['status'] == 'needs_reconciliation' and not result['executed']
        assert result['next_action']['action'] == 'stop'
    assert len(calls) == 1 and not offline_child['calls']
    assert (directory / 'transport' / marker).exists()


@pytest.mark.parametrize('change', ['journal_hash', 'run', 'request', 'pending'])
def test_head_and_pending_identity_mismatch_stops(parent_seam, offline_child, change):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    target = directory / ('github.json' if change == 'pending' else 'transport/head.json')
    data = json.loads(target.read_text())
    data[{'journal_hash': 'journal_sha256', 'run': 'run_id', 'request': 'request_id',
          'pending': 'pending_request_id'}[change]] = ('0' * 64 if change != 'run' else '999999-abcdef')
    durable(target, data)
    result = accept(response)
    assert result['status'] == 'needs_reconciliation' and not result['executed']
    assert not offline_child['calls']


def test_legacy_pending_without_receipt_does_not_create_transport(parent_seam):
    directory, calls, _ = parent_seam
    ledger = json.loads((directory / 'github.json').read_text())
    ledger['pending_request_id'] = REQUEST
    durable(directory / 'github.json', ledger)
    result = parent.execute('agent-git-next', RUN)
    assert result['code'] == 'legacy_pending_requires_reconciliation'
    assert not calls and not (directory / 'transport').exists()


@pytest.mark.parametrize('case', ['missing', 'existing', 'busy', 'incompatible_mode'])
def test_native_lock_preflight_never_replaces_or_chmods_existing_lock(parent_seam, case):
    directory, calls, _ = parent_seam
    lock = directory.parent / '.lock'
    before = None
    handle = None
    if case != 'missing':
        lock.write_bytes(b'cron lock evidence\n')
        lock.chmod(0o644 if case == 'incompatible_mode' else 0o600)
        before = lock.stat()
        if case == 'busy':
            handle = lock.open('ab')
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = parent.execute('agent-git-next', RUN)
    finally:
        if handle is not None:
            handle.close()
    if case in ('busy', 'incompatible_mode'):
        assert result['status'] == 'needs_reconciliation' and not result['executed']
        assert not calls and not (directory / 'transport').exists()
    else:
        assert result['status'] == 'awaiting_connector' and len(calls) == 1
    if before is not None:
        after = lock.stat()
        assert (after.st_dev, after.st_ino, after.st_mode) == (before.st_dev, before.st_ino, before.st_mode)
        assert lock.read_bytes() == b'cron lock evidence\n'
    else:
        # The fake native publisher does not create locks; the wrapper must not.
        assert not lock.exists()


@pytest.mark.parametrize('mode', ['missing_ready', 'wrong_ready', 'extra_ready', 'extra_json', 'truncated', 'signal'])
def test_real_subprocess_ready_or_output_failure_keeps_evidence_and_cleans_frame(parent_seam, offline_child, mode):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    offline_child['mode'] = mode
    result = accept(response)
    assert result['status'] == 'needs_reconciliation' and result['executed']
    assert result['next_action']['action'] == 'stop'
    assert response.read_bytes() == RESPONSE
    assert len(offline_child['calls']) == 1
    no_frame(directory)
    assert (directory / 'transport' / (parent.operation('accept', RUN, REQUEST) + '.response.json')).exists()
    # A second call never reaccepts even when parsing the completed child failed.
    again = accept(response)
    assert not again['executed'] and len(offline_child['calls']) == 1


def test_partial_file_frame_real_transport_refuses_without_receipt(parent_seam, offline_child, monkeypatch):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    offline_child['mode'] = 'partial_frame'

    def partial(handle, raw):
        handle.write(base64.b64encode(raw) + b'\n')
        handle.flush()
        os.fsync(handle.fileno())
        handle.seek(0)

    monkeypatch.setattr(parent, 'frame_file', partial)
    result = accept(response)
    assert result['code'] == 'transport_refused' and result['executed']
    assert response.read_bytes() == RESPONSE
    no_frame(directory)
    assert not (directory / 'transport' / (parent.operation('accept', RUN, REQUEST) + '.begin.json')).exists()
    again = accept(response)
    assert again['code'] == 'accept_attempt_requires_reconciliation' and not again['executed']
    assert len(offline_child['calls']) == 1


@pytest.mark.parametrize('mode,status,code', [('native_failure', 'failed', 7),
                                             ('failed_pending_read', 'failed', 1),
                                             ('failed_pending_write', 'needs_reconciliation', 1),
                                             ('awaiting_ci', 'awaiting_ci', 0),
                                             ('merge', 'awaiting_approval', 0)])
def test_native_failure_ci_wait_and_merge_stop_are_distinct(parent_seam, offline_child, mode, status, code):
    _, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    offline_child['mode'] = mode
    result = accept(response)
    assert result['status'] == status and result['native_exit_code'] == code
    assert result['next_action']['action'] == 'stop'
    assert result['next_action']['approval_required'] is True


def test_large_unicode_result_is_private_bounded_descriptor(parent_seam, offline_child):
    _, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    offline_child['mode'] = 'large'
    result = accept(response)
    assert result['status'] == 'awaiting_connector' and 'native' not in result
    descriptor = result['result_file']
    raw = Path(descriptor['path']).read_bytes()
    assert descriptor['bytes'] == len(raw) and descriptor['sha256'] == transport.digest(raw)
    assert descriptor['version'] == 'parent-result-file-v1'
    assert stat.S_IMODE(Path(descriptor['path']).stat().st_mode) == 0o600
    assert len(transport.encode(result)) < parent.MAX_WIRE
    assert result['next_action']['action'] == 'read_private_result_file'


@pytest.mark.parametrize('raw', [b'{}{}', b'{"x":1,"x":2}', b'NaN', b'null', b'\xff'])
def test_invalid_response_json_before_frame_or_native(parent_seam, offline_child, raw):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    response.write_bytes(raw)
    result = accept(response, raw=raw)
    assert result['status'] == 'failed' and not result['executed']
    assert not offline_child['calls'] and response.read_bytes() == raw
    no_frame(directory)


@pytest.mark.parametrize('unsafe', ['symlink', 'hardlink', 'mode', 'parent_mode', 'oversize', 'digest'])
def test_unsafe_response_path_and_hash_never_spawn(parent_seam, offline_child, unsafe):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    path = response
    if unsafe == 'symlink':
        path = response.with_name('alias')
        path.symlink_to(response)
    elif unsafe == 'hardlink':
        os.link(str(response), str(response.with_name('alias')))
    elif unsafe == 'mode':
        response.chmod(0o644)
    elif unsafe == 'parent_mode':
        response.parent.chmod(0o755)
    elif unsafe == 'oversize':
        with response.open('r+b') as handle:
            handle.truncate(transport.MAX_RESPONSE + 1)
    result = accept(path, raw=b'wrong hash' if unsafe == 'digest' else RESPONSE)
    assert result['status'] == 'failed' and not result['executed']
    assert not offline_child['calls'] and response.exists()
    no_frame(directory)


def test_input_replaced_after_frame_uses_snapshot(parent_seam, offline_child, monkeypatch):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    original = parent.frame_file

    def replace(handle, raw):
        original(handle, raw)
        replacement = response.with_name('replacement')
        replacement.write_bytes(b'{"replacement":true}')
        replacement.chmod(0o600)
        replacement.replace(response)

    monkeypatch.setattr(parent, 'frame_file', replace)
    result = accept(response)
    assert result['status'] == 'awaiting_connector' and result['executed']
    assert len(offline_child['calls']) == 1 and response.read_bytes() == b'{"replacement":true}'
    assert (directory / 'fixture-received.json').read_bytes() == RESPONSE
    assert (directory / 'transport' / (parent.operation('accept', RUN, REQUEST) + '.response.json')).read_bytes() == RESPONSE
    no_frame(directory)


def test_input_replaced_while_child_runs_retains_snapshot_and_receipt(parent_seam, offline_child, monkeypatch):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    original = parent.accept_process

    def replace(*args):
        envelope, code = original(*args)
        replacement = response.with_name('replacement')
        replacement.write_bytes(b'{"user":"newer response"}')
        replacement.chmod(0o600)
        replacement.replace(response)
        return envelope, code

    monkeypatch.setattr(parent, 'accept_process', replace)
    result = accept(response)
    assert result['status'] == 'awaiting_connector' and result['executed']
    assert response.read_bytes() == b'{"user":"newer response"}'
    assert (directory / 'transport' / (parent.operation('accept', RUN, REQUEST) + '.response.json')).read_bytes() == RESPONSE
    assert (directory / 'fixture-received.json').read_bytes() == RESPONSE
    no_frame(directory)


@pytest.mark.parametrize('during_child', [False, True])
def test_input_parent_losing_private_mode_after_snapshot(parent_seam, offline_child, monkeypatch, during_child):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    original = parent.accept_process if during_child else parent.frame_file

    def expose(*args):
        value = original(*args)
        response.parent.chmod(0o755)
        return value

    monkeypatch.setattr(parent, 'accept_process' if during_child else 'frame_file', expose)
    result = accept(response)
    assert result['status'] == 'awaiting_connector'
    assert result['executed'] and len(offline_child['calls']) == 1
    assert response.read_bytes() == RESPONSE
    saved = directory / 'transport' / (parent.operation('accept', RUN, REQUEST) + '.response.json')
    assert saved.read_bytes() == RESPONSE
    assert (directory / 'fixture-received.json').read_bytes() == RESPONSE
    no_frame(directory)


def test_same_size_mutation_before_read_with_restored_mtime_fails_digest(parent_seam, offline_child):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    before = response.stat()
    changed = RESPONSE.replace(b'text', b'next')
    assert len(changed) == len(RESPONSE) and changed != RESPONSE
    response.write_bytes(changed)
    os.utime(response, ns=(before.st_atime_ns, before.st_mtime_ns))
    result = accept(response)
    assert result['code'] == 'response_digest_mismatch' and not result['executed']
    assert not offline_child['calls']
    assert not (directory / ('parent-accept-' + parent.operation('accept', RUN, REQUEST) + '.json')).exists()
    no_frame(directory)


def test_snapshot_does_not_reopen_or_restat_response_after_read(parent_seam, offline_child, monkeypatch):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    original = parent.frame_file
    real_open, real_stat = os.open, os.stat

    def forbid_open(path, *args, **kwargs):
        assert isinstance(path, int) or os.fspath(path) not in (response.name, str(response))
        return real_open(path, *args, **kwargs)

    def forbid_stat(path, *args, **kwargs):
        assert isinstance(path, int) or os.fspath(path) not in (response.name, str(response))
        return real_stat(path, *args, **kwargs)

    def remove(handle, raw):
        original(handle, raw)
        response.unlink()
        monkeypatch.setattr(parent.os, 'open', forbid_open)
        monkeypatch.setattr(parent.os, 'stat', forbid_stat)

    monkeypatch.setattr(parent, 'frame_file', remove)
    result = accept(response)
    assert result['status'] == 'awaiting_connector'
    assert (directory / 'fixture-received.json').read_bytes() == RESPONSE
    assert (directory / 'transport' / (parent.operation('accept', RUN, REQUEST) + '.response.json')).read_bytes() == RESPONSE


def test_accept_snapshot_changed_during_fd_read_fails_before_dispatch(parent_seam, offline_child, monkeypatch):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    target = response.stat()
    original = os.fdopen
    changed = []

    def fdopen(fd, *args, **kwargs):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino) and not changed:
            response.write_bytes(RESPONSE.replace(b'text', b'next'))
            os.utime(response, ns=(target.st_atime_ns, target.st_mtime_ns))
            changed.append(True)
        return original(fd, *args, **kwargs)

    monkeypatch.setattr(parent.os, 'fdopen', fdopen)
    result = accept(response)
    assert result['code'] == 'response_digest_mismatch' and not result['executed']
    assert not offline_child['calls']
    no_frame(directory)


def test_response_other_owner_is_refused_without_chown(parent_seam, offline_child, monkeypatch):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    target = response.stat()
    real_fstat = os.fstat

    def fstat(fd):
        info = real_fstat(fd)
        if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino):
            fields = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
            fields['st_uid'] = info.st_uid + 1
            return SimpleNamespace(**fields)
        return info

    monkeypatch.setattr(parent.os, 'fstat', fstat)
    result = accept(response)
    assert result['code'] == 'unsafe_private_record' and not result['executed']
    assert not offline_child['calls']
    no_frame(directory)


def test_native_claim_wins_race_after_parent_preflight(parent_seam, offline_child, monkeypatch):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    original = parent.frame_file
    inflight = directory / 'transport/inflight.json'

    def raced(handle, raw):
        original(handle, raw)
        durable(inflight, {'another': 'native claimant'})

    monkeypatch.setattr(parent, 'frame_file', raced)
    result = accept(response)
    assert result['code'] == 'transport_refused' and result['executed']
    assert json.loads(inflight.read_text()) == {'another': 'native claimant'}
    assert response.read_bytes() == RESPONSE
    assert not (directory / 'transport' / (parent.operation('accept', RUN, REQUEST) + '.begin.json')).exists()
    no_frame(directory)


@pytest.mark.parametrize('failure', ['timeout', 'wait_io_error'])
def test_child_wait_failure_keeps_attempt_marker_and_never_reaccepts(parent_seam, monkeypatch, failure):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)

    class Child:
        killed = False

        def wait(self, timeout=None):
            if not self.killed:
                if failure == 'wait_io_error':
                    raise OSError('private child diagnostics')
                raise subprocess.TimeoutExpired('private child', timeout)
            return -9

        def kill(self):
            self.killed = True

    child = Child()
    monkeypatch.setattr(parent.subprocess, 'Popen', lambda *args, **kwargs: child)
    result = accept(response)
    assert result['code'] == 'child_exit_unknown' and child.killed
    assert result['native_exit_code'] is None and response.read_bytes() == RESPONSE
    no_frame(directory)
    again = accept(response)
    assert again['code'] == 'accept_attempt_requires_reconciliation' and not again['executed']


@pytest.mark.parametrize('fault', ['inline_hash', 'chunk_offset'])
def test_envelope_digest_and_chunk_boundaries_fail_closed(parent_seam, offline_child, monkeypatch, fault):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    if fault == 'inline_hash':
        original = parent.accept_process

        def corrupt(*args):
            envelope, code = original(*args)
            envelope['sha256'] = '0' * 64
            return envelope, code

        monkeypatch.setattr(parent, 'accept_process', corrupt)
    else:
        offline_child['mode'] = 'large'
        original = transport.chunk

        def corrupt(run, op, index):
            part = original(run, op, index)
            part['offset'] += 1
            return part

        monkeypatch.setattr(transport, 'chunk', corrupt)
    result = accept(response)
    assert result['status'] == 'needs_reconciliation' and result['executed']
    assert result['code'] in ('payload_digest_invalid', 'chunk_invalid')
    assert result['next_action']['action'] == 'stop'
    assert response.read_bytes() == RESPONSE
    no_frame(directory)


@pytest.mark.parametrize('marker', ['TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
                                 'TAVERN_IMPROVEMENT_UNATTENDED', 'READ_ONLY', 'GIT'])
def test_untrusted_context_denied_for_every_command(parent_seam, monkeypatch, marker):
    directory, calls, _ = parent_seam
    monkeypatch.setenv(marker, '0' if marker == 'GIT' else '1')
    for command in parent.COMMANDS:
        result = parent.execute(command, RUN)
        assert result['stage'] == 'authorization' and result['status'] == 'failed'
        assert not result['executed'] and result['next_action']['action'] == 'stop'
    assert not calls and not (directory / 'transport').exists()


@pytest.mark.parametrize('flag', ['read_only', 'simulated', 'no_git', 'github_enabled'])
def test_report_boundary_denies_before_transport(parent_seam, flag):
    directory, calls, _ = parent_seam
    report = json.loads((directory / 'report.json').read_text())
    report[flag] = flag != 'github_enabled'
    durable(directory / 'report.json', report)
    result = parent.execute('agent-git-next', RUN)
    assert result['code'] == 'side_effects_disabled' and not result['executed']
    assert not calls and not (directory / 'transport').exists()


@pytest.mark.parametrize('argv', [[], ['wat'], ['--help'], ['agent-git-next'],
                                  ['agent-git-next', '--run-id', 'bad'],
                                  ['agent-git-next', '--run-id', RUN, '--extra'],
                                  ['agent-git-accept-file', '--run-id', RUN],
                                  ['storage-path', '--target', 'archive']])
def test_argument_errors_are_one_versioned_json_without_stderr(capsys, argv):
    assert parent.main(argv) == 2
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert captured.err == '' and result['version'] == parent.VERSION
    assert result['status'] == 'failed' and result['stage'] == 'arguments'
    assert {'command', 'run', 'code', 'executed', 'side_effects', 'native_exit_code', 'next_action'} <= set(result)


def test_storage_resolve_then_prepare_has_explicit_effects(parent_seam):
    directory, _, _ = parent_seam
    result = parent.execute('storage-path', RUN, target='reports', category='checks', prepare=False)
    path = directory.parents[1] / 'checks' / RUN
    assert result['path'] == str(path) and not result['executed'] and not path.exists()
    prepared_result = parent.execute('storage-path', RUN, target='reports', category='checks', prepare=True)
    assert prepared_result['status'] == 'ready' and prepared_result['executed'] and path.is_dir()
    assert str(path) in prepared_result['side_effects']['created']
    again = parent.execute('storage-path', RUN, target='reports', category='checks', prepare=True)
    assert again['side_effects']['created'] == []


def test_v2_reports_cannot_escape_active_artifacts(parent_seam, monkeypatch):
    directory, _, _ = parent_seam
    root = directory.parents[3]
    mount = root.parent / 'mount'
    mount.mkdir(mode=0o700)

    class OfflineFS(storage.FileSystem):
        def mount_ready(self, path):
            return path == mount

        def free_bytes(self, path):
            return 10 ** 12

        def local_filesystem(self, path):
            return True

        def probe(self, path):
            pass

    selected = storage.Storage(root=root, version=2, config_path=root / 'synthetic.json', fs=OfflineFS(),
                               artifacts=storage.DirectorySpec(mount / 'artifacts', mount, 0),
                               temporary=storage.DirectorySpec(mount / 'temporary', mount, 0))
    monkeypatch.setattr(native, 'storage_policy', lambda: selected)
    outside = root / 'logs/reports'
    result = parent.execute('storage-path', target='reports', report_dir=str(outside), prepare=True)
    assert result['status'] == 'failed' and not result['executed']
    assert not outside.exists() and not selected.artifacts.path.exists()
    assert 'path' not in result and result['next_action']['action'] == 'stop'


def test_prepare_failure_records_partial_creations_and_stops(parent_seam, monkeypatch):
    directory, _, _ = parent_seam
    selected = native.storage_policy()
    path = selected.report_dir('checks') / RUN

    def partial(target):
        target.mkdir(parents=True, mode=0o700)
        raise storage.StorageError('private details must not be printed')

    monkeypatch.setattr(selected, 'ensure_directory', partial)
    monkeypatch.setattr(native, 'storage_policy', lambda: selected)
    result = parent.execute('storage-path', RUN, target='reports', category='checks', prepare=True)
    assert result['status'] == 'needs_reconciliation' and result['stage'] == 'prepare'
    assert str(path) in result['side_effects']['created']
    assert 'private details' not in json.dumps(result) and 'path' not in result
    assert result['next_action']['action'] == 'stop'


def test_park_adapter_uses_existing_module_and_preserves_stage(parent_seam, monkeypatch):
    from harness import worktree_park
    expected = parent.result_for('agent-worktree-park', RUN)
    expected.update(status='needs_reconciliation', stage='snapshot', code='snapshot_conflict')
    monkeypatch.setattr(worktree_park, 'park', lambda run: dict(expected))
    result = parent.execute('agent-worktree-park', RUN)
    assert result['stage'] == 'snapshot' and result['code'] == 'snapshot_conflict'
    assert result['native_exit_code'] is None


def test_real_isolated_git_fixture_unrelated_index_is_preserved(prepared):
    # Explicit fixture dependency isolates HOME, config, hooks and protocol.
    index = prepared['root'] / '.git/index'
    before = index.read_bytes()
    result = parent.execute('agent-worktree-park', RUN)
    assert result['status'] == 'needs_reconciliation'
    assert index.read_bytes() == before


def saved_descriptor(descriptor):
    path = Path(descriptor['path'])
    raw = path.read_bytes()
    assert len(raw) == descriptor['bytes'] and transport.digest(raw) == descriptor['sha256']
    info = path.stat()
    assert info.st_uid == os.geteuid() and info.st_nlink == 1
    assert stat.S_IMODE(info.st_mode) == 0o600
    return transport.parse(raw)


def retained_files(item):
    """Actual approved sources, index, snapshots, journal and receipt bytes/modes."""
    root, directory = item['root'], item['directory']
    paths = [root / name for name in ('edit.py', 'new.py', 'unrelated.py', '.git/index')]
    paths += [directory / name for name in ('github.json', 'github-approved.json', 'report.json')]
    for name in ('workspace', 'backup', 'transport'):
        paths += [path for path in (directory / name).rglob('*') if path.is_file()]
    return {str(path): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in paths}


def write_proof_input(item):
    """Save exact connector JSON pages; never invent missing native responses."""
    directory = item['directory']
    bundle = directory / 'proof-input-fixture'
    bundle.mkdir(mode=0o700, exist_ok=True)
    manifest = {'version': 'parent-proof-input-v1', 'run_id': directory.name, 'pr_number': 11,
                'journal_sha256': transport.digest((directory / 'github.json').read_bytes()),
                'approval_sha256': transport.digest((directory / 'github-approved.json').read_bytes()),
                'merge_sha': MERGE, 'responses': []}
    for index, response in enumerate(item['proof']['responses']):
        name = 'get-' + str(index) + '.json'
        raw = transport.encode(response['body'])
        (bundle / name).write_bytes(raw)
        (bundle / name).chmod(0o600)
        manifest['responses'].append({key: response[key] for key in ('method', 'url', 'status', 'complete')})
        manifest['responses'][-1].update(file=name, bytes=len(raw), sha256=transport.digest(raw))
    item.update(bundle=bundle, manifest=manifest)
    return save_proof_manifest(item)


def save_proof_manifest(item):
    raw = transport.encode(item['manifest'])
    path = item['bundle'] / 'manifest.json'
    path.write_bytes(raw)
    path.chmod(0o600)
    return transport.digest(raw)


def build_proof(item, sha256=None):
    return parent.execute('agent-git-proof-build', item['directory'].name, pr_number=11,
                          input_dir=str(item['bundle']), sha256=sha256 or save_proof_manifest(item))


def checks_for(proof):
    prefix = ('https://api.github.com/repos/' + proof['repository'] + '/commits/' + HEAD +
              '/check-runs?filter=latest&per_page=100&page=')
    return {'version': 'external-merge-checks-v1', 'run_id': proof['run_id'], 'pr_number': 11,
            'repository': proof['repository'], 'head_sha': HEAD,
            'responses': sorted([row for row in proof['responses'] if row['url'].startswith(prefix)],
                                key=lambda row: int(row['url'][len(prefix):]))}


@pytest.fixture
def native_proof_input(prepared, monkeypatch):
    # All gates and the request/receipt are real native calls. Only storage and
    # ambient guard settings are isolated; no native success seam is installed.
    for key in ('READ_ONLY', 'GIT', 'TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
                'TAVERN_IMPROVEMENT_UNATTENDED', 'TAVERN_WORKFLOW_DEMO', 'TAVERN_NO_GIT'):
        monkeypatch.delenv(key, raising=False)
    ledger, directory = prepared['ledger'], prepared['directory']
    to_pr(ledger)
    native.accept(ledger, pr_data(ledger, merge_commit_sha=TEST_MERGE))
    native.save(directory, ledger)
    first = parent.execute('agent-git-next', directory.name)
    assert first['code'] == 'native_result' and first['native_exit_code'] == 0
    assert first['request_file']['run_id'] == directory.name
    ledger = json.loads((directory / 'github.json').read_text())
    prefix = 'https://api.github.com/repos/' + ledger['config']['repository']
    responses = []

    def get(path, body):
        responses.append({'method': 'GET', 'url': prefix + path, 'status': 200,
                          'complete': True, 'body': body})

    get('/pulls/11', cleanup_pr_data(ledger))
    for sha in (HEAD, MERGE):
        get('/git/commits/' + sha, {'sha': sha, 'tree': {'sha': ledger['new_tree']},
                                   'parents': [{'sha': ledger['base_sha']}]})
    # Ten head pages distinguish numeric ordering from string sorting. Every
    # check is native-valid, and the required CI3 names occur on the last page.
    rows = [{'id': i + 10, 'name': 'extra-' + str(i), 'head_sha': HEAD,
             'app': {'slug': 'github-actions'}, 'status': 'completed', 'conclusion': 'success'}
            for i in range(900)]
    rows += [dict(row, id=1000 + index) for index, row in enumerate(rows_for(ledger))]
    for page in range(1, 11):
        body = {'total_count': len(rows), 'check_runs': rows[(page - 1) * 100:page * 100]}
        # Preserve and normalize a real supported connector envelope as well.
        if page == 1:
            body = {'structuredContent': {'content': json.dumps(body)}}
        get('/commits/' + HEAD + '/check-runs?filter=latest&per_page=100&page=' + str(page), body)
    get('/commits/' + TEST_MERGE + '/check-runs?filter=latest&per_page=100&page=1',
        {'total_count': len(rows_for(ledger)), 'check_runs': rows_for(ledger, sha=TEST_MERGE)})
    for sha in (HEAD, TEST_MERGE):
        get('/commits/' + sha + '/status', {'sha': sha, 'total_count': 0, 'statuses': []})
    get('', {'full_name': ledger['config']['repository'], 'default_branch': ledger['config']['base']})
    get('/branches?per_page=100&page=1', [{'name': 'other-' + str(i)} for i in range(100)])
    get('/branches?per_page=100&page=2',
        {'complete': True, 'page': 2, 'per_page': 100, 'truncated': False,
         'items': [{'name': ledger['branch'], 'protected': False, 'commit': {'sha': HEAD}}]})
    # This exact percent encoding is native cleanup_request's contract.
    get('/pulls?state=open&head=21in7%3Acodex%2F' + directory.name + '&per_page=100&page=1', [])
    proof = {'version': 'external-merge-proof-v1', 'run_id': directory.name, 'pr_number': 11,
             'repository': ledger['config']['repository'],
             'base': {'ref': ledger['config']['base'], 'sha': ledger['base_sha']},
             'head': {'ref': ledger['branch'], 'sha': HEAD}, 'merge_sha': MERGE,
             'responses': list(reversed(responses))}
    prepared.update(ledger=ledger, proof=proof, first=first, prefix=prefix)
    write_proof_input(prepared)
    return prepared


def test_proof_build_real_complete_gets_native_roundtrip(native_proof_input):
    item = native_proof_input
    before = retained_files(item)
    result = build_proof(item)
    assert result['code'] == 'proof_built' and result['status'] == 'ready'
    assert result['proof_build'] == {'version': 'parent-proof-build-v1', 'complete': True}
    proof, checks = [saved_descriptor(result[key]) for key in ('proof_file', 'checks_file')]
    candidate = native.external_merge_proof(item['ledger'], proof, 11)
    native.external_head_checks(item['ledger'], checks, proof)
    assert candidate['cleanup_proof']['check_sha'] == TEST_MERGE
    assert candidate['cleanup_proof']['open_prs'] == []
    assert candidate['cleanup_proof']['branch']['sha'] == HEAD
    assert checks['responses'] == checks_for(proof)['responses']
    assert [row['url'].rsplit('=', 1)[-1] for row in checks['responses']] == [str(i) for i in range(1, 11)]
    bodies = {row['url']: row['body'] for row in proof['responses']}
    assert all(row['body'] == bodies[row['url']] for row in checks['responses'])
    assert result['next_action'] == {'action': 'invoke_external_merge', 'trusted_parent_only': True,
        'command': 'agent-git-external-merge', 'required_arguments': {
            'run_id': item['directory'].name, 'pr_number': 11,
            'proof_file': result['proof_file']['path'], 'sha256': result['proof_file']['sha256'],
            'checks_file': result['checks_file']['path'], 'checks_sha256': result['checks_file']['sha256']}}
    assert result['side_effects']['created'] == [result[key]['path'] for key in ('proof_file', 'checks_file')]
    assert not result['side_effects']['transport_invoked'] and not result['side_effects']['native_invoked']
    assert retained_files(item) == before


@pytest.mark.parametrize('status,request_id,write,merged,checks,error', [
    ('awaiting_ci', None, False, False, True, None),
    ('awaiting_ci', None, None, False, True, None),
    ('awaiting_ci', None, False, False, False, 'external_checks_required'),
    ('awaiting_connector', REQUEST, True, False, False, None),
    ('awaiting_ci', REQUEST, True, False, True, 'external_pending_merge_required'),
    ('awaiting_ci', REQUEST, False, False, True, 'external_pending_merge_required'),
    ('awaiting_ci', None, True, False, True, 'external_pending_merge_required'),
    ('awaiting_ci', None, 0, False, True, 'external_pending_merge_required'),
    ('awaiting_connector', REQUEST, False, False, True, 'external_pending_merge_required'),
    ('awaiting_connector', REQUEST, 1, False, True, 'external_pending_merge_required'),
    ('awaiting_connector', None, True, False, True, 'external_pending_merge_required'),
    ('awaiting_connector', 'invalid', True, False, True, 'external_pending_merge_required'),
    ('awaiting_ci', None, False, True, True, 'external_pending_merge_required'),
    ('awaiting_connector', REQUEST, True, True, True, 'external_pending_merge_required')])
def test_external_merge_admission_at_merge(native_proof_input, monkeypatch,
        status, request_id, write, merged, checks, error):
    item = native_proof_input
    directory, ledger = item['directory'], item['ledger']
    ledger.update(status=status, step='merge', pending_request_id=request_id, pending_write=write)
    if merged:
        ledger['merge_sha'] = MERGE
    native.save(directory, ledger)
    arguments = {'pr_number': 11}
    for key, value in [('proof', item['proof']), ('checks', checks_for(item['proof']))]:
        path = directory / ('synthetic-' + key + '.json')
        durable(path, value)
        if key == 'proof' or checks:
            arguments[key + '_file'] = str(path)
            arguments['sha256' if key == 'proof' else 'checks_sha256'] = transport.digest(path.read_bytes())
    # Synthetic receipt and local cleanup seams; admission and both proof gates stay real.
    request = None if request_id is None else {'request_id': request_id, 'tool': native.TOOLS['merge_pull_request'],
        'arguments': {'repository_full_name': ledger['config']['repository'], 'pr_number': 11,
                      'expected_head_sha': HEAD, 'merge_method': 'squash'}}
    monkeypatch.setattr(parent, 'evidence', lambda *args: (
        ({'native_exit_code': 0}, None, {'request': request, 'github': {'status': status}}), {}))
    monkeypatch.setattr(parent.git_cleanup, 'Git', lambda *args: SimpleNamespace(ref=lambda ref: MERGE))
    for name in ('synced_checkout', 'verify_park'):
        monkeypatch.setattr(parent.ExternalMerge, name, lambda *args, **kwargs: None)
    cleaned = []

    def cleanup(*args, **kwargs):
        def run():
            cleaned.append(True)
            return dict(version='cleanup-v1', status='complete',
                        **{key: {} for key in ('remote', 'prune', 'sync', 'local', 'completion')})
        return SimpleNamespace(state={}, run_external=run)

    monkeypatch.setattr(parent.git_cleanup, 'Cleanup', cleanup)
    monkeypatch.setattr(parent.ExternalMerge, 'archive_phase', lambda self, *args:
        self.result.update(status='verified', code='synthetic_cleanup_complete'))
    before = retained_files(item)
    inputs = {path: path.read_bytes() for path in directory.glob('synthetic-*.json')}
    result = parent.execute('agent-git-external-merge', directory.name, **arguments)
    if error:
        assert result['code'] == error and not result['executed'] and not cleaned
        assert retained_files(item) == before
        assert all(path.read_bytes() == raw for path, raw in inputs.items())
        assert not (directory / 'external-merge.json').exists()
    else:
        assert result['status'] == 'verified' and result['code'] == 'synthetic_cleanup_complete'
        assert cleaned == [True] and result['side_effects']['cleanup_invoked']
        state = json.loads((directory / 'external-merge.json').read_text())
        assert state['discard']['status'] == ('no_request' if request_id is None else 'unsent_discarded')
        assert 'cleanup' in result['completed_stages']


@pytest.mark.parametrize('fault', ['missing_page', 'head', 'url'])
def test_proof_build_and_both_native_gates_reject_head_collection(native_proof_input, fault):
    item = native_proof_input
    proof = item['proof']
    suffix = '/commits/' + HEAD + '/check-runs?filter=latest&per_page=100&page=2'
    target = next(row for row in proof['responses'] if row['url'].endswith(suffix))
    if fault == 'missing_page':
        proof['responses'].remove(target)
    elif fault == 'head':
        target['body']['check_runs'][0]['head_sha'] = MERGE
    else:
        target['url'] = target['url'][:-1] + '02'
    checks = checks_for(proof)
    before = retained_files(item)
    with pytest.raises(native.ExternalProofError):
        native.external_merge_proof(item['ledger'], proof, 11)
    with pytest.raises(native.ExternalProofError):
        native.external_head_checks(item['ledger'], checks, proof)
    write_proof_input(item)
    result = build_proof(item)
    assert result['status'] == 'failed' and not result['executed']
    assert result['proof_build']['complete'] is False
    assert not result['side_effects']['created']
    assert not (item['directory'] / 'parent-proof.json').exists()
    if fault == 'missing_page':
        exact = {'method': 'GET', 'url': item['prefix'] + suffix}
        assert result['code'] == 'external_get_required'
        assert result['proof_build']['missing_get'] == exact
        assert {key: result['next_action'][key] for key in exact} == exact
        assert result['next_action']['action'] == 'collect_get'
        assert result['next_action']['then']['required_arguments']['input_dir'] == str(item['bundle'])
    else:
        assert result['next_action']['action'] == 'stop'
    assert retained_files(item) == before


@pytest.mark.parametrize('path', ['/pulls/11', '/git/commits/' + MERGE,
    '/commits/' + TEST_MERGE + '/check-runs?filter=latest&per_page=100&page=1',
    '/commits/' + TEST_MERGE + '/status', '', '/branches?per_page=100&page=2', 'open_prs'])
def test_proof_missing_required_get_collects_exact_url(native_proof_input, path):
    item = native_proof_input
    proof = item['proof']
    target = next(row for row in proof['responses'] if
                  ('/pulls?state=open&head=' in row['url'] if path == 'open_prs' else
                   row['url'] == item['prefix'] + path))
    proof['responses'].remove(target)
    write_proof_input(item)
    with pytest.raises(native.ExternalProofError) as error:
        native.external_merge_proof(item['ledger'], proof, 11)
    assert error.value.next_get == {'method': 'GET', 'url': target['url']}
    result = build_proof(item)
    assert result['code'] == 'external_get_required' and not result['executed']
    assert result['proof_build']['missing_get'] == error.value.next_get
    assert result['next_action']['action'] == 'collect_get'
    assert result['next_action']['url'] == target['url']
    assert not result['side_effects']['created']


@pytest.mark.parametrize('fault', ['pr_head', 'squash', 'update_branch', 'branch_head', 'protected',
    'test_merge_checks', 'test_merge_status', 'status_coverage', 'branch_page', 'open_pr_page'])
def test_proof_native_semantic_faults_never_build(native_proof_input, fault):
    item = native_proof_input
    rows = item['proof']['responses']
    def body(suffix):
        return next(row['body'] for row in rows if row['url'] == item['prefix'] + suffix)
    if fault == 'pr_head':
        body('/pulls/11')['head']['sha'] = MERGE
    elif fault == 'squash':
        body('/pulls/11')['merge_commit_sha'] = TEST_MERGE
    elif fault == 'update_branch':
        body('/git/commits/' + HEAD)['parents'].append({'sha': TEST_MERGE})
    elif fault in ('branch_head', 'protected'):
        branch = body('/branches?per_page=100&page=2')['items'][0]
        if fault == 'protected':
            branch['protected'] = True
        else:
            branch['commit']['sha'] = MERGE
    elif fault == 'test_merge_checks':
        body('/commits/' + TEST_MERGE + '/check-runs?filter=latest&per_page=100&page=1')['check_runs'][0]['conclusion'] = 'failure'
    elif fault == 'test_merge_status':
        body('/commits/' + TEST_MERGE + '/status').update(total_count=1, statuses=[{}], state='failure')
    elif fault == 'status_coverage':
        body('/commits/' + HEAD + '/status')['total_count'] = 1
    elif fault == 'branch_page':
        body('/branches?per_page=100&page=2')['page'] = 1
    else:
        row = next(row for row in rows if '/pulls?state=open&head=' in row['url'])
        row['body'] = {'complete': True, 'page': 1, 'per_page': 100, 'truncated': True, 'items': []}
    with pytest.raises(native.ExternalProofError):
        native.external_merge_proof(item['ledger'], item['proof'], 11)
    write_proof_input(item)
    before = retained_files(item)
    result = build_proof(item)
    assert result['stage'] == 'validate_proof' and result['status'] == 'failed'
    assert not result['executed'] and not result['side_effects']['created']
    assert result['next_action']['action'] == 'stop' and retained_files(item) == before


def test_native_open_pr_full_page_requires_final_short_page_then_still_blocks(native_proof_input):
    item = native_proof_input
    proof = item['proof']
    row = next(row for row in proof['responses'] if '/pulls?state=open&head=' in row['url'])
    row['body'] = [{'state': 'open', 'head': {'ref': item['ledger']['branch'],
                    'repo': {'full_name': item['ledger']['config']['repository']}}} for _ in range(100)]
    url = row['url'][:-1] + '2'
    with pytest.raises(native.ExternalProofError) as error:
        native.external_merge_proof(item['ledger'], proof, 11)
    assert error.value.next_get == {'method': 'GET', 'url': url}
    write_proof_input(item)
    assert build_proof(item)['next_action']['url'] == url
    proof['responses'].append({'method': 'GET', 'url': url, 'status': 200, 'complete': True, 'body': []})
    with pytest.raises(native.ExternalProofError, match='external_branch_not_deletable'):
        native.external_merge_proof(item['ledger'], proof, 11)
    write_proof_input(item)
    assert build_proof(item)['code'] == 'external_branch_not_deletable'


def test_native_checks_reject_conflicting_proof_body_even_with_successful_ci(native_proof_input):
    item = native_proof_input
    proof, checks = item['proof'], copy.deepcopy(checks_for(item['proof']))
    checks['responses'][-1]['body']['check_runs'][0]['check_suite'] = {'id': 987}
    native.external_merge_proof(item['ledger'], proof, 11)
    with pytest.raises(native.ExternalProofError, match='external_checks_proof_mismatch'):
        native.external_head_checks(item['ledger'], checks, proof)


@pytest.mark.parametrize('fault', ['incomplete', 'http_error', 'duplicate_id', 'old_run', 'head_identity'])
def test_native_proof_and_checks_both_reject_invalid_collections(native_proof_input, fault):
    item = native_proof_input
    proof = item['proof']
    checks = checks_for(proof)
    row = checks['responses'][-1]  # same in-memory response object as proof
    if fault == 'incomplete':
        row['complete'] = False
    elif fault == 'http_error':
        row['status'] = 500
    elif fault == 'duplicate_id':
        row['body']['check_runs'][0]['id'] = row['body']['check_runs'][1]['id']
    elif fault == 'old_run':
        proof['run_id'] = checks['run_id'] = '999999-abcdef'
    else:
        proof['head']['sha'] = checks['head_sha'] = MERGE
    with pytest.raises(native.ExternalProofError):
        native.external_merge_proof(item['ledger'], proof, 11)
    with pytest.raises(native.ExternalProofError):
        native.external_head_checks(item['ledger'], checks, proof)


@pytest.mark.parametrize('fault,code', [
    ('run', 'proof_manifest_invalid'), ('pr', 'proof_manifest_invalid'),
    ('journal', 'proof_manifest_identity_mismatch'), ('approval', 'proof_manifest_identity_mismatch'),
    ('method', 'proof_response_incomplete'), ('status', 'proof_response_incomplete'),
    ('incomplete', 'proof_response_incomplete'), ('duplicate_url', 'proof_response_url_mismatch'),
    ('repository_url', 'proof_response_url_mismatch'), ('duplicate_file', 'proof_response_path_invalid'),
    ('traversal', 'proof_response_path_invalid'), ('size', 'proof_response_size_mismatch'),
    ('hash', 'response_digest_mismatch')])
def test_proof_input_manifest_faults_preserve_sources(native_proof_input, fault, code):
    item = native_proof_input
    manifest = item['manifest']
    row = manifest['responses'][0]
    if fault == 'run':
        manifest['run_id'] = '999999-abcdef'
    elif fault == 'pr':
        manifest['pr_number'] = 12
    elif fault in ('journal', 'approval'):
        manifest[fault + '_sha256'] = '0' * 64
    elif fault == 'method':
        row['method'] = 'POST'
    elif fault == 'status':
        row['status'] = 206
    elif fault == 'incomplete':
        row['complete'] = False
    elif fault == 'duplicate_url':
        manifest['responses'][1]['url'] = row['url']
    elif fault == 'repository_url':
        row['url'] = 'https://api.github.com/repos/other/repo/pulls/11'
    elif fault == 'duplicate_file':
        manifest['responses'][1]['file'] = row['file']
    elif fault == 'traversal':
        row['file'] = '../get.json'
    elif fault == 'size':
        row['bytes'] += 1
    else:
        row['sha256'] = '0' * 64
    before = retained_files(item)
    result = build_proof(item)
    assert result['code'] == code and result['proof_build']['complete'] is False
    assert not result['executed'] and not result['side_effects']['created']
    assert retained_files(item) == before


@pytest.mark.parametrize('unsafe', ['mode', 'hardlink', 'symlink', 'parent_mode', 'manifest_hash', 'old_run'])
def test_proof_input_private_boundary(native_proof_input, unsafe):
    item = native_proof_input
    path = item['bundle'] / item['manifest']['responses'][0]['file']
    if unsafe == 'mode':
        path.chmod(0o644)
    elif unsafe == 'hardlink':
        os.link(str(path), str(item['bundle'] / 'alias'))
    elif unsafe == 'symlink':
        original = item['bundle'] / 'original'
        path.rename(original)
        path.symlink_to(original)
    elif unsafe == 'parent_mode':
        item['bundle'].chmod(0o755)
    before = retained_files(item)
    if unsafe == 'old_run':
        result = parent.execute('agent-git-proof-build', item['directory'].name, pr_number=11,
            input_dir=str(item['directory'].parent / '999999-abcdef' / item['bundle'].name),
            sha256=save_proof_manifest(item))
        assert result['code'] == 'proof_input_path_mismatch'
    else:
        result = build_proof(item, '0' * 64 if unsafe == 'manifest_hash' else None)
    assert result['status'] == 'failed' and not result['executed']
    assert not result['side_effects']['created'] and retained_files(item) == before


@pytest.mark.parametrize('name', ['parent-proof.json', 'parent-checks.json'])
def test_proof_output_collision_preserves_existing_file(native_proof_input, name):
    item = native_proof_input
    path = item['directory'] / name
    path.write_bytes(b'user retained output\n')
    path.chmod(0o640)
    before = retained_files(item)
    result = build_proof(item)
    assert result['code'] == 'proof_output_exists' and not result['executed']
    assert path.read_bytes() == b'user retained output\n' and stat.S_IMODE(path.stat().st_mode) == 0o640
    assert result['proof_build']['complete'] is False and not result['side_effects']['created']
    assert retained_files(item) == before


@pytest.mark.parametrize('failure_at', [1, 2, 3, 4])
def test_proof_partial_fsync_failure_reports_actual_outputs(native_proof_input, monkeypatch, failure_at):
    item = native_proof_input
    before = retained_files(item)
    real_fsync, calls = os.fsync, []
    def fail(fd):
        calls.append(fd)
        if len(calls) == failure_at:
            raise OSError('isolated output fsync failure')
        return real_fsync(fd)
    monkeypatch.setattr(parent.os, 'fsync', fail)
    result = build_proof(item)
    assert result['status'] == 'needs_reconciliation' and result['executed']
    assert result['proof_build']['complete'] is False and result['next_action']['action'] == 'stop'
    expected = ['parent-proof.json'] + (['parent-checks.json'] if failure_at > 2 else [])
    assert [Path(row['path']).name for row in result['partial_outputs']] == expected
    assert result['side_effects']['created'] == [str(item['directory'] / name) for name in expected]
    assert result['partial_outputs'][-1]['complete'] is False
    if failure_at > 2:
        assert result['partial_outputs'][0]['complete'] is True
        saved_descriptor(result['partial_outputs'][0])
    for name in expected:
        assert (item['directory'] / name).exists()
        assert stat.S_IMODE((item['directory'] / name).stat().st_mode) == 0o600
    assert retained_files(item) == before
    assert len(calls) == failure_at  # no automatic retry


def test_proof_readback_failure_retains_partial_file(native_proof_input, monkeypatch):
    item = native_proof_input
    real_new = parent.new_file
    class BadReadback:
        def __init__(self, handle):
            self.handle = handle
        def __getattr__(self, name):
            return getattr(self.handle, name)
        def __enter__(self):
            self.handle.__enter__()
            return self
        def __exit__(self, *args):
            return self.handle.__exit__(*args)
        def read(self, size):
            return b'wrong output readback'
    def output(directory_fd, name, *args, **kwargs):
        handle = real_new(directory_fd, name, *args, **kwargs)
        return BadReadback(handle) if name == 'parent-proof.json' else handle
    monkeypatch.setattr(parent, 'new_file', output)
    result = build_proof(item)
    assert result['code'] == 'output_readback_mismatch' and result['executed']
    assert result['proof_build']['complete'] is False
    assert result['partial_outputs'] == [{'path': str(item['directory'] / 'parent-proof.json'), 'complete': False}]
    assert (item['directory'] / 'parent-proof.json').exists()
    assert not (item['directory'] / 'parent-checks.json').exists()


def test_proof_responses_are_read_once_then_only_memory_used(native_proof_input, monkeypatch):
    item = native_proof_input
    real_snapshot = parent.response_snapshot
    reads = []
    def snapshot(selected, path, sha256):
        reads.append(str(path))
        raw = real_snapshot(selected, path, sha256)
        # Replacing connector files after their one safe read must neither
        # change outputs nor cause another response-path read/stat.
        Path(path).unlink()
        return raw
    monkeypatch.setattr(parent, 'response_snapshot', snapshot)
    result = build_proof(item)
    assert result['code'] == 'proof_built'
    assert len(reads) == len(set(reads)) == len(item['manifest']['responses']) + 1
    proof, checks = [saved_descriptor(result[key]) for key in ('proof_file', 'checks_file')]
    assert proof == item['proof']
    native.external_merge_proof(item['ledger'], proof, 11)
    native.external_head_checks(item['ledger'], checks, proof)


def read_next(descriptor, run=RUN, sha256=None, path=None):
    return parent.execute('agent-git-next-file', run, request_file=path or descriptor['path'],
                          sha256=sha256 or descriptor['sha256'])


def test_next_file_roundtrip_preserves_bridge_and_receipts(parent_seam, offline_child):
    directory, calls, response = parent_seam
    first = parent.execute('agent-git-next', RUN)
    descriptor = first['request_file']
    document = saved_descriptor(descriptor)
    assert document['version'] == 'parent-next-file-v1' and document['run_id'] == RUN
    assert document['request'] == first['native']['request']
    assert document['request_sha256'] == transport.digest(transport.encode(document['request']))
    assert document['operation_id'] == first['transport']['operation_id']
    before = {p.name: p.read_bytes() for p in (directory / 'transport').iterdir()}
    journal = (directory / 'github.json').read_bytes()
    result = read_next(descriptor)
    assert result['code'] == 'exact_request_verified' and result['status'] == 'ready'
    assert result['exact_request'] == document['request'] and result['poll_after_seconds'] == 0
    assert result['redispatch_authorized'] is False
    assert result['side_effects']['read_only'] and result['side_effects']['writes'] is False
    assert result['side_effects']['created'] == [] and not result['executed']
    assert result['next_action']['tool'] == first['next_action']['tool']
    assert result['next_action']['arguments'] == first['next_action']['arguments']
    assert result['next_action']['then'] == first['next_action']['then']
    assert {p.name: p.read_bytes() for p in (directory / 'transport').iterdir()} == before
    assert (directory / 'github.json').read_bytes() == journal and len(calls) == 1
    second = accept(response)
    assert second['request_file']['request_id'] == NEXT
    assert read_next(descriptor)['next_action']['action'] == 'stop'
    assert len(offline_child['calls']) == 1


def test_next_large_request_has_run_bound_verified_exact_descriptor(parent_seam, offline_child):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    offline_child['mode'] = 'large'
    accepted = accept(response)
    descriptor = accepted['request_file']
    document = saved_descriptor(descriptor)
    assert document['request'] is None
    result = read_next(descriptor)
    assert result['code'] == 'exact_request_verified' and 'exact_request' not in result
    exact = result['exact_request_file']
    payload = saved_descriptor(exact)
    assert exact['run_id'] == RUN and exact['request_id'] == NEXT
    assert exact['path'] == str(directory / ('parent-exact-' + NEXT + '.json'))
    assert exact['version'] == 'parent-exact-request-v1'
    assert payload['tool'] == native.TOOLS['fetch'] and payload['request_id'] == NEXT
    assert exact['request_sha256'] == transport.digest(transport.encode(payload))
    assert result['next_action']['arguments_from'] == 'verified_exact_request.arguments'
    assert result['next_action']['redispatch_authorized'] is False
    assert len(transport.encode(result)) < parent.MAX_WIRE
    assert accepted['next_action']['action'] == 'read_private_result_file'


@pytest.mark.parametrize('fault', ['new_hash_tamper', 'descriptor_tamper', 'old_run', 'traversal', 'hash'])
def test_next_file_identity_rejects_tamper_and_wrong_path(parent_seam, fault):
    directory, calls, _ = parent_seam
    first = parent.execute('agent-git-next', RUN)
    descriptor = first['request_file']
    path, digest = descriptor['path'], descriptor['sha256']
    if fault in ('new_hash_tamper', 'descriptor_tamper'):
        document = saved_descriptor(descriptor)
        if fault == 'new_hash_tamper':
            document['request']['arguments']['url'] = 'different'
        else:
            document['result_file']['path'] = '/unapproved/descriptor/stdout'
        raw = transport.encode(document)
        Path(path).write_bytes(raw)
        digest = transport.digest(raw)
    elif fault == 'old_run':
        path = str(directory.parent / '999999-abcdef' / Path(path).name)
    elif fault == 'traversal':
        path = str(directory) + '/proof-input-fixture/../' + Path(path).name
    else:
        digest = '0' * 64
    before = {p.name: p.read_bytes() for p in (directory / 'transport').iterdir()}
    result = read_next(descriptor, path=path, sha256=digest)
    assert result['next_action']['action'] == 'stop' and not result['executed']
    assert result['code'] == ('next_file_identity_mismatch' if fault.endswith('tamper') else
                              'response_digest_mismatch' if fault == 'hash' else 'next_file_path_mismatch')
    assert {p.name: p.read_bytes() for p in (directory / 'transport').iterdir()} == before
    assert len(calls) == 1


@pytest.mark.parametrize('fault', ['inflight.json', 'head.next', 'orphan.begin.json', 'begin', 'attempt', 'external', 'stale'])
def test_next_file_rejects_unknown_dispatch_checkpoint_and_stale_pending(parent_seam, fault):
    directory, calls, _ = parent_seam
    descriptor = parent.execute('agent-git-next', RUN)['request_file']
    if fault == 'external':
        durable(directory / 'external-merge.json', {'version': 'external-merge-v1'})
    elif fault == 'attempt':
        durable(directory / ('parent-accept-' + parent.operation('accept', RUN, REQUEST) + '.json'),
                {'version': 'parent-accept-attempt-v1', 'run_id': RUN,
                 'request_id': REQUEST, 'response_sha256': '0' * 64})
    elif fault == 'stale':
        ledger = json.loads((directory / 'github.json').read_text())
        ledger['pending_request_id'] = NEXT
        durable(directory / 'github.json', ledger)
    elif fault == 'begin':
        durable(directory / 'transport' / (parent.operation('accept', RUN, REQUEST) + '.begin.json'), {})
    else:
        durable(directory / 'transport' / fault, {})
    result = read_next(descriptor)
    assert result['status'] == 'failed' and result['next_action']['action'] == 'stop'
    assert not result['executed'] and not result['side_effects']['created'] and len(calls) == 1


@pytest.mark.parametrize('mode', ['merge', 'awaiting_ci', 'native_failure', 'failed_pending_read'])
def test_next_file_never_exports_terminal_native_result(parent_seam, offline_child, mode):
    _, _, response = parent_seam
    first = parent.execute('agent-git-next', RUN)
    offline_child['mode'] = mode
    terminal = accept(response)
    assert terminal['next_action']['action'] == 'stop' and 'request_file' not in terminal
    if mode == 'merge':
        assert terminal['code'] == 'stop_before_merge'
    result = read_next(first['request_file'])
    assert result['next_action']['action'] == 'stop' and 'exact_request' not in result
    assert not result['executed'] and len(offline_child['calls']) == 1


@pytest.mark.parametrize('failure', ['collision', 'fsync', 'reader'])
def test_accept_success_export_failure_preserves_native_result_no_reaccept(parent_seam, offline_child, monkeypatch, failure):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    path = directory / ('parent-next-' + NEXT + '.json')
    if failure == 'collision':
        path.write_bytes(b'existing user output')
        path.chmod(0o640)
    elif failure == 'reader':
        def denied(*args, **kwargs):
            raise parent.Stop('isolated reader failure')
        monkeypatch.setattr(parent, 'next_file', denied)
    else:
        real_save = parent.save_next_file
        def fail_export(*args, **kwargs):
            # Inject only export IO, after the native child has durably accepted.
            def fail(fd):
                raise OSError('isolated export fsync failure')
            with monkeypatch.context() as patch:
                patch.setattr(parent.os, 'fsync', fail)
                return real_save(*args, **kwargs)
        monkeypatch.setattr(parent, 'save_next_file', fail_export)
    result = accept(response)
    assert result['code'] == ('isolated reader failure' if failure == 'reader' else 'next_file_write_failed')
    assert result['native_result_retained'] is True
    assert result['status'] == 'needs_reconciliation' and result['next_action']['action'] == 'stop'
    assert result['native_exit_code'] == 0
    if failure == 'reader':
        assert 'native' not in result and 'transport' not in result
    else:
        assert result['native']['request']['request_id'] == NEXT
        assert result['transport']['operation_id'] == parent.operation('accept', RUN, REQUEST)
    before = {p.name: p.read_bytes() for p in (directory / 'transport').iterdir()}
    assert accept(response)['code'] == 'duplicate_response'
    assert {p.name: p.read_bytes() for p in (directory / 'transport').iterdir()} == before
    assert len(offline_child['calls']) == 1
    if failure == 'collision':
        assert path.read_bytes() == b'existing user output' and stat.S_IMODE(path.stat().st_mode) == 0o640
    else:
        assert str(path) in result['side_effects']['created'] and path.exists()


@pytest.mark.parametrize('argv', [
    ['agent-git-proof-build'], ['agent-git-next-file'],
    ['agent-git-proof-build', '--run-id', RUN, '--pr-number', 'x', '--input-dir', '/x', '--sha256', '0' * 64],
    ['agent-git-proof-build', '--run-id', RUN, '--pr-number', '11', '--input-dir', '/x'],
    ['agent-git-next-file', '--run-id', RUN, '--request-file', '/x', '--sha256', 'bad'],
    ['agent-git-next-file', '--run-id', RUN, '--request-file', '/x', '--sha256', '0' * 64, '--request-id', REQUEST]])
def test_new_file_commands_cli_errors_are_versioned_json(capsys, argv):
    assert parent.main(argv) == 2
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert not captured.err and result['version'] == parent.VERSION
    assert result['code'] == 'invalid_arguments' and not result['executed']


@pytest.fixture
def large_request(prepared, monkeypatch):
    """Real private FS, isolated Git checkout and transport; only native API is fake."""
    directory = prepared['directory']
    for key in ('READ_ONLY', 'GIT', 'TAVERN_WORKFLOW_DEMO', 'TAVERN_NO_GIT',
                'TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY', 'TAVERN_IMPROVEMENT_UNATTENDED'):
        monkeypatch.delenv(key, raising=False)
    selected = storage.resolve_storage(prepared['root'], env={})
    monkeypatch.setattr(native, 'storage_policy', lambda: selected)
    request = {'tool': native.TOOLS['create_tree'], 'arguments': {'owner': 'fixture', 'repo': 'fixture',
               'tree': [{'path': 'fixture.txt', 'mode': '100644', 'type': 'blob',
                         'content': '한글 🐈' * 20000}]}, 'request_id': REQUEST}
    request['arguments']['tree'][0]['content'] += 'x' * (251052 - len(transport.encode(request)))
    assert len(transport.encode(request)) == 251052
    calls = []

    def fake(args):
        calls.append(args)
        ledger = json.loads((directory / 'github.json').read_text())
        ledger.update(pending_request_id=REQUEST, pending_write=True,
                      status='awaiting_connector')
        durable(directory / 'github.json', ledger)
        print(json.dumps({'run_id': RUN, 'github': {'status': 'awaiting_connector'},
                          'request': request, 'poll_after_seconds': 0}, ensure_ascii=False))
        return 0

    monkeypatch.setattr(native, 'main', fake)
    return SimpleNamespace(directory=directory, request=request, calls=calls, prepared=prepared)


def native_bytes(directory):
    return {'github.json': (directory / 'github.json').read_bytes(),
            **{p.name: p.read_bytes() for p in (directory / 'transport').iterdir()}}


def assert_no_dispatch(result):
    assert result['next_action']['action'] == 'stop'
    assert not any(key in result for key in ('native', 'transport', 'result_file', 'request_file',
                                              'exact_request', 'exact_request_file'))
    assert not any(key in result['next_action'] for key in ('tool', 'arguments', 'descriptor'))


def test_251052_byte_create_tree_assembles_private_file_and_revalidates(large_request, monkeypatch):
    item = large_request
    chunk = transport.chunk
    reads = []

    def observed(run, operation, index):
        part = chunk(run, operation, index)
        reads.append(index)
        data = base64.b64decode(part['data'], validate=True)
        assert part['chunk_sha256'] == transport.digest(data)
        assert part['sha256'] != part['chunk_sha256']
        return part

    monkeypatch.setattr(transport, 'chunk', observed)
    first = parent.execute('agent-git-next', RUN)
    assert first['code'] == 'native_result' and first['transport']['chunks']['count'] == 21
    assert reads == list(range(21)) * 2  # finish and its real next-file reader
    exact = first['exact_request_file']
    assert exact['version'] == 'parent-exact-request-v1' and exact['bytes'] == 251052
    path = Path(exact['path'])
    assert path.parent == item.directory and path.name == 'parent-exact-' + REQUEST + '.json'
    assert path.read_bytes() == transport.encode(item.request)
    assert exact['sha256'] == transport.digest(path.read_bytes()) == exact['request_sha256']
    assert saved_descriptor(exact) == item.request
    info = path.stat()
    assert info.st_uid == os.geteuid() and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600
    assert str(path) in first['side_effects']['created']
    assert first['executed'] and first['side_effects']['writes'] and not first['side_effects']['read_only']
    before = native_bytes(item.directory)
    for _ in range(2):
        result = read_next(first['request_file'])
        assert result['code'] == 'exact_request_verified' and result['exact_request_file'] == exact
        assert result['redispatch_authorized'] is False and not result['executed']
        assert result['side_effects']['read_only'] and not result['side_effects']['writes']
        assert result['side_effects']['created'] == []
        assert parent.identity(path.stat()) == parent.identity(info)
        assert native_bytes(item.directory) == before
    assert len(item.calls) == 1
    assert (item.prepared['root'] / '.git/index').read_bytes() == item.prepared['index_before']


@pytest.mark.parametrize('fault,code', [
    ('missing', 'chunk_invalid'), ('operation_id', 'chunk_invalid'), ('index', 'chunk_invalid'),
    ('offset', 'chunk_invalid'), ('bytes', 'chunk_invalid'), ('total_bytes', 'chunk_invalid'),
    ('boolean', 'chunk_invalid'), ('sha256', 'chunk_invalid'),
    ('chunk_sha256', 'chunk_digest_invalid'), ('data', 'chunk_digest_invalid'),
    ('assembled_sha', 'payload_digest_invalid')])
def test_large_chunk_faults_never_export_or_dispatch(large_request, monkeypatch, fault, code):
    chunk = transport.chunk

    def corrupt(run, operation, index):
        part = chunk(run, operation, index)
        if index == 1:
            if fault == 'missing':
                return None
            if fault in ('data', 'assembled_sha'):
                data = bytearray(base64.b64decode(part['data']))
                data[0] ^= 1
                part['data'] = base64.b64encode(data).decode('ascii')
                if fault == 'assembled_sha':
                    part['chunk_sha256'] = transport.digest(data)
            elif fault == 'boolean':
                part['index'] = True
            elif fault in ('sha256', 'chunk_sha256', 'operation_id'):
                part[fault] = '0' * 64
            else:
                part[fault] += 1
        return part

    monkeypatch.setattr(transport, 'chunk', corrupt)
    result = parent.execute('agent-git-next', RUN)
    assert result['code'] == code
    assert_no_dispatch(result)
    assert not list(large_request.directory.glob('parent-*.json'))
    assert len(large_request.calls) == 1


@pytest.mark.parametrize('fault', ['collision', 'partial', 'tamper', 'symlink', 'hardlink', 'mode'])
def test_exact_file_conflicts_are_preserved_and_stop(large_request, fault):
    directory = large_request.directory
    path = directory / ('parent-exact-' + REQUEST + '.json')
    if fault in ('tamper', 'hardlink', 'mode'):
        first = parent.execute('agent-git-next', RUN)
        if fault == 'tamper':
            path.write_bytes(path.read_bytes().replace(b'fixture.txt', b'changed.txt'))
        elif fault == 'hardlink':
            os.link(str(path), str(directory / 'retained-link'))
        else:
            path.chmod(0o640)
    elif fault == 'symlink':
        target = directory / 'retained-target'
        target.write_bytes(b'preserve')
        path.symlink_to(target)
    else:
        path.write_bytes(b'conflict' if fault == 'collision' else transport.encode(large_request.request)[:100])
        path.chmod(0o600)
    before = path.read_bytes()
    inode = path.lstat().st_ino
    result = read_next(first['request_file']) if fault in ('tamper', 'hardlink', 'mode') else (
        parent.execute('agent-git-next', RUN))
    if fault in ('tamper', 'hardlink', 'mode', 'collision', 'partial'):
        assert_no_dispatch(result)
    assert result['next_action']['action'] == 'stop'
    assert 'exact_request_file' not in result
    assert path.read_bytes() == before and path.lstat().st_ino == inode
    if fault in ('collision', 'partial', 'tamper'):
        assert result['code'] == 'exact_request_file_conflict'
    assert len(large_request.calls) == 1


@pytest.mark.parametrize('fault', ['old_run', 'stale'])
def test_large_request_run_and_pending_freshness(large_request, fault):
    first = parent.execute('agent-git-next', RUN)
    descriptor = first['request_file']
    if fault == 'old_run':
        path = str(large_request.directory.parent / '999999-abcdef' / Path(descriptor['path']).name)
        result = read_next(descriptor, path=path)
    else:
        ledger = json.loads((large_request.directory / 'github.json').read_text())
        ledger['pending_request_id'] = NEXT
        durable(large_request.directory / 'github.json', ledger)
        result = read_next(descriptor)
    assert_no_dispatch(result)
    assert not result['executed'] and len(large_request.calls) == 1


@pytest.mark.parametrize('remaining', [301, 300, 299.5])
def test_first_next_and_reader_write_deadline_boundary(large_request, monkeypatch, remaining):
    deadline = json.loads((large_request.directory / 'github.json').read_text())['deadline']
    clock = {'now': deadline - remaining}
    monkeypatch.setattr(parent, 'time', SimpleNamespace(time=lambda: clock['now']))
    first = parent.execute('agent-git-next', RUN)
    assert first['publish_remaining_seconds'] == remaining and first['minimum_write_seconds'] == 300
    if remaining < 300:
        assert first['code'] == 'deadline_insufficient'
        assert_no_dispatch(first)
        assert not list(large_request.directory.glob('parent-*.json'))
    else:
        assert first['code'] == 'native_result'
        descriptor = first['request_file']
        before = native_bytes(large_request.directory)
        clock['now'] = deadline - 300
        reader = read_next(descriptor)
        assert reader['code'] == 'exact_request_verified' and reader['publish_remaining_seconds'] == 300
        clock['now'] += 0.5
        reader = read_next(descriptor)
        assert reader['code'] == 'deadline_insufficient'
        assert reader['publish_remaining_seconds'] == 299.5
        assert_no_dispatch(reader)
        assert native_bytes(large_request.directory) == before
        assert not reader['executed'] and reader['side_effects']['writes'] is False
    assert len(large_request.calls) == 1


@pytest.mark.parametrize('entry', ['reader', 'accept'])
def test_time_drops_during_chunk_assembly_at_every_export_boundary(
        parent_seam, offline_child, monkeypatch, entry):
    directory, _, response = parent_seam
    deadline = json.loads((directory / 'github.json').read_text())['deadline']
    clock = {'now': deadline - 301}
    monkeypatch.setattr(parent, 'time', SimpleNamespace(time=lambda: clock['now']))
    first = parent.execute('agent-git-next', RUN)
    if entry == 'reader':
        offline_child['mode'] = 'large_write'
        first = accept(response)
    chunk = transport.chunk
    native_after_accept = {}

    def falling(run, operation, index):
        part = chunk(run, operation, index)
        if index == 1:
            clock['now'] = deadline - 299
        return part

    monkeypatch.setattr(transport, 'chunk', falling)
    if entry == 'accept':
        offline_child['mode'] = 'large_write'
        real = parent.accept_process

        def snapshot(*args):
            result = real(*args)
            native_after_accept.update(native_bytes(directory))
            return result

        monkeypatch.setattr(parent, 'accept_process', snapshot)
        result = accept(response)
        assert result['native_result_retained'] is True
        assert native_bytes(directory) == native_after_accept
        assert accept(response)['code'] == 'duplicate_response'
    else:
        before = native_bytes(directory)
        result = read_next(first['request_file'])
        assert native_bytes(directory) == before
    assert result['code'] == 'deadline_insufficient' and result['publish_remaining_seconds'] == 299
    assert_no_dispatch(result)
    assert len(offline_child['calls']) == 1


def test_first_next_time_drops_during_assembly(large_request, monkeypatch):
    deadline = json.loads((large_request.directory / 'github.json').read_text())['deadline']
    clock = {'now': deadline - 301}
    monkeypatch.setattr(parent, 'time', SimpleNamespace(time=lambda: clock['now']))
    chunk = transport.chunk

    def falling(run, operation, index):
        part = chunk(run, operation, index)
        if index == 1:
            clock['now'] = deadline - 299
        return part

    monkeypatch.setattr(transport, 'chunk', falling)
    result = parent.execute('agent-git-next', RUN)
    assert result['code'] == 'deadline_insufficient' and result['publish_remaining_seconds'] == 299
    assert_no_dispatch(result)
    assert len(large_request.calls) == 1


@pytest.mark.parametrize('mode', ['write', 'large_write'])
def test_accept_retains_current_response_once_and_blocks_only_next_write(
        parent_seam, offline_child, monkeypatch, mode):
    directory, calls, response = parent_seam
    deadline = json.loads((directory / 'github.json').read_text())['deadline']
    clock = {'now': deadline - 301}
    monkeypatch.setattr(parent, 'time', SimpleNamespace(time=lambda: clock['now']))
    first = parent.execute('agent-git-next', RUN)
    assert first['code'] == 'native_result'
    offline_child['mode'] = mode
    clock['now'] = deadline - 299
    real = parent.accept_process
    retained = {}

    def snapshot(*args):
        result = real(*args)
        retained.update(native_bytes(directory))
        return result

    monkeypatch.setattr(parent, 'accept_process', snapshot)
    result = accept(response)
    assert result['code'] == 'deadline_insufficient'
    assert result['publish_remaining_seconds'] == 299 and result['minimum_write_seconds'] == 300
    assert result['native_result_retained'] is True and result['native_exit_code'] == 0
    assert_no_dispatch(result)
    assert native_bytes(directory) == retained
    assert (directory / 'fixture-received.json').read_bytes() == RESPONSE
    assert accept(response)['code'] == 'duplicate_response'
    assert len(calls) == len(offline_child['calls']) == 1
    assert native_bytes(directory) == retained
    assert not (directory / ('parent-next-' + NEXT + '.json')).exists()


def test_reads_keep_inline_contract_even_with_no_time(parent_seam, offline_child, monkeypatch):
    directory, _, response = parent_seam
    deadline = json.loads((directory / 'github.json').read_text())['deadline']
    monkeypatch.setattr(parent, 'time', SimpleNamespace(time=lambda: deadline + 1))
    first = parent.execute('agent-git-next', RUN)
    assert first['code'] == 'native_result' and first['publish_remaining_seconds'] == 0
    result = read_next(first['request_file'])
    assert result['exact_request'] == first['native']['request']
    assert result['code'] == 'exact_request_verified' and result['publish_remaining_seconds'] == 0
    second = accept(response)
    assert second['code'] == 'native_result' and second['publish_remaining_seconds'] == 0
    assert second['native_result_retained'] is True


@pytest.mark.parametrize('value', [None, True, False, 0, -1, '1800', float('nan'), float('inf'), -float('inf')])
def test_invalid_deadline_stops_before_native_or_local_output(parent_seam, value):
    directory, calls, _ = parent_seam
    ledger = json.loads((directory / 'github.json').read_text())
    if value is None:
        ledger.pop('deadline')
    else:
        ledger['deadline'] = value
    # Deliberately invalid JSON constants also exercise strict journal decoding.
    (directory / 'github.json').write_text(json.dumps(ledger))
    before = (directory / 'github.json').read_bytes()
    result = parent.execute('agent-git-next', RUN)
    assert result['code'] in ('invalid_publish_deadline', 'invalid_json')
    assert_no_dispatch(result)
    assert not calls and not result['executed'] and not (directory / 'transport').exists()
    assert (directory / 'github.json').read_bytes() == before


@pytest.mark.parametrize('value', [None, True, False, 0, -1, '300', float('nan'), float('inf'), -float('inf')])
@pytest.mark.parametrize('command', ['agent-git-next', 'agent-git-next-file', 'agent-git-accept-file'])
def test_invalid_minimum_is_local_input_and_has_no_effects(parent_seam, value, command):
    directory, calls, _ = parent_seam
    before = (directory / 'github.json').read_bytes()
    result = parent.execute(command, RUN, minimum_write_seconds=value)
    assert result['code'] == 'invalid_minimum_write_seconds'
    assert_no_dispatch(result)
    assert not calls and not result['executed'] and not (directory / 'transport').exists()
    assert (directory / 'github.json').read_bytes() == before


@pytest.mark.parametrize('mode', ['native_failure', 'awaiting_ci', 'failed_pending_write', 'merge'])
def test_low_time_preserves_terminal_native_failure_and_merge_stop(parent_seam, offline_child, monkeypatch, mode):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    deadline = json.loads((directory / 'github.json').read_text())['deadline']
    monkeypatch.setattr(parent, 'time', SimpleNamespace(time=lambda: deadline - 1))
    offline_child['mode'] = mode
    result = accept(response)
    assert result['code'] == ('stop_before_merge' if mode == 'merge' else 'native_result')
    assert result['next_action']['action'] == 'stop' and 'request_file' not in result
    assert result['publish_remaining_seconds'] == 1 and result['native_result_retained'] is True
    assert result['native_exit_code'] == (7 if mode == 'native_failure' else 1 if mode == 'failed_pending_write' else 0)
    assert len(offline_child['calls']) == 1


@pytest.mark.parametrize('command', ['agent-git-next', 'agent-git-next-file', 'agent-git-accept-file'])
@pytest.mark.parametrize('value', ['0', '-1', 'true', 'nan', 'inf', '-inf'])
def test_minimum_cli_rejects_invalid_values_without_execution(monkeypatch, capsys, command, value):
    def forbidden(*args, **kwargs):
        pytest.fail('invalid minimum reached execution')
    monkeypatch.setattr(parent, 'execute', forbidden)
    argv = [command, '--run-id', RUN, '--minimum-write-seconds=' + value]
    if command == 'agent-git-next-file':
        argv += ['--request-file', '/unused', '--sha256', '0' * 64]
    if command == 'agent-git-accept-file':
        argv += ['--request-id', REQUEST, '--response-file', '/unused', '--sha256', '0' * 64]
    assert parent.main(argv) == 2
    result = json.loads(capsys.readouterr().out)
    assert result['code'] == 'invalid_arguments' and not result['executed']


@pytest.mark.parametrize('command', ['agent-git-next', 'agent-git-next-file', 'agent-git-accept-file'])
@pytest.mark.parametrize('minimum', [None, '12.5'])
def test_make_and_cli_forward_local_minimum(monkeypatch, capsys, command, minimum):
    # Dry-run only, when the orchestrator runs this regression; no publication.
    argv = ['make', '--no-print-directory', '--dry-run', command, 'PYTHON=python3', 'RUN_ID=' + RUN,
            'REQUEST_ID=' + REQUEST, 'REQUEST_FILE=/unused/request',
            'RESPONSE_FILE=/unused/response', 'RESPONSE_SHA256=' + '0' * 64]
    if minimum is not None:
        argv.append('MINIMUM_WRITE_SECONDS=' + minimum)
    output = subprocess.run(argv, cwd=str(Path(__file__).resolve().parents[1]),
                            check=True, capture_output=True, text=True).stdout.strip()
    words = shlex.split(output)
    assert words[:3] == ['python3', '-m', 'harness.parent_commands']
    seen = []

    def capture(command, run, **kwargs):
        seen.append((command, run, kwargs))
        result = parent.result_for(command, run)
        result['code'] = 'test_stop'
        return result

    monkeypatch.setattr(parent, 'execute', capture)
    assert parent.main(words[3:]) == 1
    assert json.loads(capsys.readouterr().out)['code'] == 'test_stop'
    assert len(seen) == 1 and seen[0][:2] == (command, RUN)
    assert seen[0][2]['minimum_write_seconds'] == (300 if minimum is None else 12.5)


def test_custom_minimum_is_not_persisted_or_extended(large_request, monkeypatch):
    deadline = json.loads((large_request.directory / 'github.json').read_text())['deadline']
    monkeypatch.setattr(parent, 'time', SimpleNamespace(time=lambda: deadline - 12.5))
    first = parent.execute('agent-git-next', RUN, minimum_write_seconds=12.5)
    assert first['code'] == 'native_result' and first['minimum_write_seconds'] == 12.5
    before = native_bytes(large_request.directory)
    result = parent.execute('agent-git-next-file', RUN, request_file=first['request_file']['path'],
                            sha256=first['request_file']['sha256'], minimum_write_seconds=12.5)
    assert result['code'] == 'exact_request_verified' and result['publish_remaining_seconds'] == 12.5
    assert native_bytes(large_request.directory) == before
    ledger = json.loads(before['github.json'])
    assert ledger['deadline'] == deadline and 'minimum_write_seconds' not in ledger
    assert 'minimum_write_seconds' not in ledger['config']
    assert read_next(first['request_file'])['code'] == 'deadline_insufficient'


def test_exact_partial_output_is_retained_with_accurate_write_metadata(large_request, monkeypatch):
    write = parent.durable_output
    retained = {}

    def fail(selected, directory, name, raw, result):
        if name.startswith('parent-exact-'):
            def fsync(fd):
                raise OSError('isolated exact fsync failure')
            with monkeypatch.context() as patch:
                patch.setattr(parent.os, 'fsync', fsync)
                try:
                    return write(selected, directory, name, raw, result)
                finally:
                    retained['bytes'] = (directory / name).read_bytes()
        return write(selected, directory, name, raw, result)

    monkeypatch.setattr(parent, 'durable_output', fail)
    result = parent.execute('agent-git-next', RUN)
    path = large_request.directory / ('parent-exact-' + REQUEST + '.json')
    assert result['code'] == 'next_file_write_failed' and result['next_action']['action'] == 'stop'
    assert result['executed'] and result['side_effects']['writes'] and not result['side_effects']['read_only']
    assert str(path) in result['side_effects']['created'] and path.read_bytes() == retained['bytes']
    assert 'exact_request_file' not in result and len(large_request.calls) == 1


def test_deadline_drops_after_exact_file_fsync_without_leaking_payload(large_request, monkeypatch):
    directory = large_request.directory
    deadline = json.loads((directory / 'github.json').read_text())['deadline']
    clock = {'now': deadline - 301}
    monkeypatch.setattr(parent, 'time', SimpleNamespace(time=lambda: clock['now']))
    save = parent.save_exact_request
    retained = {}

    def falling(*args):
        descriptor = save(*args)
        retained.update(native_bytes(directory))
        clock['now'] = deadline - 299
        return descriptor

    monkeypatch.setattr(parent, 'save_exact_request', falling)
    result = parent.execute('agent-git-next', RUN)
    assert result['code'] == 'deadline_insufficient' and result['publish_remaining_seconds'] == 299
    assert_no_dispatch(result)
    path = directory / ('parent-exact-' + REQUEST + '.json')
    assert path.read_bytes() == transport.encode(large_request.request)
    assert str(path) in result['side_effects']['created'] and result['side_effects']['writes']
    assert not result['side_effects']['read_only'] and result['executed']
    assert native_bytes(directory) == retained and len(large_request.calls) == 1


def test_reader_created_exact_file_reports_local_writes(large_request):
    directory = large_request.directory
    first = parent.execute('agent-git-next', RUN)
    path = Path(first['exact_request_file']['path'])
    path.unlink()
    before = native_bytes(directory)
    result = read_next(first['request_file'])
    assert result['code'] == 'exact_request_verified' and result['executed']
    assert result['side_effects']['created'] == [str(path)]
    assert result['side_effects']['writes'] and not result['side_effects']['read_only']
    assert path.read_bytes() == transport.encode(large_request.request)
    assert native_bytes(directory) == before and len(large_request.calls) == 1


def test_state_change_after_chunk_verification_stops_before_exact_file_write(large_request, monkeypatch):
    directory = large_request.directory
    first = parent.execute('agent-git-next', RUN)
    path = directory / ('parent-exact-' + REQUEST + '.json')
    path.unlink()  # Simulate a missing local export; the native request stays pending.
    decode = parent.decode_envelope

    def stale(*args):
        payload = decode(*args)
        ledger = json.loads((directory / 'github.json').read_text())
        ledger['pending_request_id'] = NEXT
        durable(directory / 'github.json', ledger)
        return payload

    monkeypatch.setattr(parent, 'decode_envelope', stale)
    result = read_next(first['request_file'])
    assert_no_dispatch(result)
    assert not path.exists() and not result['executed']
    assert result['side_effects']['created'] == [] and not result['side_effects']['writes']
    assert len(large_request.calls) == 1


@pytest.mark.parametrize('mode', ['write_missing_deadline', 'write_bad_deadline'])
def test_accept_invalid_native_deadline_retains_response_and_fails_closed(
        parent_seam, offline_child, monkeypatch, mode):
    directory, _, response = parent_seam
    parent.execute('agent-git-next', RUN)
    offline_child['mode'] = mode
    process = parent.accept_process
    retained = {}

    def snapshot(*args):
        result = process(*args)
        retained.update(native_bytes(directory))
        return result

    monkeypatch.setattr(parent, 'accept_process', snapshot)
    result = accept(response)
    assert result['code'] == 'invalid_publish_deadline' and result['native_result_retained'] is True
    assert_no_dispatch(result)
    assert native_bytes(directory) == retained and len(offline_child['calls']) == 1
    assert accept(response)['code'] == 'duplicate_response'


@pytest.mark.parametrize('value', [True, None, float('nan'), float('inf')])
def test_reader_invalid_deadline_is_fail_closed_without_writes(parent_seam, monkeypatch, value):
    directory, _, _ = parent_seam
    first = parent.execute('agent-git-next', RUN)
    path = directory / 'github.json'
    ledger = json.loads(path.read_text())
    if value is None:
        ledger.pop('deadline')
    else:
        ledger['deadline'] = value
    path.write_text(json.dumps(ledger))
    before = native_bytes(directory)
    result = read_next(first['request_file'])
    assert result['code'] in ('invalid_publish_deadline', 'invalid_json')
    assert_no_dispatch(result)
    assert not result['executed'] and result['side_effects']['created'] == []
    assert native_bytes(directory) == before
