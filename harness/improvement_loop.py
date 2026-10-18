"""Restartable, read-only exploration; one model admission per KST hour.

Parent API (all clocks are aware datetime values, all I/O seams are injectable):
  tick(now=None, selected=None, runner=None, keys=None, local_runner=None,
       local_config=None, quota_transport=None, publisher=None, deliver=False,
       clock=None)
  status(now=None, selected=None)
  publish(now=None, selected=None, publisher=None, reconcile=False)
  validate_scan_freshness(scan, selected=None)
  authorization_context(scan) -> digest or None for legacy discovery

The production CLI's tick delivers by default through improvements.deliver_report.
An embedded caller must request deliver=True or supply publisher. Publishers take
(date, selected=storage_policy), return the existing delivery result, and run only
AFTER BOTH locks are released. Never call publish from inside Store.lock. An
unknown send needs explicit publish(reconcile=True), always with the same digest.

Integration with approval: improvements._fresh must call validate_scan_freshness
for scans carrying loop_dependencies. Existing config_fingerprint deliberately
retains its v1 meaning; silently folding new dependencies into it breaks legacy
authorization. The approval writer must additionally sign authorization_context
and the execution validator compare that bound value against the current scan.
Freshness alone cannot bind an old approval after identical candidate/review
text is rediscovered under changed loop controls. Neither this module nor tick
creates human decisions, approvals,
execution claims, workflows, Git objects, timers, daemons or retry loops.

Durability: a single atomic state write claims a slot, increments the day count,
charges the Claude reservation, and advances the local cursor BEFORE a call.
An interrupted claim consumes that count/reservation and advances its stage once
on recovery. Readiness/quota/budget failures consume the slot but no model count.
No failed slot is retried, including after a configuration change. Strict clock
high water prevents rollback and historical-day replay. Calls in the final
midnight_guard_seconds of a KST day are refused, for every provider; the guard
is at least the whole tick deadline. An interrupted call recovered on another
day conservatively counts/charges that day too and stops it. Estimates/admission
do not guarantee billing. GLM's 80% gate leaves nominal 20% development headroom
at admission; it cannot guarantee consumption during an already running call.

Each round has four local/owner pairs and one independent reviewer. A missing,
failed, empty or oversize-line local draft skips its paired owner on the next
slot. Every stage, including a skip, consumes one hourly slot. After the reviewer
stage (even failure) a fresh round starts on the NEXT slot. Cursors and bounded
sanitized feedback survive ordinary rounds; source/scope/config/model changes
invalidate both the pool and feedback and reset cursors. The local adapter sees
only its selected continuous numbered line window, never the full snapshot.

Morning selection: latest completed independent review in [yesterday 09:00,
today 09:00), matching ALL current dependencies, at most eight distinct records.
Web-v1 sorts priority high/medium/low then exact ID and displays at most three.
No suitable review produces a truthful partial/failed zero-card report, with
only actual participation in that window. Private scans retain every candidate,
review and bounded local participation. Publication journals freeze the entire
report before materialization; existing legacy days are preserved and never
automatically redelivered. Catchup considers today's date only, after 09:00.

Documentation impact: AGENTS.md, docs/{architecture,harness-design,harness,
improvements,workflow,agent-models,local-models}.md and ADR0017/index must describe
these new scheduling, privacy, costs, provenance and recovery contracts. ADR0015
keeps its approval boundary; only its daily scheduling/call policy is replaced.
Implementation workflow charges are separate from the exploration dollar ledger.
"""

import argparse
import copy
import datetime as dt
import fcntl
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import secrets
import signal
import threading
import time
from contextlib import contextmanager

from harness import agent_models, improvement_report as contract
from harness import improvements as imp, local_model, storage, workflow


CONFIG = Path(__file__).with_name('improvement-loop-config.json')
CONFIG_VERSION = 'improvement-loop-config-v1'
STATE_VERSION = 'improvement-loop-state-v1'
STATE_FILE = 'loop/state.json'
QUOTA_HOST = 'api.z.ai'
QUOTA_PATH = '/api/monitor/usage/quota/limit'
STAGES = tuple(stage for role in contract.SPECIALIST_ROLES
               for stage in (('local_explorer', role), ('specialist', role))) + (
                   ('independent_reviewer', 'reviewer'),)
_INTEGER_BOUNDS = {
    'slot_minutes': (60, 60), 'report_hour': (9, 9),
    'max_calls_per_day': (1, 24), 'tick_timeout_seconds': (120, 600),
    'model_timeout_seconds': (1, 520), 'midnight_guard_seconds': (120, 3600),
    'max_candidates_per_specialist': (1, 2), 'max_candidates': (1, 8),
    'quota_timeout_seconds': (1, 20), 'quota_max_response_bytes': (1024, 65536),
    'quota_pause_percentage': (1, 80), 'max_completed_rounds': (4, 32),
}


class LoopError(imp.ImprovementError):
    """Fixed diagnostic codes only; external bodies/exceptions never escape."""


def _number(value, minimum=0, maximum=None):
    try:
        return (type(value) in (int, float) and math.isfinite(value) and
                value >= minimum and (maximum is None or value <= maximum))
    except (ValueError, OverflowError):
        return False


def validate_config(value):
    fields = set(_INTEGER_BOUNDS) | {
        'version', 'timezone', 'daily_budget_usd', 'reviewer_max_budget_usd'}
    if not isinstance(value, dict) or set(value) != fields:
        raise LoopError('loop_config_fields')
    if value['version'] != CONFIG_VERSION or value['timezone'] != 'Asia/Seoul':
        raise LoopError('loop_config_version')
    for name, (low, high) in _INTEGER_BOUNDS.items():
        if type(value[name]) is not int or not low <= value[name] <= high:
            raise LoopError('loop_config_bounds')
    for name, high in (('daily_budget_usd', 1), ('reviewer_max_budget_usd', .2)):
        if not _number(value[name], 0, high) or value[name] == 0:
            raise LoopError('loop_config_budget')
    if (value['reviewer_max_budget_usd'] > value['daily_budget_usd'] or
            value['model_timeout_seconds'] + 80 > value['tick_timeout_seconds'] or
            value['midnight_guard_seconds'] < value['tick_timeout_seconds'] or
            value['max_candidates'] > 4 * value['max_candidates_per_specialist']):
        raise LoopError('loop_config_relationship')
    return dict(value)


def load_config(path=None):
    try:
        return validate_config(contract.parse_json(imp._read_file(path or CONFIG, 8192)[0], 8192))
    except LoopError:
        raise
    except (ValueError, OSError, TypeError):
        raise LoopError('loop_config_unavailable') from None


def _clock(now=None):
    return imp._now(now).astimezone(contract.KST)


def _stamp(value):
    if not isinstance(value, str):
        raise LoopError('state_invalid')
    return _clock(dt.datetime.fromisoformat(value.replace('Z', '+00:00')))


def _id():
    return str(time.time_ns()) + '-' + secrets.token_hex(3)


def _dependencies(config, local_config, selected):
    discovery = imp.load_config()
    # The loop never accepts a caller-selected or expanded discovery scope.
    if discovery['scope_file'] != 'harness/improvement-scope.txt':
        raise LoopError('scope_path_changed')
    scope_path = imp.ROOT / discovery['scope_file']
    body, mode = imp._read_file(scope_path, 65536)
    paths = contract.validate_scope_paths(body.decode('utf-8').splitlines(), 37)
    snapshots = imp.snapshot_sources(paths, discovery['limits'], selected)
    scope = {'sha256': hashlib.sha256(body).hexdigest(), 'mode': mode, 'paths': paths}
    dependencies = {
        'scope_fingerprint': scope,
        'source_fingerprints': contract.fingerprint_sources(snapshots),
        'config_fingerprint': contract.digest(discovery),
        'loop_config_fingerprint': contract.digest(config),
        'local_config_fingerprint': local_model.config_digest(local_config),
        'agent_config_fingerprint': contract.digest(agent_models.load_config()),
        'workflow_config_fingerprint': contract.digest(workflow.load_policy()),
    }
    return discovery, paths, snapshots, dependencies


def validate_scan_freshness(scan, *, selected=None):
    """Approval/execute hook: no models, credentials, quota or budget gate.

    Legacy scans without loop_dependencies keep their original freshness path.
    A loop scan must compare scope, source, ALL control digests, including the
    private local configuration. Missing/unreadable config fails closed.
    """
    if 'loop_dependencies' not in scan:
        if scan.get('loop_engine'):
            raise LoopError('loop_dependencies_missing')
        return
    selected = selected or storage.resolve_storage(imp.ROOT)
    selected.check_ready()
    config = load_config()
    local_config = local_model.load_config(root=imp.ROOT)
    _, _, _, current = _dependencies(config, local_config, selected)
    if scan['loop_dependencies'] != current:
        raise LoopError('loop_dependencies_changed')


