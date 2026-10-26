"""Pure and fake-HTTP health regressions. Parent owns execution."""
import copy
import datetime as dt
import json
import os
import select
import signal
import time
from contextlib import contextmanager

import pytest

from harness import improvement_health as health, improvement_loop as loop
from harness import improvement_report as contract, improvement_diagnostics as diag
from harness import improvements as imp
from harness.test_improvements import lab, NOW, DATE, scan, inbox, forbidden
from harness.test_improvement_loop import lab as tick_lab, offline as tick_offline


@pytest.fixture
def hourly(tick_offline, tick_lab, monkeypatch):
    """Real tick seams, synthetic runners/HTTP, no execution authority."""
    for name in ('approve', 'execute', 'reject'):
        monkeypatch.setattr(imp, name, forbidden)
    return tick_lab


class TickTransport:
    def __init__(self, lab, monkeypatch):
        self.lab, self.calls, self.remote = lab, [], None
        self.mode, self.deadline = None, False
        deadline = loop._deadline

        @contextmanager
        def tracked(seconds):
            self.deadline = True
            try:
                with deadline(seconds):
                    yield
            finally:
                self.deadline = False
        monkeypatch.setattr(loop, '_deadline', tracked)
        monkeypatch.setattr(imp, '_inbox_config', lambda path: ('https://fixture.invalid', 'fixture-token'))
        monkeypatch.setattr(imp, 'http_transport', self)

    def __call__(self, method, origin, path, headers, body, timeout, max_bytes):
        assert path == '/api/health' and not self.deadline
        assert origin == 'https://fixture.invalid' and timeout <= 30 and max_bytes <= health.MAX_BYTES
        # Both mutexes can be acquired anew: no nested/reentrant loophole.
        with self.lab.store.lock(), loop.project_lock.hold(self.lab.selected, reentrant=False):
            state = loop._read_state(self.lab.store)
            journal = self.lab.store.read(health.OUTBOX)
            assert state['inflight'] is None
            if method == 'POST':
                assert journal['status'] == 'sending'
                assert body == contract.canonical_json(journal['payload'])
                assert health.validate(json.loads(body)) == health.project(
                    state, journal['payload']['generated_at'])
        self.calls.append(method)
        if method == 'POST':
            self.remote = json.loads(body)
            if self.mode == 'lost':
                raise OSError('PRIVATE fixture-token /host/path')
            return 201, b'{}'
        assert method == 'GET' and body is None
        if self.mode == 'absent':
            return 404, b'{}'
        return 200, contract.canonical_json(self.remote)


def attempt(hour, status='failed', *, legacy=False):
    stamp = dt.datetime(2026, 10, 26, hour, tzinfo=contract.KST)
    error = diag.attach(ValueError('PRIVATE secret /host/path'),
                        diag.detail('role_json_invalid', 'json_invalid', phase='json'))
    row = dict(scan_id='123456789-abcdef', role='downloader', provider='PRIVATE provider',
        model='PRIVATE model', stage_index=3, stage='specialist', status=status,
        slot=stamp.strftime('%Y-%m-%dT%H'), started_at=stamp.isoformat(),
        finished_at=(stamp + dt.timedelta(seconds=147)).isoformat(),
        reason='role_json_invalid', failure_detail=diag.exception_detail(error))
    if not legacy:
        row.update(call_started_at=stamp.isoformat(), call_finished_at=row['finished_at'])
    return row


def state_with_history():
    state = loop._new_state()
    state.update(stage_index=4, pause_reason='quota_headroom',
                 participation=[attempt(0), attempt(9), attempt(12, 'succeeded')])
    return state


def payload(state=None):
    return health.project(state or state_with_history(), '2026-10-26T13:00:00+09:00')


def resign(value):
    value['digest'] = contract.digest({k: v for k, v in value.items() if k != 'digest'})
    return value


def test_failure_stage_cause_actual_times_and_distinct_later_role_success():
    state = state_with_history()
    before = copy.deepcopy(state)
    value = payload(state)
    assert state == before
    assert health.validate(value) == value
    assert [r['role'] for r in value['roles']] == list(contract.ROLES)
    assert value['roles'][1]['latest']['status'] == 'succeeded'
    assert len(value['recent_failures']) == 2
    first = value['recent_failures'][0]
    assert first['attempt']['stage_index'] == 3
    assert first['attempt']['reason'] == 'role_json_invalid'
    assert first['attempt']['cause'] == 'json_invalid'
    assert first['attempt']['phase'] == 'json'
    assert first['attempt']['call_started_at'] == '2026-10-26T00:00:00+09:00'
    assert first['attempt']['call_finished_at'] == '2026-10-26T00:02:27+09:00'
    assert first['subsequent_success_at'] == '2026-10-26T12:02:27+09:00'
    assert value['hold_code'] == 'quota_headroom'
    assert value['next_stage'] == dict(stage_index=4, stage='local_explorer', role='parser')
    assert 'PRIVATE' not in json.dumps(value)


