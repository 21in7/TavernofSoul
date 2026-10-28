"""Offline synthetic metrics cases. Execution belongs to the orchestrator."""
import copy
import datetime as dt
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import pytest

from harness import improvement_metrics as metrics, improvements as imp
from harness import review_coverage as coverage
from harness.test_review_coverage import candidate, read_events, stdout, SOURCE_DOC

C = metrics.contract
NOW = dt.datetime(2026, 10, 28, 0, tzinfo=metrics.KST)


def at(hour=0, day=27, minute=0):
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=metrics.KST).isoformat()


def scan_fixture(tmp_path, count=1, scan_id='123456-abcd', day=27, title_prefix='중복 점검 줄이기 '):
    sources = {'harness/example.py': {'exists': True, 'mode': 0o644,
                                     'content': b'one\ntwo\nthree\n'},
               'AGENTS.md': {'exists': True, 'mode': 0o644, 'content': b'document\n'}}
    fingerprints = C.fingerprint_sources(sources)
    proposals = []
    for i in range(count):
        record = C.proposal_record(candidate(title=title_prefix + str(i)), fingerprints)
        record['review'] = dict(verdict='eligible', reason='합성 소스에서 근거와 제한된 변경 범위를 확인했습니다.',
                                documentation=copy.deepcopy(SOURCE_DOC))
        proposals.append(record)
    scan = dict(version='improvement-private-v1', loop_engine='improvement-loop-state-v1',
                date=at(day=day)[:10], generated_at=at(day=day), started_at=at(day=day),
                scan_id=scan_id, status='scanned', proposals=proposals, review_complete=True,
                review_completed_at=at(8, day, 1), documentation=copy.deepcopy(SOURCE_DOC),
                approved_files=list(sources), source_fingerprints=fingerprints,
                config_fingerprint={}, scope_fingerprint={'paths': list(sources),
                    'sha256': C.digest(list(sources)), 'mode': 0o644}, errors=[],
                agents=[], local_participation=[])
    scan['loop_dependencies'] = dict(review_protocol=coverage.VERSION,
                                    source_fingerprints=fingerprints, scope_fingerprint=scan['scope_fingerprint'])
    # Match _dependencies_locked's control contract without loading any config.
    for field in ('config_fingerprint', 'loop_config_fingerprint', 'local_config_fingerprint',
                  'agent_config_fingerprint', 'workflow_config_fingerprint', 'ownership_fingerprint'):
        scan['loop_dependencies'][field] = C.digest({'synthetic_control': field})
    scan['config_fingerprint'] = scan['loop_dependencies']['config_fingerprint']
    for i, role in enumerate(metrics.ROLES):
        index = 8 if role == 'reviewer' else 2 * i + 1
        scan['agents'].append(dict(role=role, provider='claude' if index == 8 else 'codex', model='synthetic',
                                   stage_index=index, slot=at(index, day)[:13],
                                   status='succeeded', started_at=at(index, day), finished_at=at(index, day, 1),
                                   call_started_at=at(index, day), call_finished_at=at(index, day, 1)))
        if i < 4:
            scan['local_participation'].append(dict(role=role, owner_role=role, provider='mlx-vlm',
                model='synthetic', stage_index=2 * i, slot=at(2 * i, day)[:13], called=True,
                status='succeeded', started_at=at(2 * i, day), finished_at=at(2 * i, day, 1),
                call_started_at=at(2 * i, day), call_finished_at=at(2 * i, day, 1)))
    owners = {r: ['harness/example.py'] for r in C.SPECIALIST_ROLES}
    windows = coverage.plan(list(sources), sources, proposals, owners, ['AGENTS.md'])
    capture = coverage.Capture(tmp_path, sources, windows)
    capture.accept(stdout(read_events(capture)))
    proof = dict(version=coverage.VERSION, plan=windows, reads=capture.receipts,
                 assessments=[dict(window=i, assessment='합성 자료의 지정된 줄을 읽고 근거와 변경 범위를 확인했습니다.')
                              for i in range(len(windows))],
                 fingerprints_digest=C.digest(fingerprints), review_digest=C.digest(coverage.review_result(scan)))
    coverage.attach(scan, proof)
    return scan


def records_for(scan, source='hourly'):
    result = {'scans/' + scan['scan_id'] + '.json': scan}
    if source == 'hourly':
        # A real tick slot owns the scan independently of its fields or Read.
        entry = dict(scan['agents'][0], scan_id=scan['scan_id'])
        result['loop/ledgers/' + scan['date'] + '.json'] = dict(
            legacy_seen=[], slots={entry['slot']: entry})
    elif source == 'nonhourly':
        result['loop/legacy-index.json'] = dict(version=1,
            legacy=[dict(scan_id=scan['scan_id'], date=scan['date'])], participation=[])
    for record in scan['proposals']:
        result['proposals/' + record['id'] + '.json'] = dict(proposal=copy.deepcopy(record),
            scan_id=scan['scan_id'], review_complete=scan['review_complete'])
    return result


def query(records, **kwargs):
    return metrics.aggregate(records, period='day', date='2026-10-27', now=NOW, **kwargs)


def freeze(scan, limit=3):
    report = copy.deepcopy(scan)
    report.update(scan_id='morning-' + scan['scan_id'], date='2026-10-27', generated_at=at(9),
                  report_window=dict(start=at(9, 26), end=at(9)))
    report['proposals'].sort(key=lambda p: ({'high': 0, 'medium': 1, 'low': 2}[p['candidate']['priority']], p['id']))
    report['proposals'] = report['proposals'][:8]
    payload = C.build_web_report(report, limit)
    return dict(date=report['date'], status='delivered', at=at(9), report=report,
                payload=payload, digest=payload['digest'], projection_limit=limit)


def sign(body, key):
    return dict(body, signature=hmac.new(key, C.canonical_json(body), hashlib.sha256).hexdigest())


def execution_fixture(scan):
    records = records_for(scan)
    proposal = scan['proposals'][0]
    pid = proposal['id']
    key = b'K' * 32
    approval = dict(version='improvement-approval-v1', authority='trusted-parent', proposal_id=pid,
        proposal_digest=proposal['digest'], review_digest=C.digest(proposal['review']),
        source_fingerprints=proposal['source_fingerprints'], allowed_edit_files=proposal['candidate']['edit_files'],
        publication=imp.PUBLICATION, instruction='합성 제안의 지정 범위만 구현합니다.', issued_at=at(10),
        expires_at=at(10, 28), authorization_id='a' * 48, consumption='unconsumed',
        discovery_fingerprint=C.digest(dict(dependencies=scan['loop_dependencies'], scan_id=scan['scan_id'],
                                           source_review_binding=scan['source_review_binding'])))
    task = imp._task(proposal, approval)
    claim = dict(version='improvement-claim-v1', proposal_id=pid, proposal_digest=proposal['digest'],
        authorization_id=approval['authorization_id'], task_digest=hashlib.sha256(task.encode('utf-8')).hexdigest(),
        claim_id='b' * 48, run_id='123456-abcdef', status='consumed', workflow_status='awaiting_github', at=at(11))
    records.update({'authority.key': key, 'approvals/' + pid + '.json': sign(approval, key),
                    'claims/' + pid + '.json': sign(claim, key),
                    'decisions/' + pid + '.json': dict(status='approved', authorization_id='a' * 48, at=at(10)),
                    'executions/' + pid + '.json': dict(status='awaiting_github', run_id=claim['run_id'])})
    prefix = 'workflows/' + claim['run_id'] + '/'
    checks = {name: 'success' for name in metrics.REQUIRED_CI}
    cleanup = dict(version='cleanup-v1', status='complete',
                   remote={'status': 'deleted'}, local={'status': 'absent'},
                   prune={'status': 'complete'}, sync={'status': 'complete'}, completion={'status': 'complete'})
    github = dict(run_id=claim['run_id'], status='merged', step='done', merge_status='merged',
                  head_sha='1' * 40, merge_sha='2' * 40, pr_number=1, checks=checks, cleanup=cleanup,
                  cleanup_proof=dict(verified=True, head_sha='1' * 40, merge_sha='2' * 40, checks=checks))
    report = dict(run_id=claim['run_id'], status='passed', finished_at=at(14), read_only=False, simulated=False,
        no_git=False, github_enabled=True, task_sha256=imp.workflow.triage.digest(task),
        scope=approval['allowed_edit_files'], changed_files=approval['allowed_edit_files'],
        applied=approval['allowed_edit_files'], review={'verdict': 'approved'},
        required_checks=['check'], delivery_validation=[dict(command='check', status='passed', exit_code=0,
            checks={'offline': dict(status='passed', selected=2, passed=2, skipped=[], failures=[], errors=[])})],
        events=[dict(time=at(12), phase='review', state='failed'),
                dict(time=at(15), phase='github', provider='github', state='merged')], agents=[])
    records[prefix + 'report.json'] = report
    records[prefix + 'github.json'] = github
    records[prefix + 'github-approved.json'] = {'files': {f: {} for f in approval['allowed_edit_files']}}
    return records, prefix