def authorization_context(scan):
    """Pure binding for the trusted approval signature, not authorization.

    Task integrating approvals must persist this digest in signed approvals and
    compare it on execution/guard, alongside all existing exact ID/review/source
    checks. Comparing ONLY live freshness permits a rediscovery with identical
    text to silently rebind an old approval to changed loop/local settings.
    """
    if 'loop_dependencies' not in scan:
        if scan.get('loop_engine'):
            raise LoopError('loop_dependencies_missing')
        return None
    return contract.digest(scan['loop_dependencies'])


def validate_quota(value, now=None, pause_percentage=80):
    """Validate legacy TOKENS_LIMIT and new CREDIT_LIMIT; TIME_LIMIT is not quota.

    Recognized model windows: rolling five hours (unit=3,number=5), optional
    weekly (unit=6,number=1). Every returned model window must be understood and
    have finite percentage in [0,100] and a future integral epoch-ms reset.
    For BOTH model types, only the five-hour window at exactly zero may have
    an absent/null reset: consumption has not activated its rolling window.
    Keep that reset unknown (None); weekly windows always require a reset.
    Other quota types/units fail closed rather than guessing a credit price.
    """
    failed = {'status': 'paused', 'reason': 'quota_malformed', 'limits': []}
    if (type(pause_percentage) is not int or not 1 <= pause_percentage <= 80 or
            not isinstance(value, dict) or not isinstance(value.get('data'), dict)):
        return failed
    if (('success' in value and value['success'] is not True) or
            ('code' in value and (type(value['code']) is not int or value['code'] != 200))):
        return failed
    limits = value['data'].get('limits')
    if not isinstance(limits, list) or not 1 <= len(limits) <= 16:
        return failed
    epoch = int(_clock(now).timestamp() * 1000)
    models, seen = [], set()
    for item in limits:
        if not isinstance(item, dict):
            return failed
        kind = item.get('type')
        if kind == 'TIME_LIMIT':
            continue
        if kind not in ('TOKENS_LIMIT', 'CREDIT_LIMIT'):
            return dict(failed, reason='quota_unknown_model_limit')
        unit, number = item.get('unit'), item.get('number')
        reset, percentage = item.get('nextResetTime'), item.get('percentage')
        if (type(unit) is not int or type(number) is not int or
                (unit, number) not in ((3, 5), (6, 1)) or
                not _number(percentage, 0, 100)):
            return failed
        idle = (unit, number) == (3, 5) and percentage == 0 and reset is None
        if not idle and (type(reset) is not int or
                         not epoch < reset <= epoch + 8 * 86400000):
            return failed
        identity = (kind, unit, number)
        if identity in seen:
            return failed
        seen.add(identity)
        models.append({'type': kind, 'unit': unit, 'number': number,
                       'percentage': percentage, 'nextResetTime': reset})
    if not any(item['unit'] == 3 for item in models):
        return dict(failed, reason='quota_model_limit_missing')
    paused = any(item['percentage'] >= pause_percentage for item in models)
    return {'status': 'paused' if paused else 'ready',
            'reason': 'quota_headroom' if paused else 'quota_ready', 'limits': models}


def quota_http_transport(key, timeout, max_bytes):
    """Trusted-parent HTTPS GET, fixed host/path, no redirects/proxy/retries.

    This seam returns only bounded status/body to fetch_glm_quota. Callers must
    never retain either raw body or an exception. Key is a runtime header only.
    """
    connection = http.client.HTTPSConnection(QUOTA_HOST, timeout=timeout)
    deadline = time.monotonic() + timeout
    try:
        connection.request('GET', QUOTA_PATH, headers={
            'Authorization': key, 'Accept': 'application/json', 'Connection': 'close'})
        sock = connection.sock
        response = connection.getresponse()
        if sum(len(k) + len(v) + 4 for k, v in response.getheaders()) > 8192:
            raise LoopError('quota_response_invalid')
        if response.status != 200:
            return response.status, b''
        length = response.getheader('Content-Length')
        if length is not None and (not length.isdigit() or int(length) > max_bytes):
            raise LoopError('quota_response_invalid')
        body = bytearray()
        while len(body) <= max_bytes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LoopError('quota_timeout')
            sock.settimeout(remaining)
            chunk = response.read1(min(4096, max_bytes + 1 - len(body)))
            if not chunk:
                return response.status, bytes(body)
            body.extend(chunk)
        raise LoopError('quota_response_invalid')
    finally:
        connection.close()


def fetch_glm_quota(keys, now=None, *, transport=None, timeout=15, max_bytes=65536,
                    pause_percentage=80):
    """Only sanitized admission state escapes. Never send quota data to a model."""
    imp._parent()
    if (type(timeout) is not int or not 1 <= timeout <= 20 or
            type(max_bytes) is not int or not 1024 <= max_bytes <= 65536):
        raise LoopError('quota_config_invalid')
    key = keys.get('ZAI_API_KEY') if isinstance(keys, dict) else None
    if not isinstance(key, str) or not key or len(key) > 8192 or '\r' in key or '\n' in key:
        return {'status': 'paused', 'reason': 'quota_key_unavailable', 'limits': []}
    try:
        # Also bound header processing and trickle responses by wall time,
        # rather than relying solely on a per-socket idle timeout.
        with _deadline(timeout):
            code, body = (transport or quota_http_transport)(key, timeout, max_bytes)
        if type(code) is not int or code != 200:
            return {'status': 'paused', 'reason': 'quota_http_failed', 'limits': []}
        if not isinstance(body, bytes) or len(body) > max_bytes:
            raise LoopError('quota_response_invalid')
        return validate_quota(contract.parse_json(body, max_bytes), now, pause_percentage)
    except (Exception, KeyboardInterrupt):
        return {'status': 'paused', 'reason': 'quota_query_failed', 'limits': []}


def _empty_agents():
    return [{'role': role, 'provider': None, 'model': None, 'status': 'not_called',
             'cost': None, 'cost_status': 'unknown'} for role in contract.ROLES]


def _new_state():
    return {'version': STATE_VERSION, 'high_water_at': None, 'last_slot': None,
            'days': {}, 'inflight': None, 'round': None, 'stage_index': 0,
            'cursors': {}, 'feedback': {}, 'completed': [], 'last_review_at': None,
            'pause_reason': 'not_started', 'dependency_digest': None}


def _read_state(store):
    if not store.exists(STATE_FILE):
        return _new_state()
    state = store.read(STATE_FILE)
    expected = set(_new_state())
    if not isinstance(state, dict) or set(state) != expected or state['version'] != STATE_VERSION:
        raise LoopError('state_invalid')
    if (type(state['stage_index']) is not int or not 0 <= state['stage_index'] <= 9 or
            not isinstance(state['days'], dict) or len(state['days']) > 7 or
            not isinstance(state['completed'], list) or len(state['completed']) > 32 or
            not isinstance(state['feedback'], dict) or not isinstance(state['cursors'], dict)):
        raise LoopError('state_invalid')
    if state['high_water_at'] is not None:
        _stamp(state['high_water_at'])
    for date, day in state['days'].items():
        imp._date(date)
        if (not isinstance(day, dict) or type(day.get('calls')) is not int or day['calls'] < 0 or
                not _number(day.get('claude_spent_usd')) or
                not isinstance(day.get('slots'), dict) or len(day['slots']) > 24 or
                not isinstance(day.get('legacy_seen'), list) or len(day['legacy_seen']) > 4096 or
                type(day.get('stopped')) is not bool):
            raise LoopError('state_invalid')
    return state


def _write_state(store, state):
    # Store.write pins private directories, fsyncs file and directory and checks
    # policy readiness. Never swallow a failed reservation write and then call.
    store.write(STATE_FILE, state)


