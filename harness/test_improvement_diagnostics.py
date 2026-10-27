"""Private diagnostic validation/failure specifications, never operator data."""
from contextlib import contextmanager
from copy import deepcopy
import datetime as dt
import errno
import json

import pytest

from harness import improvement_diagnostics as diag, improvement_loop as loop
from harness import improvement_report as contract
from harness import improvement_snapshot as sealed, improvements as imp, storage
from harness.storage import resolve_storage as real_resolve_storage
from harness.test_improvement_loop import lab, offline, SECRET, RAW, forbidden, draft


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


# Documentation impact: failure-v1 is a new private contract. Task 3 must update
# ADR0027 and the approved design/adapter docs; these offline specs do not prove
# operational observation, storage limits, or completion of adapter/loop wiring.
def private_detail(**kwargs):
    error = diag.attach(ValueError(SECRET + RAW), diag.detail(**kwargs))
    return diag.exception_detail(error)


@pytest.mark.parametrize('key,minimum,maximum', [
    ('exit_code', 0, 255), ('errno', 0, 4095), ('http_status', 100, 599)])
def test_detail_numeric_boundary_values_and_no_coercion(key, minimum, maximum):
    for number in (minimum, maximum):
        result = private_detail(reason='role_execution_failed', cause='cli_failed', **{key: number})
        assert result[key] == number and type(result[key]) is int
    for number in (True, False, minimum - 1, maximum + 1, 10 ** 100, '1', 1.0, {}, []):
        result = private_detail(reason='role_execution_failed', cause='cli_failed', **{key: number})
        assert result[key] is None
        assert SECRET not in json.dumps(result)


@pytest.mark.parametrize('key', ['reason', 'cause', 'phase', 'field', 'rule', 'version'])
@pytest.mark.parametrize('bad', [SECRET + RAW, 'x' * 10000, True, [], {}, 1])
def test_detail_allowlists_reject_arbitrary_codes_without_echoing(key, bad):
    value = private_detail(reason='candidate_invalid', cause='validation',
                           phase='candidate', field='title', rule='length')
    value[key] = bad
    result = diag.sanitize_detail(value)
    assert result['cause'] == 'unavailable'
    assert result['field'] is None and result['rule'] is None
    serialized = json.dumps(result)
    assert SECRET not in serialized and RAW not in serialized
    assert len(serialized.encode('utf-8')) <= diag.MAX_DETAIL_BYTES


def test_detail_schema_exact_types_unknown_legacy_and_partial_validation():
    value = private_detail(reason='candidate_invalid', cause='validation',
                           phase='candidate', field='evidence.end_line', rule='range')
    class ForgedDict(dict):
        def get(self, *args):
            raise AssertionError('Do not call untrusted mapping methods')
    class ForgedStr(str):
        def __eq__(self, other):
            raise AssertionError('Do not compare untrusted string subclasses')
    for malformed in (None, {}, [], SECRET, ForgedDict(value),
                      dict(value, raw=SECRET), {'reason': 'candidate_invalid'}):
        result = diag.sanitize_detail(malformed)
        assert result['reason'] == 'unknown' and result['cause'] == 'unavailable'
    assert diag.sanitize_detail(dict(value, reason=ForgedStr('candidate_invalid')))['reason'] == 'unknown'
    for key in ('field', 'rule'):
        incomplete = diag.sanitize_detail(dict(value, **{key: None}))
        assert incomplete['reason'] == 'candidate_invalid'
        assert incomplete['cause'] == 'unavailable'
    longest = private_detail(reason=max(diag.DETAIL_REASONS, key=len), cause='validation',
        phase=max(diag.PHASES, key=len), field=max(diag.FIELDS, key=len),
        rule=max(diag.RULES, key=len), exit_code=255, errno=4095, http_status=599)
    assert len(json.dumps(longest).encode('utf-8')) <= diag.MAX_DETAIL_BYTES
    detached = diag.sanitize_detail(value)
    detached['reason'] = SECRET
    assert value['reason'] == 'candidate_invalid'