def test_legacy_unknown_is_not_backfilled_and_other_role_success_cannot_repair_failure():
    state = state_with_history()
    old = attempt(0, legacy=True)
    old.pop('failure_detail')
    state['participation'] = [old, attempt(9, 'succeeded')]
    first = payload(state)['recent_failures'][0]
    assert first['attempt']['cause'] == 'unavailable'
    assert first['attempt']['call_started_at'] is None
    assert first['subsequent_success_at'] is None
    state['participation'][0] = attempt(0)
    success = state['participation'][1]
    success.update(role='reviewer', stage_index=8, stage='independent_reviewer')
    assert payload(state)['recent_failures'][0]['subsequent_success_at'] is None


def test_projection_redacts_local_history_arbitrary_codes_and_forged_detail():
    state = state_with_history()
    state['local_history'] = [{'endpoint': 'http://secret', 'model': 'PRIVATE local'}]
    state['pause_reason'] = 'PRIVATE exception /host/path'
    state['participation'][0]['failure_detail']['field'] = '/host/path'
    state['participation'][0]['failure_detail']['extra'] = 'PRIVATE response'
    state['participation'][0]['reason'] = 'PRIVATE reason'
    state['participation'].append(dict(attempt(13), stage_index=2, stage='local_explorer'))
    value = payload(state)
    assert value['hold_code'] == 'unknown'
    assert value['recent_failures'][0]['attempt']['reason'] == 'unknown'
    assert value['recent_failures'][0]['attempt']['cause'] == 'unavailable'
    assert len(value['recent_failures']) == 2
    assert all(x not in json.dumps(value) for x in ('PRIVATE', '/host/path', 'endpoint', 'cost', 'model', 'provider'))
    state['pause_reason'] = 'endpoint_invalid'  # A valid local detail stays private.
    assert payload(state)['hold_code'] == 'unknown'


def test_unknown_role_observation_and_rollback_do_not_invent_success_times():
    state = state_with_history()
    state['participation'][0]['call_finished_at'] = '2026-10-25T23:59:59+09:00'
    state['participation'][1]['status'] = 'unavailable'
    state['participation'][-1]['status'] = 'reserved'
    value = payload(state)
    assert value['roles'][0]['latest'] is None
    assert value['roles'][1]['latest']['status'] == 'reserved'
    assert value['recent_failures'][0]['attempt']['call_finished_at'] is None
    assert value['recent_failures'][0]['subsequent_success_at'] is None
    assert value['recent_failures'][1]['attempt']['status'] == 'unavailable'


@pytest.mark.parametrize('stamp', ['2026-10-26/00:00:00+09:00',
    '2026-10-26\x0100:00:00+09:00', '2026-10-26T00:00:00', '2026-10-26T00:00:00+09:00private'])
def test_health_times_reject_hidden_strings_and_missing_timezone(stamp):
    value = payload()
    value['generated_at'] = stamp
    with pytest.raises(contract.ValidationError):
        health.validate(resign(value))


@pytest.mark.parametrize('mutation', ['extra', 'model', 'role', 'stage', 'bool', 'cause',
    'phase', 'field', 'time', 'backwards', 'success_detail', 'later', 'hold', 'digest'])