def _legacy_reports(store, date):
    """Bounded exact private scans, deduplicated by scan ID (days is a pointer).

    A full successful legacy reviewer estimate, e.g. the observed 0.0434664 USD,
    is imported once from its genuine record, never fabricated from a constant.
    Unknown prior participation conservatively spends the entire day allowance.
    Loop snapshots/projections carry a marker and are excluded from carry-in.
    """
    reports = {}
    day_path = 'days/' + date + '.json'
    if store.exists(day_path):
        report = store.read(day_path)
        if report.get('date') != date:
            raise LoopError('legacy_history_invalid')
        if not report.get('loop_engine'):
            reports[report.get('scan_id', 'legacy-day-' + date)] = report
    try:
        directory = store.policy.fs.open_directory(store.path('scans'))
    except FileNotFoundError:
        return reports
    try:
        names = []
        with os.scandir(directory) as entries:
            for entry in entries:
                if len(names) == 4096:
                    raise LoopError('legacy_history_unbounded')
                names.append(entry.name)
    finally:
        os.close(directory)
    for name in sorted(names):
        if not name.endswith('.json') or not storage.RUN_ID.fullmatch(name[:-5]):
            continue
        report = store.read('scans/' + name)
        if report.get('date') == date and not report.get('loop_engine'):
            scan_id = report.get('scan_id')
            if scan_id != name[:-5]:
                raise LoopError('legacy_history_invalid')
            # Prefer the scan if a crash left its day projection behind.
            reports[scan_id] = report
    return reports


def _day_ledger(store, state, date, config):
    day = state['days'].setdefault(date, {'calls': 0, 'claude_spent_usd': 0,
                                        'slots': {}, 'legacy_seen': [], 'stopped': False,
                                        'legacy_cost_status': 'no_prior_activity'})
    reports = _legacy_reports(store, date)
    for scan_id, report in sorted(reports.items()):
        if scan_id in day['legacy_seen']:
            continue
        agents = report.get('agents')
        if not isinstance(agents, list):
            raise LoopError('legacy_history_invalid')
        unknown = False
        cost = 0
        for agent in agents:
            if not isinstance(agent, dict):
                raise LoopError('legacy_history_invalid')
            if agent.get('status') == 'not_called':
                continue
            day['calls'] += 1
            if agent.get('provider') == 'claude' or agent.get('role') == 'reviewer':
                estimate = agent.get('cost')
                if (agent.get('status') == 'succeeded' and
                        agent.get('cost_status') == 'cli_estimated_usd' and _number(estimate)):
                    cost += estimate
                else:
                    unknown = True
        if not report.get('review_complete'):
            # Legacy daily did not reserve before its call. Its last persisted
            # not_called entry could hide an interrupted CLI. Never infer zero
            # historical cost/calls from that incomplete snapshot.
            unknown = True
            day['calls'] = max(day['calls'], config['max_calls_per_day'])
        day['claude_spent_usd'] += cost
        if unknown:
            day['claude_spent_usd'] = max(day['claude_spent_usd'], config['daily_budget_usd'])
            day['legacy_cost_status'] = 'unknown_consumed'
        elif day['legacy_cost_status'] != 'unknown_consumed':
            day['legacy_cost_status'] = 'cli_estimated_carry_in'
        day['legacy_seen'].append(scan_id)
    if len(day['legacy_seen']) > 4096 or not _number(day['claude_spent_usd']):
        raise LoopError('legacy_history_unbounded')
    # Past days cannot be reopened: durable high-water is checked first.
    _archive_days(store, state)
    return day


def _archive_days(store, state):
    for old in sorted(state['days'])[:-7]:
        name = 'loop/ledgers/' + old + '.json'
        if store.exists(name) and store.read(name) != state['days'][old]:
            raise LoopError('ledger_archive_conflict')
        store.write(name, state['days'][old])
        del state['days'][old]


def _new_round(state, now, discovery, paths, dependencies):
    report = {'version': 'improvement-private-v1', 'loop_engine': STATE_VERSION,
              'date': now.date().isoformat(), 'generated_at': now.isoformat(),
              'started_at': now.isoformat(), 'scan_id': _id(), 'status': 'failed',
              'proposals': [], 'agents': _empty_agents(), 'local_participation': [],
              'documentation': dict(imp.NO_DOCUMENT_EDITS), 'approved_files': paths,
              'review_complete': False, 'errors': [],
              'source_fingerprints': dependencies['source_fingerprints'],
              'scope_fingerprint': dependencies['scope_fingerprint'],
              'scope_input': str((imp.ROOT / discovery['scope_file']).absolute()),
              'scope_override': False, 'config_fingerprint': dependencies['config_fingerprint'],
              'loop_dependencies': dependencies}
    state['round'] = {'report': report, 'drafts': {}, 'feedback': copy.deepcopy(state['feedback'])}
    state['stage_index'] = 0


def _role_agent(report, role, participation):
    report['agents'][contract.ROLES.index(role)] = participation


def _feedback_entry(candidate=None, *, reason='', candidate_id=None, draft_digest=None):
    item = {'title': '로컬 탐색 보류', 'issue': '이전 탐색의 고정 진단을 확인하고 근거를 보완해야 합니다.',
            'edit_files': [], 'specialist_reason': contract.safe_text(reason, 1440) if reason else '',
            'review_reason': ''}
    if candidate is not None:
        item.update(title=contract.redact_text(candidate['title']),
                    issue=contract.redact_text(candidate['issue']), edit_files=list(candidate['edit_files']))
    if candidate_id is not None:
        item['candidate_id'] = candidate_id
    if draft_digest is not None:
        item['draft_digest'] = draft_digest
    return item


def _bounded_feedback(entries, paths, local_config):
    # Keep the most recent complete summaries. Never truncate candidate prose
    # and thereby silently change the meaning of an accepted earlier draft.
    result = []
    for entry in entries[:8]:
        try:
            proposed = local_model.sanitize_feedback(result + [entry], paths,
                max_bytes=local_config['limits']['max_feedback_bytes'])
        except local_model.LocalModelError:
            # Private candidate/review originals remain in the immutable scan.
            # Feedback is explicitly a sanitized summary, so use visible
            # abbreviation rather than losing a long draft's review entirely.
            compact = copy.deepcopy(entry)
            for field, limit in (('title', 80), ('issue', 400),
                                 ('specialist_reason', 240), ('review_reason', 240)):
                if compact.get(field):
                    compact[field] = contract.safe_text(compact[field], limit)
            try:
                proposed = local_model.sanitize_feedback(result + [compact], paths,
                    max_bytes=local_config['limits']['max_feedback_bytes'])
            except local_model.LocalModelError:
                continue
        result = proposed
    if entries and not result:
        # Do not silently convert a required continuation into a fresh prompt
        # with none of the previous draft's actual errors/review reasons.
        raise LoopError('feedback_cannot_fit')
    return result


def _record_feedback(state, role, entries):
    state['round']['feedback'][role] = entries[:4]
    state['feedback'][role] = copy.deepcopy(entries[:4])


def _safe_participation(participation):
    # Retain bounded real participation, never raw CLI response or diagnostics.
    # The existing helper validates identity, evidence and read-only contexts.
    result = {key: participation[key] for key in (
        'role', 'provider', 'model', 'status', 'started_at', 'finished_at',
        'elapsed_seconds', 'read_files', 'interrupted') if key in participation}
    if participation.get('provider') == 'zai':
        telemetry = imp.agent_telemetry.sanitize(participation.get('telemetry'))
        if telemetry is not None:
            result['telemetry'] = telemetry
    cost = participation.get('cost')
    known = participation.get('cost_status') == 'cli_estimated_usd' and _number(cost)
    result.update(cost=cost if known else None,
                  cost_status='cli_estimated_usd' if known else 'unknown')
    if result.get('status') != 'succeeded':
        result['reason'] = 'role_interrupted' if result.get('interrupted') else 'role_failed'
    return result


def _save_proposals(store, report, preserve_review=False):
    for record in report['proposals']:
        name = 'proposals/' + record['id'] + '.json'
        if store.exists(name):
            saved = store.read(name)
            prior = saved['proposal']
            if any(prior[key] != record[key] for key in
                   ('id', 'digest', 'candidate', 'source_fingerprints')):
                raise LoopError('proposal_identity_collision')
            if saved.get('review_complete') and (preserve_review or not report['review_complete']):
                # Incomplete rediscovery must not make an already reported,
                # fresh reviewed ID unusable. Morning materialization must not
                # roll newer review provenance back to an older snapshot.
                continue
        # Decisions/approvals/execution claims are separate and never touched.
        store.write(name, {'proposal': record, 'scan_id': report['scan_id'],
                          'date': report['date'], 'review_complete': report['review_complete'],
                          'status': report['status'],
                          'discovery_fingerprint': authorization_context(report)})


