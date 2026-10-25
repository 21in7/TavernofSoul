"""Unexecuted synthetic regression specifications, never live observation.

Reuse Lab's actual tick -> private Store -> reopened state boundary. Its offline
guard forbids subprocess, providers, credentials, network and workflow execution.
Documentation impact: ADR0025 and the approved design/operating documents define
snapshot completion, current freshness, participation and migration separately.
"""

import copy
import datetime as dt
import json
import os
from types import SimpleNamespace

import pytest

from harness import improvement_snapshot as sealed
from harness.test_improvement_loop import (
    lab, offline, FILES, START, SECRET, RAW, PowerLoss, forbidden, draft,
    loop, imp, contract, local_model,
)


def sources(lab):
    return imp.snapshot_sources(FILES, lab.discovery['limits'], lab.selected)


def instruction(lab, record):
    path = lab.root.parent / 'synthetic-instruction.txt'
    path.write_text('제안 ' + record['id'] + ' 승인', encoding='utf-8')
    path.chmod(0o600)
    return path


def test_each_tick_source_bytes_mode_and_existence_drift_keeps_pinned_nine_stages(lab):
    lab.expected_sources = sources(lab)
    original = copy.deepcopy(lab.expected_sources)
    lab.tick(0)
    scan_id = lab.state()['round']['report']['scan_id']
    seal = lab.state()['round']['snapshot']
    actual_local = lab.local

    def pinned_local(role, paths, snapshot, **options):
        assert snapshot == original
        return actual_local(role, paths, snapshot, **options)

    for hour in range(1, 9):
        path = lab.root / FILES[0]
        path.write_text('changed_{} = 1\n'.format(hour), encoding='utf-8')
        path.chmod(0o640 if hour % 2 else 0o600)
        shared = lab.root / FILES[4]
        if hour % 2:
            shared.unlink()
        else:
            shared.write_bytes(original[FILES[4]]['content'])
        lab.store = imp.Store(lab.selected)
        lab.tick(hour, local_runner=pinned_local)
        assert lab.state()['round']['snapshot'] == seal
        assert lab.state()['round']['report']['scan_id'] == scan_id
        assert lab.state()['stage_index'] == hour + 1
    report = lab.state()['round']['report']
    assert report['review_complete'] is True and report['current_fresh_at_last_tick'] is False
    assert len(lab.events) == 9 and lab.ledger()['calls'] == 9
    assert report['source_fingerprints'] == contract.fingerprint_sources(original)
    assert report['loop_dependencies']['source_fingerprints'] == report['source_fingerprints']
    record = report['proposals'][0]
    with pytest.raises(imp.ImprovementError):
        imp.approve(record['id'], instruction(lab, record), now=lab.clock(), selected=lab.selected)
    assert not lab.store.exists('approvals/' + record['id'] + '.json')
    lab.expected_sources = sources(lab)
    lab.tick(9)
    morning = lab.store.read('days/2026-10-15.json')
    assert morning['proposals'] == [] and not morning['review_complete']
    assert all(a['status'] == 'succeeded' for a in morning['agents'])
    assert '고정 소스 검토는 완료' in morning['summary']
    assert lab.state()['round']['snapshot']['bank'] != seal['bank']
    assert lab.state()['round']['report']['source_fingerprints'] == contract.fingerprint_sources(lab.expected_sources)
    # Shortening the next pinned source advances its preserved cursor safely.
    assert lab.state()['cursors']['coordinator']['line'] == 1


@pytest.mark.parametrize('change', ['bytes', 'mode', 'missing'])
def test_signed_approval_and_execute_still_reject_live_source_drift(lab, change):
    lab.hours()
    record = lab.state()['round']['report']['proposals'][0]
    imp.approve(record['id'], instruction(lab, record), now=lab.clock(), selected=lab.selected)
    path = lab.root / FILES[0]
    if change == 'bytes':
        path.write_text('different = 1\n', encoding='utf-8')
    elif change == 'mode':
        path.chmod(0o640)
    else:
        path.unlink()
    with pytest.raises(imp.ImprovementError):
        imp.execute(record['id'], now=lab.clock(), selected=lab.selected)
    assert not lab.store.exists('claims/' + record['id'] + '.json')
    assert len(lab.events) == 9