def test_strict_health_schema_rejects_even_redigested_invalid_fields(mutation):
    value = payload()
    item = value['recent_failures'][0]['attempt']
    if mutation == 'extra':
        value['exception'] = 'private'
    elif mutation == 'model':
        item['model'] = 'private'
    elif mutation == 'role':
        item['role'] = 'local_explorer'
    elif mutation == 'stage':
        item['stage_index'] = 2
    elif mutation == 'bool':
        item['stage_index'] = True
    elif mutation == 'cause':
        item['cause'] = 'private'
    elif mutation == 'phase':
        item['phase'] = 'private'
    elif mutation == 'field':
        item.update(cause='validation', field='outside.path', rule='range')
    elif mutation == 'time':
        item['call_started_at'] = '/host/path'
    elif mutation == 'backwards':
        item['call_finished_at'] = '2026-10-25T23:00:00+09:00'
    elif mutation == 'success_detail':
        value['roles'][1]['latest']['cause'] = 'json_invalid'
    elif mutation == 'later':
        value['recent_failures'][0]['subsequent_success_at'] = '2026-10-25T23:00:00+09:00'
    elif mutation == 'hold':
        value['hold_code'] = 'private'
    if mutation == 'digest':
        value['digest'] = '0' * 64
    else:
        resign(value)
    with pytest.raises(contract.ValidationError):
        health.validate(value)


def test_history_is_bounded_and_payload_is_detached():
    state = state_with_history()
    state['participation'] = [attempt(i % 24) for i in range(192)]
    value = payload(state)
    assert len(value['recent_failures']) == health.MAX_FAILURES
    value['recent_failures'][0]['attempt']['reason'] = 'changed'
    assert state['participation'][0]['reason'] == 'role_json_invalid'


class Transport:
    def __init__(self, store, mode=None):
        self.store, self.mode, self.calls, self.remote = store, mode, [], None

    def __call__(self, method, origin, path, headers, body, timeout, max_bytes):
        self.calls.append(method)
        assert path == '/api/health' and origin == 'https://fixture.invalid'
        assert headers['OAI-Sites-Authorization'] == 'Bearer fixture-service-token'
        assert max_bytes <= health.MAX_BYTES and timeout <= 30
        # HTTP is outside the state/discovery lock; sender mutex still guards it.
        with self.store.lock():
            journal = self.store.read(health.OUTBOX)
        if method == 'POST':
            assert journal['status'] == 'sending'
            assert body == contract.canonical_json(journal['payload'])
            self.remote = json.loads(body)
            if self.mode == 'lost':
                raise OSError('fixture-service-token /host/path')
            return 201, b'{}'
        assert body is None
        if self.mode == 'absent':
            return 404, b'{}'
        if self.mode == 'duplicate':
            return 200, b'{"version":"x","version":"x"}'
        if self.mode == 'oversize':
            return 200, b'x' * (max_bytes + 1)
        if self.mode == 'redirect':
            return 302, b'private'
        remote = copy.deepcopy(self.remote)
        if self.mode == 'conflict':
            remote['hold_code'] = 'unknown'
            resign(remote)
        if self.mode == 'same_digest_changed':
            remote['hold_code'] = 'unknown'
        return 200, contract.canonical_json(remote)


def test_query_no_keys_no_http_and_delivery_preserves_frozen_web(lab, monkeypatch):
    scan(lab)
    frozen = lab.store.path('web/' + DATE + '.json').read_bytes()
    with lab.store.lock():
        lab.store.write(loop.STATE_FILE, state_with_history())
    monkeypatch.setattr(imp, '_inbox_config', forbidden)
    value = health.query(now=NOW, selected=lab.selected)
    assert len(value['recent_failures']) == 2
    assert not lab.store.exists(health.OUTBOX)
    assert lab.store.path('web/' + DATE + '.json').read_bytes() == frozen


def test_fixed_post_identical_get_digest_and_separate_private_journal(lab):
    scan(lab)
    frozen = lab.store.path('web/' + DATE + '.json').read_bytes()
    transport = Transport(lab.store)
    result = health.publish(now=NOW, selected=lab.selected, inbox_config=inbox(lab), transport=transport)
    assert result['status'] == 'delivered' and transport.calls == ['POST', 'GET']
    assert lab.store.path('web/' + DATE + '.json').read_bytes() == frozen
    assert lab.store.path(health.OUTBOX).stat().st_mode & 0o777 == 0o600
    assert lab.store.path('health').stat().st_mode & 0o777 == 0o700
    assert health.publish(selected=lab.selected, inbox_config=inbox(lab), transport=forbidden,
                          digest=result['digest']) == result


@pytest.mark.parametrize('mode', ['duplicate', 'oversize', 'redirect', 'conflict', 'absent', 'same_digest_changed'])
def test_bad_get_is_never_delivery_success(lab, mode):
    transport = Transport(lab.store, mode)
    result = health.publish(now=NOW, selected=lab.selected, inbox_config=inbox(lab), transport=transport)
    assert result['status'] != 'delivered'
    assert transport.calls == ['POST', 'GET']
    assert lab.store.read(health.OUTBOX)['status'] in ('unknown', 'conflict')
    assert 'fixture-service-token' not in json.dumps(result)