def _persist_round(store, state, config, now):
    report = state['round']['report']
    all_ok = all(a['status'] == 'succeeded' for a in report['agents'])
    any_ok = any(a['status'] == 'succeeded' for a in report['agents'])
    report['status'] = ('scanned' if all_ok and report['review_complete'] else
                        'partial' if any_ok else 'failed')
    if not report['review_complete']:
        for record in report['proposals']:
            record.pop('review', None)
    report['last_activity_at'] = now.isoformat()
    store.write('scans/' + report['scan_id'] + '.json', report)
    if state['stage_index'] == len(STAGES):
        _save_proposals(store, report)
        if report['review_complete']:
            report.setdefault('review_completed_at', now.isoformat())
            store.write('scans/' + report['scan_id'] + '.json', report)
            state['last_review_at'] = report['review_completed_at']
            if not any(item['scan_id'] == report['scan_id'] for item in state['completed']):
                state['completed'].append({'scan_id': report['scan_id'],
                    'at': report['review_completed_at'], 'dependency_digest': state['dependency_digest']})
            state['completed'] = state['completed'][-config['max_completed_rounds']:]


def _account_cross_day(state, pending, now):
    if now.date().isoformat() == pending['date']:
        return
    original = state['days'][pending['date']]
    slot = original['slots'][pending['slot']]
    new_date = now.date().isoformat()
    crossed = state['days'].setdefault(new_date, {'calls': 0, 'claude_spent_usd': 0,
        'slots': {}, 'legacy_seen': [], 'stopped': False,
        'legacy_cost_status': 'cross_day_reservation'})
    token = pending['round_id'] + '/' + pending['slot']
    seen = crossed.setdefault('cross_day_attempts', [])
    if token not in seen:
        crossed['calls'] += 1
        reservation = pending['reservation_usd']
        if reservation is not None:
            estimate = slot.get('actual_estimated_usd')
            crossed['claude_spent_usd'] += max(reservation,
                estimate if _number(estimate) else reservation)
        seen.append(token)
    crossed.update(stopped=True, stop_reason='clock_crossed_accounting_day')
    original.update(stopped=True, stop_reason='clock_crossed_accounting_day')
    report = state['round']['report']
    report['review_complete'] = False
    if 'clock_crossed_accounting_day' not in report['errors']:
        report['errors'].append('clock_crossed_accounting_day')


def _recover(store, state, config, now):
    pending = state['inflight']
    if pending is None:
        return
    if not isinstance(pending, dict) or state['round'] is None:
        raise LoopError('state_invalid')
    stage, role = STAGES[state['stage_index']]
    if pending.get('round_id') != state['round']['report']['scan_id']:
        raise LoopError('state_invalid')
    report = state['round']['report']
    slot = state['days'][pending['date']]['slots'][pending['slot']]
    _account_cross_day(state, pending, now)
    if stage == 'local_explorer':
        # Recovery describes the journaled attempt, including a pre-v2 call;
        # it must not relabel that attempt as the newly configured provider.
        local = {'provider': pending['provider'], 'model': pending['model'], 'stage': stage,
                 'owner_role': role, 'status': 'failed', 'reason': 'interrupted_unknown',
                 'called': True, 'started_at': pending['at'], 'finished_at': now.isoformat(),
                 'read_windows': pending['read_windows'], 'skipped_lines': [],
                 'cost': None, 'cost_status': 'not_metered'}
        report['local_participation'].append(local)
        state['round']['drafts'][role] = {'candidates': [], 'reason': 'interrupted_unknown'}
        previous = state['feedback'].get(role, [])
        _record_feedback(state, role, [_feedback_entry(reason='local_interrupted_unknown')] + previous[:2])
    else:
        known_cost = slot.get('actual_estimated_usd')
        _role_agent(report, role, {'role': role, 'provider': pending['provider'],
            'model': pending['model'], 'status': 'failed', 'reason': 'interrupted_unknown',
            'cost': known_cost if _number(known_cost) else None,
            'cost_status': 'cli_estimated_usd' if _number(known_cost) else 'unknown',
            'started_at': pending['at'],
            'finished_at': now.isoformat()})
        if stage == 'specialist':
            drafts = state['round']['drafts'].get(role, {}).get('candidates', [])
            _record_feedback(state, role, [_feedback_entry(c, reason='specialist_interrupted_unknown',
                draft_digest=contract.digest(drafts)) for c in drafts][:2])
        else:
            report['review_complete'] = False
            _review_feedback(state, 'reviewer_interrupted_unknown')
    slot['status'] = 'interrupted_unknown'
    state['stage_index'] += 1
    state['inflight'] = None
    # Its reservation is already charged. No automatic refund or retry.
    _archive_days(store, state)
    _write_state(store, state)
    _persist_round(store, state, config, now)
    _write_state(store, state)


def _review_feedback(state, failure=None):
    verdicts = {record['id']: record.get('review') for record in state['round']['report']['proposals']}
    for role, entries in state['round']['feedback'].items():
        updated = copy.deepcopy(entries)
        for item in updated:
            review = verdicts.get(item.get('candidate_id'))
            if review is not None:
                item['review_reason'] = contract.redact_text(review['reason'])
            elif failure:
                item['review_reason'] = failure
        state['feedback'][role] = updated
        state['round']['feedback'][role] = updated


@contextmanager
def _deadline(seconds):
    """No background threads or polling; preserve an already shorter alarm."""
    if threading.current_thread() is not threading.main_thread():
        raise LoopError('runtime_guard_unavailable')
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()

    def expired(signum, frame):
        raise LoopError('tick_timeout')

    signal.signal(signal.SIGALRM, expired)
    limit = min(seconds, previous_timer[0]) if previous_timer[0] else seconds
    signal.setitimer(signal.ITIMER_REAL, limit)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0]:
            signal.setitimer(signal.ITIMER_REAL,
                            max(.001, previous_timer[0] - (time.monotonic() - started)),
                            previous_timer[1])


def _cloud_call(role, own_paths, snapshots, discovery, records, draft, feedback,
                keys, runner, selected, config, budget):
    source_bytes = sum(len(snapshots[path]['content'] or b'') for path in own_paths)

    def bounded_runner(actual_role, prompt, runtime_keys, **options):
        # Owner retains full existing ownership/shared context; only local HTTP
        # receives the small line window. Drafts are untrusted advice, not proof.
        extra = ''
        if actual_role != 'reviewer':
            extra = ('\nReview and refine these LOCAL DRAFTS against your approved sources. '
                     'Reject unsupported claims; return the existing candidates schema. '
                     'No draft is an eligible proposal or proof of specialist participation. '
                     'Prior feedback refers to the same draft batch when draft_digest matches.\n' +
                     contract.canonical_json({'local_drafts': draft, 'feedback': feedback}).decode('utf-8'))
        prompt = agent_models.redact(prompt + extra, runtime_keys)
        if source_bytes + len(prompt.encode('utf-8')) > discovery['limits']['max_context_bytes']:
            raise LoopError('cloud_context_too_large')
        options['timeout'] = min(options['timeout'], config['model_timeout_seconds'])
        if actual_role == 'reviewer':
            options['max_budget_usd'] = budget
        return runner(actual_role, prompt, runtime_keys, **options)

    bounded_config = copy.deepcopy(discovery)
    bounded_config['limits']['max_candidates_per_specialist'] = config['max_candidates_per_specialist']
    bounded_config['limits']['call_timeout_seconds'] = config['model_timeout_seconds']
    participation, parsed = imp._call_role(role, own_paths, snapshots, bounded_config,
                                          records, keys, bounded_runner, selected)
    return _safe_participation(participation), parsed


def _local_call(role, own_paths, snapshots, local_config, cursor, feedback,
                prepared, runner, config, now):
    try:
        result = runner(role, own_paths, snapshots, config=local_config, cursor=cursor,
                        feedback=feedback, candidate_limit=config['max_candidates_per_specialist'])
        if (not isinstance(result, dict) or result.get('provider') != 'mlx-vlm' or
                result.get('model') != local_config['model'] or
                result.get('stage') != 'local_explorer' or result.get('owner_role') != role):
            raise LoopError('local_identity_invalid')
        candidates = []
        windows = [{key: item[key] for key in ('path', 'start_line', 'end_line')}
                   for item in prepared['sources']]
        reason = result.get('reason')
        if not isinstance(reason, str) or reason not in local_model._REASONS:
            reason = 'transport_failed'
        succeeded = result.get('status') == 'succeeded' and result.get('called') is True
        if succeeded:
            sources = {p: snapshots[p]['content'].decode('utf-8') if snapshots[p]['exists'] else None
                       for p in own_paths}
            candidates = contract.validate_candidates({'candidates': result.get('candidates')}, sources,
                own_paths, config['max_candidates_per_specialist'])
            for candidate in candidates:
                for evidence in candidate['evidence'] + candidate['benefit']['evidence']:
                    if not any(evidence['path'] == window['path'] and
                               window['start_line'] <= evidence['start_line'] <=
                               evidence['end_line'] <= window['end_line'] for window in windows):
                        raise LoopError('evidence_outside_window')
        status = 'succeeded' if candidates else 'failed'
        return ({'provider': 'mlx-vlm', 'model': local_config['model'], 'stage': 'local_explorer',
                 'owner_role': role, 'status': status,
                 'reason': 'ok' if candidates else reason, 'called': result.get('called') is True,
                 'read_windows': windows, 'skipped_lines': prepared['skipped_lines'],
                 'started_at': now.isoformat(), 'cost': None, 'cost_status': 'not_metered'}, candidates)
    except (Exception, KeyboardInterrupt):
        return ({'provider': 'mlx-vlm', 'model': local_config['model'], 'stage': 'local_explorer',
                 'owner_role': role, 'status': 'failed', 'reason': 'local_response_invalid',
                 'called': True, 'read_windows': [{key: item[key] for key in
                     ('path', 'start_line', 'end_line')} for item in prepared['sources']],
                 'skipped_lines': prepared['skipped_lines'], 'started_at': now.isoformat(),
                 'cost': None, 'cost_status': 'not_metered'}, [])


