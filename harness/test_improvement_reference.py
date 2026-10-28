"""Synthetic private fixtures only; no operational storage or pipeline calls."""
import copy
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from harness import improvement_reference as ref


UTC = dt.timezone.utc
PAYLOAD = 'SYNTHETIC_PRIVATE_SOURCE_DO_NOT_PROJECT'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def pid(n):
    return 'IMP-{:016x}'.format(n)


def proposal(n, paths=None, title='Similar proposed change', digest=None):
    return {'proposal': {'id': pid(n), 'digest': digest or '{:064x}'.format(n),
                         'candidate': {'title': title, 'edit_files': paths or ['harness/a.py'],
                                       'issue': PAYLOAD, 'solution': PAYLOAD},
                         'review': {'verdict': 'eligible', 'reason': PAYLOAD},
                         'source_fingerprints': {'harness/a.py': PAYLOAD}},
            'scan_id': 'synthetic-scan', 'date': '2020-01-01', 'review_complete': True,
            'status': 'scanned', 'discovery_fingerprint': 'f' * 64}


def semantic(n=1, issues=None, at='2020-01-01T00:00:00+00:00', digest=None):
    return {'version': ref.VERSION, 'observed_at': at, 'proposal_id': pid(n),
            'proposal_digest': digest or '{:064x}'.format(n), 'source': 'parent_review',
            'issues': issues if issues is not None else [issue('issue_a')]}


def issue(key, status='open', prs=None):
    return {'issue_key': key, 'implementation_status': status, 'matched_prs': prs or []}


def history(*entries):
    result, previous = [], '0' * 64
    for seq, entry in enumerate(entries, 1):
        record = dict(copy.deepcopy(entry), seq=seq, previous_sha256=previous)
        previous = hashlib.sha256(canonical(record) + b'\n').hexdigest()
        result.append(record)
    return result


def workflow(run='RUN-1', number=1, at=100, paths=None):
    paths = paths or ['harness/a.py']
    checks = {name: 'success' for name in ref.REQUIRED_CI}
    report = {'run_id': run, 'status': 'passed', 'changed_files': paths, 'applied': paths,
              'read_only': False, 'simulated': False, 'no_git': False, 'github_enabled': True,
              'review': {'verdict': 'approved'}, 'raw_response': PAYLOAD, 'logs': PAYLOAD}
    github = {'run_id': run, 'status': 'merged', 'step': 'done', 'merge_status': 'merged',
              'pr_number': number, 'merge_sha': 'a' * 40, 'head_sha': 'b' * 40,
              'checks': checks, 'body': PAYLOAD, 'commit_message': PAYLOAD,
              'events': [{'step': 'merge', 'time': at, 'response': PAYLOAD}],
              'files': {p: {'before': PAYLOAD + '-before', 'after': PAYLOAD + '-after'} for p in paths},
              'cleanup_proof': {'verified': True, 'head_sha': 'b' * 40,
                                'merge_sha': 'a' * 40, 'checks': checks.copy()},
              'cleanup': {'version': 'cleanup-v1', 'status': 'complete',
                          'remote': {'status': 'deleted'}, 'local': {'status': 'absent'},
                          'prune': {'status': 'complete'}, 'sync': {'status': 'complete'},
                          'completion': {'status': 'complete'}}}
    return {'workflows/' + run + '/report.json': report,
            'workflows/' + run + '/github.json': github}


def render(records, annotations=None, approved=None):
    text = ref.render_reference(records, annotations or [], approved or ['harness/a.py'])
    return json.loads(text.split('\n', 1)[1]) if text else None


class PrivateFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'improvement'
        self.workflows = self.base / 'workflows'
        for directory in (self.root, self.root / 'proposals', self.root / 'loop', self.workflows):
            directory.mkdir(mode=0o700)
            directory.chmod(0o700)
        self.annotations = self.root / 'loop' / 'issue-annotations.jsonl'
        self.parent = mock.patch.object(ref, '_parent')
        self.parent.start()
        self.addCleanup(self.parent.stop)
        # Ambient CI restrictions must not stand in for these explicit test cases.
        self.environment = mock.patch.dict(os.environ, {k: '' for k in ref.DENY_WRITER_ENV})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def put(self, path, value=None, body=None):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        path.write_bytes(body if body is not None else canonical(value))
        path.chmod(0o600)
        return path

    def install(self, records):
        for key, value in records.items():
            if key.startswith('workflows/'):
                path = self.workflows / key[len('workflows/'):]
            else:
                path = self.root / key
            self.put(path, value)