def test_conflict_never_reposts_or_overwrites_frozen_journal(lab):
    transport = Transport(lab.store, 'conflict')
    result = health.publish(now=NOW, selected=lab.selected, inbox_config=inbox(lab), transport=transport)
    assert result['status'] == 'conflict'
    frozen = lab.store.read(health.OUTBOX)
    with lab.store.lock():
        lab.store.write(loop.STATE_FILE, state_with_history())
    again = health.publish(selected=lab.selected, transport=forbidden,
                           reconcile=True, digest=result['digest'])
    assert again == result and lab.store.read(health.OUTBOX) == frozen


def test_unknown_and_sending_only_get_explicit_same_digest_reconcile(lab):
    transport = Transport(lab.store, 'lost')
    initial = health.publish(now=NOW, selected=lab.selected, inbox_config=inbox(lab), transport=transport)
    assert initial['status'] == 'delivery_failed'
    digest = initial['digest']
    frozen = lab.store.read(health.OUTBOX)['payload']
    transport.mode = 'absent'
    for status in ('unknown', 'sending'):
        with lab.store.lock():
            lab.store.write(health.OUTBOX, dict(payload=frozen, status=status))
        result = health.publish(selected=lab.selected, inbox_config=inbox(lab), transport=transport)
        assert result['status'] == 'unknown'
    assert transport.calls == ['POST', 'GET', 'GET']
    with pytest.raises(ValueError):
        health.publish(selected=lab.selected, reconcile=True, digest='0' * 64, transport=forbidden)
    with pytest.raises(ValueError):
        health.publish(selected=lab.selected, reconcile=True, transport=forbidden)
    # GET 404 authorizes only this explicit same-digest POST. Its subsequent GET
    # remains absent in this fixture, so it truthfully stays unknown.
    result = health.publish(selected=lab.selected, inbox_config=inbox(lab), transport=transport,
                            reconcile=True, digest=digest)
    assert result['status'] == 'unknown' and transport.calls[-3:] == ['GET', 'POST', 'GET']
    assert lab.store.read(health.OUTBOX)['payload'] == frozen
    transport.mode = None
    result = health.publish(selected=lab.selected, inbox_config=inbox(lab), transport=transport)
    assert result['status'] == 'delivered' and transport.calls[-1] == 'GET'


@pytest.mark.parametrize('guard', ['TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
                                  'TAVERN_IMPROVEMENT_UNATTENDED'])
def test_parent_only_publish_rejects_before_storage_keys_or_http(monkeypatch, guard):
    monkeypatch.setenv(guard, '1')
    monkeypatch.setattr(imp, 'Store', forbidden)
    with pytest.raises(imp.ImprovementError):
        health.publish(transport=forbidden)


def test_publisher_does_not_accept_forged_caller_health_body():
    with pytest.raises(TypeError):
        health.publish(payload=payload())


def test_hourly_failed_role_and_subsequent_success_publish_after_durable_unlock(hourly, monkeypatch):
    wire = TickTransport(hourly, monkeypatch)
    monkeypatch.setenv('TAVERN_IMPROVEMENT_UNATTENDED', '1')
    hourly.hours(count=3)

    def malformed(role, result, response, options):
        return dict(result, response='{') if role == 'downloader' else result
    hourly.cloud_transform = malformed
    failed = hourly.tick(3, deliver=True)
    assert failed['reason'] == 'role_json_invalid' and failed['status'] == 'paused'
    assert failed['health_publication']['status'] == 'delivered'
    first = copy.deepcopy(wire.remote['recent_failures'][-1])
    assert first['attempt']['stage_index'] == 3
    assert first['attempt']['cause'] == 'json_invalid'
    assert first['attempt']['phase'] == 'json' and first['subsequent_success_at'] is None
    history = copy.deepcopy(hourly.state()['participation'])
    assert hourly.calls() == len(hourly.events) == 4

    hourly.cloud_transform = None
    hourly.hours(start=4, count=8)
    # Morning delivery is orthogonal; only its existing path is replaced here.
    monkeypatch.setattr(imp, 'deliver_report', lambda date, **kw: {
        'status': 'delivered', 'date': date,
        'digest': hourly.store.read('web/' + date + '.json')['digest']})
    names = ('days/' + DATE + '.json', 'web/' + DATE + '.json', loop._publication_name(DATE))
    # Settle the already frozen morning independently before comparing it.
    loop.publish(now=hourly.clock(), selected=hourly.selected)
    frozen = {name: hourly.store.path(name).read_bytes() for name in names}
    succeeded = hourly.tick(12, deliver=True)
    assert succeeded['health_publication']['status'] == 'delivered'
    assert wire.calls == ['POST', 'GET', 'POST', 'GET']
    later = wire.remote['recent_failures'][-1]
    assert later['attempt'] == first['attempt']
    assert later['subsequent_success_at'] == hourly.clock().isoformat()
    assert wire.remote['roles'][1]['latest']['status'] == 'succeeded'
    assert hourly.state()['participation'][:len(history)] == history
    assert hourly.calls() == len(hourly.events) == 13
    assert {name: hourly.store.path(name).read_bytes() for name in names} == frozen
    assert hourly.store.path(health.OUTBOX).stat().st_mode & 0o777 == 0o600
    assert hourly.store.path('health').stat().st_mode & 0o777 == 0o700
    # The unattended observation path has not relaxed manual CLI authority.
    with pytest.raises(imp.ImprovementError):
        health.publish(selected=hourly.selected)