def _morning_window(now):
    end = now.replace(hour=9, minute=0, second=0, microsecond=0)
    return end - dt.timedelta(days=1), end


def _publication_name(date):
    return 'loop/publications/' + imp._date(date) + '.json'


def _window_agents(report, start, end):
    agents = _empty_agents()
    for agent in report['agents']:
        stamp = agent.get('finished_at', agent.get('started_at'))
        if stamp is not None and start <= _stamp(stamp) < end:
            _role_agent({'agents': agents}, agent['role'], copy.deepcopy(agent))
    return agents


def _window_locals(report, start, end):
    return [copy.deepcopy(item) for item in report['local_participation']
            if start <= _stamp(item.get('finished_at', item['started_at'])) < end]


def _freeze_morning(store, state, now, discovery, dependencies):
    """Requires both locks. Prepare journal first; never overwrite an older day."""
    start, end = _morning_window(now)
    if now < end:
        return None
    date = now.date().isoformat()
    journal_name = _publication_name(date)
    if store.exists(journal_name):
        return _materialize_morning(store, store.read(journal_name), discovery)
    if store.exists('days/' + date + '.json'):
        # Includes today's pre-activation daily. No rewrite, reanalysis or send.
        journal = {'version': 'improvement-publication-v1', 'date': date,
                   'status': 'legacy_preserved', 'at': now.isoformat(), 'digest': None}
        store.write(journal_name, journal)
        return journal
    chosen = None
    dependency_digest = contract.digest(dependencies)
    eligible = [entry for entry in state['completed'] if
                entry['dependency_digest'] == dependency_digest and
                start <= _stamp(entry['at']) < end]
    for entry in sorted(eligible, key=lambda item: (item['at'], item['scan_id']), reverse=True):
        candidate = store.read('scans/' + entry['scan_id'] + '.json')
        if candidate.get('review_complete') and candidate.get('loop_dependencies') == dependencies:
            # Revalidate all verdict coverage instead of trusting a stored flag.
            contract.validate_review({'reviews': [dict(record['review'], candidate_id=record['id'])
                for record in candidate['proposals']], 'documentation': candidate['documentation']},
                candidate['proposals'], candidate['approved_files'], private=True)
            if any(a['role'] == 'reviewer' and a['status'] == 'succeeded' for a in candidate['agents']):
                chosen = copy.deepcopy(candidate)
                break
    if chosen is not None:
        # A quota/downtime pause may stretch one round beyond the window.
        # Keep complete private provenance, but never present its old owners as
        # today's successful participation. Its fresh reviewer remains genuine.
        chosen['reviewed_agents'] = copy.deepcopy(chosen['agents'])
        chosen['reviewed_local_participation'] = copy.deepcopy(chosen['local_participation'])
        chosen['agents'] = _window_agents(chosen, start, end)
        chosen['local_participation'] = _window_locals(chosen, start, end)
        if not all(a['status'] == 'succeeded' for a in chosen['agents']):
            chosen['status'] = 'partial'
            chosen['errors'].append('participation_outside_report_window')
    if chosen is None:
        current = state['round']['report'] if state['round'] else None
        agents = _empty_agents()
        locals_ = []
        if current and current['loop_dependencies'] == dependencies:
            agents = _window_agents(current, start, end)
            locals_ = _window_locals(current, start, end)
        any_ok = any(a['status'] == 'succeeded' for a in agents) or bool(locals_)
        chosen = {'version': 'improvement-private-v1', 'loop_engine': STATE_VERSION,
                  'proposals': [], 'agents': agents, 'local_participation': locals_,
                  'documentation': dict(imp.NO_DOCUMENT_EDITS), 'review_complete': False,
                  'status': 'partial' if any_ok else 'failed',
                  'errors': ['no_fresh_completed_review'], 'approved_files': dependencies['scope_fingerprint']['paths'],
                  'source_fingerprints': dependencies['source_fingerprints'],
                  'scope_fingerprint': dependencies['scope_fingerprint'],
                  'scope_input': str((imp.ROOT / discovery['scope_file']).absolute()),
                  'scope_override': False, 'config_fingerprint': dependencies['config_fingerprint'],
                  'loop_dependencies': dependencies}
    reviewed_scan_id = chosen.get('scan_id')
    chosen.update(scan_id=_id(), date=date, generated_at=now.isoformat(),
                  reviewed_scan_id=reviewed_scan_id,
                  report_window={'start': start.isoformat(), 'end': end.isoformat()},
                  summary=('이전 오전 9시부터 오늘 오전 9시까지의 최신 완료 검토를 정리했습니다. 사용자 승인을 대신하지 않습니다.'
                           if chosen['review_complete'] else
                           '이전 오전 9시부터 오늘 오전 9시까지 현재 소스에 유효한 독립 검토가 완료되지 않았습니다.'))
    payload = contract.build_web_report(chosen, discovery['limits']['max_reported_proposals'])
    journal = {'version': 'improvement-publication-v1', 'date': date, 'status': 'prepared',
               'at': now.isoformat(), 'digest': payload['digest'], 'report': chosen, 'payload': payload}
    journal['projection_limit'] = discovery['limits']['max_reported_proposals']
    store.write(journal_name, journal)
    return _materialize_morning(store, journal, discovery)


def _freeze_unavailable_morning(store, state, now, reason):
    """No current dependencies => no eligible pool, but still a factual report.

    Used for local configuration/source readiness failures after the slot was
    durably claimed. It reads no additional source or configuration. Storage
    failure can prevent finalization; the prepared journal repairs next tick.
    """
    start, end = _morning_window(now)
    if now < end:
        return None
    date = now.date().isoformat()
    name = _publication_name(date)
    if store.exists(name):
        return _materialize_morning(store, store.read(name), None)
    if store.exists('days/' + date + '.json'):
        journal = {'version': 'improvement-publication-v1', 'date': date,
                   'status': 'legacy_preserved', 'at': now.isoformat(), 'digest': None}
        store.write(name, journal)
        return journal
    agents, locals_ = _empty_agents(), []
    current = state['round']['report'] if state['round'] else None
    if current:
        agents = _window_agents(current, start, end)
        locals_ = _window_locals(current, start, end)
    report = {'version': 'improvement-private-v1', 'loop_engine': STATE_VERSION,
              'scan_id': _id(), 'date': date, 'generated_at': now.isoformat(),
              'status': 'partial' if any(a['status'] == 'succeeded' for a in agents) else 'failed',
              'proposals': [], 'agents': agents, 'local_participation': locals_,
              'documentation': dict(imp.NO_DOCUMENT_EDITS), 'approved_files': [],
              'review_complete': False, 'errors': ['current_dependencies_unavailable'],
              'readiness_reason': reason,
              'report_window': {'start': start.isoformat(), 'end': end.isoformat()},
              'summary': '현재 설정과 소스의 유효성을 확인할 수 없어 독립 검토 완료 후보를 선택하지 못했습니다.'}
    payload = contract.build_web_report(report)
    journal = {'version': 'improvement-publication-v1', 'date': date, 'status': 'prepared',
               'at': now.isoformat(), 'digest': payload['digest'], 'report': report,
               'payload': payload, 'projection_limit': contract.MAX_PROPOSALS}
    store.write(name, journal)
    return _materialize_morning(store, journal, None)