def test_exception_link_rejects_forged_attributes_and_preserves_original_wrapper():
    original = ValueError(SECRET + RAW)
    forged = private_detail(reason='role_execution_failed', cause='quota', phase='execution')
    original.reason = 'quota'
    original.diagnostic = original.failure_detail = forged
    original._improvement_failure = forged
    assert diag.attach(original, forged) is original  # JSON is not a capability.
    assert diag.exception_detail(original)['cause'] == 'unavailable'
    assert diag.attach(original, diag.detail('role_execution_failed', 'cli_failed',
        phase='execution', exit_code=7)) is original
    # A second classification and a copied private link cannot replace/forge it.
    diag.attach(original, diag.detail('role_execution_failed', 'quota'))
    copied = ValueError(RAW)
    copied.__dict__.update(original.__dict__)
    assert diag.exception_detail(copied)['cause'] == 'unavailable'
    wrapped = RuntimeError(SECRET)
    assert diag.inherit(wrapped, original) is wrapped
    with diag.Trace() as trace:
        with pytest.raises(RuntimeError) as caught:
            with diag.boundary('stage'):
                raise wrapped from original
        assert caught.value is wrapped and wrapped.__cause__ is original
        first = dict(trace.first)
        diag.record('settlement', OSError(errno.ENOSPC, SECRET))
        assert trace.first == first
    assert first['reason'] == 'stage_invalid'
    assert first['detail']['reason'] == 'role_execution_failed'
    assert first['detail']['cause'] == 'cli_failed' and first['detail']['exit_code'] == 7
    assert SECRET not in json.dumps(first) and RAW not in json.dumps(first)


@pytest.mark.parametrize('field', [
    'review.plan', 'review.capture', 'review.stream', 'review.metadata',
    'review.read_request', 'review.read_pair', 'review.read_content', 'review.result',
    'review.coverage', 'review.assessments', 'review.documentation', 'review.proof',
])
def test_review_boundary_codes_use_existing_private_capability_and_first_failure(field):
    value = private_detail(reason='source_review_unverified', cause='validation',
                           phase='review', field=field, rule='fields')
    assert diag.sanitize_detail(value) == value
    assert len(json.dumps(value).encode('utf-8')) <= diag.MAX_DETAIL_BYTES
    forged = dict(role='reviewer', provider='claude', model='synthetic',
                  status='failed', failure_detail=value)
    assert diag.result_detail(forged) == diag.sanitize_detail(None)
    original = ValueError(RAW + SECRET)
    original.failure_detail = value
    assert diag.exception_detail(original) == diag.sanitize_detail(None)
    diag.attach(original, diag.detail('source_review_unverified', 'validation',
        phase='review', field=field, rule='fields'))
    wrapped = diag.inherit(RuntimeError(RAW), original)
    with diag.Trace() as trace:
        diag.record('stage', wrapped)
        first = deepcopy(trace.first)
        diag.record('settlement', OSError(errno.ENOSPC, SECRET))
        assert trace.first == first
    linked = diag.attach_result(forged, source=wrapped)
    linked['failure_detail'] = dict(value, field='/private/source')
    assert diag.result_detail(linked) == first['detail'] == value
    assert diag.result_detail(json.loads(json.dumps(linked))) == diag.sanitize_detail(None)
    assert diag.sanitize_detail(dict(value, field='review.' + SECRET))['cause'] == 'unavailable'


def test_exception_metadata_uses_native_storage_without_invoking_provider_properties():
    class ProviderError(ValueError):
        @property
        def __dict__(self):
            pytest.fail('Provider __dict__ hook was invoked')

        @property
        def reason(self):
            pytest.fail('Provider reason hook was invoked')

        @property
        def failure_detail(self):
            pytest.fail('Provider failure_detail hook was invoked')

    original = ProviderError(SECRET + RAW)
    assert diag.exception_detail(original)['cause'] == 'unavailable'
    assert diag.attach(original, diag.detail('role_execution_failed', 'cli_failed',
        phase='execution', exit_code=9)) is original
    wrapped = diag.inherit(RuntimeError(RAW), original)
    assert diag.exception_detail(wrapped)['exit_code'] == 9
    result = diag.attach_result({'status': 'failed'}, source=original)
    assert diag.result_detail(result) == diag.exception_detail(wrapped)
    assert SECRET not in json.dumps(result) and RAW not in json.dumps(result)