def test_nine_stages_complete_and_zero_candidate_completion(tmp_path):
    for count in (0, 2):
        scan = scan_fixture(tmp_path, count=count)
        assert coverage.validate(scan) is True
        result = query(records_for(scan))
        assert result['rounds']['counts']['completed'] == 1
        assert result['rounds']['completion']['value'] == 1
        assert [s['calls'] for s in result['rounds']['stages']] == [1] * 9
        assert result['rounds']['duration_seconds']['median'] == 8 * 3600 + 60
        assert result['funnel']['generated'] is None


@pytest.mark.parametrize('case,expected', [('failed', 'failed'), ('superseded', 'superseded'),
    ('skipped_reviewer', 'superseded'), ('invalidated', 'invalidated'), ('held', 'held'),
    ('quota', 'held'), ('progress', 'in_progress'), ('legacy', 'unknown')])
def test_round_outcomes_without_inventing_review(tmp_path, case, expected):
    scan = scan_fixture(tmp_path)
    scan['review_complete'] = case == 'legacy'
    scan.pop('source_review', None)
    scan['agents'][-1]['status'] = 'failed' if case != 'skipped_reviewer' else 'not_called'
    scan['agents'][-1]['reason'] = 'review_invalid'
    records = records_for(scan)
    if case in ('superseded', 'skipped_reviewer'):
        later = copy.deepcopy(scan)
        later.update(scan_id='123457-abcd', started_at=at(10), generated_at=at(10))
        records['scans/' + later['scan_id'] + '.json'] = later
        records['loop/state.json'] = dict(completed=[dict(scan_id=later['scan_id'], at=at(10))])
    if case == 'invalidated':
        records['loop/invalidated/' + scan['scan_id'] + '.json'] = scan
    if case in ('held', 'quota', 'progress'):
        records['loop/state.json'] = dict(round={'report': scan}, stage_index=3,
            pause_reason='quota_unavailable' if case == 'quota' else 'daily_budget_limit' if case == 'held' else 'running')
    result = query(records)
    assert result['rounds']['items'][0]['status'] == expected
    if expected in ('invalidated', 'held', 'in_progress', 'unknown'):
        assert result['rounds']['completion']['value'] is None


def test_local_failure_empty_and_preparation_skip_are_separate(tmp_path):
    scan = scan_fixture(tmp_path)
    scan['local_participation'][0].update(status='failed', reason='empty_draft')
    scan['local_participation'][1].update(status='failed', reason='transport_failed')
    scan['local_participation'][2].update(status='skipped', called=False)
    result = query(records_for(scan))
    assert result['rounds']['counts']['completed'] == 1
    assert result['rounds']['local_valid_draft_calls']['numerator'] == 1
    assert result['rounds']['local_valid_draft_calls']['denominator'] == 3
    assert result['rounds']['local_draft_cardinality'] is None


def test_first_failed_attempt_survives_later_success_in_another_slot(tmp_path):
    scan = scan_fixture(tmp_path)
    first = dict(scan['agents'][0], scan_id=scan['scan_id'], status='failed', reason='role_execution_failed')
    scan['agents'][0].update(started_at=at(10), slot=at(10)[:13], call_started_at=at(10), call_finished_at=at(10, minute=1))
    records = records_for(scan)
    records['loop/state.json'] = {'version': 'improvement-loop-state-v1', 'participation': [first]}
    result = query(records)
    assert result['rounds']['stages'][1]['calls'] == 2
    assert result['rounds']['stages'][1]['failed'] == 1
    assert result['rounds']['stages'][1]['success'] == 1


def test_duplicate_ids_digests_transitively_merge_and_future_review_stays_out(tmp_path):
    scan = scan_fixture(tmp_path, count=3)
    # The union contract also handles inconsistent legacy identity aliases.
    scan['review_complete'] = False
    a, b, c = scan['proposals']
    b['digest'] = a['digest']
    c['id'] = b['id']
    result = query(records_for(scan))
    assert result['funnel']['validated_retained'] == 1
    assert result['funnel']['duplicates'] == 2
    assert result['funnel']['verdicts']['review_incomplete'] == 1
    future = scan_fixture(tmp_path, scan_id='123458-abcd')
    future['review_completed_at'] = at(8, 28)
    future['agents'][-1]['finished_at'] = at(8, 28)
    result = query(records_for(future))
    assert result['funnel']['eligible'] == 0


def test_morning_historical_digest_top3_and_delivery_are_independent(tmp_path):
    scan = scan_fixture(tmp_path, count=5)
    records = records_for(scan)
    records['loop/publications/2026-10-27.json'] = freeze(scan)
    result = query(records)
    assert result['funnel']['selected'] == 5
    assert result['funnel']['exposed'] == 3
    assert [l['reason'] for l in result['funnel']['mornings'][0]['losses']] == ['top3'] * 2
    frozen = records['loop/publications/2026-10-27.json']
    frozen['report']['loop_dependencies'] = dict(changed='historic')
    frozen['report']['proposals'] = []
    result = query(records)
    assert len(result['funnel']['mornings'][0]['losses']) == 5
    assert {l['reason'] for l in result['funnel']['mornings'][0]['losses']} == {'dependency_digest_mismatch'}


def test_top8_and_provenance_unavailable_keep_displaced_verdict(tmp_path):
    scan = scan_fixture(tmp_path, count=8)
    second = scan_fixture(tmp_path, count=1, scan_id='123459-abcd', title_prefix='별도 후보 ')
    second['proposals'][0]['review']['verdict'] = 'rejected'
    second['source_review']['review_digest'] = C.digest(coverage.review_result(second))
    coverage.attach(second, second['source_review'])
    records = records_for(scan)
    records.update(records_for(second))
    records['loop/state.json'] = dict(completed=[dict(scan_id=scan['scan_id'], at=at(8, minute=1))])
    combined = copy.deepcopy(scan)
    combined['proposals'] += second['proposals']
    journal = freeze(combined)
    records['loop/publications/2026-10-27.json'] = journal
    result = query(records)
    assert len([l for l in result['funnel']['mornings'][0]['losses'] if l['reason'] == 'top8']) == 1
    omitted = next(p for p in combined['proposals'] if p['id'] not in {r['id'] for r in journal['report']['proposals']})
    records.pop('proposals/' + omitted['id'] + '.json')
    result = query(records)
    assert any(l['reason'] == 'provenance_unavailable' for l in result['funnel']['mornings'][0]['losses'])