def _materialize_morning(store, journal, discovery):
    if journal['status'] != 'prepared':
        return journal
    date, report, payload = journal['date'], journal['report'], journal['payload']
    limit = journal.get('projection_limit')
    if type(limit) is not int or not 1 <= limit <= contract.MAX_PROPOSALS:
        raise LoopError('publication_digest_changed')
    contract.validate_web_report(payload)
    if (not contract.verify_web_digest(payload, date) or payload['digest'] != journal['digest'] or
            contract.build_web_report(report, limit) != payload):
        raise LoopError('publication_digest_changed')
    if store.exists('days/' + date + '.json'):
        existing = store.read('days/' + date + '.json')
        if existing != report:
            journal = dict(journal, status='existing_day_conflict')
            store.write(_publication_name(date), journal)
            return journal
    store.write('scans/' + report['scan_id'] + '.json', report)
    if report['review_complete']:
        _save_proposals(store, report, preserve_review=True)
    if not store.exists('days/' + date + '.json'):
        store.write('days/' + date + '.json', report)
    for extension, value in (('json', payload), ('html', contract.render_html(payload)),
                             ('md', contract.render_markdown(payload))):
        name = 'web/' + date + '.' + extension
        if store.exists(name):
            body, _ = imp._read_file(store.path(name), imp.MAX_PRIVATE_BYTES, private=True)
            expected = (contract.canonical_json(value) + b'\n' if extension == 'json' else value.encode('utf-8'))
            if body != expected:
                raise LoopError('publication_digest_changed')
        elif extension == 'json':
            store.write(name, value)
        else:
            store.write_bytes(name, value.encode('utf-8'))
    store.write('latest.json', {'date': date})
    journal = dict(journal, status='publication_pending')
    store.write(_publication_name(date), journal)
    return journal


@contextmanager
def _sender_lock(store):
    """Serialize the unlocked callback too, including explicit reconciliation.

    This is a transport mutex, never an improvement execution authorization or
    proposal claim. The callback can acquire both ordinary locks freely. A
    crash releases the kernel lock while its durable sending journal survives.
    """
    store.prepare()
    directory = store.path('loop')
    store.policy.ensure_directory(directory)
    handle = workflow.git_publish.open_lock(store.policy, directory / '.publication-lock')
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LoopError('publication_busy') from None
        yield
    finally:
        handle.close()


def publish(*, now=None, selected=None, publisher=None, reconcile=False):
    """One frozen digest, serialized sender, callback outside both state locks.

    Normal publication never retries an ambiguous send. reconcile=True is an
    explicit same-digest reconciliation, serialized even with an active sender.
    No source analysis or model is invoked here.
    """
    imp._parent()
    store = imp.Store(selected)
    with _sender_lock(store):
        return _publish_once(now=now, selected=store.policy, publisher=publisher, reconcile=reconcile)


def _publish_once(*, now=None, selected=None, publisher=None, reconcile=False):
    """Deliver an already frozen current-day report, without analysis or models.

    A crash/failed send is ambiguous: auto ticks never resend it. Explicit
    reconciliation can reuse ONLY its frozen digest. Existing delivery success
    settles the journal without repeating HTTP. A prepared report can be
    materialized from its exact journal; it is never regenerated.
    """
    imp._parent()
    now = _clock(now)
    if now.hour < 9:
        return {'status': 'before_report_time', 'date': now.date().isoformat()}
    if type(reconcile) is not bool:
        raise LoopError('publication_input_invalid')
    store = imp.Store(selected)
    date = now.date().isoformat()
    name = _publication_name(date)
    with store.lock(), store.lock(project=True):
        state = _read_state(store)
        if state['high_water_at'] and now < _stamp(state['high_water_at']):
            return {'date': date, 'status': 'paused', 'reason': 'clock_rollback'}
        if not store.exists(name):
            return {'status': 'publication_unprepared', 'date': date}
        journal = store.read(name)
        if journal['status'] == 'prepared':
            journal = _materialize_morning(store, journal, None)
        if journal['status'] in ('legacy_preserved', 'existing_day_conflict', 'delivered'):
            return {key: journal[key] for key in ('date', 'status', 'digest')}
        payload = contract.validate_web_report(store.read('web/' + date + '.json'))
        if payload['digest'] != journal['digest'] or not contract.verify_web_digest(payload, date):
            raise LoopError('publication_digest_changed')
        delivery_name = 'delivery/' + date + '.json'
        if store.exists(delivery_name):
            delivery = store.read(delivery_name)
            if delivery.get('digest') == journal['digest'] and delivery.get('status') == 'delivered':
                journal.update(status='delivered', finished_at=now.isoformat())
                store.write(name, journal)
                return {key: journal[key] for key in ('date', 'status', 'digest')}
        if journal['status'] != 'publication_pending' and not reconcile:
            journal['status'] = 'publication_unknown'
            store.write(name, journal)
            return {'date': date, 'status': 'publication_unknown', 'digest': journal['digest']}
        journal.update(status='sending', attempt_id=_id(), attempt_at=now.isoformat())
        store.write(name, journal)
        attempt_id, digest = journal['attempt_id'], journal['digest']
    # deliver_report acquires its own Store.lock. No callback under either lock.
    delivered = False
    try:
        result = (publisher or imp.deliver_report)(date, selected=store.policy)
        delivered = (isinstance(result, dict) and result.get('status') == 'delivered' and
                     result.get('date') == date and result.get('digest') == digest)
    except (Exception, KeyboardInterrupt):
        pass
    with store.lock(), store.lock(project=True):
        journal = store.read(name)
        if journal.get('attempt_id') != attempt_id or journal['digest'] != digest:
            raise LoopError('publication_attempt_changed')
        journal.update(status='delivered' if delivered else 'publication_unknown',
                       finished_at=now.isoformat())
        store.write(name, journal)
    return {'date': date, 'status': journal['status'], 'digest': digest}


def _summary(state, now, config):
    date = now.date().isoformat()
    day = state['days'].get(date, {})
    stage_index = state['stage_index'] if state['stage_index'] < len(STAGES) else 0
    stage, role = STAGES[stage_index]
    report_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if now >= report_time:
        report_time += dt.timedelta(days=1)
    spent = day.get('claude_spent_usd')
    remaining = max(0, config['daily_budget_usd'] - spent) if spent is not None else None
    reason = state['pause_reason']
    budget_status = day.get('legacy_cost_status', 'not_initialized')
    costs = [item.get('cost_status') for item in day.get('slots', {}).values()]
    if any(item in ('reservation_consumed_unknown', 'reservation_consumed_failed') for item in costs):
        budget_status = 'conservative_reservations_consumed'
    elif any(item.get('reservation_usd') is not None for item in day.get('slots', {}).values()):
        budget_status = 'cli_estimated_and_reserved'
    current_review = any(entry['dependency_digest'] == state['dependency_digest']
                         for entry in state['completed'])
    return {'version': STATE_VERSION, 'date': date, 'status': 'paused' if reason else 'researching',
            'reason': reason, 'next_stage': stage, 'next_role': role,
            'calls_today': day.get('calls', 0), 'max_calls_per_day': config['max_calls_per_day'],
            'claude_spent_estimated_usd': spent, 'claude_remaining_estimated_usd': remaining,
            'budget_status': budget_status,
            'last_review_at': state['last_review_at'], 'next_report_at': report_time.isoformat(),
            'last_review_current_at_last_tick': current_review,
            'last_slot': state['last_slot'],
            'message_ko': ('Claude 추정 잔액 {} · 오늘 호출 {}/{} · 보류 {} · 다음 {}({}) · '
                           '마지막 독립 검토 {} · 다음 보고 {}').format(
                               '${:.6f}'.format(remaining) if remaining is not None else '미초기화',
                               day.get('calls', 0), config['max_calls_per_day'],
                               reason or '없음', role, stage,
                               ((state['last_review_at'] + (' (현재 조건 무효)' if not current_review else ''))
                                if state['last_review_at'] else '없음'),
                               report_time.isoformat())}


def status(*, now=None, selected=None):
    imp._parent()
    now, config = _clock(now), load_config()
    store = imp.Store(selected)
    # Status never initializes ledgers, claims slots, reads keys or queries quota.
    with store.lock():
        state = _read_state(store)
        result = _summary(state, now, config)
        name = _publication_name(now.date().isoformat())
        if store.exists(name):
            journal = store.read(name)
            result['publication'] = {key: journal[key] for key in ('date', 'status', 'digest')}
        elif now.hour >= 9:
            result['next_report_at'] = now.replace(hour=9, minute=0, second=0, microsecond=0).isoformat()
            result['publication'] = {'date': now.date().isoformat(), 'status': 'publication_unprepared'}
            result['message_ko'] += ' · 오늘 오전 9시 보고 확정 대기'
        return result


