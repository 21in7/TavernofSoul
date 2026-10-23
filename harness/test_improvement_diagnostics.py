"""Private diagnostic validation/failure specifications, never operator data."""
from contextlib import contextmanager
import datetime as dt
import errno
import json

import pytest

from harness import improvement_diagnostics as diag, improvement_loop as loop
from harness import improvement_snapshot as sealed, improvements as imp, storage
from harness.storage import resolve_storage as real_resolve_storage
from harness.test_improvement_loop import lab, offline, SECRET, RAW, forbidden


@pytest.mark.parametrize('marker', ['TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY'])
def test_leaf_guard_still_precedes_tick_diagnostics_and_state_writes(lab, monkeypatch, marker):
    # The imported offline fixture models a trusted parent. Explicit leaf tests
    # restore the marker rather than weakening the production authority guard.
    monkeypatch.setenv(marker, '1')
    with pytest.raises(imp.ImprovementError, match='cannot orchestrate'):
        lab.tick(9)
    assert lab.events == [] and not lab.store.exists(loop.STATE_FILE)
    assert not lab.store.exists('loop/last-diagnostic.json')


@pytest.mark.parametrize('value', [True, False, -1, 4096, 10 ** 100, 1.5, '13', {}, []])
def test_numeric_metadata_rejects_bool_nonintegers_and_out_of_bounds(value):
    event = diag.event('project_lock', 'io', errno=value, slot=value)
    assert event['errno'] is None and event['slot'] is None
    assert event['holder_pid'] is None


@pytest.mark.parametrize('value', [True, False, -1, 86400001, 10 ** 100, 1.5, '1', {}, []])
def test_elapsed_is_bounded_typed_and_never_coerced(value):
    assert diag.event('stage', 'invalid', elapsed_ms=value)['elapsed_ms'] is None


@pytest.mark.parametrize('code', [True, {}, [], SECRET, 'project_lock_busy'])
def test_external_codes_cannot_select_a_failure_boundary(code):
    with pytest.raises(ValueError):
        diag.event(code, 'io')


def test_actual_clock_fixed_types_and_first_failure_survive_secondary_error():
    start = dt.datetime.now(dt.timezone.utc)
    with diag.Trace() as trace:
        diag.position('specialist', 9)
        with pytest.raises(OSError):
            with diag.boundary('snapshot'):
                error = OSError(errno.EACCES, SECRET + RAW)
                error.reason = 'project_lock_busy'
                raise error
        first = dict(trace.first)
        with pytest.raises(OSError):
            with diag.boundary('diagnostic_save'):
                raise OSError(errno.ENOSPC, SECRET)
        assert trace.first == first
    assert first['boundary'] == 'snapshot' and first['reason'] == 'snapshot_io'
    assert first['errno'] == errno.EACCES and first['slot'] == 9
    assert type(first['elapsed_ms']) is int
    assert dt.datetime.fromisoformat(first['at']) >= start
    assert SECRET not in json.dumps(first) and RAW not in json.dumps(first)


@pytest.mark.parametrize('where,reason', [
    ('config', 'config_io'), ('readiness', 'storage_readiness_io')])
def test_storage_optional_observer_preserves_active_trace_and_original_error(lab, monkeypatch, where, reason):
    error = OSError(errno.EACCES, SECRET + RAW)

    def fail(*args, **kwargs):
        raise error

    if where == 'config':
        # Preserve the resolver at collection time; the shared offline guard
        # stays installed for every production caller, including this Lab.
        assert storage.resolve_storage is forbidden
        monkeypatch.setattr(storage, 'resolve_project_root', fail)
        operation = lambda: real_resolve_storage(lab.root, env={})
    else:
        monkeypatch.setattr(lab.selected, '_check_ready', fail)
        operation = lab.selected.check_ready
    with diag.Trace() as trace:
        with pytest.raises(OSError) as caught:
            operation()
        assert caught.value is error
        assert trace.first['reason'] == reason
        assert trace.first['errno'] == errno.EACCES
        assert trace.first['holder_pid'] is None
        assert SECRET not in json.dumps(trace.first) and RAW not in json.dumps(trace.first)