@pytest.mark.parametrize('damage', ['oversize', 'utf8', 'symlink'])
def test_unreadable_live_sources_do_not_block_valid_sealed_review_or_grant_freshness(lab, damage):
    lab.expected_sources = sources(lab)
    lab.tick(0)
    seal = lab.state()['round']['snapshot']
    path = lab.root / FILES[0]
    if damage == 'oversize':
        path.write_bytes(b'x' * (lab.discovery['limits']['max_file_bytes'] + 1))
    elif damage == 'utf8':
        path.write_bytes(b'\xff')
    else:
        path.unlink()
        path.symlink_to(lab.root / FILES[1])
    lab.store = imp.Store(lab.selected)
    lab.hours(start=1, count=8)
    report = lab.state()['round']['report']
    assert lab.state()['stage_index'] == 9 and lab.state()['round']['snapshot'] == seal
    assert report['review_complete'] and not report['current_fresh_at_last_tick']
    assert len(lab.events) == 9 and lab.ledger()['calls'] == 9
    record = report['proposals'][0]
    with pytest.raises((ValueError, OSError)):
        imp.approve(record['id'], instruction(lab, record), now=lab.clock(), selected=lab.selected)
    assert not lab.store.exists('approvals/' + record['id'] + '.json')
    # A fresh round needs a valid current capture, so it must not reuse this seal.
    result = lab.tick(9, runner=forbidden, local_runner=forbidden, quota_transport=forbidden)
    assert result['status'] == 'paused' and len(lab.events) == 9
    morning = lab.store.read('web/2026-10-15.json')
    assert morning['proposals'] == [] and morning['counts']['eligible'] == 0
    assert all(a['status'] == 'succeeded' for a in morning['agents'])


def test_unreadable_live_source_exception_does_not_relax_control_invalidation(lab):
    lab.tick(0)
    old_id = lab.state()['round']['report']['scan_id']
    (lab.root / FILES[0]).write_bytes(b'\xff')
    lab.config['daily_budget_usd'] = .9
    lab.save_loop()
    result = lab.tick(1, runner=forbidden, local_runner=forbidden, quota_transport=forbidden)
    assert result['status'] == 'paused' and result['reason'] == 'current_sources_unavailable'
    assert lab.state()['round'] is None and lab.state()['stage_index'] == 0
    assert lab.store.exists('loop/invalidated/' + old_id + '.json')
    assert len(lab.events) == 1 and lab.ledger()['calls'] == 1


@pytest.mark.parametrize('failure,reason', [
    ('duplicate', 'candidate_edit_files_duplicate'), ('empty', 'empty_draft'),
    ('exception', 'timeout'),
])
def test_specialists_produce_independent_evidence_after_failed_optional_local(lab, failure, reason):
    def fail_local(user, candidates):
        if failure == 'exception':
            raise TimeoutError(SECRET + RAW)
        if failure == 'empty':
            return []
        candidates[0]['edit_files'] *= 2
        return candidates

    def independent(role, result, response, options):
        if role != 'reviewer':
            path = imp.role_scope(role, FILES, lab.discovery)[0]
            assert response == {'candidates': []}
            response = {'candidates': [draft(path, 1, 1, '독립 소스 점검 ' + role)]}
            result['response'] = json.dumps(response, ensure_ascii=False)
        return result

    lab.local_transform, lab.cloud_transform = fail_local, independent
    lab.hours()
    report = lab.state()['round']['report']
    assert len(lab.events) == 9 and lab.ledger()['calls'] == 9
    assert len(report['proposals']) == 4 and report['review_complete']
    assert all(a['status'] == 'succeeded' for a in report['agents'])
    assert all(a['status'] == 'failed' and a['reason'] == reason
               for a in report['local_participation'])
    assert all('Independently inspect' in r['prompt'] for r in lab.cloud_requests[:-1])
    assert 'Independently evaluate coverage' in lab.cloud_requests[-1]['prompt']
    assert SECRET not in json.dumps(report) and RAW not in json.dumps(report)