def test_hostile_or_oversized_exception_attributes_fail_closed_without_key_hooks():
    class Collision:
        def __hash__(self):
            return hash('_improvement_failure')

        def __eq__(self, other):
            pytest.fail('Untrusted exception attribute key was compared')

    for attributes in ({Collision(): SECRET}, {str(i): RAW for i in range(64)},
                       {str(i): RAW for i in range(65)}):
        original = ValueError(RAW)
        original.__dict__.update(attributes)
        assert diag.attach(original, diag.detail('role_execution_failed', 'quota')) is original
        assert diag.exception_detail(original)['cause'] == 'unavailable'
        assert diag.exception_detail(diag.inherit(RuntimeError(), original))['reason'] == 'unknown'
    original = ValueError(RAW)
    original.__dict__.update({str(i): RAW for i in range(63)})
    diag.attach(original, diag.detail('role_execution_failed', 'cli_failed'))
    assert diag.exception_detail(original)['cause'] == 'cli_failed'


@pytest.mark.parametrize('failure', [OSError, KeyboardInterrupt])
def test_optional_event_detail_failure_keeps_broad_event_and_first_exception(monkeypatch, failure):
    value = private_detail(reason='candidate_invalid', cause='validation',
                           phase='candidate', field='title', rule='length')
    def broken(*args, **kwargs):
        raise failure(SECRET + RAW)
    monkeypatch.setattr(diag, 'sanitize_detail', broken)
    event = diag.event('stage', 'invalid', stage='specialist', slot=12, detail=value)
    assert event['reason'] == 'stage_invalid' and event['slot'] == 12
    assert event['detail']['reason'] == 'unknown'
    assert event['detail']['cause'] == 'unavailable'
    original = ValueError(RAW)
    with diag.Trace() as trace:
        with pytest.raises(ValueError) as caught:
            with diag.boundary('stage'):
                raise original
        assert caught.value is original
        first = dict(trace.first)
        diag.record('settlement', OSError(errno.ENOSPC, SECRET))
        assert trace.first == first
    assert SECRET not in json.dumps(event) and RAW not in json.dumps(first)


def test_missing_validation_coordinates_and_unavailable_causes_are_not_inferred():
    for field, rule in ((None, 'range'), ('title', None), (None, None)):
        result = private_detail(reason='candidate_invalid', cause='validation',
                               phase='candidate', field=field, rule=rule)
        assert (result['reason'], result['phase']) == ('candidate_invalid', 'candidate')
        assert (result['cause'], result['field'], result['rule']) == ('unavailable', None, None)
    for cause in ('unavailable', 'cli_failed'):
        result = private_detail(reason='role_execution_failed', cause=cause,
                               phase='execution', field='title', rule='range')
        assert result['cause'] == cause and result['field'] is result['rule'] is None


def test_result_provenance_is_private_and_lost_on_json_copy():
    result = {'role': 'parser', 'provider': 'synthetic', 'model': 'synthetic', 'status': 'failed'}
    linked = diag.attach_result(result, diag.detail('role_execution_failed', 'timeout', phase='execution'))
    assert linked == dict(result, failure_detail=diag.result_detail(linked))
    assert 'failure_detail' not in result
    assert diag.result_detail(linked)['cause'] == 'timeout'
    for forged in (dict(linked), json.loads(json.dumps(linked)),
                   dict(result, diagnostic={'category': 'authentication_failed'})):
        assert diag.result_detail(forged)['cause'] == 'unavailable'
    # Mutable display fields do not become the authoritative internal detail.
    linked['failure_detail'] = {'cause': 'quota', 'raw': SECRET}
    assert diag.result_detail(linked)['cause'] == 'timeout'
    other = diag.attach_result(result, diag.detail('role_execution_failed', 'cli_failed'))
    other.__dict__.update(linked.__dict__)
    assert diag.result_detail(other)['cause'] == 'unavailable'