@pytest.mark.parametrize('where,reason', [
    ('config', 'config_invalid'), ('store', 'store_invalid'),
    ('readiness', 'storage_readiness_io'), ('state', 'state_read_invalid'),
    ('snapshot', 'snapshot_io'), ('seal', 'seal_invalid'),
    ('stage', 'stage_invalid'), ('settlement', 'settlement_io')])
def test_tick_records_actual_boundary_without_secret_or_exception_reason(lab, monkeypatch, where, reason):
    def invalid(*a, **kw):
        error = ValueError(SECRET + RAW)
        error.reason = 'project_lock_busy'
        raise error
    def io(*a, **kw):
        raise OSError(errno.EIO, SECRET + RAW)
    if where == 'config':
        monkeypatch.setattr(loop, 'load_config', invalid)
    elif where == 'store':
        monkeypatch.setattr(imp, 'Store', invalid)
    elif where == 'readiness':
        monkeypatch.setattr(storage.Storage, 'check_ready', io)
    elif where == 'state':
        monkeypatch.setattr(loop, '_read_state', diag.at('state_read')(invalid))
    elif where == 'snapshot':
        monkeypatch.setattr(imp, '_snapshot_sources_locked', io)
    elif where == 'seal':
        monkeypatch.setattr(sealed, 'publish', diag.at('seal')(invalid))
    elif where == 'stage':
        monkeypatch.setattr(loop, '_tick_locked', invalid)
    else:
        monkeypatch.setattr(loop, '_persist_round', diag.at('settlement')(io))
    result = lab.tick(9)
    assert result['diagnostic']['reason'] == reason
    assert result['diagnostic']['holder_pid'] is None
    assert result['status'] == 'paused'
    serialized = json.dumps(result)
    for private in (SECRET, RAW, str(lab.root), 'ValueError', 'OSError'):
        assert private not in serialized
    if where in ('config', 'store', 'readiness', 'state'):
        assert result['diagnostic_preservation'] == 'private_result_only'
        assert lab.events == [] and not lab.store.exists(loop.STATE_FILE)


def test_deadline_code_comes_from_handler_and_reservation_is_not_replayed(lab, monkeypatch):
    actual = lab.local
    def timeout(*a, **kw):
        diag.timeout()  # the trusted alarm path, independent of exception text
        raise loop.LoopError('tick_timeout')
    monkeypatch.setattr(loop, '_local_call', timeout)
    result = lab.tick(9)
    assert result['diagnostic']['reason'] == 'deadline_timeout'
    assert result['diagnostic']['stage'] == 'local_explorer'
    assert lab.ledger()['calls'] == 1 and lab.state()['inflight'] is not None
    assert lab.tick(9, local_runner=actual)['reason'] == 'slot_already_claimed'
    assert lab.ledger()['calls'] == 1


def test_failed_diagnostic_and_pause_writes_preserve_original_and_durable_call(lab, monkeypatch):
    actual = imp.Store.write
    def fail_stage(*a, **kw):
        raise ValueError(SECRET)
    def write(store, name, value):
        if name == 'loop/last-diagnostic.json':
            raise OSError(errno.ENOSPC, SECRET)
        return actual(store, name, value)
    monkeypatch.setattr(imp.Store, 'write', write)
    monkeypatch.setattr(loop, '_local_call', fail_stage)
    result = lab.tick(0)
    assert result['reason'] == 'stage_invalid'
    assert result['diagnostic_preservation'] == 'private_result_only'
    pending = lab.state()['inflight']
    assert pending is not None and lab.ledger()['calls'] == 1
    assert lab.tick(0)['reason'] == 'slot_already_claimed'
    assert lab.ledger()['calls'] == 1