def _pause(store, state, slot, reason, now, config):
    state['pause_reason'] = reason
    day = state['days'].get(now.date().isoformat())
    if day and slot in day['slots']:
        day['slots'][slot].update(status='paused', reason=reason)
    _write_state(store, state)
    return _summary(state, now, config)


def _skip_stage(store, state, day, slot, now, config, reason):
    stage, role = STAGES[state['stage_index']]
    report = state['round']['report']
    if stage != 'local_explorer':
        _role_agent(report, role, {'role': role, 'provider': None, 'model': None,
            'status': 'not_called', 'reason': reason, 'cost': None, 'cost_status': 'unknown',
            'started_at': now.isoformat(), 'finished_at': now.isoformat()})
    if stage == 'independent_reviewer':
        _review_feedback(state, reason)
    state['stage_index'] += 1
    day['slots'][slot].update(status='skipped', reason=reason)
    state['pause_reason'] = reason
    _write_state(store, state)
    _persist_round(store, state, config, now)
    _write_state(store, state)
    return _summary(state, now, config)


def _tick_locked(store, state, now, config, runner, keys, local_runner,
                 supplied_local_config, quota_transport, finish_clock):
    date = now.date().isoformat()
    slot = date + 'T{:02d}'.format(now.hour)
    if state['high_water_at'] and now < _stamp(state['high_water_at']):
        return dict(_summary(state, now, config), status='paused', reason='clock_rollback',
                    message_ko='시계가 이전 기록보다 과거여서 모델 호출과 보고 확정을 보류했습니다.')
    _recover(store, state, config, now)
    # Repair a crash between the atomic completion/settlement write and its
    # derived private scan/proposal writes. This never repeats a model call.
    if state['round'] and state['stage_index'] == len(STAGES):
        report = state['round']['report']
        indexed = any(item['scan_id'] == report['scan_id'] for item in state['completed'])
        if not report['review_complete'] or not indexed:
            _persist_round(store, state, config, now)
            _write_state(store, state)
    day = _day_ledger(store, state, date, config)
    if slot in day['slots']:
        return dict(_summary(state, now, config), status='paused', reason='slot_already_claimed')
    state.update(high_water_at=now.isoformat(), last_slot=slot)
    day['slots'][slot] = {'status': 'claimed', 'at': now.isoformat()}
    # First durable journal, before local config, snapshots, quota or model I/O.
    _write_state(store, state)
    local_config = (local_model.load_config(root=imp.ROOT) if supplied_local_config is None else
                    local_model.validate_config(supplied_local_config))
    if local_config['limits']['timeout_seconds'] + 80 > config['tick_timeout_seconds']:
        raise LoopError('local_timeout_exceeds_tick')
    discovery, paths, snapshots, dependencies = _dependencies(config, local_config, store.policy)
    dependency_digest = contract.digest(dependencies)
    if state['dependency_digest'] != dependency_digest:
        if state['round']:
            old = state['round']['report']
            old['review_complete'] = False
            old['status'] = 'partial' if old['proposals'] else 'failed'
            old['errors'].append('dependencies_changed')
            for record in old['proposals']:
                record.pop('review', None)
            # Never rewrite a completed immutable scan used by an approval.
            store.write('loop/invalidated/' + old['scan_id'] + '.json', old)
        state.update(dependency_digest=dependency_digest, round=None, stage_index=0,
                     feedback={}, cursors={}, completed=[])
    if state['round'] is None or state['stage_index'] == len(STAGES):
        _new_round(state, now, discovery, paths, dependencies)
    # Morning is independent of budget, quota and model availability. It runs
    # before admission and will never invoke a model to manufacture a report.
    _freeze_morning(store, state, now, discovery, dependencies)
    _write_state(store, state)
    midnight = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if (midnight - now).total_seconds() <= config['midnight_guard_seconds']:
        return _pause(store, state, slot, 'midnight_guard', now, config)
    if day['calls'] >= config['max_calls_per_day']:
        return _pause(store, state, slot, 'daily_call_limit', now, config)
    if day['stopped']:
        return _pause(store, state, slot, day.get('stop_reason', 'daily_budget_overrun'), now, config)
    stage, role = STAGES[state['stage_index']]
    own_paths = imp.role_scope(role, paths, discovery)
    if not own_paths:
        return _skip_stage(store, state, day, slot, now, config, 'owner_scope_empty')
    if stage == 'specialist' and not state['round']['drafts'].get(role, {}).get('candidates'):
        return _skip_stage(store, state, day, slot, now, config, 'local_draft_unavailable')
    if stage == 'independent_reviewer':
        report = state['round']['report']
        if not report['proposals'] and not all(a['status'] == 'succeeded' for a in report['agents'][:-1]):
            return _skip_stage(store, state, day, slot, now, config, 'specialist_pool_unavailable')
    budget, spec, feedback, prepared, cursor = None, None, [], None, None
    if stage == 'local_explorer':
        cursor = state['cursors'].get(role, {'file_index': 0, 'line': 1})
        feedback = _bounded_feedback(state['feedback'].get(role, []), own_paths, local_config)
        prepared = local_model.prepare_request(role, own_paths, snapshots, config=local_config,
            cursor=cursor, feedback=feedback, candidate_limit=config['max_candidates_per_specialist'])
        state['cursors'][role] = prepared['next_cursor']
        if prepared['status'] != 'ready':
            state['round']['drafts'][role] = {'candidates': [], 'reason': prepared['reason']}
            report = state['round']['report']
            report['local_participation'].append({'provider': 'mlx-vlm', 'model': local_config['model'],
                'stage': 'local_explorer', 'owner_role': role, 'status': 'skipped', 'called': False,
                'reason': prepared['reason'], 'read_windows': [], 'skipped_lines': prepared['skipped_lines'],
                'started_at': now.isoformat(), 'finished_at': now.isoformat(),
                'cost': None, 'cost_status': 'not_metered'})
            previous = state['feedback'].get(role, [])
            _record_feedback(state, role, [_feedback_entry(reason=prepared['reason'])] + previous[:2])
            return _skip_stage(store, state, day, slot, now, config, prepared['reason'])
        provider, model = 'mlx-vlm', local_config['model']
    else:
        spec = agent_models.load_config()['roles'][role]
        provider, model = spec['provider'], spec['model']
        if provider not in ('codex', 'zai', 'claude'):
            return _pause(store, state, slot, 'provider_unavailable', now, config)
        # Load the existing connection keys only in the trusted parent; never
        # include the key, quota response or budget state in a model prompt.
        keys = agent_models.load_keys() if keys is None else keys
        if provider == 'zai':
            quota = fetch_glm_quota(keys, now, transport=quota_transport,
                timeout=config['quota_timeout_seconds'], max_bytes=config['quota_max_response_bytes'],
                pause_percentage=config['quota_pause_percentage'])
            day['slots'][slot]['quota'] = quota
            if quota['status'] != 'ready':
                return _pause(store, state, slot, quota['reason'], now, config)
        if role == 'reviewer':
            if provider != 'claude':
                return _pause(store, state, slot, 'reviewer_provider_invalid', now, config)
            remaining = config['daily_budget_usd'] - day['claude_spent_usd']
            configured = spec.get('max_budget_usd')
            if not _number(configured, 0) or configured == 0:
                return _pause(store, state, slot, 'reviewer_budget_invalid', now, config)
            budget = min(config['reviewer_max_budget_usd'], remaining, configured)
            if budget <= 0:
                return _pause(store, state, slot, 'daily_budget_limit', now, config)
        elif provider == 'claude':
            # Existing specialist providers must remain their subscribed roles.
            return _pause(store, state, slot, 'unexpected_metered_specialist', now, config)
    store.policy.check_ready()
    # ATOMIC call reservation: slot + role count + cost + cursor + pending call.
    day['calls'] += 1
    if budget is not None:
        day['claude_spent_usd'] += budget
    pending = {'date': date, 'slot': slot, 'round_id': state['round']['report']['scan_id'],
               'stage_index': state['stage_index'], 'provider': provider, 'model': model,
               'at': now.isoformat(), 'reservation_usd': budget,
               'read_windows': [{key: item[key] for key in ('path', 'start_line', 'end_line')}
                                for item in prepared['sources']] if prepared else []}
    state['inflight'] = pending
    day['slots'][slot].update(status='calling', stage=stage, role=role,
                             reservation_usd=budget)
    _write_state(store, state)
    report = state['round']['report']
    if stage == 'local_explorer':
        participation, candidates = _local_call(role, own_paths, snapshots, local_config, cursor,
            feedback, prepared, local_runner or local_model.run, config, now)
        participation['finished_at'] = now.isoformat()
        report['local_participation'].append(participation)
        state['round']['drafts'][role] = {'candidates': candidates,
            'reason': participation['reason'], 'draft_digest': contract.digest(candidates)}
        if not candidates:
            prior = state['feedback'].get(role, [])
            _record_feedback(state, role, [_feedback_entry(reason=participation['reason'])] + prior[:2])
    else:
        drafts = state['round']['drafts'].get(role, {}).get('candidates', [])
        feedback = _bounded_feedback(state['feedback'].get(role, []), own_paths, local_config)
        participation, parsed = _cloud_call(role, own_paths, snapshots, discovery,
            report['proposals'], drafts, feedback, keys, runner or agent_models.run,
            store.policy, config, budget)
        # Use the supplied trusted clock, not helper wall time, for window tests.
        participation.update(started_at=now.isoformat(), finished_at=now.isoformat())
        _role_agent(report, role, participation)
        if stage == 'specialist':
            refined = []
            if parsed is not None:
                for candidate in parsed:
                    record = contract.proposal_record(candidate, dependencies['source_fingerprints'])
                    existing = next((r for r in report['proposals'] if r['id'] == record['id']), None)
                    if existing is not None:
                        refined.append(existing)
                    else:
                        if len(report['proposals']) >= config['max_candidates']:
                            break
                        report['proposals'].append(record)
                        refined.append(record)
            entries = [_feedback_entry(r['candidate'], reason=contract.redact_text(r['candidate']['issue']),
                candidate_id=r['id'], draft_digest=contract.digest(drafts)) for r in refined]
            if not entries:
                reason = 'specialist_empty_candidates' if parsed is not None else 'specialist_failed'
                entries = [_feedback_entry(candidate, reason=reason, draft_digest=contract.digest(drafts))
                           for candidate in drafts][:2]
            _record_feedback(state, role, entries)
        else:
            if parsed is not None:
                report['review_complete'] = True
                report['documentation'] = parsed['documentation']
                verdicts = {item['candidate_id']: item for item in parsed['reviews']}
                for record in report['proposals']:
                    record['review'] = {key: value for key, value in verdicts[record['id']].items()
                                        if key != 'candidate_id'}
            estimate = participation.get('cost')
            if _number(estimate):
                day['slots'][slot].update(actual_estimated_usd=estimate, cost_status='cli_estimated_usd')
                if estimate > budget:
                    # An observed excess matters even if response validation
                    # failed. Failed/unknown calls are never refunded.
                    day['claude_spent_usd'] += estimate - budget
                    day['stopped'] = True
                    day['stop_reason'] = 'daily_budget_overrun'
                    day['slots'][slot]['budget_overrun'] = True
                elif participation['status'] == 'succeeded':
                    day['claude_spent_usd'] += estimate - budget
                else:
                    day['slots'][slot]['cost_status'] = 'reservation_consumed_failed'
            else:
                # Failures, timeouts, interrupts and unknown costs keep the cap.
                day['slots'][slot]['cost_status'] = 'reservation_consumed_unknown'
            # Preserve a reported excess before clock/freshness/scan I/O. A
            # crash here leaves a pending review, but cannot lose its known
            # cost or refund it on recovery.
            _write_state(store, state)
            _review_feedback(state, None if parsed is not None else 'independent_review_failed')
    finished = _clock(finish_clock())
    if finished < now:
        # Keep the original day's reservation and stop; clock rollback must
        # never move a completed review into an earlier publication window.
        finished = now
        day['stopped'] = True
        day['stop_reason'] = 'clock_rollback_during_call'
        report['review_complete'] = False
        report['errors'].append('clock_rollback_during_call')
    now = finished
    if now.date().isoformat() != date:
        # The midnight guard plus runtime deadline prevent ordinary crossing.
        # A forward wall-clock jump is still possible. Charge/count both days
        # conservatively and stop the new day instead of granting a fresh full
        # allowance to an execution that crossed its accounting boundary.
        _account_cross_day(state, pending, now)
    participation['finished_at'] = now.isoformat()
    state['high_water_at'] = max(_stamp(state['high_water_at']), now).isoformat()
    # Re-read fingerprints after the call, before marking its review current.
    try:
        _, _, _, after = _dependencies(config, local_config, store.policy)
        if after != dependencies:
            report['review_complete'] = False
            report['errors'].append('dependencies_changed_during_call')
    except Exception:
        report['review_complete'] = False
        report['errors'].append('freshness_unavailable_after_call')
    state['stage_index'] += 1
    state['inflight'] = None
    day['slots'][slot]['status'] = participation['status']
    state['pause_reason'] = (day.get('stop_reason', 'daily_budget_overrun') if day['stopped'] else
                             None if participation['status'] == 'succeeded' else
                             participation.get('reason', 'role_failed'))
    if state['stage_index'] == len(STAGES) and report['review_complete']:
        report['review_completed_at'] = now.isoformat()
    # Settlement and terminal stage are authoritative even if a subsequent
    # derived scan write fails. In particular, never lose an observed overrun.
    _archive_days(store, state)
    _write_state(store, state)
    _persist_round(store, state, config, now)
    _write_state(store, state)
    return _summary(state, now, config)