def test_validator_exception_result_wrapper_chain_preserves_cause_without_reclassification():
    with pytest.raises(contract.ValidationError) as caught:
        contract.validate_candidate(dict(draft('harness/example.py'), analogy=False),
                                    {'harness/example.py': 'one\ntwo\n'})
    error = caught.value
    report = {'role': 'parser', 'provider': 'synthetic', 'model': 'synthetic', 'status': 'failed'}
    result = diag.attach_result(report, source=error)
    wrapper = diag.inherit(RuntimeError(SECRET), result)
    assert diag.exception_detail(wrapper) == diag.result_detail(result) == diag.exception_detail(error)
    assert diag.exception_detail(wrapper)['field'] == 'analogy'
    # A context cleanup failure cannot replace an existing result's first cause.
    cleanup = diag.attach_result(result, diag.detail('role_context_cleanup_failed', 'context_cleanup_failed'))
    assert cleanup is result and diag.result_detail(cleanup)['field'] == 'analogy'


@pytest.mark.parametrize('which', ['mint', 'sanitize'])
def test_diagnostic_failure_does_not_replace_validation_error_or_first_failure(monkeypatch, which):
    def broken(*args, **kwargs):
        raise OSError(errno.ENOSPC, SECRET)
    monkeypatch.setattr(diag, 'detail' if which == 'mint' else 'sanitize_detail', broken)
    with diag.Trace() as trace:
        with pytest.raises(contract.ValidationError) as caught:
            with diag.boundary('stage'):
                contract.validate_candidate(dict(draft('harness/example.py'), title=None),
                                            {'harness/example.py': 'one\ntwo\n'})
        assert str(caught.value) == 'empty or oversized text'
        first = dict(trace.first)
        with pytest.raises(OSError):
            with diag.boundary('settlement'):
                raise OSError(errno.ENOSPC, SECRET)
        assert trace.first == first and first['reason'] == 'stage_invalid'
        assert first['detail']['cause'] == 'unavailable'


def test_unavailable_diagnostic_clock_preserves_original_error_and_first_boundary(monkeypatch):
    class MissingClock:
        @staticmethod
        def now(*args):
            raise ValueError(SECRET)
    monkeypatch.setattr(diag, 'datetime', MissingClock)
    original = ValueError(RAW)
    with diag.Trace() as trace:
        with pytest.raises(ValueError) as caught:
            with diag.boundary('snapshot'):
                raise original
        assert caught.value is original
        diag.record('settlement', OSError(errno.ENOSPC, SECRET))
        assert trace.first['at'] is None
        assert trace.first['reason'] == 'snapshot_invalid'
        assert trace.first['detail']['cause'] == 'unavailable'