@pytest.mark.parametrize('case', ['approval_wait', 'ci_wait', 'ci_fail', 'cleanup_wait', 'merged', 'missing_journal', 'bad_signature'])
def test_signed_conversion_waits_failures_and_completed_merge(tmp_path, case):
    scan = scan_fixture(tmp_path)
    records, prefix = execution_fixture(scan)
    github = records[prefix + 'github.json']
    pid = scan['proposals'][0]['id']
    if case == 'approval_wait':
        records.pop('approvals/' + pid + '.json')
    elif case == 'ci_wait':
        github.update(checks={}, cleanup_proof={}, merge_sha=None)
    elif case == 'ci_fail':
        github['checks'] = {next(iter(metrics.REQUIRED_CI)): 'failure'}
    elif case == 'cleanup_wait':
        github['cleanup']['status'] = 'pending'
        github['step'] = 'cleanup_execute'
    elif case == 'missing_journal':
        records.pop(prefix + 'github.json')
    elif case == 'bad_signature':
        records['approvals/' + pid + '.json']['instruction'] = 'tampered'
    result = query(records)
    item = result['conversion']['items'][0]
    assert item['cleanup'] == ('passed' if case == 'merged' else 'unavailable' if case == 'missing_journal' else 'waiting')
    if case == 'ci_fail':
        assert item['ci3'] == 'failed'
    if case == 'cleanup_wait':
        assert item['merge'] == 'passed'
    if case == 'bad_signature':
        assert item['approval'] == 'unavailable'
    if case == 'merged':
        assert result['conversion']['unique_runs'] == 1
        assert result['conversion']['merge_completion_rate']['value'] == 1
        assert item['events'][0]['state'] == 'failed'


def test_resumed_journal_count_is_one_and_future_merge_does_not_leak(tmp_path):
    scan = scan_fixture(tmp_path)
    records, prefix = execution_fixture(scan)
    records['executions/alias.json'] = copy.deepcopy(next(v for k, v in records.items() if k.startswith('executions/')))
    assert query(records)['conversion']['unique_runs'] == 1
    records[prefix + 'report.json']['events'][-1]['time'] = at(1, 28)
    assert query(records)['conversion']['items'][0]['merge'] == 'unavailable'


def test_missing_observations_zero_denominators_role_and_domain(tmp_path):
    result = query({})
    assert result['rounds']['completion']['status'] == '미산출'
    assert result['funnel']['selected'] is None
    assert result['efficiency']['calls_per_merge']['unit'] == 'calls_per_merge'
    scan = scan_fixture(tmp_path)
    result = query(records_for(scan), role='reviewer')
    assert result['efficiency']['research_slots'] == 1
    assert result['funnel']['eligible'] == 0
    assert result['efficiency']['research'][0]['tokens']['input_tokens']['known_sum'] is None
    assert metrics.domain(['downloader/a.py', 'harness/b.py']) == 'mixed'
    assert metrics.domain([]) == 'unknown'


def test_kst_midnight_nine_am_half_open_windows_and_duration_statistics(tmp_path):
    scan = scan_fixture(tmp_path)
    records = records_for(scan)
    scan['started_at'] = '2026-10-26T15:00:00+00:00'
    assert query(records)['rounds']['counts']['completed'] == 1
    scan['started_at'] = '2026-10-27T15:00:00+00:00'
    assert query(records)['rounds']['counts']['completed'] == 0
    bounds = (metrics.timestamp(at(9, 26)), metrics.timestamp(at(9)))
    assert metrics.inside(at(9, 26), bounds)
    assert not metrics.inside(at(9), bounds)
    assert metrics.stats([1, 2, 3, 480, None]) == dict(n=4, median=2.5, p90=480, max=480)
    assert metrics.elapsed(None, at(1)) is None


def legacy_fixture(tmp_path, with_reads=True, day=27):
    scan = scan_fixture(tmp_path, scan_id='223456-abcd', day=day, title_prefix='legacy 별도 후보 ')
    scan.pop('loop_engine')
    scan.pop('loop_dependencies')
    if with_reads:
        coverage.attach(scan, scan['source_review'])
    else:
        scan.pop('source_review')
        scan.pop('source_review_binding')
    # Deliberately retain hourly-looking admission times, slots and stage IDs.
    return scan


def history_entry(scan, index=0, local=False):
    agent = scan['local_participation' if local else 'agents'][index]
    # _remember's persisted shape has no local called flag or format marker.
    return dict(scan_id=scan['scan_id'], slot=agent['slot'], stage_index=agent['stage_index'],
                role=agent['role'], owner_role=agent['role'], provider=agent['provider'],
                model=agent['model'], status=agent['status'], started_at=agent['started_at'],
                finished_at=agent['finished_at'], call_started_at=agent['call_started_at'],
                call_finished_at=agent['call_finished_at'])


@pytest.mark.parametrize('period', ['day', '7d', '30d'])
@pytest.mark.parametrize('role', [None, 'reviewer', C.SPECIALIST_ROLES[0]])
@pytest.mark.parametrize('with_reads', [False, True])
def test_mixed_formats_share_one_hourly_cohort_across_all_metrics(tmp_path, period, role, with_reads):
    hourly = scan_fixture(tmp_path)
    frozen = freeze(hourly)
    # Exercise the metrics origin-role filter without adding private test
    # metadata to build_web_report's strict proposal contract.
    hourly['proposals'][0]['origin_role'] = C.SPECIALIST_ROLES[0]
    records, prefix = execution_fixture(hourly)
    records[prefix + 'report.json']['agents'] = [dict(role=C.SPECIALIST_ROLES[0],
        provider='codex', status='passed', started_at=at(12), finished_at=at(13))]
    records['loop/publications/2026-10-27.json'] = frozen
    baseline = metrics.aggregate(records, period=period, date='2026-10-27', now=NOW, role=role)
    legacy = legacy_fixture(tmp_path, with_reads=with_reads)
    expected_excluded_attempts = sum(
        1 for call in legacy['agents'] + legacy['local_participation']
        if role is None or call['role'] == role)
    assert metrics.read_proof(legacy) is with_reads
    records.update(records_for(legacy, source='nonhourly'))
    records['loop/state.json'] = dict(version='improvement-loop-state-v1',
        round={'report': copy.deepcopy(hourly)}, stage_index=9,
        participation=[history_entry(s, i) for s in (legacy, hourly) for i in range(5)],
        local_history=[history_entry(s, i, local=True) for s in (legacy, hourly) for i in range(4)])
    result = metrics.aggregate(records, period=period, date='2026-10-27', now=NOW, role=role)
    for field in ('scope', 'rounds', 'funnel', 'conversion', 'efficiency'):
        assert result[field] == baseline[field]
    assert result['status'] == 'available'
    assert result['coverage']['scans'] == 2
    assert result['coverage']['hourly_scans'] == 1
    assert result['coverage']['legacy_non_loop_scans'] == 1
    assert result['coverage']['unknown_format_scans'] == 0
    assert len(result['coverage']['excluded_attempts']) == expected_excluded_attempts


@pytest.mark.parametrize('case,kind', [
    ('current', 'hourly'), ('pre_read', 'hourly'), ('legacy_reads', 'legacy'), ('legacy_old', 'legacy'),
    ('private_missing', 'hourly'), ('private_unknown', 'hourly'),
    ('engine_missing', 'hourly'), ('engine_unknown', 'hourly'), ('engine_null', 'hourly'),
    ('dependencies_missing', 'hourly'), ('dependencies_null', 'hourly'),
    ('dependencies_list', 'hourly'), ('dependencies_empty', 'hourly'),
    ('control_missing', 'hourly'), ('control_malformed', 'hourly'),
    ('sources_missing', 'hourly'), ('sources_null', 'hourly'), ('sources_empty', 'hourly'),
    ('scope_malformed', 'hourly'), ('protocol_missing', 'hourly'),
    ('protocol_unknown', 'hourly'), ('protocol_null', 'hourly')])