class CaptureTests(PrivateFixture):
    def test_real_store_projection_and_direct_development_without_claims(self):
        records = {'proposals/' + pid(1) + '.json': proposal(1)}
        records.update(workflow())
        self.install(records)
        # Unrelated stores and archive contents are never opened.
        self.put(self.root / 'claims' / 'broken.json', body=b'not-json')
        self.put(self.root / 'authority.key', body=PAYLOAD.encode())
        self.put(self.workflows / 'archive' / 'RUN-old' / 'github.json', body=b'not-json')
        captured, errors = ref.capture_reference_inputs(self.root, self.workflows)
        self.assertEqual(errors, [])
        self.assertEqual(set(captured), set(records))
        output = ref.render_reference(captured, [], ['harness/a.py'])
        self.assertNotIn(PAYLOAD, output)
        data = json.loads(output.split('\n', 1)[1])
        self.assertEqual(data['merged_prs'][0]['pr_number'], 1)
        self.assertEqual(data['issues'][0]['implementation_status'], 'unknown')
        self.assertEqual(data['issues'][0]['title'], 'Similar proposed change')
        self.assertEqual(data['issues'][0]['review_verdict'], 'eligible')

    def test_missing_corrupt_and_unsafe_roots_are_advisory(self):
        for path in (self.base / 'absent', self.put(self.base / 'regular', body=b'{}')):
            with self.subTest(path=path.name):
                records, errors = ref.capture_reference_inputs(path, self.workflows)
                self.assertEqual(records, {})
                self.assertEqual(errors, ['references_unavailable'])
        self.root.chmod(0o755)
        records, errors = ref.capture_reference_inputs(self.root)
        self.assertEqual(records, {})
        self.assertIn('unsafe_attachment', errors)

    def test_malformed_record_does_not_project_payload(self):
        self.put(self.root / 'proposals' / (pid(1) + '.json'), body=b'{"proposal":NaN}')
        captured, errors = ref.capture_reference_inputs(self.root)
        # Capture's strict decoder rejects non-finite values.
        self.assertEqual(captured, {})
        self.assertTrue(errors)
        self.assertEqual(ref.render_reference(captured, [], ['harness/a.py']), '')

    def test_busy_lock_and_change_are_not_retried(self):
        lock = self.put(self.root / '.lock', body=b'')
        with lock.open('rb') as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(ref.capture_reference_inputs(self.root), ({}, ['lock_busy']))
        self.install({'proposals/' + pid(1) + '.json': proposal(1)})
        from harness.improvement_metrics import Capture
        original = Capture.verify
        calls = []

        def changed(capture):
            calls.append(True)
            (self.root / 'proposals' / (pid(1) + '.json')).write_bytes(b'{}')
            original(capture)

        with mock.patch.object(Capture, 'verify', changed):
            records, errors = ref.capture_reference_inputs(self.root)
        self.assertEqual(records, {})
        self.assertEqual(errors, ['concurrent_change'])
        self.assertEqual(len(calls), 1)

    def test_limits_and_no_follow(self):
        target = self.put(self.root / 'payload', proposal(1))
        link = self.root / 'proposals' / (pid(1) + '.json')
        link.symlink_to(target)
        self.assertEqual(ref.capture_reference_inputs(self.root)[0], {})
        link.unlink()
        self.install({'proposals/' + pid(1) + '.json': proposal(1)})
        with mock.patch.object(ref, 'MAX_BYTES', 1):
            self.assertEqual(ref.capture_reference_inputs(self.root), ({}, ['record_bound']))
        with mock.patch.object(ref, 'MAX_FILES', 1):
            self.assertEqual(ref.capture_reference_inputs(self.root), ({}, ['inventory_bound']))
        self.assertEqual((ref.MAX_FILES, ref.MAX_BYTES, ref.MAX_RECORD),
                         (4096, 64 * 1024 * 1024, 8 * 1024 * 1024))

    def test_child_collector_denied_before_capture(self):
        with mock.patch.object(ref, '_parent', side_effect=ref.ReferenceError('parent_only')):
            with mock.patch.object(ref.os, 'open', side_effect=AssertionError('storage touched')):
                self.assertEqual(ref.capture_reference_inputs(self.root), ({}, ['parent_only']))

    def test_eight_mib_record_limit_precedes_parsing(self):
        path = self.put(self.root / 'proposals' / (pid(1) + '.json'), body=b'')
        with path.open('wb') as handle:
            handle.truncate(8 * 1024 * 1024 + 1)
        self.assertEqual(ref.capture_reference_inputs(self.root), ({}, ['record_bound']))

    def test_direct_workflow_busy_lock_is_not_ignored(self):
        self.install(workflow())
        lock = self.put(self.workflows / 'RUN-1' / 'github.lock', body=b'')
        with lock.open('rb') as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(ref.capture_reference_inputs(self.root, self.workflows),
                             ({}, ['lock_busy']))