@pytest.mark.parametrize('path,value,field,rule', [
    (('title',), None, 'title', 'type'),
    (('title',), ' ', 'title', 'empty'),
    (('title',), '가' * 321, 'title', 'length'),
    (('title',), '가\0', 'title', 'control'),
    (('title',), '가\ud800', 'title', 'encoding'),
    (('title',), 'English', 'title', 'korean'),
    (('analogy',), 'English', 'analogy', 'korean'),
    (('analogy',), [], 'analogy', 'type'),
    (('priority',), 'urgent', 'priority', 'allowlist'),
    (('issue',), '', 'issue', 'empty'),
    (('evidence',), [], 'evidence', 'length'),
    (('evidence',), {}, 'evidence', 'type'),
    (('evidence', 0), {}, 'evidence', 'fields'),
    (('evidence', 0, 'path'), '../private/secret', 'evidence.path', 'path'),
    (('evidence', 0, 'path'), 'harness/other.py', 'evidence.path', 'outside_scope'),
    (('evidence', 0, 'start_line'), True, 'evidence.start_line', 'type'),
    (('evidence', 0, 'start_line'), 0, 'evidence.start_line', 'range'),
    (('evidence', 0, 'end_line'), 3, 'evidence.end_line', 'range'),
    (('evidence', 0, 'summary'), '', 'evidence.summary', 'empty'),
    (('benefit',), [], 'benefit', 'type'),
    (('benefit', 'kind'), 'invented', 'benefit.kind', 'allowlist'),
    (('benefit', 'text'), False, 'benefit.text', 'type'),
    (('benefit', 'evidence'), {}, 'benefit.evidence', 'type'),
    (('risk',), None, 'risk', 'type'),
    (('validation_plan',), [], 'validation_plan', 'length'),
    (('validation_plan', 0), '가' * 801, 'validation_plan', 'length'),
    (('documentation_impact',), '', 'documentation_impact', 'empty'),
])
def test_shared_candidate_classifies_at_actual_rejection_without_values(path, value, field, rule):
    candidate = draft('harness/example.py')
    target = candidate
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(contract.ValidationError) as caught:
        contract.validate_candidates({'candidates': [candidate]}, {'harness/example.py': 'one\ntwo\n'})
    result = diag.exception_detail(caught.value)
    assert result == dict(version=diag.DETAIL_VERSION, reason='candidate_invalid', cause='validation',
        phase='candidate', field=field, rule=rule, errno=None, exit_code=None, http_status=None)
    assert SECRET not in json.dumps(result) and 'private/secret' not in json.dumps(result)


@pytest.mark.parametrize('edits,rule,reason', [
    ([], 'length', 'candidate_edit_files_invalid'),
    ('harness/example.py', 'type', 'candidate_edit_files_invalid'),
    (['../private/secret'], 'path', 'candidate_edit_files_invalid'),
    (['harness/example.py'] * 2, 'duplicate', 'candidate_edit_files_duplicate'),
    (['harness/other.py'], 'outside_scope', 'candidate_edit_files_outside_scope'),
])
def test_edit_file_three_reasons_are_compatible_and_detail_is_more_specific(edits, rule, reason):
    with pytest.raises(contract.ValidationError) as caught:
        contract.validate_candidate(dict(draft('harness/example.py'), edit_files=edits),
                                    {'harness/example.py': 'one\ntwo\n'})
    result = diag.exception_detail(caught.value)
    assert caught.value.reason == result['reason'] == reason
    assert (result['field'], result['rule']) == ('edit_files', rule)


def test_schema_candidate_collection_and_measured_benefit_failures_are_distinct():
    candidate = draft('harness/example.py')
    source = {'harness/example.py': 'one\ntwo\n'}
    for value, field, rule in [
            ([], 'schema', 'type'),
            ({'candidates': [], SECRET: RAW}, 'schema', 'fields'),
            ({'candidates': None}, 'candidates', 'type'),
            ({'candidates': [candidate] * 3}, 'candidates', 'length'),
            ({'candidates': [None]}, 'schema', 'type'),
            ({'candidates': [dict(candidate, **{SECRET: RAW})]}, 'schema', 'fields'),
            ({'candidates': [candidate, candidate]}, 'candidates', 'duplicate')]:
        with pytest.raises(contract.ValidationError) as caught:
            contract.validate_candidates(value, source)
        result = diag.exception_detail(caught.value)
        assert (result['field'], result['rule']) == (field, rule)
        assert SECRET not in json.dumps(result) and RAW not in json.dumps(result)
    candidate['benefit']['kind'] = 'measured'
    with pytest.raises(contract.ValidationError) as caught:
        contract.validate_candidate(candidate, source)
    assert diag.exception_detail(caught.value)['field'] == 'benefit.evidence'
    assert diag.exception_detail(caught.value)['rule'] == 'length'
    candidate['benefit']['evidence'] = [dict(candidate['evidence'][0], end_line=3)]
    with pytest.raises(contract.ValidationError) as caught:
        contract.validate_candidate(candidate, source)
    assert diag.exception_detail(caught.value)['field'] == 'benefit.evidence.end_line'