def test_empty_pool_reviewer_receives_failed_coverage_and_cannot_mark_whole_round_scanned(lab):
    lab.local_transform = lambda user, candidates: []

    def fail_parser(role, result, response, options):
        if role == 'parser':
            result['response'] = 'invalid JSON ' + SECRET
        return result

    lab.cloud_transform = fail_parser
    lab.hours()
    report = lab.state()['round']['report']
    assert len(lab.events) == 9 and report['review_complete']
    assert report['proposals'] == [] and report['status'] == 'partial'
    prompt = lab.cloud_requests[-1]['prompt']
    assert '"role":"parser","status":"failed"' in prompt
    lab.tick(9)
    public = lab.store.read('web/2026-10-15.json')
    assert public['status'] == 'partial' and public['agents'][2]['status'] == 'failed'


def test_newer_successful_owner_attempt_is_distinct_from_selected_completed_review(lab):
    lab.hours(start=8)
    completed_id = lab.state()['round']['report']['scan_id']
    lab.hours(start=17, count=2)  # successful coordinator, later review still pending
    later_id = lab.state()['round']['report']['scan_id']
    lab.tick(33)
    report = lab.store.read('days/2026-10-16.json')
    assert report['reviewed_scan_id'] == completed_id != later_id
    assert all(a['status'] == 'succeeded' for a in report['agents'])
    assert report['status'] == 'partial' and report['review_complete']
    assert '별도 회차 참여' in report['summary']


@pytest.mark.parametrize('damage', [
    'missing', 'tamper', 'manifest', 'oversize', 'permission', 'directory_permission',
    'owner', 'symlink', 'hardlink', 'bank_symlink',
])
def test_corrupt_or_unsafe_snapshot_is_no_call_after_store_reopen(lab, monkeypatch, damage):
    lab.tick(0)
    state = lab.state()
    prefix = 'loop/snapshots/' + state['round']['snapshot']['bank']
    record = lab.store.path(prefix + '/0.json')
    if damage == 'missing':
        record.unlink()
    elif damage == 'tamper':
        value = lab.store.read(prefix + '/0.json')
        value['content'] = 'eAo='
        lab.store.write(prefix + '/0.json', value)
    elif damage == 'manifest':
        value = lab.store.read(prefix + '/manifest.json')
        value['paths'].reverse()
        lab.store.write(prefix + '/manifest.json', value)
    elif damage == 'oversize':
        record.write_bytes(b'x' * (imp.MAX_PRIVATE_BYTES + 1))
    elif damage == 'permission':
        record.chmod(0o644)
    elif damage == 'directory_permission':
        record.parent.chmod(0o755)
    elif damage == 'symlink':
        record.unlink()
        record.symlink_to(lab.root / FILES[0])
    elif damage == 'hardlink':
        target = record.with_name('linked.json')
        os.link(str(record), str(target))
    elif damage == 'bank_symlink':
        bank = record.parent
        moved = bank.with_name('moved-bank')
        bank.rename(moved)
        bank.symlink_to(moved, target_is_directory=True)
    else:
        actual = os.fstat
        inode = record.stat().st_ino

        def foreign_owner(fd):
            info = actual(fd)
            if info.st_ino != inode:
                return info
            return SimpleNamespace(st_mode=info.st_mode, st_uid=info.st_uid + 1,
                                   st_nlink=info.st_nlink, st_size=info.st_size,
                                   st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns)

        monkeypatch.setattr(os, 'fstat', foreign_owner)
    lab.store = imp.Store(lab.selected)
    result = lab.tick(1, runner=forbidden, local_runner=forbidden, quota_transport=forbidden)
    assert result['status'] == 'paused'
    assert result['reason'].startswith('snapshot_')
    assert lab.ledger()['calls'] == 1 and lab.state()['stage_index'] == 1
    assert len(lab.events) == 1
    assert lab.tick(1, 1)['reason'] == 'slot_already_claimed'


