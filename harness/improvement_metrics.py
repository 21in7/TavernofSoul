"""Private, offline projections of retained improvement records (Python 3.8).

No Store writer, source capture, subprocess, transport or operational entrypoint
is used. Capture is bounded and optimistic; neither contention nor changes retry.
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import stat
import statistics

from harness import improvement_report as contract, review_coverage

KST = dt.timezone(dt.timedelta(hours=9), 'Asia/Seoul')
MAX_FILES = 4096
MAX_BYTES = 64 * 1024 * 1024
MAX_RECORD = 8 * 1024 * 1024
ID = re.compile(r'IMP-[0-9a-f]{16}\Z')
RUN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
SHA = re.compile(r'[0-9a-f]{40}\Z')
ROLES = tuple(contract.SPECIALIST_ROLES) + ('reviewer',)
REQUIRED_CI = {'Offline harness (SQLite)', 'MySQL harness', 'Chromium browser harness'}
STATES = ('completed', 'failed', 'invalidated', 'superseded', 'held', 'in_progress', 'unknown')
VERDICTS = ('eligible', 'needs_evidence', 'rejected', 'review_incomplete', 'unknown')
TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'cached_input_tokens',
                'cache_read_input_tokens', 'cache_creation_input_tokens')
LOOP_VERSION = 'improvement-loop-state-v1'


class Unavailable(ValueError):
    """Fixed diagnostics only: never render an OS exception or private payload."""


def timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.utcoffset() is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def numeric(value):
    return value if type(value) in (int, float) and 0 <= value <= 10 ** 15 and math.isfinite(value) else None


def stats(values):
    values = sorted(v for v in values if numeric(v) is not None)
    return {'n': len(values), 'median': statistics.median(values) if values else None,
            'p90': values[math.ceil(len(values) * .9) - 1] if values else None,
            'max': max(values) if values else None}


def elapsed(start, end):
    start, end = timestamp(start), timestamp(end)
    return (end - start).total_seconds() if start and end and end >= start else None


def ratio(numerator, denominator, scope, unit='fraction'):
    return {'numerator': numerator, 'denominator': denominator, 'scope': scope,
            'unit': unit, 'value': numerator / denominator if denominator else None,
            'status': 'available' if denominator else '미산출'}


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _private(info, directory=False):
    if (info.st_uid != os.geteuid() or
            stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600) or
            not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)) or
            (not directory and info.st_nlink != 1)):
        raise Unavailable('unsafe_attachment')


def open_directory(path):
    """Pin every ancestor, refusing symlinks including intermediate components."""
    path = Path(os.path.abspath(str(path)))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:]:
            new = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                          dir_fd=fd)
            os.close(fd)
            fd = new
        _private(os.fstat(fd), directory=True)
        return fd
    except BaseException:
        os.close(fd)
        raise


class Capture:
    """One pass, retained descriptors, attachment+inventory+byte stability.

    Existing lock inodes are probed briefly and released before record reads.
    Rechecking both probes and every attachment brackets an optimistic snapshot;
    this does not claim atomicity against a malicious same-uid writer.
    """
    def __init__(self, root):
        self.root = Path(root)
        self.fds = []
        self.directories = []
        self.files = []
        self.total = 0

    def __enter__(self):
        fd = open_directory(self.root)
        self.fds.append(fd)
        names = tuple(sorted(os.listdir(fd)))
        if len(names) > MAX_FILES:
            os.close(fd)
            raise Unavailable('inventory_bound')
        self.directories.append((None, None, fd, identity(os.fstat(fd)), names))
        return self

    def directory(self, relative):
        fd = self.fds[0]
        prefix = ''
        for part in Path(relative).parts:
            prefix += '/' + part
            known = next((entry[2] for entry in self.directories if entry[1] == prefix), None)
            if known is not None:
                fd = known
                continue
            parent = fd
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            self.fds.append(fd)
            _private(os.fstat(fd), directory=True)
            names = tuple(sorted(os.listdir(fd)))
            if len(names) > MAX_FILES:
                raise Unavailable('inventory_bound')
            self.directories.append((parent, prefix, fd, identity(os.fstat(fd)), names))
        return fd

    def names(self, relative):
        try:
            fd = self.directory(relative)
        except FileNotFoundError:
            return []
        return sorted(os.listdir(fd))

    def read(self, relative, raw=False):
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise Unavailable('unsafe_attachment')
        parent = self.directory(str(path.parent)) if str(path.parent) != '.' else self.fds[0]
        fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        try:
            info = os.fstat(fd)
            _private(info)
            if info.st_size > MAX_RECORD or len(self.files) >= MAX_FILES:
                raise Unavailable('record_bound')
            chunks, remaining = [], info.st_size + 1
            while remaining:
                chunk = os.read(fd, min(remaining, 65536))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            body = b''.join(chunks)
            self.total += len(body)
            if self.total > MAX_BYTES or len(body) != info.st_size or identity(os.fstat(fd)) != identity(info):
                raise Unavailable('concurrent_change')
            self.files.append((parent, path.name, identity(info), hashlib.sha256(body).digest()))
        finally:
            os.close(fd)
        return body if raw else json.loads(body.decode('utf-8'), object_pairs_hook=_unique,
                                          parse_constant=_constant)

    def verify(self):
        # Content hash plus inode/metadata: detect replacements, rewrites and
        # append-only journals; a directory attachment change is also fatal.
        attached = open_directory(self.root)
        try:
            if identity(os.fstat(attached)) != self.directories[0][3]:
                raise Unavailable('concurrent_change')
        finally:
            os.close(attached)
        for parent, prefix, fd, before, names in self.directories:
            if identity(os.fstat(fd)) != before or tuple(sorted(os.listdir(fd))) != names:
                raise Unavailable('concurrent_change')
            if parent is not None and identity(os.stat(prefix.rsplit('/', 1)[-1], dir_fd=parent,
                                                       follow_symlinks=False)) != before:
                raise Unavailable('concurrent_change')
        for parent, name, before, digest in self.files:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                if identity(os.fstat(fd)) != before:
                    raise Unavailable('concurrent_change')
                body = b''
                while len(body) <= before[5]:
                    chunk = os.read(fd, min(65536, before[5] + 1 - len(body)))
                    if not chunk:
                        break
                    body += chunk
                if hashlib.sha256(body).digest() != digest or identity(os.fstat(fd)) != before:
                    raise Unavailable('concurrent_change')
            finally:
                os.close(fd)

    def __exit__(self, *exc):
        for fd in reversed(self.fds):
            os.close(fd)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Unavailable('record_invalid')
        result[key] = value
    return result


def _constant(value):
    raise Unavailable('record_invalid')


def probe(path):
    """Never create a lock or retain it during capture/aggregation."""
    path = Path(path)
    try:
        parent = open_directory(path.parent)
    except FileNotFoundError:
        return None
    try:
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        except FileNotFoundError:
            return None
        try:
            _private(os.fstat(fd))
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            result = identity(os.fstat(fd))
            fcntl.flock(fd, fcntl.LOCK_UN)
            return result
        except BlockingIOError:
            raise Unavailable('lock_busy') from None
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def capture_records(root, workflow_root=None, locks=()):
    """Read selected roots only. Archive is never an active run index."""
    import contextlib
    records, errors = {}, []
    lock_paths = list(locks) + [Path(root) / '.lock']
    with contextlib.ExitStack() as stack:
        before = [probe(p) for p in lock_paths]
        source = stack.enter_context(Capture(root))

        def read(reader, name, key=None, raw=False):
            try:
                records[key or name] = reader.read(name, raw=raw)
            except FileNotFoundError:
                pass
            except (OSError, ValueError, UnicodeError, RecursionError):
                errors.append({'record': key or name, 'reason': 'record_unavailable'})

        read(source, 'loop/state.json')
        read(source, 'loop/legacy-index.json')
        for folder in ('scans', 'proposals', 'approvals', 'claims', 'decisions', 'executions',
                       'loop/invalidated', 'loop/publications', 'loop/ledgers'):
            for name in source.names(folder):
                if not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}\.json', name):
                    raise Unavailable('unsafe_inventory')
                read(source, folder + '/' + name)
        if any(k.startswith(('approvals/', 'claims/')) for k in records):
            read(source, 'authority.key', raw=True)
        run_ids = sorted({v.get('run_id') for k, v in records.items()
                          if k.startswith('claims/') and isinstance(v, dict)
                          and isinstance(v.get('run_id'), str) and RUN.fullmatch(v['run_id'])})
        workflow_capture = None
        if workflow_root and run_ids:
            try:
                workflow_capture = stack.enter_context(Capture(workflow_root))
            except (OSError, ValueError):
                errors.append({'record': 'workflows', 'reason': 'active_journal_unavailable'})
        for run_id in run_ids:
            if workflow_capture:
                run_lock = Path(workflow_root) / run_id / 'github.lock'
                lock_paths.append(run_lock)
                before.append(probe(run_lock))
                for name in ('report.json', 'github.json', 'github-approved.json',
                             'archive-state.json', 'archive-transfer.json'):
                    read(workflow_capture, run_id + '/' + name, 'workflows/' + run_id + '/' + name)
        source.verify()
        if workflow_capture:
            workflow_capture.verify()
        if before != [probe(p) for p in lock_paths]:
            raise Unavailable('concurrent_change')
    return records, errors


def read_proof(scan):
    try:
        return review_coverage.validate(scan) is True
    except (TypeError, ValueError, KeyError, RecursionError):
        return False


def domain(files):
    groups = set()
    for name in files or []:
        if not isinstance(name, str):
            groups.add('unknown')
        elif name.startswith(('downloader/', 'parser_tidy/', 'TavernofSoul/')):
            groups.add('product')
        elif name.startswith('harness/'):
            groups.add('harness')
        elif name.startswith('docs/'):
            groups.add('docs')
        elif '/' not in name:
            groups.add('root_meta')
        else:
            groups.add('unknown')
    return next(iter(groups)) if len(groups) == 1 else 'mixed' if groups else 'unknown'


def ledgers(records, state):
    days = state.get('days', {})
    if isinstance(days, dict):
        for date, day in sorted(days.items()):
            if isinstance(day, dict):
                yield 'loop/state.json:days:' + date, day
    for name, value in sorted(records.items()):
        if name.startswith('loop/ledgers/') and isinstance(value, dict):
            yield name, value


def source_cohorts(records, scans, state):
    """Join producer ownership, never scan format, clocks or review receipts.

    Participation can be migrated daily history. Only a retained legacy index
    disambiguates history-only links; explicit round/slot ownership stands alone.
    A daily entry in imported history is not contradictory tick ownership.
    """
    tick, daily, history, copies, clocks = {}, {}, {}, {}, {}

    def link(target, sid, evidence, at=None):
        if isinstance(sid, str) and sid:
            target.setdefault(sid, set()).add(evidence)
            if timestamp(at):
                clocks.setdefault(sid, at)

    index = records.get('loop/legacy-index.json')
    indexed = (isinstance(index, dict) and isinstance(index.get('legacy'), list) and
               all(isinstance(e, dict) and isinstance(e.get('scan_id'), str) and
                   bool(e['scan_id']) for e in index['legacy']))
    if indexed:
        for entry in index['legacy']:
            link(daily, entry['scan_id'], 'loop/legacy-index.json:legacy')
    active = (state.get('round') or {}).get('report')
    if original(active):
        link(tick, active.get('scan_id'), 'loop/state.json:round', active.get('started_at'))
    for entry in state.get('completed', []) if isinstance(state.get('completed', []), list) else []:
        if isinstance(entry, dict):
            link(tick, entry.get('scan_id'), 'loop/state.json:completed', entry.get('at'))
    for name, value in records.items():
        if name.startswith('loop/invalidated/') and original(value):
            link(tick, value.get('scan_id'), name, value.get('started_at'))
        if name.startswith('loop/publications/') and isinstance(value, dict):
            report = value.get('report')
            if isinstance(report, dict):
                link(copies, report.get('scan_id'), name,
                     report.get('generated_at') or value.get('at'))
        if (name.startswith(('scans/', 'loop/invalidated/')) and isinstance(value, dict) and
                not original(value) and value.get('scan_id') not in scans):
            link(copies, value.get('scan_id'), 'report_materialization', value.get('generated_at'))
    if isinstance(active, dict) and not original(active) and active.get('scan_id') not in scans:
        link(copies, active.get('scan_id'), 'report_materialization', active.get('generated_at'))
    for name, day in ledgers(records, state):
        for sid in day.get('legacy_seen', []) if isinstance(day.get('legacy_seen', []), list) else []:
            link(daily, sid, name + ':legacy_seen')
        slots = day.get('slots', {})
        if isinstance(slots, dict):
            for slot, entry in slots.items():
                if isinstance(entry, dict):
                    link(tick, entry.get('scan_id'), name + ':slots:' + slot,
                         entry.get('started_at') or entry.get('at'))
    for field in ('participation', 'local_history'):
        entries = state.get(field, [])
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    link(history, entry.get('scan_id'), 'loop/state.json:' + field, entry.get('started_at'))
    result = {}
    for sid in sorted(set(scans) | set(tick) | set(daily) | set(history) | set(copies)):
        hard, nonhourly, imported = tick.get(sid, set()), daily.get(sid, set()), history.get(sid, set())
        if sid in copies:
            kind, reason = 'materialization', 'morning_report_materialization'
        elif sid not in scans:
            kind, reason = 'unknown', 'original_scan_unavailable'
        elif hard and nonhourly:
            kind, reason = 'unknown', 'conflicting_execution_ownership'
        elif nonhourly:
            kind, reason = 'nonhourly', 'daily_or_development_source'
        elif hard or (imported and indexed):
            kind, reason = 'hourly', 'tick_execution_source'
        else:
            kind, reason = 'unknown', ('legacy_index_unavailable_for_history' if imported else
                                       'execution_source_unavailable')
        scan = scans.get(sid, {})
        result[sid] = {'scan_id': sid, 'source': kind, 'reason': reason,
                       'at': (clocks.get(sid) if kind == 'materialization' else
                              scan.get('started_at') or scan.get('generated_at') or clocks.get(sid)),
                       'evidence': sorted(hard | nonhourly | imported | copies.get(sid, set()))}
    return result


def original(scan):
    return (isinstance(scan, dict) and isinstance(scan.get('scan_id'), str) and
            'report_window' not in scan and 'morning_aggregate' not in scan)


def originals(records):
    scans = {}
    for key, value in sorted(records.items()):
        if key.startswith('scans/') and original(value):
            scans[value['scan_id']] = value
    state = records.get('loop/state.json', {})
    active = (state.get('round') or {}).get('report')
    if original(active):
        scans[active['scan_id']] = active
    for key, value in records.items():
        if key.startswith('loop/invalidated/') and original(value):
            scans[value['scan_id']] = value
    return scans, state


def period_bounds(period, date, now, scans):
    end_date = dt.date.fromisoformat(date) if date else now.astimezone(KST).date()
    if period == 'latest':
        stamps = [timestamp(s.get('started_at') or s.get('generated_at')) for s in scans.values()]
        end_date = max((s.astimezone(KST).date() for s in stamps if s), default=end_date)
    length = {'latest': 1, 'day': 1, '7d': 7, '30d': 30}[period]
    end = dt.datetime.combine(end_date + dt.timedelta(days=1), dt.time(), KST)
    return end - dt.timedelta(days=length), min(end, now)


def inside(value, bounds):
    value = timestamp(value)
    return bool(value and bounds[0] <= value < bounds[1])


def attempts(scans, state, excluded=None, records=None):
    """Union originals/history/settled slots by scan/stage/slot; first failure wins.

    Source classification is separate; migrated daily history is deduplicated
    with its original agents before its observed calls are counted as excluded.
    """
    merged = {}
    excluded = excluded if excluded is not None else []

    def add(value, scan_id=None, local=False):
        if not isinstance(value, dict):
            excluded.append({'scan_id': scan_id, 'reason': 'attempt_malformed'})
            return
        if value.get('status') in ('skipped', 'not_called'):
            return
        linked = value.get('scan_id', scan_id)
        if not isinstance(linked, str) or linked not in scans or (scan_id is not None and linked != scan_id):
            excluded.append({'scan_id': linked if isinstance(linked, str) else None,
                             'at': value.get('started_at'), 'role': value.get('owner_role', value.get('role')),
                             'reason': 'original_scan_unavailable'})
            return
        role = value.get('owner_role', value.get('role'))
        index = value.get('stage_index')
        if index is None and role in ROLES:
            index = 8 if role == 'reviewer' else 2 * ROLES.index(role) + (0 if local else 1)
        expected = (8 if role == 'reviewer' else 2 * ROLES.index(role) + (0 if local else 1)) if role in ROLES else None
        if type(index) is not int or index != expected or (local and role == 'reviewer'):
            excluded.append({'scan_id': linked, 'at': value.get('started_at'), 'role': role,
                             'reason': 'attempt_stage_malformed'})
            return
        at = value.get('started_at')
        slot = value.get('slot') or (timestamp(at).astimezone(KST).strftime('%Y-%m-%dT%H')
                                      if timestamp(at) else None)
        scan_id = linked
        if not isinstance(slot, str) or not slot or not timestamp(at):
            excluded.append({'scan_id': linked, 'at': at, 'role': role, 'reason': 'attempt_clock_unavailable'})
            return
        key = (scan_id, index, slot)
        old = merged.get(key, {})
        new = dict(old)
        new.update(value)
        new.update(scan_id=scan_id, role=role, stage_index=index, slot=slot, local=local)
        if old.get('status') in ('failed', 'unavailable'):
            new['status'] = old['status']
            new['reason'] = old.get('reason')
        merged[key] = new

    records = records or {}
    index = records.get('loop/legacy-index.json', {})
    if isinstance(index, dict) and isinstance(index.get('participation'), list):
        for entry in index['participation']:
            add(entry)
    for local, field in ((False, 'participation'), (True, 'local_history')):
        history = state.get(field, [])
        if not isinstance(history, list):
            excluded.append({'scan_id': None, 'reason': 'history_malformed'})
            continue
        if field in state and state.get('version') != LOOP_VERSION:
            for entry in history:
                if isinstance(entry, dict):
                    excluded.append({'scan_id': entry.get('scan_id'), 'at': entry.get('started_at'),
                                     'role': entry.get('owner_role', entry.get('role')),
                                     'reason': 'history_version_unknown'})
            continue
        for entry in history:
            add(entry, local=local)
    for _, day in ledgers(records, state):
        slots = day.get('slots', {})
        if isinstance(slots, dict):
            for slot, entry in slots.items():
                if isinstance(entry, dict) and entry.get('scan_id') and entry.get('started_at'):
                    stage = entry.get('stage_index')
                    add(dict(entry, slot=slot), local=type(stage) is int and stage < 8 and stage % 2 == 0)
    for scan in scans.values():
        for local, field in ((False, 'agents'), (True, 'local_participation')):
            agents = scan.get(field, [])
            if not isinstance(agents, list):
                excluded.append({'scan_id': scan['scan_id'], 'reason': 'attempts_malformed'})
                continue
            for entry in agents:
                add(entry, scan['scan_id'], local)
    return sorted(merged.values(), key=lambda e: (e.get('started_at') or '', e['scan_id'], e['stage_index']))


def called(entry):
    if entry.get('status') in ('skipped', 'not_called', 'reserved') or entry.get('called') is False:
        return False
    if timestamp(entry.get('call_started_at')):
        return True
    if entry.get('local'):
        # _remember stores call clocks, but not the local adapter's called flag.
        if entry.get('called') is True:
            return True
    return bool(entry.get('provider') and entry.get('model') and
                entry.get('reason') != 'role_preparation_failed' and
                (numeric(entry.get('elapsed_seconds')) is not None or
                 elapsed(entry.get('started_at'), entry.get('finished_at')) is not None))


def round_rows(scans, state, entries, records, bounds, role):
    active_report = (state.get('round') or {}).get('report')
    active = active_report['scan_id'] if original(active_report) else None
    invalid = {v.get('scan_id') for k, v in records.items()
               if k.startswith('loop/invalidated/') and original(v)}
    rows = []
    ordered = sorted(scans.values(), key=lambda s: (s.get('started_at', s.get('generated_at', '')), s['scan_id']))
    for pos, scan in enumerate(ordered):
        own = [e for e in entries if e['scan_id'] == scan['scan_id'] and
               timestamp(e.get('started_at')) and timestamp(e['started_at']) < bounds[1]]
        at = scan.get('started_at') or scan.get('generated_at')
        if not inside(at, bounds) or (role and not any(e['role'] == role for e in own)):
            continue
        proof = read_proof(scan)
        successor = any(timestamp(s.get('started_at') or s.get('generated_at')) and
                        timestamp(at) and timestamp(s.get('started_at') or s.get('generated_at')) > timestamp(at)
                        and timestamp(s.get('started_at') or s.get('generated_at')) < bounds[1]
                        for s in ordered[pos + 1:])
        if scan['scan_id'] in invalid:
            status = 'invalidated'
        elif proof and inside(scan.get('review_completed_at') or next((e.get('finished_at') for e in own
                                if e['role'] == 'reviewer'), None), (dt.datetime.min.replace(tzinfo=KST), bounds[1])):
            status = 'completed'
        elif scan.get('review_complete'):
            status = 'unknown'
        elif successor:
            status = 'superseded'
        elif scan['scan_id'] == active and state.get('stage_index', 0) < 9:
            reason = state.get('pause_reason') or ''
            status = 'held' if any(word in reason for word in ('budget', 'quota', 'limit', 'paused', 'policy')) else 'in_progress'
        elif any(e.get('status') in ('failed', 'unavailable') for e in own):
            status = 'failed'
        else:
            status = 'unknown'
        starts = [timestamp(e.get('call_started_at')) for e in own if called(e)]
        starts = [v for v in starts if v]
        finish = next((e.get('call_finished_at') for e in reversed(own)
                       if e['role'] == 'reviewer' and e.get('status') == 'succeeded'), None)
        rows.append({'scan_id': scan['scan_id'], 'at': at, 'status': status,
                     'elapsed_seconds': elapsed(min(starts).isoformat(), finish) if starts and proof else None,
                     'failures': [{'stage_index': e['stage_index'], 'reason': code(e.get('reason'))}
                                  for e in own if e.get('status') in ('failed', 'unavailable')]})
    return rows


def code(value):
    # Only identifiers, never free-form diagnostics or provider exception text.
    allowed = {'unknown', 'empty_draft', 'transport_failed', 'timeout', 'interrupted_unknown',
               'input_invalid', 'local_response_invalid', 'source_review_unverified',
               'dependencies_changed', 'legacy_snapshot_unavailable', 'evidence_outside_window'}
    from harness.improvements import ROLE_FAILURE_REASONS
    return value if isinstance(value, str) and value in allowed | ROLE_FAILURE_REASONS else 'unknown'


def candidate_rows(scans, bounds, role):
    """Admission cohort; verdicts observed before period end only. OR union is transitive."""
    occurrences = []
    for scan in scans.values():
        at = scan.get('started_at') or scan.get('generated_at')
        if not timestamp(at) or timestamp(at) >= bounds[1]:
            continue
        proof = read_proof(scan)
        reviewed_at = scan.get('review_completed_at') or next((e.get('finished_at') for e in scan.get('agents', [])
                                                             if e.get('role') == 'reviewer'), None)
        proof = proof and timestamp(reviewed_at) is not None and timestamp(reviewed_at) < bounds[1]
        for record in scan.get('proposals', []):
            if (not isinstance(record, dict) or not ID.fullmatch(str(record.get('id', ''))) or
                    not re.fullmatch(r'[0-9a-f]{64}', str(record.get('digest', '')))):
                continue
            occurrences.append({'record': record, 'scan': scan, 'at': at, 'proof': proof,
                                'reviewed_at': reviewed_at})
    parent = list(range(len(occurrences)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen = {}
    for i, event in enumerate(occurrences):
        record = event['record']
        for kind in ('id', 'digest'):
            value = record.get(kind)
            if not isinstance(value, str) or not value:
                continue
            key = (kind, value)
            if key in seen:
                parent[find(i)] = find(seen[key])
            seen[key] = i
    groups = {}
    for i, event in enumerate(occurrences):
        groups.setdefault(find(i), []).append(event)
    rows = []
    for group in groups.values():
        group.sort(key=lambda e: (timestamp(e['at']), e['scan']['scan_id']))
        first = group[0]
        if not inside(first['at'], bounds):
            continue
        # Only explicit retained provenance fields support an origin role.
        origin = first['record'].get('origin_role')
        origin = origin if origin in contract.SPECIALIST_ROLES else None
        if role and origin != role:
            continue
        verified = [e for e in group if e['proof'] and e['record'].get('review', {}).get('verdict') in VERDICTS[:3]]
        verified.sort(key=lambda e: (timestamp(e['reviewed_at']), e['scan']['scan_id']))
        latest = verified[-1] if verified else group[-1]
        record = latest['record']
        verdict = (record['review']['verdict'] if verified else
                   'unknown' if any(e['scan'].get('review_complete') for e in group) else 'review_incomplete')
        rows.append({'id': first['record']['id'], 'ids': sorted({e['record']['id'] for e in group}),
                     'digest': record.get('digest'), 'first_at': first['at'],
                     'latest_review_at': latest['reviewed_at'] if verified else None,
                     'origin_role': origin, 'verdict': verdict,
                     'domain': domain(record.get('candidate', {}).get('edit_files')),
                     'repetitions': len(group) - 1, 'local_derivation': 'unknown'})
    return sorted(rows, key=lambda e: (e['first_at'], e['id']))


def morning_rows(records, scans, bounds, candidates):
    rows = []
    cohort = {pid for c in candidates for pid in c['ids']}
    for name, journal in sorted(records.items()):
        if not name.startswith('loop/publications/') or not isinstance(journal, dict):
            continue
        report = journal.get('report', {})
        window = report.get('report_window', {})
        start, end = timestamp(window.get('start')), timestamp(window.get('end'))
        if not end or not start or not inside(end.isoformat(), bounds):
            continue
        # Never substitute current dependencies for the frozen selection input.
        dependencies = report.get('loop_dependencies')
        frozen = report.get('proposals', [])
        payload = journal.get('payload', {})
        cards = payload.get('proposals')
        complete_payload = isinstance(cards, list) and bool(contract.verify_web_digest(payload))
        selected = {p.get('id') for p in frozen}
        exposed = {p.get('id') for p in cards} if complete_payload else set()
        losses, pool = [], {}
        for scan in sorted(scans.values(), key=lambda s: (s.get('review_completed_at', ''), s['scan_id'])):
            reviewed = timestamp(scan.get('review_completed_at'))
            if not reviewed or reviewed >= end or not read_proof(scan):
                continue
            for proposal in scan.get('proposals', []):
                pid = proposal['id']
                verdict = proposal.get('review', {}).get('verdict', 'unknown')
                reason = ('outside_window' if reviewed < start else
                          'dependency_digest_mismatch' if dependencies is not None and scan.get('loop_dependencies') != dependencies
                          else 'provenance_unavailable' if dependencies is None else None)
                pool[pid] = (proposal, scan, verdict, reason)
        usable = []
        provenance_unknown = []
        for pid, (proposal, scan, verdict, reason) in pool.items():
            # Frozen membership proves historical provenance. Current overwritten
            # proposal records cannot prove the reason for historical absence.
            if reason is None and pid not in selected:
                saved = records.get('proposals/' + pid + '.json', {})
                if not (saved.get('proposal') == proposal and saved.get('scan_id') == scan['scan_id'] and
                        saved.get('review_complete') is True):
                    reason = 'provenance_unavailable'
                    provenance_unknown.append(pid)
            if reason:
                if pid in cohort:
                    losses.append({'id': pid, 'verdict': verdict, 'reason': reason})
            else:
                usable.append(proposal)
        usable.sort(key=lambda p: ({'high': 0, 'medium': 1, 'low': 2}.get(
            p.get('candidate', {}).get('priority'), 3), p['id']))
        projected = {p['id'] for p in usable[:8]}
        projection_matches = projected == selected
        for index, p in enumerate(usable):
            if p['id'] not in cohort:
                continue
            if p['id'] not in selected:
                losses.append({'id': p['id'], 'verdict': p.get('review', {}).get('verdict', 'unknown'),
                               'reason': 'top8' if projection_matches and index >= 8 else 'provenance_unavailable'})
            elif p['id'] not in exposed and complete_payload:
                losses.append({'id': p['id'], 'verdict': p.get('review', {}).get('verdict', 'unknown'),
                               'reason': 'top3'})
        rows.append({'date': journal.get('date'), 'window': window,
                     'selected': sorted(selected & cohort), 'exposed': sorted(exposed & cohort),
                     'delivery': journal.get('status') if journal.get('status') in
                         ('delivered', 'prepared', 'publication_pending', 'publication_unknown', 'sending') else 'unknown',
                     'losses': losses, 'top8': {'status': 'available' if projection_matches and not provenance_unknown else 'unavailable',
                                               'basis': 'retained original proofs, matching proposal provenance and frozen projection'},
                     'projection_limit': journal.get('projection_limit'),
                     'payload_status': 'available' if complete_payload else 'unavailable'})
    return rows


def _signed(raw, key):
    if not isinstance(raw, dict) or not isinstance(key, bytes) or len(key) != 32:
        raise Unavailable('authorization_unavailable')
    body = {k: v for k, v in raw.items() if k != 'signature'}
    signature = raw.get('signature')
    expected = hmac.new(key, contract.canonical_json(body), hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise Unavailable('authorization_unavailable')
    return body


def approval_evidence(records, pid, proposal, scan, cutoff):
    approval = _signed(records.get('approvals/' + pid + '.json'), records.get('authority.key'))
    decision = records.get('decisions/' + pid + '.json', {})
    issued, expires = timestamp(approval.get('issued_at')), timestamp(approval.get('expires_at'))
    context = (contract.digest({'dependencies': scan['loop_dependencies'], 'scan_id': scan['scan_id'],
                               'source_review_binding': scan['source_review_binding']})
               if scan.get('loop_dependencies') and read_proof(scan) else None)
    if (approval.get('version') != 'improvement-approval-v1' or approval.get('authority') != 'trusted-parent' or
            approval.get('proposal_id') != pid or approval.get('proposal_digest') != proposal.get('digest') or
            approval.get('review_digest') != contract.digest(proposal.get('review')) or
            approval.get('source_fingerprints') != proposal.get('source_fingerprints') or
            approval.get('allowed_edit_files') != proposal.get('candidate', {}).get('edit_files') or
            approval.get('discovery_fingerprint') != context or not read_proof(scan) or
            approval.get('consumption') != 'unconsumed' or
            approval.get('publication') not in ('local-only', 'commit/pr/three-required-ci/squash-merge/cleanup') or
            not isinstance(approval.get('instruction'), str) or not approval['instruction'].strip() or
            not issued or not expires or not issued < expires or expires - issued > dt.timedelta(days=7) or
            issued >= cutoff or decision.get('status') != 'approved' or
            not re.fullmatch(r'[0-9a-f]{48}', str(approval.get('authorization_id', ''))) or
            not timestamp(decision.get('at')) or timestamp(decision['at']) >= cutoff or
            decision.get('authorization_id') != approval.get('authorization_id')):
        raise Unavailable('authorization_unavailable')
    return approval


def conversion_rows(records, scans, candidates, bounds):
    rows, run_ids = [], set()
    for candidate in candidates:
        if candidate['verdict'] != 'eligible':
            continue
        row = {'id': candidate['id'], 'approval': 'waiting', 'execution': 'waiting',
               'validation': 'waiting', 'pr': 'waiting', 'ci3': 'waiting',
               'merge': 'waiting', 'cleanup': 'waiting', 'run_id': None, 'merge_sha': None}
        for pid in candidate['ids']:
            saved = records.get('proposals/' + pid + '.json', {})
            proposal = saved.get('proposal', {})
            scan = scans.get(saved.get('scan_id'), {})
            decision = records.get('decisions/' + pid + '.json', {})
            if decision.get('status') == 'rejected' and inside(decision.get('at'),
                    (dt.datetime.min.replace(tzinfo=KST), bounds[1])):
                row['approval'] = 'rejected'
            if 'approvals/' + pid + '.json' not in records:
                continue
            try:
                approval = approval_evidence(records, pid, proposal, scan, bounds[1])
                row['approval'] = 'passed'
                claim_name = 'claims/' + pid + '.json'
                if claim_name not in records:
                    continue
                claim = _signed(records[claim_name], records.get('authority.key'))
                at = timestamp(claim.get('at'))
                from harness.improvements import _task
                task = _task(proposal, approval)
                if (claim.get('version') != 'improvement-claim-v1' or claim.get('proposal_id') != pid or
                        claim.get('proposal_digest') != proposal.get('digest') or
                        claim.get('authorization_id') != approval.get('authorization_id') or not at or
                        not timestamp(approval['issued_at']) <= at < timestamp(approval['expires_at']) or at >= bounds[1] or
                        claim.get('task_digest') != hashlib.sha256(task.encode('utf-8')).hexdigest() or
                        not re.fullmatch(r'[0-9a-f]{48}', str(claim.get('claim_id', ''))) or
                        claim.get('status') not in ('claimed', 'running', 'consumed')):
                    raise Unavailable('claim_unavailable')
                run_id = claim.get('run_id')
                if not isinstance(run_id, str) or not RUN.fullmatch(run_id):
                    row['execution'] = 'waiting'
                    continue
                row.update(execution='passed', run_id=run_id)
                run_ids.add(run_id)
                prefix = 'workflows/' + run_id + '/'
                report, github = records.get(prefix + 'report.json'), records.get(prefix + 'github.json')
                if not isinstance(report, dict) or report.get('run_id') != run_id:
                    row.update(validation='unavailable', pr='unavailable', ci3='unavailable',
                               merge='unavailable', cleanup='unavailable')
                    continue
                linked_claims = [c for k, c in records.items() if k.startswith('claims/') and
                                 isinstance(c, dict) and c.get('run_id') == run_id]
                from harness.improvements import workflow
                if len(linked_claims) == 1 and report.get('task_sha256') != workflow.triage.digest(task):
                    raise Unavailable('task_binding_unavailable')
                row['events'] = [{'at': e.get('time'), 'state': e['state'],
                                  'phase': e['phase'] if e.get('phase') in
                                  ('prepare', 'triage', 'plan', 'implement', 'review', 'validate', 'apply', 'github', 'complete') else 'unknown'}
                                 for e in report.get('events', []) if e.get('state') in
                                 ('failed', 'passed', 'interrupted', 'awaiting_ci', 'cleanup_pending', 'merged') and
                                 timestamp(e.get('time')) and timestamp(e['time']) < bounds[1]]
                # Mutable terminal reports without a finish time cannot certify
                # that success already existed before a historical cutoff.
                finish = timestamp(report.get('finished_at'))
                if finish and finish >= bounds[1]:
                    continue
                checks = report.get('delivery_validation', [])
                required = report.get('required_checks', [])
                def groups_pass(check):
                    groups = check.get('checks')
                    return (isinstance(groups, dict) and bool(groups) and
                            all(isinstance(g, dict) and g.get('status') == 'passed' and
                                type(g.get('selected')) is int and g['selected'] > 0 and
                                g.get('passed') == g['selected'] and
                                all(g.get(key) == [] for key in ('failures', 'errors', 'skipped'))
                                for g in groups.values()))
                validation = (bool(required) and len(checks) == len(required) and
                              {c.get('command') for c in checks} == set(required) and
                              all(c.get('status') == 'passed' and c.get('exit_code') == 0 and
                                  groups_pass(c)
                                  for c in checks))
                row['validation'] = 'passed' if validation and finish else 'failed' if report.get('status') == 'failed' else 'unavailable'
                if not isinstance(github, dict) or github.get('run_id') != run_id:
                    row.update(pr='unavailable', ci3='unavailable', merge='unavailable', cleanup='unavailable')
                    continue
                github_events = [e for e in report.get('events', []) if e.get('provider') == 'github']
                latest_git = timestamp(github_events[-1].get('time')) if github_events else None
                if not latest_git or latest_git >= bounds[1]:
                    row.update(pr='unavailable', ci3='unavailable', merge='unavailable', cleanup='unavailable')
                    continue
                publication = records.get(prefix + 'github-approved.json', {})
                authorized = set(approval['allowed_edit_files'])
                scope = set(report.get('scope', []))
                changed = set(report.get('changed_files', []))
                # Multiple independently signed claims may share one run. Their
                # task digest is checked individually and scope is the union.
                for other_name, raw_claim in records.items():
                    if not other_name.startswith('claims/') or not isinstance(raw_claim, dict) or raw_claim.get('run_id') != run_id:
                        continue
                    other = _signed(raw_claim, records.get('authority.key'))
                    other_pid = other.get('proposal_id')
                    if other_pid == pid:
                        continue
                    saved_other = records.get('proposals/' + str(other_pid) + '.json', {})
                    other_proposal = saved_other.get('proposal', {})
                    other_approval = approval_evidence(records, other_pid, other_proposal,
                                                      scans.get(saved_other.get('scan_id'), {}), bounds[1])
                    if (other.get('authorization_id') != other_approval.get('authorization_id') or
                            other.get('proposal_digest') != other_proposal.get('digest') or
                            other.get('task_digest') != hashlib.sha256(_task(other_proposal, other_approval).encode('utf-8')).hexdigest()):
                        raise Unavailable('bundle_unavailable')
                    authorized.update(other_approval['allowed_edit_files'])
                publication_valid = (scope == authorized and bool(changed) and changed <= scope and
                                     set(report.get('applied', [])) == changed and
                                     set(publication.get('files', {})) == changed)
                number = github.get('pr_number')
                row['pr'] = 'passed' if publication_valid and type(number) is int and number > 0 else 'waiting'
                expected = {name: 'success' for name in REQUIRED_CI}
                proof = github.get('cleanup_proof', {})
                head, merge = github.get('head_sha'), github.get('merge_sha')
                pinned = (isinstance(head, str) and SHA.fullmatch(head) and proof.get('head_sha') == head)
                row['ci3'] = ('passed' if pinned and github.get('checks') == expected and proof.get('checks') == expected
                              else 'failed' if any(s in ('failure', 'cancelled', 'timed_out')
                                                   for s in github.get('checks', {}).values()) else 'waiting')
                merged = (finish and report.get('read_only') is False and report.get('simulated') is False and
                          report.get('no_git') is False and report.get('github_enabled') is True and
                          validation and publication_valid and row['ci3'] == 'passed' and report.get('review', {}).get('verdict') == 'approved' and
                          github.get('merge_status') == 'merged' and isinstance(merge, str) and SHA.fullmatch(merge) and
                          proof.get('merge_sha') == merge and proof.get('verified') is True)
                row['merge'] = 'passed' if merged else 'waiting'
                row['merge_sha'] = merge if merged else None
                cleanup = github.get('cleanup', {})
                done = (merged and github.get('status') == 'merged' and github.get('step') == 'done' and
                        report.get('status') == 'passed' and cleanup.get('version') == 'cleanup-v1' and
                        cleanup.get('status') == 'complete' and
                        all(cleanup.get(k, {}).get('status') in ('deleted', 'absent') for k in ('remote', 'local')) and
                        all(cleanup.get(k, {}).get('status') == 'complete' for k in ('prune', 'sync', 'completion')))
                row['cleanup'] = 'passed' if done else 'waiting'
                archive = records.get(prefix + 'archive-state.json', {})
                row['archive'] = archive.get('status') if archive.get('run_id') == run_id and archive.get('status') in ('pending', 'archived') else 'unavailable'
            except (ValueError, KeyError, TypeError, AttributeError):
                row['approval'] = 'unavailable'
        rows.append(row)
    return rows, run_ids


def efficiency(entries, bounds, role):
    selected = [e for e in entries if inside(e.get('started_at'), bounds) and
                (not role or e.get('role') == role) and called(e)]
    groups = {}
    for e in selected:
        provider = e.get('provider') if e.get('provider') in ('codex', 'zai', 'claude', 'mlx-vlm', 'mlx-lm') else 'unknown'
        key = (e.get('role') if e.get('role') in ROLES else 'unknown', provider)
        groups.setdefault(key, []).append(e)
    rows = []
    for (owner, provider), group in sorted(groups.items()):
        tokens = {}
        for field in TOKEN_FIELDS:
            observed = [numeric((e.get('agent_usage') or e.get('usage') or {}).get(field)) for e in group]
            known = [v for v in observed if v is not None]
            tokens[field] = {'known_sum': sum(known) if known else None,
                             'known_calls': len(known), 'unknown_calls': len(group) - len(known)}
        costs = [numeric(e.get('cost')) for e in group if e.get('cost_status') == 'cli_estimated_usd'] if provider == 'claude' else []
        costs = [v for v in costs if v is not None]
        telemetry = [e.get('telemetry') for e in group]
        from harness.agent_telemetry import sanitize
        telemetry = [sanitize(t) for t in telemetry]
        logical = [t['logical_requests_observed'] for t in telemetry if t and t.get('logical_requests_observed') is not None]
        rows.append({'role': owner, 'provider': provider, 'slots': len(group),
                     'success': sum(e.get('status') in ('passed', 'succeeded') for e in group),
                     'failed': sum(e.get('status') in ('failed', 'unavailable') for e in group),
                     'duration_seconds': stats(elapsed(e.get('call_started_at'), e.get('call_finished_at')) for e in group),
                     'tokens': tokens, 'claude_estimated_usd': sum(costs) if costs else None,
                     'cost_known_calls': len(costs), 'billing': 'CLI 추정; 실제 청구 아님' if provider == 'claude' else
                     'local calls' if provider.startswith('mlx-') else 'subscription calls',
                     'glm_logical_requests_observed': sum(logical) if logical else None,
                     'glm_observed_records': len(logical), 'unexported_requests': 'unknown'})
    return selected, rows


def aggregate(records, period='latest', date=None, role=None, now=None, errors=()):
    now = now or dt.datetime.now(dt.timezone.utc)
    retained, state = originals(records)
    sources = source_cohorts(records, retained, state)
    scans = {sid: scan for sid, scan in retained.items() if sources[sid]['source'] == 'hourly'}
    bounds = period_bounds(period, date, now, scans)
    scope = {'period': period, 'start': bounds[0].isoformat(), 'end_exclusive': bounds[1].isoformat(),
             'timezone': 'Asia/Seoul', 'role': role, 'population': 'retained hourly admission cohort'}
    unavailable = []
    originals_only = {sid: scan for sid, scan in retained.items() if sources[sid]['source'] != 'materialization'}
    all_entries = attempts(originals_only, state, unavailable, records)
    entries = [e for e in all_entries if sources[e['scan_id']]['source'] == 'hourly']
    nonhourly, _ = efficiency([e for e in all_entries if sources[e['scan_id']]['source'] == 'nonhourly'], bounds, role)

    def selected_attempt(entry):
        return inside(entry.get('at') or entry.get('started_at'), bounds) and (not role or entry.get('role') == role)

    # Every coverage number and diagnostic uses this query's period. A missing
    # clock remains visible separately rather than entering a dated denominator.
    scoped_sources = [s for s in sources.values() if inside(s['at'], bounds) and
                      (not role or any(e.get('scan_id') == s['scan_id'] and e.get('role') == role
                                       for e in all_entries + unavailable))]
    excluded = [{'scan_id': e['scan_id'], 'stage_index': e['stage_index'], 'slot': e['slot'],
                 'at': e['started_at'], 'reason': sources[e['scan_id']]['reason']}
                for e in all_entries if sources[e['scan_id']]['source'] != 'hourly' and selected_attempt(e)]
    excluded.extend(e for e in unavailable if selected_attempt(e) and
                    sources.get(e.get('scan_id'), {}).get('source') != 'materialization')
    untimed = [e for e in unavailable if not timestamp(e.get('at')) and
               sources.get(e.get('scan_id'), {}).get('source') != 'materialization']
    errors = list(errors)
    errors.extend({'record': 'scans/' + s['scan_id'] + '.json', 'reason': s['reason']}
                  for s in scoped_sources if s['source'] == 'unknown')
    if any(sources.get(e['scan_id'], {}).get('source') not in ('nonhourly', 'materialization') for e in excluded) or untimed:
        errors.append({'record': 'hourly_attempts', 'reason': 'attempts_unavailable_or_unclassified'})
    rounds = round_rows(scans, state, entries, records, bounds, role)
    counts = {name: sum(r['status'] == name for r in rounds) for name in STATES}
    candidates = candidate_rows(scans, bounds, role)
    drafts = (state.get('round') or {}).get('drafts', {})
    for candidate in candidates:
        for owner, feedback in state.get('feedback', {}).items():
            batch = drafts.get(owner, {}).get('candidates')
            if batch is not None and any(e.get('candidate_id') in candidate['ids'] and
                                         e.get('draft_digest') == contract.digest(batch) for e in feedback):
                candidate['local_derivation'] = 'linked_retained_draft_batch'
    verdicts = {v: sum(c['verdict'] == v for c in candidates) for v in VERDICTS}
    mornings = morning_rows(records, scans, bounds, candidates)
    conversions, run_ids = conversion_rows(records, scans, candidates, bounds)
    research, costs = efficiency(entries, bounds, role)
    implementation = []
    untimed_implementation = 0
    for run_id in sorted(run_ids):
        report = records.get('workflows/' + run_id + '/report.json', {})
        running = [e for e in report.get('events', []) if e.get('agent_started') is True]
        for i, agent in enumerate(report.get('agents', [])):
            matching = next((e for e in running if e.get('role') == agent.get('role') and
                             e.get('phase') == agent.get('phase') and e.get('task_id') == agent.get('task_id')), None)
            if matching:
                running.remove(matching)
            at = agent.get('started_at') or (matching or {}).get('time')
            if not timestamp(at):
                untimed_implementation += 1
            implementation.append(dict(agent, scan_id=run_id, stage_index=i, local=False,
                                       started_at=at, call_started_at=agent.get('started_at'),
                                       call_finished_at=agent.get('finished_at')))
    implementation_calls, implementation_costs = efficiency(implementation, bounds, role)
    local = [e for e in research if e.get('local')]
    stages = []
    for index in range(9):
        own = [e for e in research if e['stage_index'] == index]
        failures = {}
        for e in own:
            if e.get('status') in ('failed', 'unavailable'):
                reason = code(e.get('reason'))
                failures[reason] = failures.get(reason, 0) + 1
        stages.append({'stage_index': index, 'calls': len(own),
                       'success': sum(e.get('status') == 'succeeded' for e in own),
                       'failed': sum(e.get('status') in ('failed', 'unavailable') for e in own),
                       'reasons': failures, 'duration_seconds': stats(elapsed(e.get('call_started_at'), e.get('call_finished_at')) for e in own)})
    approved = sum(c['approval'] == 'passed' for c in conversions)
    merged = sum(c['cleanup'] == 'passed' for c in conversions)
    return {'version': 'improvement-metrics-v1', 'privacy': 'private stdout', 'scope': scope,
            'status': 'partial' if errors else 'available', 'unavailable_records': list(errors),
            'coverage': {'history': 'bounded retained subset; absence is not zero',
                         'scans': sum(s['source'] != 'materialization' and s['scan_id'] in retained for s in scoped_sources),
                         'hourly_scans': sum(s['source'] == 'hourly' for s in scoped_sources),
                         'excluded_nonhourly_role_calls': len(nonhourly),
                         'nonhourly_scans': sum(s['source'] == 'nonhourly' for s in scoped_sources),
                         'legacy_non_loop_scans': sum(s['source'] == 'nonhourly' for s in scoped_sources),
                         'legacy_non_loop_scans_basis': 'compatibility alias of nonhourly_scans; producer source, not scan format',
                         'unknown_source_scans': sum(s['source'] == 'unknown' for s in scoped_sources),
                         'unknown_format_scans': sum(s['source'] == 'unknown' for s in scoped_sources),
                         'unknown_format_scans_basis': 'compatibility alias of unknown_source_scans',
                         'excluded_materialization_scans': sum(s['source'] == 'materialization' for s in scoped_sources),
                         'source_scans': scoped_sources,
                         'sources_without_period_clock': [s for s in sources.values() if not timestamp(s['at'])],
                         'excluded_attempts': excluded,
                         'attempts_without_period_clock': untimed,
                         'raw_generated_candidates': None, 'raw_generation_status': 'unavailable: not persisted',
                         'archive': 'unavailable: active linked records only; no archive search',
                         'budget_ledger': 'reservations excluded from observed CLI costs',
                         'candidate_clock': 'first retained round admission; only reviews before period end',
                         'historical_mutable_records': 'latest retained state; missing event clocks unavailable'},
            'rounds': {'counts': counts, 'items': rounds, 'stages': stages,
                       'completion': ratio(counts['completed'], counts['completed'] + counts['failed'] + counts['superseded'], scope),
                       'duration_seconds': stats(r['elapsed_seconds'] for r in rounds),
                       'local_valid_draft_calls': ratio(sum(e.get('status') == 'succeeded' for e in local), len(local), scope),
                       'local_draft_cardinality': None, 'local_lineage': 'unknown'},
            'funnel': {'generated': None, 'validated_retained': len(candidates), 'verdicts': verdicts,
                       'reviewed': sum(verdicts[v] for v in VERDICTS[:3]), 'eligible': verdicts['eligible'],
                       'independent_review_pass': ratio(verdicts['eligible'], sum(verdicts[v] for v in VERDICTS[:3]), scope),
                       'duplicates': sum(c['repetitions'] for c in candidates), 'candidates': candidates,
                       'domains': {d: sum(c['domain'] == d for c in candidates) for d in
                                   ('product', 'harness', 'docs', 'root_meta', 'mixed', 'unknown')},
                       'morning_status': 'observed' if mornings else 'unavailable: no reporting opportunity observed',
                       'mornings': mornings, 'selected': len({p for m in mornings for p in m['selected']}) if mornings else None,
                       'exposed': len({p for m in mornings for p in m['exposed']}) if mornings else None},
            'conversion': {'items': conversions, 'unique_runs': len(run_ids),
                           'stages': {stage: {s: sum(c[stage] == s for c in conversions) for s in
                                             ('passed', 'waiting', 'rejected', 'failed', 'unavailable')}
                                      for stage in ('approval', 'execution', 'validation', 'pr', 'ci3', 'merge', 'cleanup')},
                           'approval_rate': ratio(approved, verdicts['eligible'], scope),
                           'merge_completion_rate': ratio(merged, approved, scope)},
            'efficiency': {'research_slots': len(research), 'implementation_slots': len(implementation_calls),
                           'implementation_slots_without_admission_clock': untimed_implementation,
                           'local_calls': len(local), 'research': costs, 'implementation': implementation_costs,
                           'calls_per_eligible': ratio(len(research), verdicts['eligible'], scope, 'calls_per_candidate'),
                           'calls_per_merge': ratio(len(implementation_calls), merged, scope, 'calls_per_merge')},
            'post_merge_effect': {'status': 'excluded'},
            'comparison': {'status': 'unavailable', 'reason': 'adjacent period not independently calculated'}}


def render_text(result):
    if result.get('status') == 'unavailable':
        return '성과 집계: unavailable (' + result['reason'] + ')\n'
    scope = result['scope']
    lines = ['성과 집계 (private)', '{} ~ {} (끝 제외, Asia/Seoul), 역할 {}'.format(
        scope['start'], scope['end_exclusive'], scope['role'] or '전체'),
        '범위: 보존된 hourly 기록; 누락 이력은 0으로 간주하지 않음',
        '회차: ' + json.dumps(result['rounds']['counts'], ensure_ascii=False),
        '후보: ' + json.dumps(result['funnel']['verdicts'], ensure_ascii=False)]
    lines.append('실행 출처 hourly/nonhourly/unknown: {}/{}/{}; 제외된 참여 기록 {}; 상태 {}'.format(
        result['coverage']['hourly_scans'], result['coverage']['legacy_non_loop_scans'],
        result['coverage']['unknown_format_scans'], len(result['coverage']['excluded_attempts']), result['status']))
    lines.append('제외된 nonhourly 역할 호출: {}; 오전 복제: {}'.format(
        result['coverage']['excluded_nonhourly_role_calls'], result['coverage']['excluded_materialization_scans']))
    for label, item in [('완주율', result['rounds']['completion']),
                        ('독립 검토 통과율', result['funnel']['independent_review_pass']),
                        ('승인율', result['conversion']['approval_rate']),
                        ('병합 완료율', result['conversion']['merge_completion_rate']),
                        ('eligible당 연구 호출', result['efficiency']['calls_per_eligible']),
                        ('병합당 구현 호출', result['efficiency']['calls_per_merge'])]:
        value = '미산출' if item['value'] is None else ('{:.2f}'.format(item['value']) if item['unit'].startswith('calls_')
                                                       else '{:.1%}'.format(item['value']))
        lines.append('{}: {}/{} = {}'.format(label, item['numerator'], item['denominator'], value))
    lines.append('오전 선택/노출: {}/{}; {}'.format(result['funnel']['selected'], result['funnel']['exposed'],
                                                result['funnel']['morning_status']))
    for morning in result['funnel']['mornings']:
        reasons = {}
        for loss in morning['losses']:
            key = loss['reason'] + '/' + loss['verdict']
            reasons[key] = reasons.get(key, 0) + 1
        lines.append('{} 손실 {} / 전달 {}'.format(morning['date'], json.dumps(reasons, ensure_ascii=False), morning['delivery']))
    lines.append('연구/구현/local 호출: {}/{}/{}'.format(result['efficiency']['research_slots'],
                  result['efficiency']['implementation_slots'], result['efficiency']['local_calls']))
    lines.append('시간 통계 n/중앙값/p90/최대: ' + json.dumps(result['rounds']['duration_seconds'], ensure_ascii=False))
    lines.append('생성 원수·local 유래·미관측 토큰: unavailable/unknown. 지표 4 제외. 비용은 CLI 추정이며 실제 청구액 아님.')
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--period', choices=('latest', 'day', '7d', '30d'), default='latest')
    parser.add_argument('--date')
    parser.add_argument('--role', choices=ROLES)
    parser.add_argument('--format', choices=('json', 'text'), default='text')
    parser.add_argument('--workflow-storage-config', help='Explicit separate active workflow storage config')
    args = parser.parse_args(argv)
    if args.date:
        try:
            if dt.date.fromisoformat(args.date).isoformat() != args.date:
                raise ValueError()
        except ValueError:
            parser.error('DATE must be YYYY-MM-DD')
    try:
        from harness import storage
        root = Path(__file__).resolve().parent.parent
        selected = storage.resolve_storage(root)
        workflow_selected = selected
        if args.workflow_storage_config:
            env = dict(os.environ, HARNESS_STORAGE_CONFIG=os.path.abspath(args.workflow_storage_config))
            # A report override for improvement records must not redirect an
            # explicitly separately selected workflow root back to that store.
            env.pop('HARNESS_REPORT_DIR', None)
            workflow_selected = storage.resolve_storage(root, env=env)
        report_root = selected.report_dir('improvements', local_default=root / 'logs/harness/improvements')
        workflow_root = workflow_selected.workflow_root(local_default=root / 'logs/harness/workflows')
        lock = selected.project_lock_path
        records, errors = capture_records(report_root, workflow_root,
                            locks=(lock, lock.with_name('.discovery-lock'), lock.with_name('.workflow-lock')))
        result = aggregate(records, args.period, args.date, args.role, errors=errors)
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        result = {'version': 'improvement-metrics-v1', 'status': 'unavailable',
                  'reason': 'consistent_private_read_unavailable'}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) if args.format == 'json'
          else render_text(result), end='\n' if args.format == 'json' else '')
    return 0 if result.get('status') != 'unavailable' else 1


if __name__ == '__main__':
    raise SystemExit(main())