@pytest.mark.parametrize('role_failure', [False, True])
def test_health_transport_failure_does_not_replace_tick_failure_or_accounting(hourly, monkeypatch, role_failure):
    hourly.tick(0)
    def response(role, result, body, options):
        return dict(result, response='{') if role_failure else result
    hourly.cloud_transform = response
    wire = TickTransport(hourly, monkeypatch)
    wire.mode = 'lost'
    result = hourly.tick(1, deliver=True)
    assert result['health_publication']['status'] == 'delivery_failed'
    assert result['status'] == ('paused' if role_failure else 'researching')
    assert result['reason'] == ('role_json_invalid' if role_failure else None)
    if role_failure:
        assert result['diagnostic']['detail']['reason'] == 'role_json_invalid'
        assert hourly.store.read('loop/last-diagnostic.json') == result['diagnostic']
    else:
        assert 'diagnostic' not in result
    assert hourly.calls() == len(hourly.events) == 2 and hourly.state()['stage_index'] == 2
    assert hourly.state()['inflight'] is None
    assert hourly.state()['participation'][-1]['status'] == ('failed' if role_failure else 'succeeded')
    assert hourly.spent() == 0 and wire.calls == ['POST']
    frozen = hourly.store.read(health.OUTBOX)['payload']
    wire.mode = 'absent'
    result = hourly.tick(2, deliver=True)
    assert result['health_publication']['status'] == 'unknown'
    assert wire.calls == ['POST', 'GET']
    assert hourly.store.read(health.OUTBOX)['payload'] == frozen
    with hourly.store.lock():
        hourly.store.write(health.OUTBOX, dict(payload=frozen, status='sending'))
    result = hourly.tick(3, deliver=True)
    assert result['health_publication']['status'] == 'unknown'
    assert wire.calls == ['POST', 'GET', 'GET']
    assert hourly.store.read(health.OUTBOX)['payload'] == frozen


@pytest.mark.parametrize('point', ['config', 'store', 'readiness', 'binding', 'lock', 'state', 'bootstrap'])
def test_unqualified_startup_never_invokes_health_or_credentials(hourly, monkeypatch, point):
    attempts = []
    def unavailable(*args, **kwargs):
        attempts.append(point)
        raise OSError('PRIVATE /host/path')
    seams = {'config': (loop, 'load_config'), 'store': (imp, 'Store'),
             'readiness': (type(hourly.selected), 'check_ready'),
             'binding': (loop.project_lock, 'bind_discovery_root'),
             'lock': (imp.Store, 'lock'), 'state': (loop, '_read_state'),
             'bootstrap': (loop, '_tick_locked')}
    obj, name = seams[point]
    monkeypatch.setattr(obj, name, unavailable)
    monkeypatch.setattr(health, '_after_tick', forbidden)
    monkeypatch.setattr(loop, 'publish', forbidden)
    monkeypatch.setattr(imp, '_inbox_config', forbidden)
    monkeypatch.setattr(imp, 'http_transport', forbidden)
    result = hourly.tick(9, deliver=True)
    assert result['status'] == 'paused' and 'health_publication' not in result
    assert attempts == [point] and hourly.events == []
    assert not hourly.store.exists(health.OUTBOX)