class AnnotationTests(PrivateFixture):
    def assert_refusal_unchanged(self, entry, code=None):
        before = self.annotations.read_bytes()
        with self.assertRaises(ref.ReferenceError) as caught:
            ref.append_annotation(self.annotations, entry)
        if code:
            self.assertEqual(str(caught.exception), code)
        self.assertEqual(self.annotations.read_bytes(), before)

    def test_append_prefix_readback_hash_mode_and_corrections(self):
        first = ref.append_annotation(self.annotations, semantic())
        prefix = self.annotations.read_bytes()
        inode = self.annotations.stat().st_ino
        second = ref.append_annotation(self.annotations, semantic(
            issues=[issue('issue_a', 'partial', [7]), issue('issue_b', 'open', [8])],
            at='2020-01-02T00:00:00+00:00'))
        self.assertEqual(self.annotations.stat().st_ino, inode)
        self.assertEqual(stat.S_IMODE(self.annotations.stat().st_mode), 0o600)
        self.assertEqual(self.annotations.stat().st_nlink, 1)
        self.assertTrue(self.annotations.read_bytes().startswith(prefix))
        self.assertEqual(second['previous_sha256'], hashlib.sha256(prefix).hexdigest())
        self.assertEqual(first['previous_sha256'], '0' * 64)
        self.assertEqual([first['seq'], second['seq']], [1, 2])
        self.assertEqual(ref.read_annotations(self.annotations), [first, second])
        self.assertEqual(ref.annotation_at([first, second], pid(1), '0' * 63 + '1',
                                         '2020-01-02T00:00:00Z'), first)
        self.assertEqual(ref.annotation_at([first, second], pid(1), '0' * 63 + '1',
                                         '2020-01-03T00:00:00Z'), second)
        self.assert_refusal_unchanged(semantic(at='2019-01-01T00:00:00Z'),
                                      'annotation_time_regression')

    def test_missing_file_read_is_non_creating(self):
        self.assertEqual(ref.read_annotations(self.annotations), [])
        self.assertFalse(self.annotations.exists())

    def test_semantic_rejections_preserve_existing_bytes(self):
        ref.append_annotation(self.annotations, semantic())
        variants = []
        for field, value in (('version', 'other'), ('observed_at', '2020-01-01'),
                             ('proposal_id', 'IMP-bad'), ('proposal_digest', 'x' * 64),
                             ('source', 'model'), ('seq', 2), ('credential', PAYLOAD)):
            entry = semantic()
            entry[field] = value
            variants.append(entry)
        for issues in ([issue('space key')], [issue('a', 'done')], [issue('a', prs=[1, 1])],
                       [issue('a', prs=[True])], [issue('a', prs=[0])],
                       [issue('a'), issue('a')], [issue(str(n)) for n in range(9)],
                       [dict(issue('a'), explanation=PAYLOAD)]):
            variants.append(semantic(issues=issues))
        for index, entry in enumerate(variants):
            with self.subTest(index=index):
                self.assert_refusal_unchanged(entry)

    def test_malformed_existing_history_is_never_repaired(self):
        records = history(semantic(), semantic(at='2020-01-02T00:00:00Z'))
        good = b''.join(canonical(e) + b'\n' for e in records)
        broken_hash = copy.deepcopy(records)
        broken_hash[1]['previous_sha256'] = 'f' * 64
        bad_seq = copy.deepcopy(records)
        bad_seq[1]['seq'] = 1
        backwards = history(semantic(), semantic(at='2019-01-01T00:00:00Z'))
        duplicate = canonical(records[0]).replace(b'"seq":1', b'"seq":1,"seq":1') + b'\n'
        nan = canonical(records[0]).replace(b'"seq":1', b'"seq":NaN') + b'\n'
        unknown = dict(records[0], instruction=PAYLOAD)
        variants = [good[:-1], b'\xff\n', duplicate, nan, canonical(unknown) + b'\n',
                    b''.join(canonical(e) + b'\n' for e in broken_hash),
                    b''.join(canonical(e) + b'\n' for e in bad_seq),
                    b''.join(canonical(e) + b'\n' for e in backwards), b'\n',
                    canonical(records[0]) + b'\r\n']
        for index, body in enumerate(variants):
            with self.subTest(index=index):
                self.put(self.annotations, body=body)
                with self.assertRaises(ref.ReferenceError):
                    ref.read_annotations(self.annotations)
                self.assert_refusal_unchanged(semantic(at='2020-01-03T00:00:00Z'))

    def test_mode_owner_symlink_hardlink_and_ancestor_safety(self):
        ref.append_annotation(self.annotations, semantic())
        prefix = self.annotations.read_bytes()
        self.annotations.chmod(0o640)
        self.assert_refusal_unchanged(semantic())
        self.annotations.chmod(0o600)
        with mock.patch.object(ref.os, 'geteuid', return_value=os.geteuid() + 1):
            self.assert_refusal_unchanged(semantic())
        hardlink = self.root / 'another-link'
        os.link(self.annotations, hardlink)
        self.assert_refusal_unchanged(semantic())
        hardlink.unlink()
        target = self.root / 'target'
        self.annotations.rename(target)
        self.annotations.symlink_to(target)
        self.assert_refusal_unchanged(semantic())
        self.annotations.unlink()
        target.rename(self.annotations)
        moved = self.root / 'original-loop'
        self.annotations.parent.rename(moved)
        (self.root / 'loop').symlink_to(moved, target_is_directory=True)
        self.assert_refusal_unchanged(semantic())
        self.assertEqual((moved / self.annotations.name).read_bytes(), prefix)

    def test_busy_file_lock_preserves_prefix(self):
        ref.append_annotation(self.annotations, semantic())
        with self.annotations.open('rb') as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assert_refusal_unchanged(semantic(), 'lock_busy')
            with self.assertRaisesRegex(ref.ReferenceError, 'lock_busy'):
                ref.read_annotations(self.annotations)

    def test_inode_replacement_and_unlocked_concurrent_append(self):
        ref.append_annotation(self.annotations, semantic())
        prefix = self.annotations.read_bytes()
        original = ref._read_locked
        calls = []
        replacement = self.root / 'replacement'
        self.put(replacement, body=prefix)

        def replace_after_read(fd):
            result = original(fd)
            if not calls:
                os.replace(replacement, self.annotations)
            calls.append(True)
            return result

        with mock.patch.object(ref, '_read_locked', side_effect=replace_after_read):
            self.assert_refusal_unchanged(semantic())
        self.assertEqual(self.annotations.read_bytes(), prefix)
        calls.clear()

        def concurrent_append(fd):
            if calls:
                with self.annotations.open('ab') as handle:
                    handle.write(b' ')
            calls.append(True)
            return original(fd)

        with mock.patch.object(ref, '_read_locked', side_effect=concurrent_append):
            with self.assertRaisesRegex(ref.ReferenceError, 'concurrent_change'):
                ref.append_annotation(self.annotations, semantic())
        # The only new byte belongs to the modeled non-cooperating writer.
        self.assertEqual(self.annotations.read_bytes(), prefix + b' ')

    def test_ancestor_detachment_before_write(self):
        ref.append_annotation(self.annotations, semantic())
        prefix = self.annotations.read_bytes()
        original = ref._read_locked
        detached = self.root / 'detached-loop'
        calls = []

        def detach(fd):
            result = original(fd)
            if not calls:
                self.annotations.parent.rename(detached)
                self.annotations.parent.mkdir(mode=0o700)
            calls.append(True)
            return result

        with mock.patch.object(ref, '_read_locked', side_effect=detach):
            with self.assertRaisesRegex(ref.ReferenceError, 'concurrent_change'):
                ref.append_annotation(self.annotations, semantic())
        self.assertEqual((detached / self.annotations.name).read_bytes(), prefix)
        self.assertFalse(self.annotations.exists())

    def test_child_discovery_unattended_denied_before_any_storage(self):
        class UntouchablePath:
            def __fspath__(self):
                raise AssertionError('path inspected')

        for flag in ref.DENY_WRITER_ENV:
            with self.subTest(flag=flag), mock.patch.dict(os.environ, {flag: '1'}):
                with mock.patch.object(ref.os, 'open', side_effect=AssertionError('storage opened')):
                    with self.assertRaisesRegex(ref.ReferenceError, 'parent_only'):
                        ref.append_annotation(UntouchablePath(), semantic())
        with mock.patch.object(ref, '_parent', side_effect=ref.ReferenceError('parent_only')):
            with self.assertRaisesRegex(ref.ReferenceError, 'parent_only'):
                ref.append_annotation(UntouchablePath(), semantic())

    def test_annotation_byte_line_and_entry_caps(self):
        ref.append_annotation(self.annotations, semantic())
        prefix = self.annotations.read_bytes()
        with mock.patch.object(ref, 'MAX_ANNOTATIONS', 1):
            self.assert_refusal_unchanged(semantic(), 'annotation_bound')
        with mock.patch.object(ref, 'MAX_ANNOTATION_BYTES', len(prefix)):
            self.assert_refusal_unchanged(semantic(), 'annotation_bound')
        # A real >4096-byte semantic record is refused before opening storage.
        with mock.patch.object(ref.os, 'open', side_effect=AssertionError('storage opened')):
            with self.assertRaisesRegex(ref.ReferenceError, 'annotation_bound'):
                ref.append_annotation(self.annotations, semantic(issues=[issue('a', prs=list(range(1, 2000)))]))
        self.assertEqual(self.annotations.read_bytes(), prefix)
        self.put(self.annotations, body=b'x' * (ref.MAX_LINE + 1) + b'\n')
        self.assert_refusal_unchanged(semantic())
        self.put(self.annotations, body=b'x' * (ref.MAX_ANNOTATION_BYTES + 1))
        self.assert_refusal_unchanged(semantic(), 'annotation_bound')
        self.assertEqual((ref.MAX_ANNOTATION_BYTES, ref.MAX_LINE, ref.MAX_ANNOTATIONS),
                         (1024 * 1024, 4096, 2048))

    def test_actual_2048_entry_boundary_and_full_4096_byte_line(self):
        records = history(*(semantic() for _ in range(2048)))
        body = b''.join(canonical(e) + b'\n' for e in records)
        self.assertLessEqual(len(body), 1024 * 1024)
        self.put(self.annotations, body=body)
        self.assertEqual(len(ref.read_annotations(self.annotations)), 2048)
        self.assert_refusal_unchanged(semantic(), 'annotation_bound')
        # Construct a valid exactly 4096-byte line using a positive PR integer.
        self.annotations.unlink()
        entry = semantic(issues=[issue('a', prs=[1])])
        base_size = len(canonical(history(entry)[0])) + 1
        entry['issues'][0]['matched_prs'] = [10 ** (4096 - base_size)]
        ref.append_annotation(self.annotations, entry)
        self.assertEqual(len(self.annotations.read_bytes()), 4096)
        self.assertEqual(ref.read_annotations(self.annotations)[0]['issues'], entry['issues'])