@pytest.mark.parametrize('source,field,rule', [
    (None, 'evidence.path', 'source_unavailable'),
    (False, 'sources', 'type'),
    ('\ud800', 'sources', 'encoding'),
    ('x' * 131073, 'sources', 'byte_limit')])
def test_source_failures_use_fixed_fields_without_source_or_host_path(source, field, rule):
    with pytest.raises(contract.ValidationError) as caught:
        contract.validate_candidate(draft('harness/example.py'), {'harness/example.py': source})
    result = diag.exception_detail(caught.value)
    assert (result['field'], result['rule']) == (field, rule)
    assert 'harness/example.py' not in json.dumps(result)


def test_edit_character_budget_and_existing_duplicate_acceptance_are_preserved():
    candidate = draft('harness/example.py')
    sources = {'harness/example.py': 'one\ntwo\n'}
    # These duplicates have always been permitted; only the existing edit-file
    # and whole-candidate uniqueness checks confer duplicate rejection.
    candidate['evidence'] *= 2
    candidate['validation_plan'] *= 2
    assert contract.validate_candidate(candidate, sources) == candidate
    edits = ['harness/' + letter * 200 + '.py' for letter in 'abc']
    sources.update({path: None for path in edits})
    candidate['edit_files'] = edits
    with pytest.raises(contract.ValidationError) as caught:
        contract.validate_candidate(candidate, sources)
    result = diag.exception_detail(caught.value)
    assert caught.value.reason == result['reason'] == 'candidate_edit_files_invalid'
    assert (result['field'], result['rule']) == ('edit_files', 'length')


def test_first_candidate_rejection_order_and_later_success_do_not_erase_trace(monkeypatch):
    candidate = dict(draft('harness/example.py'), title='English', analogy=None, edit_files=[])
    sources = {'harness/example.py': 'one\ntwo\n'}
    calls = []
    validate = contract.validate_candidate
    def once(*args, **kwargs):
        calls.append(True)
        return validate(*args, **kwargs)
    monkeypatch.setattr(contract, 'validate_candidate', once)
    with diag.Trace() as trace:
        diag.position('specialist', 13)
        with pytest.raises(contract.ValidationError):
            with diag.boundary('stage'):
                contract.validate_candidates({'candidates': [candidate]}, sources)
        assert len(calls) == 1  # No second validation to reconstruct a cause.
        first = dict(trace.first)
        # Existing evaluation validates analogy text before checking title Korean.
        assert first['detail']['field'] == 'analogy' and first['detail']['rule'] == 'type'
        diag.position('settlement', 14)
        diag.record('diagnostic_save', OSError(errno.ENOSPC, SECRET))
        assert contract.validate_candidate(draft('harness/example.py'), sources) == draft('harness/example.py')
        assert trace.first == first and first['slot'] == 13


def test_private_detail_does_not_change_public_projection_or_digest():
    report = {'date': '2026-10-15', 'generated_at': '2026-10-15T09:00:00+09:00',
        'status': 'failed', 'proposals': [],
        'agents': [{'role': 'parser', 'provider': 'synthetic', 'model': 'synthetic', 'status': 'failed'}],
        'documentation': {'status': 'not_required', 'files': [],
                          'reason': '읽기 전용 합성 분석이며 구조나 계약 변경은 없습니다.'}}
    before = contract.build_web_report(report)
    failure = private_detail(reason='candidate_invalid', cause='validation',
                             phase='candidate', field='evidence.end_line', rule='range')
    report['failure_detail'] = failure
    report['diagnostic'] = diag.event('stage', 'invalid', detail=failure)
    report['agents'][0].update(failure_detail=failure, reason='candidate_invalid', error_type='ValidationError')
    after = contract.build_web_report(report)
    assert contract.canonical_json(after) == contract.canonical_json(before)
    assert after['digest'] == before['digest']
    assert 'failure_detail' not in json.dumps(after) and 'candidate_invalid' not in json.dumps(after)