@pytest.mark.parametrize('guard', ['TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY'])
def test_tick_and_internal_sender_reject_child_before_storage(hourly, monkeypatch, guard):
    monkeypatch.setenv(guard, '1')
    monkeypatch.setattr(imp, 'Store', forbidden)
    monkeypatch.setattr(loop, 'load_config', forbidden)
    monkeypatch.setattr(health, '_publish', forbidden)
    with pytest.raises(imp.ImprovementError):
        hourly.tick(0, deliver=True)
    assert health._after_tick(hourly.store, hourly.clock, '2026-10-15T00') == {'status': 'health_unavailable'}


def test_status_query_morning_no_deliver_and_replayed_slot_never_send_health(hourly, monkeypatch):
    monkeypatch.setattr(health, '_after_tick', forbidden)
    monkeypatch.setattr(imp, '_inbox_config', forbidden)
    monkeypatch.setattr(imp, 'http_transport', forbidden)
    assert 'health_publication' not in hourly.tick(0)
    assert 'health_publication' not in loop.status(now=hourly.clock(), selected=hourly.selected)
    health.query(now=hourly.clock(), selected=hourly.selected)
    assert loop.publish(now=hourly.clock(), selected=hourly.selected)['status'] == 'before_report_time'
    assert 'health_publication' not in hourly.tick(0, deliver=True)
    assert 'health_publication' not in hourly.tick(1, deliver=False)
    assert hourly.calls() == 2 and not hourly.store.exists(health.OUTBOX)


@pytest.mark.parametrize('when', ['before_tick', 'during_call', 'after_unlock'])
def test_clock_rollback_never_sends_health(hourly, monkeypatch, when):
    hourly.tick(0)
    monkeypatch.setattr(imp, '_inbox_config', forbidden)
    monkeypatch.setattr(imp, 'http_transport', forbidden)
    if when == 'before_tick':
        hourly.tick(1)
        result = hourly.tick(0, deliver=True)
        assert result['reason'] == 'clock_rollback'
    elif when == 'during_call':
        def rollback(role, result, body, options):
            hourly.clock.at(0)
            return result
        hourly.cloud_transform = rollback
        result = hourly.tick(1, deliver=True)
        assert result['reason'] == 'clock_rollback_during_call'
    else:
        sender = health._after_tick
        def rollback(store, clock, slot):
            hourly.clock.at(0)
            return sender(store, clock, slot)
        monkeypatch.setattr(health, '_after_tick', rollback)
        result = hourly.tick(1, deliver=True)
        assert result['health_publication'] == {'status': 'clock_rollback'}
    assert not hourly.store.exists(health.OUTBOX)


@pytest.mark.parametrize('role_failure', [False, True])
@pytest.mark.parametrize('failure_type', [OSError, KeyboardInterrupt])
def test_post_tick_sender_failure_is_separate_from_completed_research(
        hourly, monkeypatch, role_failure, failure_type):
    hourly.tick(0)
    if role_failure:
        hourly.cloud_transform = lambda role, result, response, options: dict(result, response='{')
    attempts = []
    def unavailable(*args, **kwargs):
        attempts.append(True)
        raise failure_type('PRIVATE /host/path')
    sender = health._after_tick
    def fail_after_settlement(store, clock, slot):
        # Model a real sender acquisition failure. Keep pytest.fail-based
        # forbidden guards for unexpected authority/transport calls: they must
        # escape the production Exception/KeyboardInterrupt boundary.
        monkeypatch.setattr(loop, '_stable_sender_lock', unavailable)
        return sender(store, clock, slot)
    monkeypatch.setattr(health, '_after_tick', fail_after_settlement)
    monkeypatch.setattr(imp, '_inbox_config', forbidden)
    monkeypatch.setattr(imp, 'http_transport', forbidden)
    result = hourly.tick(1, deliver=True)
    assert result['health_publication'] == {'status': 'health_unavailable'}
    assert attempts == [True] and not hourly.store.exists(health.OUTBOX)
    assert result['status'] == ('paused' if role_failure else 'researching')
    assert result['reason'] == ('role_json_invalid' if role_failure else None)
    if role_failure:
        assert result['diagnostic']['detail']['reason'] == 'role_json_invalid'
        assert hourly.store.read('loop/last-diagnostic.json') == result['diagnostic']
    else:
        assert 'diagnostic' not in result
    assert hourly.state()['stage_index'] == 2 and hourly.calls() == len(hourly.events) == 2
    assert hourly.state()['inflight'] is None and hourly.spent() == 0
    assert hourly.state()['participation'][-1]['status'] == ('failed' if role_failure else 'succeeded')