class RenderingTests(unittest.TestCase):
    def test_similar_unannotated_proposals_remain_individually_unknown(self):
        records = {'proposals/' + pid(n) + '.json': proposal(n) for n in (2, 1)}
        records['proposals/duplicate.json'] = proposal(1)
        data = render(records)
        self.assertEqual([p['proposal_id'] for p in data['issues']], [pid(1), pid(2)])
        for row in data['issues']:
            self.assertEqual((row['issue_key'], row['implementation_status'], row['proposal_count']),
                             ('unknown', 'unknown', 1))

    def test_digest_binding_cutoff_and_future_observations(self):
        records = {'proposals/' + pid(1) + '.json': proposal(1)}
        annotations = history(semantic(), semantic(issues=[issue('issue_a', 'implemented')],
                                                   at='2020-01-02T00:00:00Z'))
        data = render(records, {'entries': annotations, 'cutoff': '2020-01-02T00:00:00Z'})
        self.assertEqual(data['issues'][0]['implementation_status'], 'open')
        data = render(records, {'entries': annotations, 'cutoff': '2020-01-01T00:00:00Z'})
        self.assertEqual(data['issues'][0]['implementation_status'], 'unknown')
        for entries in (history(semantic(digest='f' * 64)),
                        history(semantic(at='2999-01-01T00:00:00Z'))):
            self.assertEqual(render(records, entries)['issues'][0]['implementation_status'], 'unknown')
        # A later digest supersedes an older observation, rather than reviving it.
        changed_digest = history(semantic(), semantic(at='2020-01-02T00:00:00Z', digest='f' * 64))
        self.assertEqual(render(records, changed_digest)['issues'][0]['implementation_status'], 'unknown')
        self.assertEqual(render(records, {'entries': annotations, 'cutoff': 'naive'})['issues'][0]
                         ['implementation_status'], 'unknown')
        aware = dt.datetime(2020, 1, 2, tzinfo=UTC)
        self.assertEqual(render(records, {'entries': annotations, 'cutoff': aware})['issues'][0]
                         ['implementation_status'], 'open')

    def test_empty_correction_withdraws_grouping_and_invalid_chain_is_unknown(self):
        records = {'proposals/' + pid(1) + '.json': proposal(1)}
        annotations = history(semantic(), semantic(issues=[], at='2020-01-02T00:00:00Z'))
        row = render(records, annotations)['issues'][0]
        self.assertEqual((row['issue_key'], row['implementation_status']), ('unknown', 'unknown'))
        annotations[1]['previous_sha256'] = 'f' * 64
        self.assertEqual(render(records, annotations)['issues'][0]['implementation_status'], 'unknown')

    def test_multiple_issues_group_representative_count_and_path_intersection(self):
        records = {'proposals/' + pid(n) + '.json': proposal(
            n, ['harness/a.py', 'harness/b.py', 'outside/private.py']) for n in (2, 1)}
        annotations = history(semantic(2, [issue('shared'), issue('second', 'partial')]),
                              semantic(1, [issue('shared', 'implemented')]))
        data = render(records, annotations, ['harness/a.py', 'harness/b.py'])
        self.assertEqual(len(data['issues']), 2)
        shared = next(p for p in data['issues'] if p['issue_key'] == 'shared')
        self.assertEqual(shared['proposal_count'], 2)
        self.assertEqual(shared['proposal_id'], pid(1))
        self.assertEqual(shared['implementation_status'], 'open')
        self.assertEqual(shared['edit_files'], ['harness/a.py', 'harness/b.py'])
        self.assertNotIn('outside/private.py', str(data))

    def test_store_projection_uses_only_nested_proposal_fields(self):
        saved = proposal(1)
        saved.update(id=pid(9), digest='f' * 64, title=PAYLOAD,
                     edit_files=['outside/secret.py'], review={'verdict': 'rejected'})
        data = render({'proposals/' + pid(1) + '.json': saved})
        row = data['issues'][0]
        self.assertEqual(row['proposal_id'], pid(1))
        self.assertEqual(row['title'], 'Similar proposed change')
        self.assertEqual(row['review_verdict'], 'eligible')
        self.assertEqual(row['edit_files'], ['harness/a.py'])
        self.assertNotIn(PAYLOAD, str(data))

    def test_equal_recency_uses_issue_or_individual_identifier(self):
        records = {'proposals/' + pid(n) + '.json': proposal(n) for n in (1, 2)}
        annotations = history(semantic(1, [issue('zz_group', 'partial')]))
        data = render(records, annotations)
        self.assertEqual([row['proposal_id'] for row in data['issues']], [pid(2), pid(1)])

    def test_open_first_then_merge_recency_and_stable_identifier_ties(self):
        records, annotations = {}, []
        for n, status, time in ((1, 'partial', 200), (2, 'open', 1),
                                (3, 'partial', 300), (4, 'partial', 300), (5, 'partial', None)):
            records['proposals/' + pid(n) + '.json'] = proposal(n)
            records.update(workflow('RUN-' + str(n), n, time))
            annotations.append(semantic(n, [issue('key_' + str(n), status, [n])]))
        annotations = history(*annotations)
        expected = ['key_2', 'key_3', 'key_4', 'key_1', 'key_5']
        data = render(records, annotations)
        self.assertEqual([p['issue_key'] for p in data['issues']], expected)
        self.assertEqual([p['pr_number'] for p in data['merged_prs']], [3, 4, 1])
        reversed_records = dict(reversed(list(records.items())))
        self.assertEqual(ref.render_reference(records, annotations, ['harness/a.py']),
                         ref.render_reference(reversed_records, annotations, ['harness/a.py']))
        # Merged alone never changes the annotation's status.
        self.assertEqual(data['issues'][1]['implementation_status'], 'partial')

    def test_completed_journal_requirements_and_payload_exclusion(self):
        good = workflow()
        self.assertEqual(len(render(good)['merged_prs']), 1)
        mutations = [
            ('report', 'status', 'failed'), ('report', 'run_id', 'other'),
            ('report', 'changed_files', ['harness/other.py']), ('report', 'applied', []),
            ('report', 'read_only', True), ('report', 'simulated', True),
            ('report', 'github_enabled', False), ('report', 'no_git', True),
            ('report', 'scope', ['harness/other.py']), ('report', 'review', {'verdict': 'rejected'}),
            ('github', 'run_id', 'other'), ('github', 'status', 'awaiting_ci'),
            ('github', 'step', 'cleanup'), ('github', 'merge_status', 'waiting'),
            ('github', 'pr_number', True), ('github', 'pr_number', 0),
            ('github', 'merge_sha', 'invalid'), ('github', 'head_sha', 'invalid'),
            ('github', 'checks', {}), ('github', 'files', {}),
            ('github', 'files', {'harness/a.py': {'before': 'same', 'after': 'same'}}),
            ('github', 'cleanup_proof', {}), ('github', 'cleanup', {}),
            ('github', 'cleanup', {'status': 'complete', 'version': 'cleanup-v1', 'remote': None}),
        ]
        for journal, field, value in mutations:
            with self.subTest(journal=journal, field=field, value=value):
                broken = copy.deepcopy(good)
                broken['workflows/RUN-1/' + journal + '.json'][field] = value
                self.assertEqual(ref.render_reference(broken, [], ['harness/a.py']), '')
        for nested, field, value in (
                ('cleanup_proof', 'checks', {}), ('cleanup_proof', 'verified', False),
                ('cleanup_proof', 'head_sha', 'c' * 40), ('cleanup_proof', 'merge_sha', 'c' * 40),
                ('cleanup', 'status', 'pending'), ('cleanup', 'sync', {'status': 'pending'})):
            broken = copy.deepcopy(good)
            broken['workflows/RUN-1/github.json'][nested][field] = value
            self.assertIsNone(render(broken))
        output = ref.render_reference(good, [], ['harness/a.py'])
        self.assertNotIn(PAYLOAD, output)
        self.assertNotIn('body', output)
        self.assertNotIn('commit_message', output)
        self.assertNotIn('before', output)

    def test_unknown_merge_time_is_never_recent_and_pr_overlap_is_required(self):
        records = workflow('RUN-1', 1, 100, ['harness/a.py', 'outside/secret.py'])
        records.update(workflow('RUN-2', 2, 200, ['outside/secret.py']))
        records.update(workflow('RUN-3', 3, None))
        data = render(records)
        self.assertEqual([r['pr_number'] for r in data['merged_prs']], [1, 3])
        self.assertEqual(data['merged_prs'][0]['edit_files'], ['harness/a.py'])
        self.assertIsNone(data['merged_prs'][1]['merge_time'])
        for time in (None, -1, 0, True, float('nan'), float('inf'), '300'):
            with self.subTest(time=time):
                broken_clock = workflow(at=time)
                self.assertIsNone(render(broken_clock)['merged_prs'][0]['merge_time'])
        records = workflow()
        records['workflows/RUN-1/github.json']['events'] = [
            {'step': 'cleanup', 'time': 999}, {'step': 'merge', 'time': 10},
            {'step': 'merge', 'time': 20}]
        self.assertEqual(render(records)['merged_prs'][0]['merge_time'], 20)

    def test_contradictory_duplicate_pr_journals_are_excluded(self):
        records = workflow('RUN-1', 1, 100)
        records.update(workflow('RUN-2', 1, 200))
        self.assertIsNone(render(records))

    def test_count_byte_caps_multibyte_and_skip_large_whole_entries(self):
        records = {}
        for n in range(1, 10):
            records['proposals/' + pid(n) + '.json'] = proposal(n, title='가' * 200)
            records.update(workflow('RUN-' + str(n), n, n))
        text = ref.render_reference(records, [], ['harness/a.py'])
        data = json.loads(text.split('\n', 1)[1])
        self.assertEqual((len(data['issues']), len(data['merged_prs'])), (5, 3))
        self.assertLessEqual(len(text.encode('utf-8')), 8192)
        self.assertEqual(text.encode('utf-8').decode('utf-8'), text)
        self.assertLessEqual(len(ref.HEADER.encode()) + len(canonical({'issues': [], 'merged_prs': []})) + 8, 256)
        for row in data['issues']:
            self.assertLessEqual(len(canonical(row)), 768)
            self.assertTrue(row['title_truncated'])
            self.assertTrue(row['title'].endswith('…'))
        for row in data['merged_prs']:
            self.assertLessEqual(len(canonical(row)), 1024)
        # A huge first entry must not prevent a later small entry being selected.
        many = ['harness/{}-{}.py'.format('가' * 20, n) for n in range(30)]
        records = {'proposals/' + pid(1) + '.json': proposal(1, many),
                   'proposals/' + pid(2) + '.json': proposal(2)}
        records.update(workflow('RUN-large', 99, 999, many))
        records.update(workflow('RUN-small', 1, 1))
        data = render(records, approved=many + ['harness/a.py'])
        self.assertEqual([r['proposal_id'] for r in data['issues']], [pid(2)])
        self.assertEqual([r['pr_number'] for r in data['merged_prs']], [1])

    def test_final_hard_cap_is_checked_and_entries_are_never_byte_sliced(self):
        records = {'proposals/' + pid(1) + '.json': proposal(1)}
        with mock.patch.object(ref, 'REFERENCE_BYTES', 1):
            with self.assertRaisesRegex(ref.ReferenceError, 'reference_bound'):
                ref.render_reference(records, [], ['harness/a.py'])
        row = render(records)['issues'][0]
        size = len(canonical(row))
        with mock.patch.object(ref, 'ISSUE_BYTES', size):
            self.assertEqual(len(render(records)['issues']), 1)
        with mock.patch.object(ref, 'ISSUE_BYTES', size - 1):
            self.assertIsNone(render(records))
        pr_records = workflow()
        pr_size = len(canonical(render(pr_records)['merged_prs'][0]))
        with mock.patch.object(ref, 'PR_BYTES', pr_size):
            self.assertEqual(len(render(pr_records)['merged_prs']), 1)
        with mock.patch.object(ref, 'PR_BYTES', pr_size - 1):
            self.assertIsNone(render(pr_records))

    def test_no_match_zero_bytes_and_no_render_storage_access(self):
        records = {'proposals/' + pid(1) + '.json': proposal(1)}
        records.update(workflow())
        self.assertEqual(ref.render_reference(records, [], ['elsewhere/file.py']), '')
        self.assertEqual(len(ref.render_reference(records, [], []).encode('utf-8')), 0)
        # Warm the existing sanitizer import, then forbid all descriptor I/O.
        render(records)
        with mock.patch.object(ref.os, 'open', side_effect=AssertionError('storage access')):
            self.assertIsNotNone(render(records))
        self.assertEqual(records['proposals/' + pid(1) + '.json'], proposal(1))


if __name__ == '__main__':
    unittest.main()
