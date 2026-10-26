"""Separate owner-private health projection and trusted-parent delivery.

Projection/validation are pure; query uses no keys/HTTP. Manual publish and the
qualified post-tick path share the private Store/sender and credentials/HTTP.
There is no model, retry loop, approval, execute or Git path.
"""
import argparse
import datetime as dt
import json
import re

from harness import improvement_report as contract, improvement_diagnostics as diagnostics

VERSION = 'improvement-health-v1'
MAX_BYTES = 65536
MAX_FAILURES = 16
HISTORY_LIMIT = 192
OUTBOX = 'health/outbox.json'
STAGES = tuple((stage, role) for role in contract.SPECIALIST_ROLES
               for stage in ('local_explorer', 'specialist')) + (('independent_reviewer', 'reviewer'),)
HOLDS = frozenset(('unknown', 'not_started', 'midnight_guard', 'daily_call_limit',
    'daily_budget_limit', 'daily_budget_overrun', 'provider_unavailable',
    'reviewer_provider_invalid', 'reviewer_budget_invalid', 'unexpected_metered_specialist',
    'quota_unavailable', 'quota_invalid', 'quota_paused', 'glm_quota_unavailable',
    'glm_quota_limit', 'quota_ready', 'quota_headroom', 'quota_malformed',
    'quota_model_limit_missing', 'quota_unknown_model_limit', 'quota_key_unavailable',
    'quota_http_failed', 'quota_query_failed', 'clock_rollback',
    'clock_rollback_during_call', 'clock_crossed_accounting_day',
    'review_invalid', 'source_review_unverified')) | diagnostics.REASONS | frozenset(
        code for code in diagnostics.DETAIL_REASONS if code.startswith(('role_', 'candidate_')))
STATUSES = ('reserved', 'succeeded', 'failed', 'unavailable')
ATTEMPT_KEYS = {'role', 'stage_index', 'stage', 'status', 'slot', 'call_started_at',
                'call_finished_at', 'reason', 'cause', 'phase', 'field', 'rule'}


def _invalid():
    raise contract.ValidationError('Invalid improvement health contract.')


def _time(value):
    if (type(value) is not str or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', value)):
        _invalid()
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            _invalid()
        return parsed
    except (ValueError, OverflowError):
        _invalid()


def _safe_time(value):
    try:
        return _time(value).astimezone(contract.KST).isoformat() if value is not None else None
    except (contract.ValidationError, ValueError, OverflowError):
        return None


def _slot(value):
    if type(value) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}', value):
        return None
    try:
        dt.datetime.strptime(value, '%Y-%m-%dT%H')
    except ValueError:
        return None
    return value


def _enum(value, allowed):
    return type(value) is str and value in allowed


def _attempt(entry):
    if type(entry) is not dict or not _enum(entry.get('role'), contract.ROLES):
        return None
    role = entry['role']
    index = 8 if role == 'reviewer' else 2 * contract.SPECIALIST_ROLES.index(role) + 1
    if (type(entry.get('stage_index')) is not int or entry['stage_index'] != index or
            not _enum(entry.get('status'), STATUSES)):
        return None  # Local stages cannot enter the public cloud history.
    detail = diagnostics.sanitize_detail(entry.get('failure_detail'))
    failed = entry['status'] in ('failed', 'unavailable')
    reason = detail['reason'] if failed else None
    if failed and reason == 'unknown' and _enum(entry.get('reason'), diagnostics.DETAIL_REASONS):
        reason = entry['reason']
    start, end = (_safe_time(entry.get(key)) for key in ('call_started_at', 'call_finished_at'))
    if start is not None and end is not None and _time(end) < _time(start):
        end = None  # A clock rollback cannot establish a completed call interval.
    return dict(role=role, stage_index=index, stage=STAGES[index][0], status=entry['status'],
        slot=_slot(entry.get('slot')), call_started_at=start,
        call_finished_at=end, reason=reason,
        cause=detail['cause'] if failed else None, phase=detail['phase'] if failed else None,
        field=detail['field'] if failed else None, rule=detail['rule'] if failed else None)