@pytest.mark.parametrize('point', ['bootstrap', 'claim_save', 'final_save'])
def test_failed_bootstrap_or_state_save_has_no_readiness_retry_or_health(hourly, monkeypatch, point):
    ready_calls, at_failure = [], []
    ready = hourly.selected.check_ready
    def observed_ready():
        ready_calls.append(True)
        return ready()
    monkeypatch.setattr(hourly.selected, 'check_ready', observed_ready)

    @diag.at('state_save' if point != 'bootstrap' else 'stage')
    def fail(*args, **kwargs):
        at_failure.append(len(ready_calls))
        raise OSError('PRIVATE /host/path')
    if point == 'bootstrap':
        monkeypatch.setattr(loop, '_tick_locked', fail)
    else:
        write = loop._write_state
        def save(store, state):
            final = state['stage_index'] == 1 and state['inflight'] is None
            if point == 'claim_save' or final:
                return fail()
            return write(store, state)
        monkeypatch.setattr(loop, '_write_state', save)
    monkeypatch.setattr(health, '_after_tick', forbidden)
    monkeypatch.setattr(imp, '_inbox_config', forbidden)
    monkeypatch.setattr(imp, 'http_transport', forbidden)
    result = hourly.tick(9, deliver=True)
    assert result['status'] == 'paused' and 'health_publication' not in result
    assert at_failure == [len(ready_calls)]
    assert result['diagnostic_preservation'] == 'private_result_only'
    assert len(hourly.events) == int(point == 'final_save')
    assert not hourly.store.exists(health.OUTBOX)


def test_morning_transport_exception_keeps_role_failure_and_separate_health(hourly, monkeypatch):
    hourly.hours(count=3)
    hourly.cloud_transform = lambda role, result, response, options: dict(result, response='{')
    wire = TickTransport(hourly, monkeypatch)
    def failed_morning(**options):
        raise OSError('PRIVATE /host/path')
    monkeypatch.setattr(loop, 'publish', failed_morning)
    result = hourly.tick(9, deliver=True)
    assert result['status'] == 'paused' and result['reason'] == 'role_json_invalid'
    assert result['diagnostic']['detail']['reason'] == 'role_json_invalid'
    assert result['publication'] == {'status': 'publication_unknown'}
    assert result['health_publication']['status'] == 'delivered' and wire.calls == ['POST', 'GET']
    assert hourly.state()['stage_index'] == 4 and hourly.calls() == len(hourly.events) == 4