def test_tick_source_classification_never_uses_scan_format(tmp_path, case, kind):
    scan = scan_fixture(tmp_path)
    dependencies = scan['loop_dependencies']
    if case.startswith('legacy_'):
        scan = legacy_fixture(tmp_path, with_reads=case == 'legacy_reads')
    elif case == 'pre_read':
        dependencies.pop('review_protocol')
        scan.pop('source_review')
        scan.pop('source_review_binding')
    elif case == 'private_missing':
        scan.pop('version')
    elif case == 'private_unknown':
        scan['version'] = 'improvement-private-v999'
    elif case == 'engine_missing':
        scan.pop('loop_engine')
    elif case == 'engine_unknown':
        scan['loop_engine'] = 'improvement-loop-state-v999'
    elif case == 'engine_null':
        scan['loop_engine'] = None
    elif case == 'dependencies_missing':
        scan.pop('loop_dependencies')
    elif case.startswith('dependencies_'):
        scan['loop_dependencies'] = {'dependencies_null': None, 'dependencies_list': [],
                                     'dependencies_empty': {}}[case]
    elif case == 'control_missing':
        dependencies.pop('ownership_fingerprint')
    elif case == 'control_malformed':
        dependencies['ownership_fingerprint'] = True
    elif case == 'sources_missing':
        dependencies.pop('source_fingerprints')
    elif case in ('sources_null', 'sources_empty'):
        scan['source_fingerprints'] = dependencies['source_fingerprints'] = None if case == 'sources_null' else {}
    elif case == 'scope_malformed':
        scan['scope_fingerprint'] = dependencies['scope_fingerprint'] = {'paths': []}
    elif case == 'protocol_missing':
        dependencies.pop('review_protocol')
    elif case in ('protocol_unknown', 'protocol_null'):
        dependencies['review_protocol'] = 'source-read-review-v999' if case == 'protocol_unknown' else None
    records = records_for(scan, source='nonhourly' if kind == 'legacy' else 'hourly')
    records['loop/state.json'] = dict(version='improvement-loop-state-v1',
        participation=[history_entry(scan)], local_history=[history_entry(scan, local=True)])
    result = query(records)
    assert result['coverage']['hourly_scans'] == int(kind == 'hourly')
    assert result['coverage']['legacy_non_loop_scans'] == int(kind == 'legacy')
    assert result['coverage']['unknown_format_scans'] == int(kind == 'unknown')
    assert result['status'] == ('partial' if kind == 'unknown' else 'available')
    if kind != 'hourly':
        assert result['rounds']['items'] == []
        assert result['funnel']['validated_retained'] == 0
        assert result['efficiency']['research_slots'] == 0
        assert result['efficiency']['calls_per_eligible']['value'] is None
        assert result['rounds']['completion']['value'] is None
    elif not metrics.read_proof(scan):
        assert result['rounds']['counts']['unknown'] == 1
        assert result['funnel']['verdicts']['unknown'] == 1
        assert result['efficiency']['research_slots'] == 9
    else:
        assert result['rounds']['counts']['completed'] == 1
        assert result['funnel']['eligible'] == 1
    if case == 'legacy_reads':
        assert metrics.read_proof(scan) is True
    if case == 'legacy_old':
        assert metrics.read_proof(scan) is False


def test_state_imports_require_hourly_original_and_preserve_first_failures(tmp_path):
    scan = scan_fixture(tmp_path)
    legacy = legacy_fixture(tmp_path, with_reads=False)
    first = history_entry(scan)
    first.update(status='failed', reason='role_execution_failed')
    first_local = history_entry(scan, local=True)
    first_local.update(status='failed', reason='transport_failed')
    local_only = history_entry(scan, index=1, local=True)
    # Valid hourly history can retain an attempt no longer in the role projection.
    scan['local_participation'].pop(1)
    orphan = dict(first, scan_id='323456-abcd', status='succeeded')
    local_orphan = dict(first_local, scan_id='323456-abcd', status='succeeded')
    unidentified = dict(orphan)
    unidentified.pop('scan_id')
    records = records_for(scan)
    records.update(records_for(legacy, source='nonhourly'))
    records['loop/state.json'] = dict(version='improvement-loop-state-v1',
        participation=[first, dict(first, status='succeeded'), history_entry(legacy), orphan, unidentified],
        local_history=[first_local, dict(first_local, status='succeeded'), local_only,
                       history_entry(legacy, local=True), local_orphan])
    result = query(records)
    stages = result['rounds']['stages']
    assert [stage['calls'] for stage in stages] == [1] * 9
    assert stages[1]['failed'] == stages[0]['failed'] == 1
    assert stages[1]['reasons'] == {'role_execution_failed': 1}
    assert stages[0]['reasons'] == {'transport_failed': 1}
    assert result['rounds']['local_valid_draft_calls']['numerator'] == 3
    assert result['rounds']['local_valid_draft_calls']['denominator'] == 4
    assert result['efficiency']['research_slots'] == 9
    assert result['efficiency']['local_calls'] == 4
    assert result['efficiency']['calls_per_eligible']['numerator'] == 9
    assert result['efficiency']['calls_per_eligible']['denominator'] == 1
    assert result['status'] == 'partial'
    assert len(result['coverage']['excluded_attempts']) == 12
    assert {e['scan_id'] for e in result['coverage']['excluded_attempts']} == {legacy['scan_id'], orphan['scan_id'], None}


@pytest.mark.parametrize('version', [None, 'improvement-loop-state-v999'])
def test_history_container_needs_supported_version_even_for_known_scan(tmp_path, version):
    scan = scan_fixture(tmp_path)
    records = records_for(scan)
    first = history_entry(scan)
    first.update(status='failed', reason='role_execution_failed', started_at=at(10), slot=at(10)[:13],
                 finished_at=at(10, minute=1), call_started_at=at(10), call_finished_at=at(10, minute=1))
    local = history_entry(scan, local=True)
    state = dict(participation=[first], local_history=[local])
    if version is not None:
        state['version'] = version
    records['loop/state.json'] = state
    result = query(records)
    assert result['status'] == 'partial'
    assert result['efficiency']['research_slots'] == 9
    assert result['rounds']['stages'][1]['failed'] == 0
    assert {e['reason'] for e in result['coverage']['excluded_attempts']} == {'history_version_unknown'}


@pytest.mark.parametrize('location', ['scans', 'active', 'invalidated'])
@pytest.mark.parametrize('same_id', [False, True])
def test_morning_copies_are_not_originals_in_any_location(tmp_path, location, same_id):
    scan = scan_fixture(tmp_path)
    records = records_for(scan)
    baseline = query(records)
    projection = freeze(scan)['report']
    projection['scan_id'] = scan['scan_id'] if same_id else '423456-abcd'
    if location == 'active':
        records['loop/state.json'] = {'round': {'report': projection}, 'stage_index': 9}
    else:
        prefix = 'scans/' if location == 'scans' else 'loop/invalidated/'
        # Keep the original file when testing an extra scan copy with its ID.
        name = 'projection-copy' if location == 'scans' and same_id else projection['scan_id']
        records[prefix + name + '.json'] = projection
    result = query(records)
    for field in ('rounds', 'funnel', 'conversion', 'efficiency'):
        assert result[field] == baseline[field]
    assert result['coverage']['hourly_scans'] == 1


def test_latest_period_follows_tick_source_not_newer_legacy_date(tmp_path):
    hourly = scan_fixture(tmp_path, day=26)
    legacy = legacy_fixture(tmp_path, day=27)
    records = records_for(hourly)
    records.update(records_for(legacy, source='nonhourly'))
    result = metrics.aggregate(records, now=NOW)
    assert result['scope']['start'] == at(day=26)
    assert [r['scan_id'] for r in result['rounds']['items']] == [hourly['scan_id']]
    assert result['efficiency']['research_slots'] == 9