def project(state, generated_at):
    """Project trusted private state; no raw strings or guessed old observations.

    Serialized detail is filtered, not authenticated by these pure functions.
    publish obtains validated state itself, never accepts a caller health body.
    Later role success means only that separate attempt succeeded.
    """
    generated_at = _time(generated_at).astimezone(contract.KST).isoformat()
    if type(state) is not dict:
        _invalid()
    history = state.get('participation', [])
    if type(history) is not list or len(history) > HISTORY_LIMIT:
        _invalid()
    # Use private admission timestamps solely to order attempts. Never substitute
    # them for absent actual call times in a legacy entry.
    ordered = []
    for entry in history:
        item = _attempt(entry)
        admitted = _safe_time(entry.get('started_at')) if type(entry) is dict else None
        if item is not None and admitted is not None:
            ordered.append((_time(admitted), item))
    ordered.sort(key=lambda row: row[0])
    roles = [dict(role=role, latest=next((item for _, item in reversed(ordered)
                                        if item['role'] == role), None)) for role in contract.ROLES]
    failures = []
    for admitted, item in ordered:
        if item['status'] not in ('failed', 'unavailable'):
            continue
        # Without the failed call's end, the historical temporal relation is
        # unavailable. Admission/recovery time is not actual CLI completion.
        end = item['call_finished_at']
        later = next((success['call_finished_at'] for at, success in ordered
            if end is not None and at > admitted and success['role'] == item['role'] and
            success['status'] == 'succeeded' and success['call_started_at'] is not None and
            success['call_finished_at'] is not None and
            _time(success['call_started_at']) > _time(end)), None)
        failures.append(dict(attempt=item, subsequent_success_at=later))
    index = state.get('stage_index')
    next_stage = None
    if type(index) is int and 0 <= index <= 9:
        index = index if index < 9 else 0
        stage, role = STAGES[index]
        next_stage = dict(stage_index=index, stage=stage, role=role)
    hold = state.get('pause_reason')
    hold = hold if hold is None or _enum(hold, HOLDS) else 'unknown'
    body = dict(version=VERSION, generated_at=generated_at, roles=roles,
                recent_failures=failures[-MAX_FAILURES:], next_stage=next_stage, hold_code=hold)
    body['digest'] = contract.digest(body)
    return validate(body)


def _validate_attempt(item):
    if type(item) is not dict or set(item) != ATTEMPT_KEYS:
        _invalid()
    if (not _enum(item['role'], contract.ROLES) or not _enum(item['status'], STATUSES) or
            type(item['stage_index']) is not int):
        _invalid()
    index = 8 if item['role'] == 'reviewer' else 2 * contract.SPECIALIST_ROLES.index(item['role']) + 1
    if item['stage_index'] != index or item['stage'] != STAGES[index][0]:
        _invalid()
    if item['slot'] is not None and _slot(item['slot']) != item['slot']:
        _invalid()
    for key in ('call_started_at', 'call_finished_at'):
        if item[key] is not None:
            _time(item[key])
    if (item['call_started_at'] is not None and item['call_finished_at'] is not None and
            _time(item['call_finished_at']) < _time(item['call_started_at'])):
        _invalid()
    if item['status'] in ('failed', 'unavailable'):
        if (not _enum(item['reason'], diagnostics.DETAIL_REASONS) or
                not _enum(item['cause'], diagnostics.CAUSES) or
                item['phase'] is not None and not _enum(item['phase'], diagnostics.PHASES)):
            _invalid()
        if item['cause'] == 'validation':
            if not _enum(item['field'], diagnostics.FIELDS) or not _enum(item['rule'], diagnostics.RULES):
                _invalid()
        elif item['field'] is not None or item['rule'] is not None:
            _invalid()
    elif any(item[key] is not None for key in ('reason', 'cause', 'phase', 'field', 'rule')):
        _invalid()


