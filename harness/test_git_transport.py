"""Offline transport contract. Parent runs these with existing publisher regressions."""
import base64
import copy
import fcntl
import io
import json
import os
import stat

import pytest

from harness import git_publish as native, git_transport as transport, storage
# Explicit reuse: synthetic repository only, never the caller's checkout or keys.
from harness.test_git_publish import (prepared, isolated_storage_environment,
                                      configured_delivery, journal_at, to_pr,
                                      pr_data, rows_for, check_response)


RUN = '123456-abcdef'
REQUEST = '1' * 64
NEXT = '2' * 64


def value(envelope):
    return json.loads(envelope['inline'])


def durable(path, data):
    raw = transport.encode(data)
    with path.open('wb') as handle:
        handle.write(raw)
    path.chmod(0o600)


@pytest.fixture
def seam(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    directory = root / 'logs/harness/workflows' / RUN
    directory.mkdir(parents=True, mode=0o700)
    directory.chmod(0o700)
    durable(directory / 'github.json', {'run_id': RUN, 'step': 'repository'})
    selected = storage.resolve_storage(root, env={})
    monkeypatch.setattr(native, 'ROOT', root)
    monkeypatch.setattr(native, 'REPORTS', directory.parent)
    monkeypatch.setattr(native, 'storage_policy', lambda: selected)
    for key in ('TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY', 'TAVERN_IMPROVEMENT_UNATTENDED'):
        monkeypatch.delenv(key, raising=False)
    calls = []

    def main(args):
        calls.append(args)
        # The durable marker serializes native entry; no extra flock is held
        # across native cleanup/completion/archive or connector network waits.
        assert (directory / 'transport/inflight.json').exists()
        with (directory / 'transport/claim').open('a') as claim:
            fcntl.flock(claim, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ledger = json.loads((directory / 'github.json').read_text())
        if args[0] == 'accept':
            assert args[1:5] == ['--run-id', RUN, '--request-id', REQUEST]
            response = directory / 'transport' / (transport.digest(transport.encode([RUN, 'accept', REQUEST])) + '.response.json')
            assert args[5:] == ['--response-file', str(response)]
            assert stat.S_IMODE(response.stat().st_mode) == 0o600
            assert stat.S_IMODE(response.parent.stat().st_mode) == 0o700
            assert response.read_bytes() == transport.encode({'text': '한글 🐈'})
        ledger['pending_request_id'] = REQUEST if args[0] == 'request' else NEXT
        durable(directory / 'github.json', ledger)
        print(json.dumps({'run_id': RUN, 'github': {'status': 'awaiting_connector'},
                          'request': {'request_id': ledger['pending_request_id'],
                                      'tool': native.TOOLS['fetch'], 'arguments': {'url': 'fixture'}},
                          'poll_after_seconds': 0}))
        return 0

    monkeypatch.setattr(native, 'main', main)
    return directory, calls


def test_single_call_exact_native_args_private_utf8_and_durable_digest(seam, monkeypatch):
    directory, calls = seam
    fsyncs = []
    fsync = os.fsync
    monkeypatch.setattr(os, 'fsync', lambda fd: (fsyncs.append(os.fstat(fd).st_mode), fsync(fd))[1])
    first = transport.transact('request', RUN)
    assert value(first)['request']['request_id'] == REQUEST
    raw = transport.encode({'text': '한글 🐈'})
    result = transport.transact('accept', RUN, REQUEST, raw)
    assert len(calls) == 2
    assert value(result)['request']['request_id'] == NEXT
    assert result['bytes'] == len(result['inline'].encode('utf-8'))
    assert result['sha256'] == transport.digest(result['inline'].encode('utf-8'))
    receipt = json.loads((directory / 'transport' / (result['operation_id'] + '.complete.json')).read_text())
    assert receipt['response_sha256'] == transport.digest(raw)
    assert receipt['request_id'] == REQUEST and receipt['run_id'] == RUN
    assert any(stat.S_ISDIR(mode) for mode in fsyncs)
    assert any(stat.S_ISREG(mode) for mode in fsyncs)


@pytest.mark.parametrize('raw', [b'NaN', b'{"x":1,"x":2}', b'{}trailing', b'\xff', b'null', b'1', b'{'])
def test_invalid_json_never_enters_native(seam, raw):
    _, calls = seam
    with pytest.raises(transport.TransportError):
        transport.transact('accept', RUN, REQUEST, raw)
    assert calls == []


def test_oversized_input_before_native(seam):
    _, calls = seam
    with pytest.raises(transport.TransportError, match='too_large'):
        transport.transact('accept', RUN, REQUEST, b' ' * (transport.MAX_RESPONSE + 1))
    assert not calls


@pytest.mark.parametrize('run,request_id', [('bad', REQUEST), (RUN, '../x'), (RUN, 'a' * 63), (RUN, NEXT)])
def test_wrong_run_or_stale_id_never_calls_native(seam, run, request_id):
    _, calls = seam
    with pytest.raises((ValueError, OSError)):
        transport.transact('accept', run, request_id, b'{}')
    assert not calls


@pytest.mark.parametrize('changed', [False, True])
def test_duplicate_accept_and_changed_response_require_reconciliation(seam, changed):
    _, calls = seam
    transport.transact('request', RUN)
    transport.transact('accept', RUN, REQUEST, transport.encode({'text': '한글 🐈'}))
    with pytest.raises(transport.TransportError, match='reconciliation'):
        transport.transact('accept', RUN, REQUEST, b'{}' if changed else transport.encode({'text': '한글 🐈'}))
    assert len(calls) == 2
    with pytest.raises(transport.TransportError):
        transport.transact('request', RUN)
    assert len(calls) == 2


@pytest.mark.parametrize('after', [False, True])
def test_interruption_preserves_receipt_and_blocks_all_new_operations(seam, monkeypatch, after):
    directory, calls = seam
    real = native.main

    def interrupted(args):
        assert (directory / 'transport/inflight.json').exists()
        if after:
            real(args)
        raise KeyboardInterrupt()

    monkeypatch.setattr(native, 'main', interrupted)
    with pytest.raises(KeyboardInterrupt):
        transport.transact('request', RUN)
    monkeypatch.setattr(native, 'main', real)
    for command, request, raw in [('request', None, None), ('accept', REQUEST, b'{}')]:
        with pytest.raises(transport.TransportError, match='reconciliation'):
            transport.transact(command, RUN, request, raw)
    assert len(calls) == int(after)
    assert list((directory / 'transport').glob('*.begin.json'))
    assert list((directory / 'transport').glob('*.stdout'))


@pytest.mark.parametrize('after', [False, True])
def test_accept_interruption_keeps_exact_saved_response(seam, monkeypatch, after):
    directory, calls = seam
    transport.transact('request', RUN)
    actual = native.main

    def interrupted(args):
        path = directory / 'transport' / (transport.digest(transport.encode([RUN, 'accept', REQUEST])) + '.response.json')
        assert path.read_bytes() == transport.encode({'text': '한글 🐈'})
        if after:
            actual(args)
        raise KeyboardInterrupt()

    monkeypatch.setattr(native, 'main', interrupted)
    with pytest.raises(KeyboardInterrupt):
        transport.transact('accept', RUN, REQUEST, transport.encode({'text': '한글 🐈'}))
    monkeypatch.setattr(native, 'main', actual)
    with pytest.raises(transport.TransportError, match='reconciliation'):
        transport.transact('accept', RUN, REQUEST, transport.encode({'text': '한글 🐈'}))
    assert len(calls) == 1 + int(after)


def test_completed_receipt_and_native_journal_disagreement_is_closed(seam):
    directory, calls = seam
    transport.transact('request', RUN)
    durable(directory / 'github.json', {'run_id': RUN, 'pending_request_id': NEXT})
    with pytest.raises(transport.TransportError, match='reconciliation'):
        transport.transact('accept', RUN, NEXT, b'{}')
    assert len(calls) == 1


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'mode', 'owner'])
def test_private_read_boundary(seam, monkeypatch, kind):
    directory, calls = seam
    path = directory / 'github.json'
    if kind == 'symlink':
        saved = directory / 'saved.json'
        path.rename(saved)
        path.symlink_to(saved)
    elif kind == 'hardlink':
        os.link(str(path), str(directory / 'alias.json'))
    elif kind == 'mode':
        path.chmod(0o644)
    else:
        monkeypatch.setattr(os, 'geteuid', lambda: path.stat().st_uid + 1)
    with pytest.raises((ValueError, OSError)):
        transport.transact('request', RUN)
    assert not calls