@pytest.mark.parametrize('owner', ['round', 'completed', 'invalidated', 'state_slot', 'archived_slot', 'participation'])
@pytest.mark.parametrize('old_protocol', [None, 'sealed-round-history-v1'])
def test_old_hourly_uses_each_tick_path_without_ownership_or_reads(tmp_path, owner, old_protocol):
    scan = scan_fixture(tmp_path)
    scan['loop_dependencies'].pop('ownership_fingerprint')
    if old_protocol is None:
        scan['loop_dependencies'].pop('review_protocol')
    else:
        scan['loop_dependencies']['review_protocol'] = old_protocol
    scan.pop('source_review')
    scan.pop('source_review_binding')
    records = records_for(scan, source=None)
    state = dict(version=metrics.LOOP_VERSION)
    if owner == 'round':
        state.update(round={'report': scan}, stage_index=9)
    elif owner == 'completed':
        state['completed'] = [dict(scan_id=scan['scan_id'], at=at(8, minute=1))]
    elif owner == 'invalidated':
        records['loop/invalidated/' + scan['scan_id'] + '.json'] = scan
    elif owner in ('state_slot', 'archived_slot'):
        day = dict(slots={at(1)[:13]: dict(scan_id=scan['scan_id'], at=at(1))}, legacy_seen=[])
        if owner == 'state_slot':
            state['days'] = {'2026-10-27': day}
        else:
            records['loop/ledgers/2026-10-27.json'] = day
    else:
        state['participation'] = [history_entry(scan)]
        records['loop/legacy-index.json'] = dict(version=1, legacy=[], participation=[])
    records['loop/state.json'] = state
    result = query(records)
    assert result['coverage']['hourly_scans'] == 1
    assert result['coverage']['unknown_source_scans'] == 0
    assert result['efficiency']['research_slots'] == 9
    assert result['efficiency']['local_calls'] == 4
    assert result['rounds']['counts']['completed'] == 0
    assert result['rounds']['counts']['invalidated' if owner == 'invalidated' else 'unknown'] == 1
    assert result['funnel']['verdicts']['unknown'] == 1
    assert metrics.read_proof(scan) is False


def test_old_new_and_same_format_daily_share_only_tick_cohort(tmp_path):
    old = scan_fixture(tmp_path, scan_id='old-tick', title_prefix='구형 후보 ')
    old['loop_dependencies'].pop('ownership_fingerprint')
    old['loop_dependencies']['review_protocol'] = 'sealed-round-history-v1'
    old.pop('source_review')
    new = scan_fixture(tmp_path, scan_id='new-tick', title_prefix='신형 후보 ')
    daily = scan_fixture(tmp_path, scan_id='daily-origin', title_prefix='개발 후보 ')
    # Exactly the new scan's format, date, slots and genuine Read receipts.
    assert metrics.read_proof(daily) is True
    records = records_for(old, source=None)
    records.update(records_for(new, source=None))
    records.update(records_for(daily, source='nonhourly'))
    records['loop/state.json'] = dict(version=metrics.LOOP_VERSION,
        completed=[dict(scan_id=s['scan_id'], at=at(8, minute=1)) for s in (old, new)],
        participation=[history_entry(s, i) for s in (old, new, daily) for i in range(5)],
        local_history=[history_entry(s, i, local=True) for s in (old, new) for i in range(4)])
    records['loop/legacy-index.json']['participation'] = [history_entry(daily, i) for i in range(5)]
    # Duplicate role projections/history must not count as additional calls.
    records['loop/state.json']['participation'] += copy.deepcopy(records['loop/state.json']['participation'])
    result = query(records)
    assert result['status'] == 'available'
    assert result['coverage']['hourly_scans'] == 2
    assert result['coverage']['nonhourly_scans'] == 1
    assert result['coverage']['excluded_nonhourly_role_calls'] == 9
    assert result['coverage']['unknown_source_scans'] == 0
    assert result['efficiency']['research_slots'] == 18
    assert result['efficiency']['local_calls'] == 8
    assert result['funnel']['validated_retained'] == 2
    assert result['funnel']['verdicts']['unknown'] == 1
    assert result['rounds']['counts']['completed'] == 1
    assert {r['scan_id'] for r in result['rounds']['items']} == {old['scan_id'], new['scan_id']}


@pytest.mark.parametrize('source', ['index', 'state_legacy_seen', 'archived_legacy_seen'])
def test_daily_source_beats_migrated_history_and_calls_need_execution_evidence(tmp_path, source):
    daily = scan_fixture(tmp_path)
    # Legacy role calls have duration/identity, but no newer tick call clocks.
    for agent in daily['agents']:
        agent.pop('call_started_at')
        agent.pop('call_finished_at')
        agent['elapsed_seconds'] = 0
    daily['local_participation'] = []
    daily['agents'][0].update(status='unavailable', provider=None, model=None)
    daily['agents'][1].update(status='reserved')
    daily['agents'][2].update(status='skipped', reason='role_preparation_failed')
    records = records_for(daily, source='nonhourly' if source == 'index' else None)
    imported = [dict(a, scan_id=daily['scan_id']) for a in daily['agents']]
    state = dict(version=metrics.LOOP_VERSION, participation=imported + copy.deepcopy(imported))
    if source != 'index':
        ledger = dict(legacy_seen=[daily['scan_id']], slots={})
        if source == 'state_legacy_seen':
            state['days'] = {'2026-10-27': ledger}
        else:
            records['loop/ledgers/2026-10-27.json'] = ledger
    records['loop/state.json'] = state
    result = query(records)
    assert result['coverage']['nonhourly_scans'] == 1
    assert result['coverage']['excluded_nonhourly_role_calls'] == 2
    assert result['coverage']['unknown_source_scans'] == 0
    assert result['efficiency']['research_slots'] == 0
    assert result['rounds']['items'] == []
    assert result['funnel']['validated_retained'] == 0


@pytest.mark.parametrize('history_slot', [False, True])
def test_daily_call_without_slot_keeps_normalized_slot_and_deduplicates_history(tmp_path, history_slot):
    daily = scan_fixture(tmp_path)
    daily['agents'] = [daily['agents'][-1]]
    daily['local_participation'] = []
    agent = daily['agents'][0]
    agent.pop('slot')
    agent.pop('call_started_at')
    agent.pop('call_finished_at')
    agent['elapsed_seconds'] = 60
    records = records_for(daily, source='nonhourly')
    imported = dict(agent, scan_id=daily['scan_id'])
    expected_slot = at(8)[:13]
    if history_slot:
        imported['slot'] = expected_slot
    records['loop/legacy-index.json']['participation'] = [copy.deepcopy(imported)]
    records['loop/state.json'] = dict(version=metrics.LOOP_VERSION,
        participation=[imported, copy.deepcopy(imported)])

    result = query(records)

    assert result['status'] == 'available'
    assert result['coverage']['nonhourly_scans'] == 1
    assert result['coverage']['excluded_nonhourly_role_calls'] == 1
    assert result['coverage']['hourly_scans'] == 0
    assert result['coverage']['unknown_source_scans'] == 0
    assert result['efficiency']['research_slots'] == 0
    assert result['coverage']['excluded_attempts'] == [dict(
        scan_id=daily['scan_id'], stage_index=8, slot=expected_slot,
        at=agent['started_at'], reason='daily_or_development_source')]


@pytest.mark.parametrize('case', ['unlinked', 'history_without_index', 'malformed_index',
                                  'daily_tick_conflict', 'missing_original', 'missing_ledger'])
def test_unknown_and_conflicting_sources_never_fall_back_to_scan_fields(tmp_path, case):
    scan = scan_fixture(tmp_path)
    records = records_for(scan, source=None)
    state = dict(version=metrics.LOOP_VERSION)
    reason = 'execution_source_unavailable'
    if case in ('history_without_index', 'malformed_index'):
        state['participation'] = [history_entry(scan)]
        reason = 'legacy_index_unavailable_for_history'
        if case == 'malformed_index':
            records['loop/legacy-index.json'] = {'legacy': None}
    elif case == 'daily_tick_conflict':
        records.update(records_for(scan, source='nonhourly'))
        state['round'] = {'report': scan}
        reason = 'conflicting_execution_ownership'
    elif case == 'missing_original':
        records.pop('scans/' + scan['scan_id'] + '.json')
        state['completed'] = [dict(scan_id=scan['scan_id'], at=at(8, minute=1))]
        reason = 'original_scan_unavailable'
    elif case == 'missing_ledger':
        # An empty provenance index alone supplies no execution ownership.
        records['loop/legacy-index.json'] = dict(version=1, legacy=[], participation=[])
    records['loop/state.json'] = state
    result = query(records)
    assert result['status'] == 'partial'
    assert result['coverage']['unknown_source_scans'] == 1
    assert result['coverage']['source_scans'][0]['reason'] == reason
    assert result['coverage']['hourly_scans'] == 0
    assert result['coverage']['excluded_nonhourly_role_calls'] == 0
    assert result['efficiency']['research_slots'] == 0
    assert result['funnel']['validated_retained'] == 0
    assert result['rounds']['completion']['value'] is None