def validate(payload):
    if (type(payload) is not dict or set(payload) != {'version', 'generated_at', 'roles',
            'recent_failures', 'next_stage', 'hold_code', 'digest'} or payload['version'] != VERSION):
        _invalid()
    _time(payload['generated_at'])
    if type(payload['roles']) is not list or len(payload['roles']) != len(contract.ROLES):
        _invalid()
    for row, role in zip(payload['roles'], contract.ROLES):
        if type(row) is not dict or set(row) != {'role', 'latest'} or row['role'] != role:
            _invalid()
        if row['latest'] is not None:
            _validate_attempt(row['latest'])
            if row['latest']['role'] != role:
                _invalid()
    failures = payload['recent_failures']
    if type(failures) is not list or len(failures) > MAX_FAILURES:
        _invalid()
    for row in failures:
        if type(row) is not dict or set(row) != {'attempt', 'subsequent_success_at'}:
            _invalid()
        _validate_attempt(row['attempt'])
        if row['attempt']['status'] not in ('failed', 'unavailable'):
            _invalid()
        later = row['subsequent_success_at']
        if later is not None:
            end = row['attempt']['call_finished_at']
            if end is None or _time(later) <= _time(end):
                _invalid()
    stage = payload['next_stage']
    if stage is not None:
        if (type(stage) is not dict or set(stage) != {'stage_index', 'stage', 'role'} or
                type(stage['stage_index']) is not int or not 0 <= stage['stage_index'] < 9 or
                (stage['stage'], stage['role']) != STAGES[stage['stage_index']]):
            _invalid()
    if payload['hold_code'] is not None and not _enum(payload['hold_code'], HOLDS):
        _invalid()
    digest = payload['digest']
    if (type(digest) is not str or not re.fullmatch('[0-9a-f]{64}', digest) or
            contract.digest({k: v for k, v in payload.items() if k != 'digest'}) != digest or
            len(contract.canonical_json(payload)) > MAX_BYTES):
        _invalid()
    return payload


def query(*, now=None, selected=None):
    """Keys/HTTP-free parent query; never writes a publication or morning report."""
    from harness import improvements as imp, improvement_loop as loop
    imp._parent()
    store = imp.Store(selected)
    with store.lock():
        return project(loop._read_state(store), imp._now(now).isoformat())


def _journal(store):
    if not store.exists(OUTBOX):
        return None
    value = store.read(OUTBOX)
    if (type(value) is not dict or set(value) != {'payload', 'status'} or
            value['status'] not in ('pending', 'sending', 'unknown', 'delivered', 'conflict')):
        _invalid()
    validate(value['payload'])
    return value


def publish(*, now=None, selected=None, inbox_config=None, transport=None,
            reconcile=False, digest=None):
    """Trusted parent only. Ambiguous sends require GET; never automatic POST.

    reconcile requires the exact frozen digest and a GET 404 before reposting.
    Network runs after state/source locks are released, under the existing
    sender mutex. Delivery is independent of tick, budgets and frozen web-v1.
    """
    from harness import improvements as imp
    imp._parent(trusted=True)
    if type(reconcile) is not bool or (reconcile and digest is None):
        _invalid()
    store = imp.Store(selected)
    return _publish(store, now=now, inbox_config=inbox_config, transport=transport,
                    reconcile=reconcile, digest=digest)


def _after_tick(store, clock, slot):
    """Internal settlement path, called only after a durable tick and lock exit.

    Unattended permits sanitized transport here, never human authorization.
    A separate trace keeps even Store/sender failures out of the tick's first
    failure. The existing Store/policy is reused; no resolution or fallback.
    """
    from harness import improvements as imp, improvement_loop as loop
    with diagnostics.Trace():
        try:
            imp._parent()  # Child/discovery denial still precedes any storage.
            return _publish(store, now=loop._clock(clock()), tick_slot=slot)
        except (Exception, KeyboardInterrupt):
            return {'status': 'health_unavailable'}