@pytest.mark.parametrize('boundary', ['payload', 'manifest', 'state'])
def test_snapshot_atomic_publication_crash_never_admits_partial_bank(lab, monkeypatch, boundary):
    actual = imp.Store.write

    def crash(store, name, value):
        match = ((boundary == 'payload' and name.endswith('/0.json')) or
                 (boundary == 'manifest' and name.endswith('/manifest.json')) or
                 (boundary == 'state' and name == loop.STATE_FILE and value.get('round') is not None))
        if match:
            raise PowerLoss()
        return actual(store, name, value)

    with monkeypatch.context() as patch:
        patch.setattr(imp.Store, 'write', crash)
        with pytest.raises(PowerLoss):
            lab.tick(0)
    assert lab.events == [] and lab.ledger()['calls'] == 0
    lab.store = imp.Store(lab.selected)
    assert lab.tick(0, 1)['reason'] == 'slot_already_claimed'
    lab.tick(1)
    assert lab.events == [('local_explorer', 'coordinator')]
    assert lab.state()['stage_index'] == 1


@pytest.mark.parametrize('size', ['file', 'total'])
def test_snapshot_size_bound_fails_before_model_admission(lab, size):
    # Direct publication tests the persistent boundary independently of the live
    # source reader's identical bounds; all payloads remain synthetic.
    snapshot = sources(lab)
    limits = dict(lab.discovery['limits'])
    if size == 'file':
        snapshot[FILES[0]]['content'] = b'x' * (limits['max_file_bytes'] + 1)
    else:
        limits['max_source_bytes'] = 1
    with lab.store.lock(), pytest.raises(sealed.SnapshotError):
        sealed.publish(lab.store, '123456789-abcdef', FILES, snapshot, limits)
    assert lab.events == []


@pytest.mark.parametrize('staging', ['partial', 'permission', 'symlink', 'hardlink', 'oversize'])
def test_snapshot_fixed_staging_bounds_crash_recovery_and_preserves_unsafe_files(lab, staging):
    prefix = 'loop/snapshots/a'
    lab.store.write(prefix + '/.0.json.pending', {'partial': True})
    pending = lab.store.path(prefix + '/.0.json.pending')
    if staging == 'partial':
        pending.write_bytes(b'{"partial":')
    elif staging == 'permission':
        pending.chmod(0o644)
    elif staging == 'symlink':
        pending.unlink()
        pending.symlink_to(lab.root / FILES[0])
    elif staging == 'hardlink':
        os.link(str(pending), str(pending.with_name('untrusted-alias')))
    else:
        pending.write_bytes(b'x' * (imp.MAX_PRIVATE_BYTES + 1))
    original = pending.lstat()
    if staging == 'partial':
        lab.tick(0)
        assert len(lab.events) == 1 and not pending.exists()
        assert lab.store.read(prefix + '/0.json')['path'] == FILES[0]
    else:
        result = lab.tick(0, runner=forbidden, local_runner=forbidden, quota_transport=forbidden)
        assert result['status'] == 'paused' and result['reason'] == 'snapshot_unavailable'
        assert lab.events == [] and lab.ledger()['calls'] == 0
        assert pending.lstat().st_ino == original.st_ino