def test_publication_scan_id_excludes_even_unmarked_materialization(tmp_path):
    scan = scan_fixture(tmp_path)
    records = records_for(scan)
    baseline = query(records)
    journal = freeze(scan)
    projection = copy.deepcopy(journal['report'])
    projection.pop('report_window')
    records['scans/' + projection['scan_id'] + '.json'] = projection
    records['loop/publications/2026-10-27.json'] = journal
    records['loop/state.json'] = dict(version=metrics.LOOP_VERSION,
        completed=[dict(scan_id=projection['scan_id'], at=at(9))],
        participation=[history_entry(projection, i) for i in range(5)])
    result = query(records)
    assert result['coverage']['hourly_scans'] == 1
    assert result['coverage']['excluded_materialization_scans'] == 1
    assert result['coverage']['unknown_source_scans'] == 0
    assert result['efficiency'] == baseline['efficiency']
    assert result['rounds'] == baseline['rounds']
    assert result['funnel']['validated_retained'] == 1


def test_source_coverage_and_excluded_calls_use_query_period_and_role(tmp_path):
    hourly = scan_fixture(tmp_path)
    previous_hourly = scan_fixture(tmp_path, scan_id='tick-previous', day=26)
    daily = scan_fixture(tmp_path, scan_id='daily-current')
    historical = scan_fixture(tmp_path, scan_id='daily-previous', day=26)
    records = records_for(hourly)
    records.update(records_for(daily, source='nonhourly'))
    records.update(records_for(historical, source=None))
    records.update(records_for(previous_hourly, source=None))
    records['loop/state.json'] = dict(completed=[dict(scan_id=previous_hourly['scan_id'], at=at(8, 26, 1))])
    records['loop/legacy-index.json']['legacy'].append(dict(scan_id=historical['scan_id'], date=historical['date']))
    day = query(records, role='reviewer')
    week = metrics.aggregate(records, period='7d', date='2026-10-27', now=NOW, role='reviewer')
    assert day['coverage']['hourly_scans'] == 1
    assert week['coverage']['hourly_scans'] == 2
    assert day['coverage']['nonhourly_scans'] == 1
    assert week['coverage']['nonhourly_scans'] == 2
    assert day['coverage']['excluded_nonhourly_role_calls'] == 1
    assert week['coverage']['excluded_nonhourly_role_calls'] == 2
    assert day['efficiency']['research_slots'] == 1
    assert week['efficiency']['research_slots'] == 2
    assert all(s['at'] >= at() for s in day['coverage']['source_scans'])


def test_settled_archived_slot_can_retain_a_call_once_without_role_projection(tmp_path):
    scan = scan_fixture(tmp_path)
    retained = dict(scan['agents'][0], scan_id=scan['scan_id'])
    records = records_for(scan)
    scan['agents'].pop(0)
    records['loop/state.json'] = dict(version=metrics.LOOP_VERSION, participation=[copy.deepcopy(retained)])
    result = query(records)
    assert result['efficiency']['research_slots'] == 9
    assert result['rounds']['stages'][1]['calls'] == 1


def synthetic_workflow_records(scan, run_id, agents, events, marker):
    """New signed synthetic bindings, independent of retained private reports."""
    records = records_for(scan, source=None)
    records['loop/state.json'] = dict(completed=[dict(scan_id=scan['scan_id'], at=at(8, minute=7))])
    proposal = scan['proposals'][0]
    pid = proposal['id']
    key = hashlib.sha256(b'synthetic-legacy-call-fixtures-01').digest()
    authorization_id = marker * 48
    approval = dict(version='improvement-approval-v1', authority='trusted-parent', proposal_id=pid,
        proposal_digest=proposal['digest'], review_digest=C.digest(proposal['review']),
        source_fingerprints=proposal['source_fingerprints'], allowed_edit_files=proposal['candidate']['edit_files'],
        publication=imp.PUBLICATION, instruction='합성 호출 연결의 승인 범위를 확인합니다.',
        issued_at=at(9, minute=13), expires_at=at(1, 28), authorization_id=authorization_id,
        consumption='unconsumed', discovery_fingerprint=C.digest(dict(dependencies=scan['loop_dependencies'],
            scan_id=scan['scan_id'], source_review_binding=scan['source_review_binding'])))
    task = imp._task(proposal, approval)
    claim = dict(version='improvement-claim-v1', proposal_id=pid, proposal_digest=proposal['digest'],
        authorization_id=authorization_id, task_digest=hashlib.sha256(task.encode('utf-8')).hexdigest(),
        claim_id=hashlib.sha256(run_id.encode('utf-8')).hexdigest()[:48], run_id=run_id,
        status='consumed', at=at(10, minute=17))
    prefix = 'workflows/' + run_id + '/'
    records.update({'authority.key': key, 'approvals/' + pid + '.json': sign(approval, key),
        'claims/' + pid + '.json': sign(claim, key),
        'decisions/' + pid + '.json': dict(status='approved', authorization_id=authorization_id,
                                          at=at(9, minute=14)),
        prefix + 'report.json': dict(run_id=run_id, status='passed', finished_at=at(14, minute=47),
            task_sha256=imp.workflow.triage.digest(task), agents=agents, events=events)})
    return records, prefix


def legacy_workflow_seven_fixture(tmp_path):
    scan = scan_fixture(tmp_path, scan_id='synthetic-call-orchid', title_prefix='합성 호출 라운드 가 ')
    identities = [('fixture-planner', 'plan', None), ('fixture-builder', 'implement', 0),
                  ('fixture-builder', 'implement', 1), ('reviewer', 'review', None),
                  ('fixture-builder', 'implement', 0), ('reviewer', 'review', None),
                  ('fixture-git', 'github', None)]
    agents = [dict(role=role, phase=phase, task_id=task, status='passed',
                   provider='claude' if role == 'reviewer' else 'codex', model='synthetic-orchid',
                   response='합성 라운드 결과를 기록했습니다.') for role, phase, task in identities]
    events = [dict(role=role, phase=phase, task_id=task, agent_started=True, time=at(11, minute=3 + 4 * i))
              for i, (role, phase, task) in enumerate(identities)]
    return synthetic_workflow_records(scan, 'synthetic-orchid-workflow', agents, events, 'c')


def legacy_workflow_six_fixture(tmp_path):
    scan = scan_fixture(tmp_path, scan_id='synthetic-call-maple', title_prefix='합성 호출 라운드 나 ')
    identities = [('fixture-designer', 'plan', None), ('fixture-maintainer', 'implement', 0),
                  ('fixture-maintainer', 'implement', 1), ('fixture-maintainer', 'implement', 0),
                  ('reviewer', 'review', None), ('fixture-publisher', 'github', None)]
    agents = [dict(role=role, phase=phase, task_id=task, status='succeeded',
                   provider='claude' if role == 'reviewer' else 'codex', model='synthetic-maple',
                   response='합성 변경 라운드의 완료 결과입니다.') for role, phase, task in identities]
    events = [dict(role=role, phase=phase, task_id=task, agent_started=True, time=at(13, minute=2 + 5 * i))
              for i, (role, phase, task) in enumerate(identities)]
    return synthetic_workflow_records(scan, 'synthetic-maple-workflow', agents, events, 'd')