def _publish(store, *, now=None, inbox_config=None, transport=None,
             reconcile=False, digest=None, tick_slot=None):
    from harness import improvements as imp, improvement_loop as loop
    imp._parent()
    with loop._stable_sender_lock(store), loop._sender_lock(store):
        with store.lock():
            state = None
            if tick_slot is not None:
                state = loop._read_state(store)
                # Validate the saved observation before credentials/HTTP, even
                # when an older ambiguous outbox only needs a GET.
                if (state['high_water_at'] is None or
                        loop._clock(now) < loop._stamp(state['high_water_at']) or
                        state['pause_reason'] in ('clock_rollback', 'clock_rollback_during_call')):
                    return {'status': 'clock_rollback'}
                if state['last_slot'] != tick_slot or state['inflight'] is not None:
                    return {'status': 'health_superseded'}
            journal = _journal(store)
            if digest is not None:
                if journal is None or journal['payload']['digest'] != digest:
                    _invalid()
            elif journal is None or journal['status'] == 'delivered':
                journal = dict(payload=project(state if state is not None else loop._read_state(store),
                                               imp._now(now).isoformat()),
                               status='pending')
                store.write(OUTBOX, journal)
            payload = journal['payload']
            if journal['status'] in ('conflict', 'delivered'):
                return dict(status=journal['status'], digest=payload['digest'])
        def save(status):
            journal['status'] = status
            with store.lock():
                store.write(OUTBOX, journal)
        try:
            config = imp.load_config()['limits']
            timeout = config['delivery_timeout_seconds']
            bound = min(config['max_delivery_bytes'], MAX_BYTES)
            body = contract.canonical_json(payload)
            if len(body) > bound:
                _invalid()
            origin, token = imp._inbox_config(inbox_config or imp.ROOT / 'logs/harness/improvement-inbox.json')
            headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
                       'OAI-Sites-Authorization': 'Bearer ' + token}
            request = transport or imp.http_transport
            def call(method):
                code, response = request(method, origin, '/api/health', headers,
                    body if method == 'POST' else None, timeout, bound)
                if (type(code) is not int or type(response) is not bytes or len(response) > bound):
                    _invalid()
                return code, response
            def readback():
                code, response = call('GET')
                if code == 404:
                    return 'absent'
                if not 200 <= code < 300:
                    return 'unknown'
                remote = validate(contract.parse_json(response, bound))
                return 'delivered' if remote == payload else 'conflict'
            do_post = journal['status'] == 'pending'
            if not do_post:
                observed = readback()
                if observed in ('delivered', 'conflict'):
                    save(observed)
                    return dict(status=observed, digest=payload['digest'])
                do_post = observed == 'absent' and reconcile and digest == payload['digest']
            if do_post:
                save('sending')  # durable before the first byte can leave
                code, _ = call('POST')
                if not 200 <= code < 300:
                    save('unknown')
                    return dict(status='unknown', digest=payload['digest'])
                observed = readback()
                save(observed if observed in ('delivered', 'conflict') else 'unknown')
            else:
                save('unknown')
        except (Exception, KeyboardInterrupt):
            # No exception strings, credential/config/body or host paths escape.
            # A crash after sending leaves a durable ambiguous journal.
            if journal['status'] == 'sending':
                save('unknown')
            return dict(status='delivery_failed', digest=payload['digest'])
        return dict(status=journal['status'], digest=payload['digest'])


def main(argv=None):
    parser = argparse.ArgumentParser(description='Parent-only owner-private improvement health')
    parser.add_argument('command', choices=('query', 'publish'))
    parser.add_argument('--reconcile', action='store_true')
    parser.add_argument('--digest')
    args = parser.parse_args(argv)
    try:
        if args.command == 'query':
            if args.reconcile or args.digest:
                _invalid()
            result = query()
        else:
            result = publish(reconcile=args.reconcile, digest=args.digest)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if args.command == 'query' or result['status'] == 'delivered' else 1
    except (Exception, KeyboardInterrupt):
        print('{"status":"health_unavailable"}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