def test_latest_failed_attempts_visible_while_current_completed_pool_keeps_its_provenance(lab):
    lab.hours(start=8)
    successful = lab.state()['round']['report']['scan_id']

    def fail(role, result, response, options):
        if role in ('coordinator', 'reviewer'):
            result['response'] = 'invalid JSON ' + RAW + SECRET
        return result

    lab.cloud_transform = fail
    lab.hours(start=17)
    failed = lab.state()['round']['report']['scan_id']
    before = copy.deepcopy(lab.state()['participation'])
    assert len(before) == 10
    lab.store = imp.Store(lab.selected)
    assert lab.tick(25, 1)['reason'] == 'slot_already_claimed'
    assert lab.state()['participation'] == before
    lab.tick(33)
    report = lab.store.read('days/2026-10-16.json')
    assert report['reviewed_scan_id'] == successful and report['reviewed_scan_id'] != failed
    assert report['reviewed_agents'][0]['status'] == 'succeeded'
    assert report['agents'][0]['status'] == report['agents'][-1]['status'] == 'failed'
    assert report['status'] == 'partial' and report['review_complete']
    public = lab.store.read('web/2026-10-16.json')
    contract.validate_web_report(public)
    assert public['counts']['candidates'] == 4
    # Latest failed participation does not revoke the original verified review.
    assert public['counts']['eligible'] == 4
    assert public['agents'][-1]['status'] == 'failed'
    assert all(imp._eligible(lab.store, r['id']) == r for r in report['proposals'])
    for sensitive in ('local_participation', 'loop_dependencies', 'cost', RAW, SECRET,
                      'snapshot', 'diagnostic', str(lab.root)):
        assert sensitive not in json.dumps(public)


def test_cloud_reservation_crash_history_survives_control_invalidation(lab):
    lab.tick(0)

    def crash(*args, **kwargs):
        raise PowerLoss()

    with pytest.raises(PowerLoss):
        lab.tick(1, runner=crash)
    assert lab.state()['participation'][0]['status'] == 'reserved'
    lab.config['daily_budget_usd'] = .9
    lab.save_loop()
    lab.store = imp.Store(lab.selected)
    lab.tick(9)
    report = lab.store.read('days/2026-10-15.json')
    assert report['agents'][0]['status'] == 'failed'
    assert report['agents'][0]['started_at'] == (START + dt.timedelta(hours=1)).isoformat()
    assert report['proposals'] == [] and not report['review_complete']
    assert lab.state()['participation'][0]['status'] == 'failed'


def test_history_half_open_boundary_and_bounded_exact_identity(lab):
    # Engine attempts at previous 09:00 are included; today's 09:00 model is
    # after freeze and belongs to the next window. Older activity is excluded.
    lab.hours(start=8)
    lab.tick(33)
    report = lab.store.read('days/2026-10-16.json')
    assert report['agents'][0]['started_at'] == (START + dt.timedelta(hours=9)).isoformat()
    assert report['agents'][-1]['started_at'] == (START + dt.timedelta(hours=16)).isoformat()
    frozen = lab.store.path('web/2026-10-16.json').read_bytes()
    state = lab.state()
    for offset in range(loop.HISTORY_LIMIT + 20):
        stamp = START + dt.timedelta(days=3, hours=offset)
        agent = {'provider': 'codex', 'model': 'synthetic', 'status': 'succeeded',
                 'started_at': stamp.isoformat(), 'finished_at': stamp.isoformat()}
        scan_id = '{}-abcdef'.format(100000000 + offset)
        loop._remember(state, scan_id, 'coordinator', agent)
        loop._remember(state, scan_id, 'coordinator', agent)
    assert len(state['participation']) == loop.HISTORY_LIMIT
    assert len({loop._history_identity(e) for e in state['participation']}) == loop.HISTORY_LIMIT
    assert lab.store.path('web/2026-10-16.json').read_bytes() == frozen


def test_one_time_legacy_index_never_rescans_and_never_invents_missing_timestamps(lab, monkeypatch):
    lab.tick(0)
    actual = os.scandir
    scans_inode = lab.store.path('scans').stat().st_ino

    def no_scan(path):
        if isinstance(path, int) and os.fstat(path).st_ino == scans_inode:
            pytest.fail('recurring scan of private history directory')
        return actual(path)

    with monkeypatch.context() as patch:
        patch.setattr(os, 'scandir', no_scan)
        lab.store = imp.Store(lab.selected)
        lab.tick(1)
        assert len(lab.state()['participation']) == 1
        report = copy.deepcopy(lab.state()['round']['report'])
        report['scan_id'] = '123456789-abcdef'
        report['agents'][0].pop('started_at')
        report['agents'][0].pop('finished_at')
        state = loop._new_state()
        loop._import_participation(state, report)
        assert state['participation'] == []


