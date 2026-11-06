"""Offline A1 regressions; these tests are run only by the orchestrator.

Reuse the isolated publisher Git fixture explicitly. The transport seam fakes
the connector/native publisher; offline_child still runs the real transport
module, frame parser, READY protocol and durable receipts in a real subprocess.
"""
import base64
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from harness import git_publish as native, git_transport as transport, parent_commands as parent, storage
from harness.test_git_publish import isolated_storage_environment, prepared
from harness.test_git_transport import seam, durable, RUN, REQUEST, NEXT


RESPONSE = transport.encode({'text': '한글 🐈'})


@pytest.fixture
def parent_seam(seam, monkeypatch):
    directory, calls = seam
    for key in ('READ_ONLY', 'GIT', 'TAVERN_WORKFLOW_DEMO', 'TAVERN_NO_GIT'):
        monkeypatch.delenv(key, raising=False)
    durable(directory / 'github.json', {'run_id': RUN, 'step': 'repository',
                                       'status': 'awaiting_connector', 'config': {'enabled': True}})
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