def test_error_state_save_cannot_hide_original_failure(lab, monkeypatch):
    actual = imp.Store.write
    claimed = False
    def writes(store, name, value):
        nonlocal claimed
        if name == loop.STATE_FILE:
            if value.get('last_slot') is not None:
                if claimed:
                    raise OSError(errno.ENOSPC, SECRET)
                claimed = True
        return actual(store, name, value)
    monkeypatch.setattr(imp.Store, 'write', writes)
    monkeypatch.setattr(loop.local_model, 'load_config', lambda **kw: (_ for _ in ()).throw(ValueError(SECRET)))
    result = lab.tick(9)
    assert result['reason'] == 'config_invalid'
    assert result['diagnostic']['reason'] == 'config_invalid'
    assert result['recovery'] == 'durable_state_retained'
    assert lab.ledger()['calls'] == 0 and lab.events == []


def test_publication_failure_has_private_diagnostic_and_does_not_retry(lab, capsys, monkeypatch):
    lab.tick(9)
    calls = []
    def failed(date, **kw):
        calls.append(date)
        raise OSError(errno.ECONNRESET, SECRET)
    with diag.Trace() as trace:
        result = loop.publish(now=lab.clock(), selected=lab.selected, publisher=failed)
        assert result['status'] == 'publication_unknown'
        assert trace.first['reason'] == 'publication_io'
        assert result['diagnostic_preservation'] == 'private_record_and_result'
        assert lab.store.read('loop/last-diagnostic.json') == trace.first
    loop.publish(now=lab.clock(), selected=lab.selected, publisher=failed)
    assert len(calls) == 1
    assert 'diagnostic' not in lab.store.read('web/2026-10-15.json')
    monkeypatch.setattr(loop, 'publish', diag.at('publication')(lambda **kw: (_ for _ in ()).throw(OSError(errno.EIO, SECRET))))
    assert loop.main(['publish']) == 1
    private = json.loads(capsys.readouterr().out)
    assert private['diagnostic']['reason'] == 'publication_io'
    assert SECRET not in json.dumps(private)


@pytest.mark.parametrize('value', [SECRET, True, {}, [], 'project_lock_busy forged'])
def test_safe_reason_rejects_forged_reason_and_fallback(value):
    assert diag.safe_reason(value) == 'stage_invalid'
    with pytest.raises(ValueError):
        diag.safe_reason('stage_invalid', fallback=value)


def test_caught_local_failure_keeps_actual_stage_boundary_and_safe_private_result(lab):
    def failed(*a, **kw):
        raise OSError(errno.ECONNRESET, SECRET + RAW)
    result = lab.tick(0, local_runner=failed)
    assert result['diagnostic']['reason'] == 'stage_io'
    assert result['diagnostic']['stage'] == 'local_explorer'
    assert result['diagnostic']['errno'] == errno.ECONNRESET
    assert result['diagnostic_preservation'] == 'private_record_and_result'
    assert lab.state()['inflight'] is None and lab.ledger()['calls'] == 1
    assert lab.tick(0)['reason'] == 'slot_already_claimed'
    assert SECRET not in json.dumps(result) and RAW not in json.dumps(result)


def test_post_call_config_failure_keeps_actual_boundary_and_consumed_reservation(lab, monkeypatch):
    load = loop.local_model.load_config
    reads = []
    def config(**kwargs):
        reads.append(True)
        if len(reads) == 2:
            raise OSError(errno.EIO, SECRET + RAW)
        return load(**kwargs)
    monkeypatch.setattr(loop.local_model, 'load_config', config)
    result = lab.tick(0)
    assert result['diagnostic']['reason'] == 'config_io'
    assert result['diagnostic']['stage'] == 'local_explorer'
    assert result['diagnostic_preservation'] == 'private_record_and_result'
    report = lab.state()['round']['report']
    assert not report['review_complete'] and not report['current_fresh_at_last_tick']
    assert 'freshness_unavailable_after_call' in report['errors']
    assert lab.state()['inflight'] is None and lab.ledger()['calls'] == 1
    assert lab.tick(0)['reason'] == 'slot_already_claimed'
    assert len(reads) == 2 and lab.ledger()['calls'] == 1
    assert SECRET not in json.dumps(result) and RAW not in json.dumps(result)