def test_post_migration_exact_legacy_day_pointer_adds_participation_once(lab):
    lab.tick(0)
    scan_id = '123456789-abcdef'
    stamp = (START + dt.timedelta(hours=2)).isoformat()
    spec = lab.models['roles']['downloader']
    report = {'scan_id': scan_id, 'date': START.date().isoformat(),
              'review_complete': True, 'agents': [
                  {'role': 'downloader', 'provider': spec['provider'], 'model': spec['model'],
                   'status': 'succeeded', 'started_at': stamp, 'finished_at': stamp}]}
    lab.store.write('scans/' + scan_id + '.json', report)
    # Only the exact pointer, not another directory discovery, admits carry-in.
    lab.store.write('days/2026-10-15.json', report)
    lab.tick(3)
    attempts = [e for e in lab.state()['participation'] if e['scan_id'] == scan_id]
    assert len(attempts) == 1 and attempts[0]['role'] == 'downloader'
    count = lab.ledger()['calls']
    lab.store = imp.Store(lab.selected)
    lab.tick(4)
    assert [e for e in lab.state()['participation'] if e['scan_id'] == scan_id] == attempts
    assert lab.ledger()['calls'] == count + 1


def test_legacy_directory_migration_overflow_is_bounded_no_call(lab, monkeypatch):
    lab.store.write('scans/ignored', {})
    inode = lab.store.path('scans').stat().st_ino
    actual = os.scandir

    class ExcessEntries:
        def __enter__(self):
            return iter(SimpleNamespace(name='ignored-{}'.format(i)) for i in range(4097))

        def __exit__(self, *args):
            return False

    def bounded_fixture(path):
        if isinstance(path, int) and os.fstat(path).st_ino == inode:
            return ExcessEntries()
        return actual(path)

    with monkeypatch.context() as patch:
        patch.setattr(os, 'scandir', bounded_fixture)
        result = lab.tick(0, runner=forbidden, local_runner=forbidden, quota_transport=forbidden)
        assert result['status'] == 'paused' and result['reason'] == 'legacy_history_unbounded'
        assert lab.events == [] and not lab.store.exists(loop.LEGACY_INDEX)


@pytest.mark.parametrize('change', ['scope_mode', 'ownership', 'provider', 'model', 'protocol'])
def test_control_boundaries_revalidate_and_retire_active_progress(lab, monkeypatch, change):
    lab.hours(count=2)
    old = lab.state()['round']['report']['scan_id']
    attempts = copy.deepcopy(lab.state()['participation'])
    if change == 'scope_mode':
        lab.scope.chmod(0o640)
    elif change == 'ownership':
        actual = loop.imp.workflow.owner
        monkeypatch.setattr(loop.imp.workflow, 'owner',
                            lambda name: 'django' if name == FILES[1] else actual(name))
    elif change == 'provider':
        assert lab.models['roles']['parser']['provider'] != 'zai'
        lab.models['roles']['parser']['provider'] = 'zai'
    elif change == 'model':
        lab.models['roles']['parser']['model'] = 'synthetic-model'
    else:
        # A pre-policy round lacks the explicit protocol control binding.
        state = lab.state()
        state['round']['report']['loop_dependencies'].pop('review_protocol')
        lab.store.write(loop.STATE_FILE, state)
    result = lab.tick(2)
    state = lab.state()
    assert state['round']['report']['scan_id'] != old and state['stage_index'] == 1
    assert result['status'] != 'paused'
    assert lab.events[-1] == ('local_explorer', 'coordinator')
    assert state['participation'] == attempts
    assert lab.store.exists('loop/invalidated/' + old + '.json')