@pytest.mark.parametrize('duplicate_deliver', [False, True])
def test_same_slot_process_during_morning_post_preserves_sender_busy_and_health(
        hourly, monkeypatch, duplicate_deliver):
    wire = TickTransport(hourly, monkeypatch)
    morning_calls, remote, duplicates = [], [], []
    hourly.hours()

    def http(method, origin, path, headers, body, timeout, max_bytes):
        if path == '/api/health':
            return wire(method, origin, path, headers, body, timeout, max_bytes)
        morning_calls.append((method, path))
        if method == 'GET':
            assert path == '/api/reports/' + DATE and body is None
            return 200, contract.canonical_json(remote[0])
        assert method == 'POST' and path == '/api/reports'
        remote.append(contract.validate_web_report(json.loads(body)))
        return 201, b'{}'

    def morning_publisher(date, *, selected):
        # publish holds only its sender mutexes here. Inside deliver_report's
        # HTTP callback Store.lock is also held: that is discovery_lock_busy.
        before = copy.deepcopy(hourly.state())
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(read_fd)
            reply = {}
            try:
                events, posts = len(hourly.events), []
                def child_post(*args, **kwargs):
                    posts.append(True)
                    return {'status': 'unexpected_post'}
                # A duplicate must stop at the real sender mutex before any
                # credential, HTTP or health path; all models remain fake.
                monkeypatch.setattr(health, '_after_tick', forbidden)
                monkeypatch.setattr(imp, '_inbox_config', forbidden)
                monkeypatch.setattr(imp, 'http_transport', forbidden)
                reply = dict(result=hourly.tick(9, deliver=duplicate_deliver, publisher=child_post),
                             posts=posts, model_calls=len(hourly.events) - events,
                             state_unchanged=hourly.state() == before)
            except BaseException as exc:
                reply = {'child_error': type(exc).__name__}
            finally:
                try:
                    with os.fdopen(write_fd, 'w') as output:
                        json.dump(reply, output)
                finally:
                    os._exit(0)
        os.close(write_fd)
        status = None
        try:
            deadline = time.monotonic() + 10
            chunks, size = [], 0
            with os.fdopen(read_fd, 'rb', buffering=0) as incoming:
                while True:
                    remaining = deadline - time.monotonic()
                    assert remaining > 0 and select.select([incoming], [], [], remaining)[0], \
                        'duplicate tick pipe timed out'
                    chunk = os.read(incoming.fileno(), 65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    assert size <= 65536, 'duplicate tick reply exceeded bound'
            while status is None:
                finished, child_status = os.waitpid(pid, os.WNOHANG)
                if finished:
                    status = child_status
                    break
                assert time.monotonic() < deadline, 'duplicate tick exit timed out'
                time.sleep(0.01)
            duplicates.append(json.loads(b''.join(chunks)))
        finally:
            if status is None:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
        assert status == 0
        duplicate = duplicates[-1]
        assert 'child_error' not in duplicate
        assert duplicate['posts'] == [] and duplicate['model_calls'] == 0
        assert duplicate['state_unchanged']
        result = duplicate['result']
        assert result['status'] == 'paused' and result['reason'] == 'sender_lock_busy'
        assert result['publication'] == {'status': 'paused', 'reason': 'sender_lock_busy'}
        assert result['diagnostic']['boundary'] == 'sender_lock'
        assert result['diagnostic']['reason'] == 'sender_lock_busy'
        assert 'health_publication' not in result
        return imp.deliver_report(date, selected=selected)

    monkeypatch.setattr(imp, 'http_transport', http)
    result = hourly.tick(9, deliver=True, publisher=morning_publisher)
    assert len(duplicates) == 1
    assert morning_calls == [('POST', '/api/reports'), ('GET', '/api/reports/' + DATE)]
    assert result['publication']['status'] == 'delivered'
    assert hourly.store.read(loop._publication_name(DATE))['status'] == 'delivered'
    assert result['publication']['digest'] == remote[0]['digest']
    assert result['health_publication']['status'] == 'delivered' and wire.calls == ['POST', 'GET']
    assert hourly.calls() == len(hourly.events) == 10 and hourly.state()['inflight'] is None


@pytest.mark.parametrize('role_failure', [False, True])
@pytest.mark.parametrize('sender', ['_stable_sender_lock', '_sender_lock'])
def test_morning_sender_busy_keeps_settled_role_history_and_accounting(
        hourly, monkeypatch, role_failure, sender):
    hourly.hours(count=3)
    history = copy.deepcopy(hourly.state()['participation'])
    if role_failure:
        hourly.cloud_transform = lambda role, result, response, options: dict(result, response='{')
    monkeypatch.setattr(imp, '_inbox_config', forbidden)
    monkeypatch.setattr(imp, 'http_transport', forbidden)
    with getattr(loop, sender)(hourly.store):
        result = hourly.tick(9, deliver=True, publisher=forbidden)
    assert result['publication'] == {'status': 'paused', 'reason': 'sender_lock_busy'}
    assert result['health_publication'] == {'status': 'health_unavailable'}
    assert result['status'] == 'paused'
    assert result['reason'] == ('role_json_invalid' if role_failure else 'sender_lock_busy')
    if role_failure:
        assert result['diagnostic']['detail']['reason'] == 'role_json_invalid'
        assert hourly.store.read('loop/last-diagnostic.json') == result['diagnostic']
    else:
        assert result['diagnostic']['boundary'] == 'sender_lock'
        assert result['diagnostic']['reason'] == 'sender_lock_busy'
    state = hourly.state()
    assert state['participation'][:len(history)] == history
    assert state['participation'][-1]['status'] == ('failed' if role_failure else 'succeeded')
    assert state['pause_reason'] == ('role_json_invalid' if role_failure else None)
    assert hourly.slots()[DATE + 'T09']['status'] == ('failed' if role_failure else 'succeeded')
    assert state['stage_index'] == 4 and state['inflight'] is None
    assert hourly.calls() == len(hourly.events) == 4 and hourly.spent() == 0
    assert not hourly.store.exists(health.OUTBOX)