def test_legacy_workflow_native_rounds_count_seven_six_and_thirteen(tmp_path):
    first, first_prefix = legacy_workflow_seven_fixture(tmp_path)
    second, second_prefix = legacy_workflow_six_fixture(tmp_path)
    for records, prefix, expected in ((first, first_prefix, 7), (second, second_prefix, 6)):
        report = records[prefix + 'report.json']
        assert len(report['agents']) == len(report['events']) == expected
        assert {type(a['task_id']) for a in report['agents']} == {int, type(None)}
        assert {a['task_id'] for a in report['agents']} == {None, 0, 1}
        assert all('call_started_at' not in a and 'elapsed_seconds' not in a for a in report['agents'])
        result = query(records)
        assert result['conversion']['unique_runs'] == 1
        assert result['efficiency']['implementation_slots'] == expected
        assert result['efficiency']['calls_per_merge']['numerator'] == expected
        assert sum(row['success'] for row in result['efficiency']['implementation']) == expected
        for row in result['efficiency']['implementation']:
            assert row['duration_seconds'] == dict(n=0, median=None, p90=None, max=None)
            assert row['claude_estimated_usd'] is None
            assert row['cost_known_calls'] == 0
            for field in metrics.TOKEN_FIELDS:
                assert row['tokens'][field] == dict(known_sum=None, known_calls=0, unknown_calls=row['slots'])
    # Equal terminal payloads are distinct calls when the observed starts differ.
    assert first[first_prefix + 'report.json']['agents'][1] == first[first_prefix + 'report.json']['agents'][4]
    assert second[second_prefix + 'report.json']['agents'][1] == second[second_prefix + 'report.json']['agents'][3]
    combined = dict(first)
    combined.update(second)
    combined['loop/state.json'] = dict(completed=(first['loop/state.json']['completed'] +
                                                 second['loop/state.json']['completed']))
    result = query(combined)
    assert result['conversion']['unique_runs'] == 2
    assert result['efficiency']['implementation_slots'] == 13
    assert result['efficiency']['calls_per_merge']['numerator'] == 13
    assert sum(row['success'] for row in result['efficiency']['implementation']) == 13


@pytest.mark.parametrize('fixture,expected', [(legacy_workflow_seven_fixture, 7), (legacy_workflow_six_fixture, 6)])
def test_legacy_workflow_orphan_starts_and_duplicate_transmission_do_not_add_success(tmp_path, fixture, expected):
    records, prefix = fixture(tmp_path)
    report = records[prefix + 'report.json']
    baseline = query(records)['efficiency']
    # A retransmitted start is one observation; additional starts have no result.
    report['events'].insert(2, copy.deepcopy(report['events'][1]))
    report['events'].extend([dict(report['events'][1], time=at(14, minute=1)),
                             dict(role='unreturned-worker', phase='implement', task_id=1,
                                  agent_started=True, time=at(14, minute=2))])
    report['agents'].append(copy.deepcopy(report['agents'][-1]))
    result = query(records)
    assert result['efficiency']['implementation_slots'] == expected
    assert result['efficiency']['calls_per_merge']['numerator'] == expected
    assert result['efficiency']['implementation'] == baseline['implementation']


@pytest.mark.parametrize('status', ['failed', 'unavailable', 'running', 'reserved', 'not_called', 'skipped', None])
def test_legacy_workflow_requires_terminal_success_without_changing_later_rounds(tmp_path, status):
    records, prefix = legacy_workflow_seven_fixture(tmp_path)
    report = records[prefix + 'report.json']
    report['agents'][1]['status'] = status
    result = query(records)
    assert result['efficiency']['implementation_slots'] == 6
    assert result['efficiency']['calls_per_merge']['numerator'] == 6
    assert sum(row['success'] for row in result['efficiency']['implementation']) == 6
    entries = metrics.workflow_entries(report, report['run_id'])
    assert entries[4]['call_started_at'] == report['events'][4]['time']
    assert not metrics.called(entries[1])
    assert entries[1]['call_finished_at'] is None


@pytest.mark.parametrize('side', ['agent', 'event'])
@pytest.mark.parametrize('change', [dict(task_id=True), dict(task_id=False), dict(task_id=0.0),
    dict(task_id=[]), dict(task_id={}), dict(task_id='0'), dict(task_id=None),
    dict(role='other-fixture-role'), dict(phase='other-fixture-phase'), dict(run_id='other-fixture-run')])
def test_legacy_workflow_never_joins_different_or_malformed_identity(tmp_path, side, change):
    records, prefix = legacy_workflow_six_fixture(tmp_path)
    report = records[prefix + 'report.json']
    # task 1 occurs only once, so a wrong identity cannot match another round.
    target = report['agents' if side == 'agent' else 'events'][2]
    target.update(change)
    result = query(records)
    assert result['efficiency']['implementation_slots'] == 5
    assert result['efficiency']['calls_per_merge']['numerator'] == 5


@pytest.mark.parametrize('change', [dict(time='invalid-clock'), dict(agent_started=False)])
def test_legacy_workflow_needs_a_valid_observed_start(tmp_path, change):
    records, prefix = legacy_workflow_six_fixture(tmp_path)
    records[prefix + 'report.json']['events'][2].update(change)
    result = query(records)
    assert result['efficiency']['implementation_slots'] == 5
    assert result['efficiency']['calls_per_merge']['numerator'] == 5


@pytest.mark.parametrize('side', ['agents', 'events'])
def test_legacy_workflow_run_boundaries_and_absent_task_are_not_null(tmp_path, side):
    records, prefix = legacy_workflow_six_fixture(tmp_path)
    report = records[prefix + 'report.json']
    report[side][0].pop('task_id')
    assert query(records)['efficiency']['implementation_slots'] == 5
    report[side][0]['task_id'] = None
    report['run_id'] = 'unrelated-synthetic-workflow'
    assert query(records)['efficiency']['implementation_slots'] == 0


def test_legacy_workflow_missing_result_and_explicit_not_called_stay_unobserved(tmp_path):
    records, prefix = legacy_workflow_six_fixture(tmp_path)
    report = records[prefix + 'report.json']
    report['agents'].pop(2)
    report['agents'][0]['called'] = False
    result = query(records)
    assert result['efficiency']['implementation_slots'] == 4
    assert result['efficiency']['calls_per_merge']['numerator'] == 4
    assert sum(row['success'] for row in result['efficiency']['implementation']) == 4


def test_legacy_workflow_modern_calls_failures_filters_and_observed_telemetry(tmp_path):
    records, prefix = legacy_workflow_seven_fixture(tmp_path)
    report = records[prefix + 'report.json']
    # Aggregate role filters also require the existing proposal-origin cohort.
    origin = C.SPECIALIST_ROLES[0]
    for name, record in records.items():
        if name.startswith('scans/'):
            record['proposals'][0]['origin_role'] = origin
        elif name.startswith('proposals/'):
            record['proposal']['origin_role'] = origin
    for record in report['agents'] + report['events']:
        if record['role'] == 'fixture-builder':
            record['role'] = origin
    # A modern result for the same identity is interleaved with legacy rounds.
    modern = dict(report['agents'][1], started_at=at(11, minute=10), call_started_at=at(11, minute=11),
                  finished_at=at(11, minute=13), call_finished_at=at(11, minute=12), status='failed')
    report['agents'].insert(2, modern)
    report['events'].insert(2, dict(report['events'][1], time=at(11, minute=11)))
    # Observed telemetry stays observed; no completion clock is inferred for legacy results.
    report['agents'][4].update(usage=dict(input_tokens=17), cost=0.25, cost_status='cli_estimated_usd')
    entries = metrics.workflow_entries(report, report['run_id'])
    assert entries[1]['call_started_at'] == at(11, minute=7)
    assert entries[2]['call_started_at'] == at(11, minute=11)
    assert entries[5]['call_started_at'] == at(11, minute=19)
    result = query(records)
    assert result['efficiency']['implementation_slots'] == 8
    assert result['efficiency']['calls_per_merge']['numerator'] == 8
    assert sum(row['failed'] for row in result['efficiency']['implementation']) == 1
    assert sum(row['success'] for row in result['efficiency']['implementation']) == 7
    assert sum(row['duration_seconds']['n'] for row in result['efficiency']['implementation']) == 1
    assert next(row for row in result['efficiency']['implementation'] if row['duration_seconds']['n'])['duration_seconds']['median'] == 60
    reviewer_calls, reviewer_rows = metrics.efficiency(entries, (metrics.timestamp(at()), NOW), 'reviewer')
    assert len(reviewer_calls) == 2
    assert reviewer_rows[0]['tokens']['input_tokens'] == dict(known_sum=17, known_calls=1, unknown_calls=1)
    assert reviewer_rows[0]['claude_estimated_usd'] == 0.25
    assert reviewer_rows[0]['cost_known_calls'] == 1
    assert reviewer_rows[0]['duration_seconds']['n'] == 0
    assert query(records, role='reviewer')['efficiency']['implementation_slots'] == 0
    author = query(records, role=origin)['efficiency']
    assert author['implementation_slots'] == author['calls_per_merge']['numerator'] == 4
    # The period is half open and uses each call's observed admission clock.
    cutoff = metrics.aggregate(records, period='day', date='2026-10-27',
                               now=metrics.timestamp(at(11, minute=19)))
    assert cutoff['efficiency']['implementation_slots'] == 5
    assert cutoff['efficiency']['calls_per_merge']['numerator'] == 5
    previous = metrics.aggregate(records, period='day', date='2026-10-26', now=NOW)
    assert previous['efficiency']['implementation_slots'] == 0
    # Repeated transmissions with explicit modern clocks are the same call.
    report['agents'].insert(3, copy.deepcopy(modern))
    assert query(records)['efficiency'] == result['efficiency']