def test_owner_first_exploration_keeps_membership_and_maps_legacy_cursor_by_path(lab):
    paths = [FILES[4], FILES[5]] + list(FILES[:4])
    state = loop._new_state()
    state['cursors'] = {'downloader': {'file_index': 0, 'line': 3}}
    loop._migrate_cursors(state, paths, lab.discovery)
    own = imp.role_scope('downloader', paths, lab.discovery)
    assert own[0] == FILES[1]
    assert set(own) == {FILES[1], FILES[4], FILES[5]}
    assert own[state['cursors']['downloader']['file_index']] == FILES[4]
    assert state['cursors']['downloader']['line'] == 3
    before = copy.deepcopy(state)
    loop._migrate_cursors(state, paths, lab.discovery)
    assert state == before


def test_optional_local_prepare_exception_advances_only_local_slot(lab, monkeypatch):
    actual = local_model.prepare_request

    def unavailable(*args, **kwargs):
        raise local_model.LocalModelError('context_too_large')

    with monkeypatch.context() as patch:
        patch.setattr(local_model, 'prepare_request', unavailable)
        lab.tick(0)
    assert lab.ledger()['calls'] == 0 and lab.state()['stage_index'] == 1
    assert lab.state()['round']['report']['local_participation'][0]['reason'] == 'context_too_large'
    lab.tick(1)
    assert [r['role'] for r in lab.cloud_requests] == ['coordinator']
    assert lab.ledger()['calls'] == 1


def test_supplied_oct21_old_skips_are_synthetic_legacy_input_and_frozen_report_is_preserved(lab):
    """Parent-supplied observation, no private record or live call is read here.

    Encode 00/04/06 local success, 02 duplicate, cloud 01/05/07 success with no
    candidates, historical skips 03/08, then exercise actual restart at 09/10.
    """
    lab.clock.value = START.replace(day=21)
    lab.tick()
    state = lab.state()
    report = state['round']['report']
    origin = lab.clock()
    report['local_participation'] = [dict(report['local_participation'][0],
        owner_role=role, started_at=(origin + dt.timedelta(hours=hour)).isoformat(),
        finished_at=(origin + dt.timedelta(hours=hour)).isoformat(),
        status='failed' if hour == 2 else 'succeeded',
        reason='candidate_edit_files_duplicate' if hour == 2 else 'ok')
        for hour, role in ((0, 'coordinator'), (2, 'downloader'), (4, 'parser'), (6, 'django'))]
    for hour, role in ((1, 'coordinator'), (5, 'parser'), (7, 'django')):
        spec = lab.models['roles'][role]
        loop._role_agent(report, role, dict(role=role, provider=spec['provider'], model=spec['model'],
            status='succeeded', started_at=(origin + dt.timedelta(hours=hour)).isoformat(),
            finished_at=(origin + dt.timedelta(hours=hour)).isoformat()))
    state['stage_index'] = 9
    state['round'].pop('snapshot')  # Old active state has no provable sealed input.
    for key in ('participation', 'history_migrated', 'cursor_order'):
        state.pop(key)
    state['high_water_at'] = (origin + dt.timedelta(hours=8)).isoformat()
    lab.store.write(loop.STATE_FILE, state)
    lab.store.write('scans/' + report['scan_id'] + '.json', report)
    lab.clock.value = origin + dt.timedelta(hours=9)
    lab.store = imp.Store(lab.selected)
    lab.tick()
    public = lab.store.read('web/2026-10-21.json')
    assert [a['status'] for a in public['agents']] == [
        'succeeded', 'not_called', 'succeeded', 'succeeded', 'not_called']
    assert public['status'] == 'partial' and public['counts']['reported'] == 0
    frozen = lab.store.path('web/2026-10-21.json').read_bytes()
    scan_id = lab.state()['round']['report']['scan_id']
    lab.expected_sources = sources(lab)
    (lab.root / FILES[0]).write_text('source drift at ten\n', encoding='utf-8')
    lab.clock.value = origin + dt.timedelta(hours=10)
    lab.tick()
    assert lab.state()['round']['report']['scan_id'] == scan_id
    assert lab.state()['stage_index'] == 2
    assert lab.store.path('web/2026-10-21.json').read_bytes() == frozen