@pytest.mark.parametrize('level', ['run', 'transport'])
def test_symlink_directory_never_traversed(seam, level):
    directory, calls = seam
    if level == 'run':
        moved = directory.with_name('777777-abcdef')
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    else:
        other = directory / 'other'
        other.mkdir(mode=0o700)
        (directory / 'transport').symlink_to(other, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        transport.transact('request', RUN)
    assert not calls


@pytest.mark.parametrize('kind', ['symlink', 'hardlink'])
def test_response_destination_is_exclusive_and_never_overwritten(seam, kind):
    directory, calls = seam
    transport.transact('request', RUN)
    original = (directory / 'github.json').read_bytes()
    operation = transport.digest(transport.encode([RUN, 'accept', REQUEST]))
    destination = directory / 'transport' / (operation + '.response.json')
    if kind == 'symlink':
        destination.symlink_to(directory / 'github.json')
    else:
        source = directory / 'other-response.json'
        durable(source, {'preserve': True})
        os.link(str(source), str(destination))
    with pytest.raises((ValueError, OSError)):
        transport.transact('accept', RUN, REQUEST, transport.encode({'text': '한글 🐈'}))
    assert (directory / 'github.json').read_bytes() == original
    assert len(calls) == 1


def test_bounded_inline_and_chunk_readback_fail_closed(seam, monkeypatch):
    directory, _ = seam
    payload = {'run_id': RUN, 'request': {'body': '한글' * 20000}}
    monkeypatch.setattr(native, 'main', lambda args: (print(json.dumps(payload, ensure_ascii=False)), 0)[1])
    result = transport.transact('request', RUN)
    assert 'inline' not in result and result['bytes'] > transport.INLINE_BYTES
    raw = b''
    for i in range(result['chunks']['count']):
        part = transport.chunk(RUN, result['operation_id'], i)
        assert part['offset'] == len(raw)
        raw += base64.b64decode(part['data'], validate=True)
    assert transport.digest(raw) == result['sha256'] and len(raw) == result['bytes']
    assert json.loads(raw) == payload
    for index in [-1, True, result['chunks']['count']]:
        with pytest.raises(transport.TransportError):
            transport.chunk(RUN, result['operation_id'], index)
    with pytest.raises(transport.TransportError):
        transport.chunk(RUN, '../github.json', 0)
    path = directory / 'transport' / (result['operation_id'] + '.stdout')
    path.write_bytes(raw[:-1])
    with pytest.raises(transport.TransportError, match='digest'):
        transport.chunk(RUN, result['operation_id'], 0)


def test_usual_create_tree_stays_inline(seam, monkeypatch):
    payload = {'request': {'tool': native.TOOLS['create_tree'], 'arguments': {'content': 'x' * 17000}}}
    monkeypatch.setattr(native, 'main', lambda args: (print(json.dumps(payload)), 0)[1])
    assert value(transport.transact('request', RUN)) == payload


def test_chunk_does_not_create_a_transport_directory(seam):
    directory, calls = seam
    with pytest.raises(FileNotFoundError):
        transport.chunk(RUN, REQUEST, 0)
    assert not (directory / 'transport').exists()
    assert not calls


@pytest.mark.parametrize('kind', ['hardlink', 'symlink', 'mode', 'same_size_change'])
def test_result_readback_checks_all_private_and_digest_boundaries(seam, monkeypatch, kind):
    directory, _ = seam
    monkeypatch.setattr(native, 'main', lambda args: (print(json.dumps({'body': 'x' * 40000})), 0)[1])
    result = transport.transact('request', RUN)
    path = directory / 'transport' / (result['operation_id'] + '.stdout')
    if kind == 'hardlink':
        os.link(str(path), str(directory / 'transport/alias'))
    elif kind == 'symlink':
        saved = directory / 'saved-stdout'
        path.rename(saved)
        path.symlink_to(saved)
    elif kind == 'mode':
        path.chmod(0o644)
    else:
        raw = path.read_bytes()
        path.write_bytes(raw.replace(b'x', b'y', 1))
    with pytest.raises((ValueError, OSError)):
        transport.chunk(RUN, result['operation_id'], 0)


@pytest.mark.parametrize('code,status,extra', [
    (1, 'merged', {'step': 'cleanup_pr'}),
    (1, 'cleanup_pending', {'cleanup': {'status': 'cleanup_pending'}}),
    (0, 'merged', {'step': 'done', 'cleanup': {'status': 'complete'}}),
    (1, 'failed', {'error': 'native_fixture_error'}),
    (1, 'merged', {'step': 'done', 'archive': {'status': 'pending'}}),
])
def test_native_codes_cleanup_archive_and_terminal_are_not_synthesized(seam, monkeypatch, code, status, extra):
    extra = dict(extra)
    archive = extra.pop('archive', None)
    payload = {'github': {'status': status, **extra}, 'request': None, 'poll_after_seconds': 10}
    if archive:
        payload['archive'] = archive
    monkeypatch.setattr(native, 'main', lambda args: (print(json.dumps(payload)), code)[1])
    result = transport.transact('request', RUN)
    assert result['native_exit_code'] == code
    assert value(result) == payload


def test_invalid_native_output_cannot_issue_another_request(seam, monkeypatch):
    monkeypatch.setattr(native, 'main', lambda args: (print('{truncated'), 0)[1])
    with pytest.raises(transport.TransportError):
        transport.transact('request', RUN)
    with pytest.raises(transport.TransportError, match='reconciliation'):
        transport.transact('request', RUN)


def test_stdin_is_bounded_utf8_base64_and_framed():
    raw = transport.encode({'text': '한글 🐈' * 3000})
    encoded = base64.b64encode(raw)
    frame = b'\n'.join(encoded[i:i+2048] for i in range(0, len(encoded), 2048)) + b'\n.\n'
    assert transport.stdin_response(io.BytesIO(frame)) == raw
    for invalid in (b'$$$$\n.\n', b'e30=', b'e30=\n', b'x' * 2051 + b'\n.\n'):
        with pytest.raises(transport.TransportError):
            transport.stdin_response(io.BytesIO(invalid))


@pytest.mark.parametrize('key', ['TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY', 'TAVERN_IMPROVEMENT_UNATTENDED'])
def test_child_and_discovery_are_rejected_before_storage(seam, monkeypatch, key):
    monkeypatch.setenv(key, '1')
    monkeypatch.setattr(native, 'storage_policy', lambda: pytest.fail('child reached storage'))
    with pytest.raises(transport.TransportError, match='trusted_parent'):
        transport.transact('request', RUN)


def test_unknown_cli_input_never_calls_native(seam):
    _, calls = seam
    with pytest.raises(SystemExit):
        transport.main(['request', '--run-id', RUN, '--response-file', '/not-accepted'])
    assert calls == []


def test_real_native_main_is_used_for_request_and_accept(prepared, monkeypatch):
    calls = []
    actual = native.main

    def spy(args):
        calls.append(list(args))
        return actual(args)

    monkeypatch.setattr(native, 'main', spy)
    run = prepared['directory'].name
    first = value(transport.transact('request', run))
    reply = {'full_name': prepared['ledger']['config']['repository'], 'archived': False,
             'permissions': {'push': True}, 'allow_squash_merge': True}
    accepted = transport.transact('accept', run, first['request']['request_id'], transport.encode(reply))
    assert accepted['native_exit_code'] == 0
    assert value(accepted)['github']['step'] == 'base_ref'
    assert len(calls) == 2 and calls[-1][0] == 'accept'
    assert value(accepted)['request']['tool'] == native.TOOLS['fetch']


@pytest.mark.parametrize('corrupt', ['scope', 'hash', 'mode'])
def test_actual_native_validation_remains_required(prepared, corrupt):
    directory = prepared['directory']
    ledger = copy.deepcopy(prepared['ledger'])
    if corrupt == 'scope':
        report = copy.deepcopy(prepared['report'])
        report['scope'] = []
        durable(directory / 'report.json', report)
    elif corrupt == 'hash':
        ledger['files']['edit.py']['after']['content'] += 'tampered'
    else:
        ledger['files']['edit.py']['after']['mode'] = '100644'
    durable(directory / 'github.json', ledger)
    result = transport.transact('request', directory.name)
    assert result['native_exit_code'] == 1 and value(result)['status'] == 'failed'
    assert 'request' not in value(result)


@pytest.mark.parametrize('kind', ['missing', 'wrong_app', 'failure', 'neutral', 'skipped'])
def test_transport_keeps_actual_native_required_ci_gates(prepared, kind):
    ledger = prepared['ledger']
    to_pr(ledger)
    native.accept(ledger, pr_data(ledger))
    native.save(prepared['directory'], ledger)
    rows = rows_for(ledger)
    if kind == 'missing':
        rows.pop()
    elif kind == 'wrong_app':
        rows[0]['app'] = {'slug': 'other-app'}
    else:
        rows[0]['conclusion'] = kind
    first = value(transport.transact('request', ledger['run_id']))
    result = transport.transact('accept', ledger['run_id'], first['request']['request_id'],
                                transport.encode(check_response(rows)))
    current = value(result)
    if kind in ('missing', 'wrong_app'):
        assert current['github']['status'] == 'waiting_for_ci'
        assert current['request']['tool'] == native.TOOLS['fetch']
        assert current['poll_after_seconds'] == 10
    else:
        assert result['native_exit_code'] == 1
        assert current['github']['status'] == 'failed'
        assert current['request'] is None


@pytest.mark.parametrize('placement', ['legacy', 'configured'])
def test_v1_selected_active_locations_use_native_lookup(configured_delivery, placement):
    directory, _ = journal_at(configured_delivery, placement)
    result = transport.transact('request', directory.name)
    assert value(result)['run_id'] == directory.name
    assert (directory / 'transport').is_dir()


def test_v2_explicit_active_location(prepared, tmp_path, monkeypatch):
    # No archive access is necessary before PR creation. Unknown mounts fail in
    # production; this fixture supplies only the existing offline local-FS seam.
    class LocalFS(storage.FileSystem):
        def local_filesystem(self, path):
            return True

        def mount_ready(self, path):
            return path == local

        def free_bytes(self, path):
            return 10**12

        def probe(self, path):
            pass

    config_path = prepared['root'] / 'logs/harness/storage-local.json'
    local = tmp_path / 'active'
    local.mkdir()
    # The v2 schema is the public storage contract, not a relaxed native gate.
    config = {'version': 2,
              'artifacts': {'path': str(local / 'artifacts'), 'required_mount': str(local), 'min_free_bytes': 1},
              'temporary': {'path': str(local / 'temporary'), 'required_mount': str(local), 'min_free_bytes': 1},
              'archive': {'path': str(tmp_path / 'remote/results'), 'required_mount': str(tmp_path / 'remote'), 'min_free_bytes': 1}}
    durable(config_path, config)
    selected = storage.resolve_storage(prepared['root'], env={}, fs=LocalFS())
    monkeypatch.setattr(native, 'storage_policy', lambda: selected)
    item = {**prepared, 'storage': selected}
    directory, _ = journal_at(item, 'configured')
    result = transport.transact('request', directory.name)
    assert value(result)['run_id'] == directory.name
    assert (directory / 'transport').is_dir()
    assert not (tmp_path / 'remote').exists()