def tick(*, now=None, selected=None, runner=None, keys=None, local_runner=None,
         local_config=None, quota_transport=None, publisher=None, deliver=False, clock=None):
    """One bounded opportunity; no retry, sleep, pipeline, approval or fallback.

    Callers should set TAVERN_IMPROVEMENT_UNATTENDED=1 in the scheduler wrapper.
    Omit injected configs/runners in production. Offline tests inject isolated
    storage, aware clocks, modeled runners, a quota transport and a publisher.
    """
    imp._parent()
    fixed_now = now
    finish_clock = clock or ((lambda: fixed_now) if fixed_now is not None else
                             (lambda: dt.datetime.now(dt.timezone.utc)))
    now = _clock(clock() if clock is not None else now)
    try:
        config = load_config()
        store = imp.Store(selected)
        with _deadline(config['tick_timeout_seconds']):
            store.policy.check_ready()
            with store.lock(), store.lock(project=True):
                state = _read_state(store)
                try:
                    result = _tick_locked(store, state, now, config, runner, keys, local_runner,
                                          local_config, quota_transport, finish_clock)
                except (Exception, KeyboardInterrupt) as exc:
                    # Disk failure can prevent this diagnostic write. The last
                    # durable pending reservation remains authoritative then.
                    reason = (exc.reason if isinstance(exc, local_model.LocalModelError) else
                              str(exc) if isinstance(exc, LoopError) else 'tick_unavailable')
                    state['pause_reason'] = reason
                    if state['inflight'] is not None:
                        # Leave durable pending intact for next-slot recovery;
                        # never accidentally refund an attempted model call.
                        result = dict(_summary(state, now, config), reason=reason, status='paused')
                    else:
                        slot = state['last_slot']
                        result = _pause(store, state, slot, reason, now, config)
                    _freeze_unavailable_morning(store, state, now, reason)
            if (publisher is not None or deliver) and result.get('reason') != 'clock_rollback':
                result['publication'] = publish(now=_clock(finish_clock()),
                                                selected=store.policy, publisher=publisher)
            return result
    except (Exception, KeyboardInterrupt):
        # Lock/storage/runtime failures are not successful scans. No keys,
        # paths, raw HTTP bodies or provider exceptions leave this boundary.
        return {'version': STATE_VERSION, 'date': now.date().isoformat(), 'status': 'paused',
                'reason': 'lock_storage_or_runtime_unavailable',
                'message_ko': '프로젝트 잠금·저장소·실행 제한을 확인할 수 없어 탐색을 보류했습니다.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='한 시간에 한 단계의 읽기 전용 개선 탐색')
    parser.add_argument('action', choices=('tick', 'status', 'publish'))
    parser.add_argument('--no-deliver', action='store_true', help='tick의 보고 전달을 생략')
    parser.add_argument('--reconcile', action='store_true', help='동일 digest의 모호한 전달만 명시 재조정')
    args = parser.parse_args(argv)
    if args.reconcile and args.action != 'publish':
        parser.error('--reconcile requires publish')
    if args.no_deliver and args.action != 'tick':
        parser.error('--no-deliver requires tick')
    try:
        if args.action == 'tick':
            result = tick(deliver=not args.no_deliver)
        elif args.action == 'publish':
            result = publish(reconcile=args.reconcile)
        else:
            result = status()
    except (Exception, KeyboardInterrupt):
        result = {'status': 'paused', 'reason': 'loop_unavailable',
                  'message_ko': '개선 탐색 상태를 확인할 수 없어 보류했습니다.'}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 1 if result.get('status') in ('paused', 'publication_unknown') else 0


if __name__ == '__main__':
    raise SystemExit(main())