def test_legacy_workflow_orphans_cannot_cross_an_explicit_modern_round(tmp_path):
    records, prefix = legacy_workflow_six_fixture(tmp_path)
    report = records[prefix + 'report.json']
    modern = report['agents'][1]
    modern.update(started_at=report['events'][1]['time'], finished_at=at(13, minute=8))
    report['events'].insert(1, dict(report['events'][1], time=at(13, minute=5)))
    entries = metrics.workflow_entries(report, report['run_id'])
    assert entries[3]['call_started_at'] == at(13, minute=17)
    assert query(records)['efficiency']['implementation_slots'] == 6


@pytest.mark.parametrize('status', ['passed', 'failed'])
def test_legacy_workflow_modern_result_needs_no_start_event(tmp_path, status):
    records, prefix = legacy_workflow_six_fixture(tmp_path)
    report = records[prefix + 'report.json']
    # The same identity's later legacy start must remain available to its result.
    report['agents'].insert(2, dict(report['agents'][1], status=status,
        call_started_at=at(13, minute=10), call_finished_at=at(13, minute=11)))
    entries = metrics.workflow_entries(report, report['run_id'])
    assert entries[4]['call_started_at'] == at(13, minute=17)
    result = query(records)['efficiency']
    assert result['implementation_slots'] == result['calls_per_merge']['numerator'] == 7
    assert sum(row['success'] for row in result['implementation']) == (7 if status == 'passed' else 6)
    assert sum(row['failed'] for row in result['implementation']) == (1 if status == 'failed' else 0)
    assert sum(row['duration_seconds']['n'] for row in result['implementation']) == 1


def write_private(path, value, *, root=None):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root is not None:
        # parents=True applies mode only to the leaf directory. Keep every
        # fixture directory private without touching parents outside root.
        relative_parent = path.parent.relative_to(root)
        directory = root
        directory.chmod(0o700)
        for part in relative_parent.parts:
            directory = directory / part
            directory.chmod(0o700)
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode('utf-8'))
    path.chmod(0o600)


def inventory(root):
    result = {}
    for path in [root] + sorted(root.rglob('*')):
        info = path.lstat()
        result[str(path.relative_to(root))] = (info.st_mode, info.st_ino,
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None)
    return result


def test_repeat_read_only_bytes_modes_locks_and_zero_external_actions(tmp_path, monkeypatch):
    store = tmp_path / 'store'
    store.mkdir(mode=0o700)
    scan = scan_fixture(tmp_path, count=0)
    for name, value in records_for(scan).items():
        write_private(store / name, value, root=store)
    legacy_index = dict(version=1, legacy=[], participation=[])
    write_private(store / 'loop/legacy-index.json', legacy_index, root=store)
    for name in ('.lock', 'loop/.publication-lock', 'loop/state.json'):
        write_private(store / name, {} if name.endswith('.json') else b'', root=store)
    # Unrelated archive/report bytes must remain untouched too.
    write_private(store / 'archive/fixed.json', {'status': 'failed'}, root=store)
    write_private(store / 'days/2026-10-27.json', {'status': 'partial'}, root=store)
    before = inventory(store)
    def forbidden(*args, **kwargs):
        pytest.fail('metrics crossed an offline read-only boundary')
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    for method in ('prepare', 'write', 'write_bytes', 'lock', 'key'):
        monkeypatch.setattr(imp.Store, method, forbidden)
    monkeypatch.setattr(imp, 'discover', forbidden)
    first, errors = metrics.capture_records(store)
    second, other_errors = metrics.capture_records(store)
    assert first['loop/legacy-index.json'] == legacy_index
    assert first['loop/ledgers/2026-10-27.json']['slots']
    assert query(first) == query(second)
    assert not errors and not other_errors
    assert inventory(store) == before
    assert metrics.probe(store / 'absent.lock') is None
    assert not (store / 'absent.lock').exists()


@pytest.mark.parametrize('name', ['loop/legacy-index.json', 'loop/ledgers/2026-10-27.json'])
def test_provenance_capture_keeps_existing_record_bounds_and_read_only_failure(tmp_path, monkeypatch, name):
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    write_private(root / name, {'payload': 'x' * 64}, root=root)
    before = inventory(root)
    monkeypatch.setattr(metrics, 'MAX_RECORD', 32)
    records, errors = metrics.capture_records(root)
    assert name not in records
    assert errors == [dict(record=name, reason='record_unavailable')]
    assert inventory(root) == before


def test_nonblocking_contention_never_waits_or_creates_files(tmp_path):
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    lock = root / '.lock'
    write_private(lock, b'')
    with lock.open('rb') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        start = time.monotonic()
        with pytest.raises(metrics.Unavailable, match='lock_busy'):
            metrics.capture_records(root)
        assert time.monotonic() - start < 1
    assert sorted(p.name for p in root.iterdir()) == ['.lock']


@pytest.mark.parametrize('damage', ['symlink', 'hardlink', 'mode', 'fifo', 'replacement', 'inventory', 'ancestor'])
def test_unsafe_or_changed_attachments_are_unavailable(tmp_path, damage):
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    file = root / 'record.json'
    write_private(file, {})
    if damage == 'symlink':
        file.unlink()
        file.symlink_to(tmp_path / 'not-approved')
    elif damage == 'hardlink':
        os.link(file, root / 'other.json')
    elif damage == 'mode':
        file.chmod(0o644)
    elif damage == 'fifo':
        file.unlink()
        os.mkfifo(str(file), 0o600)
    elif damage == 'ancestor':
        alias = tmp_path / 'alias'
        alias.symlink_to(root, target_is_directory=True)
        with pytest.raises((OSError, metrics.Unavailable)):
            with metrics.Capture(alias):
                pytest.fail('symlink ancestor accepted')
        return
    with pytest.raises((OSError, metrics.Unavailable)):
        with metrics.Capture(root) as reader:
            reader.read('record.json')
            if damage == 'replacement':
                file.unlink()
                write_private(file, {'new': True})
            elif damage == 'inventory':
                write_private(root / 'new.json', {})
            reader.verify()


def test_bare_make_returns_help_without_running_python(tmp_path):
    makefile = Path(__file__).resolve().parents[1] / 'Makefile'
    (tmp_path / 'Makefile').write_bytes(makefile.read_bytes())
    python_stub = tmp_path / 'python-must-not-run'
    python_stub.write_text('#!/bin/sh\nexit 97\n', encoding='utf-8')
    python_stub.chmod(0o700)
    env = dict(os.environ, PYTHON=str(python_stub), MAKEFLAGS='', GNUMAKEFLAGS='',
               MFLAGS='', MAKEFILES='', MAKEOVERRIDES='')
    result = subprocess.run(['make'], cwd=tmp_path, env=env, capture_output=True,
                            text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'doctor          Check the offline harness environment' in result.stdout
    assert 'improvement-metrics' in result.stdout
    assert 'Override the interpreter with: make check PYTHON=/path/to/python' in result.stdout
