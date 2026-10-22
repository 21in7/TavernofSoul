"""Private discovery-only Read receipts. No model self-report is evidence.

The trusted parent feeds CLI stdout directly to Capture, never response text.
Only paired top-level Claude assistant/user events with structured Read results
prove reads. Observed bounded rate-limit advisories are discarded. Unknown CLI
formats fail closed; ordinary workflow is unchanged.
Receipts retain hashes/ranges, not source, stdout, tool text or host paths.
Same-uid rewriting of the private Store remains outside the trust boundary.
"""
import ast
import hashlib
import json
from pathlib import Path
import re

from harness import improvement_report as contract

VERSION = 'source-read-review-v1'
MAX_STDOUT = 524288
MAX_STDERR = 16384
MAX_WINDOWS = 32
MAX_SOURCE = 32768
MAX_EVENTS = 256
MAX_CODE_LINES = 96
MAX_RATE_LIMIT_BYTES = 8192
MAX_RATE_LIMIT_NODES = 256
MAX_RATE_LIMIT_DEPTH = 8


def fail():
    raise ValueError('source_review_unverified')


def _sha(body):
    return hashlib.sha256(body).hexdigest()


def event_json(value):
    """Private stream bound; do not broaden the ordinary model JSON parser."""
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                fail()
            result[key] = item
        return result
    try:
        if type(value) is not str or len(value.encode('utf-8')) > MAX_STDOUT:
            fail()
        result = json.loads(value, object_pairs_hook=pairs,
                            parse_constant=lambda _: fail())
        contract.canonical_json(result)
        return result
    except (ValueError, TypeError, RecursionError):
        fail()


def _rate_limit_metadata(event, line):
    """Validate only the observed advisory envelope; discard every value.

    Optional info is bounded JSON, not Read, identity, cost, status or diagnostic
    authority. Even a 'rejected' advisory cannot override the actual CLI result.
    """
    if (len(line.encode('utf-8')) > MAX_RATE_LIMIT_BYTES or
            set(event) != {'type', 'rate_limit_info', 'uuid', 'session_id'} or
            any(type(event[k]) is not str or not 1 <= len(event[k].encode('utf-8')) <= 128
                for k in ('uuid', 'session_id'))):
        fail()
    info = event['rate_limit_info']
    if (not isinstance(info, dict) or type(info.get('status')) is not str or
            info['status'] not in ('allowed', 'allowed_warning', 'rejected')):
        fail()
    stack, nodes = [(event, 0)], 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_RATE_LIMIT_NODES or depth > MAX_RATE_LIMIT_DEPTH:
            fail()
        if isinstance(value, dict):
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)


def _lines(source):
    # Original range bytes for hashes/evidence; never use as CLI projection.
    body = source['content'].decode('utf-8')
    if not body:
        return []
    pieces = body.split('\n')
    return [p + '\n' for p in pieces[:-1]] + ([pieces[-1]] if pieces[-1] else [])


def _cli_lines(source):
    # Claude text Read strips one initial BOM, splits on LF (including a
    # terminal empty line), and removes one terminal CR from each line.
    body = source['content'].decode('utf-8')
    if body.startswith('\ufeff'):
        body = body[1:]
    return [line[:-1] if line.endswith('\r') else line for line in body.split('\n')]


def _program_path(path):
    name = Path(path).name
    return (path.endswith('.py') and name not in ('config.py', 'settings.py', 'conftest.py') and
            not name.endswith(('_config.py', '_settings.py')) and
            not {'config', 'settings'}.intersection(Path(path).parts[:-1]))


def _code_sample(source):
    """Find executable Python beyond leading imports/comments/docstrings.

    The approved runtime owners currently contain Python programs. Unknown
    languages/configuration are not promoted to code by guessing. Parsing is
    only sample selection, never execution or a whole-file semantic review.
    """
    try:
        tree = ast.parse(source['content'].decode('utf-8-sig'))
    except (UnicodeError, SyntaxError, ValueError, RecursionError):
        fail()

    def first_body(nodes):
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.Pass)):
                continue
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Str):
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                line = first_body(node.body)
                if line is not None:
                    return line
            else:
                return node.lineno
        return None

    # Prefer a function body over module-level constants/setup that may form a
    # long header. Scripts without functions can still expose executable work.
    functions = sorted((n for n in ast.walk(tree) if isinstance(
        n, (ast.FunctionDef, ast.AsyncFunctionDef))), key=lambda n: n.lineno)
    line = next((found for found in (first_body(n.body) for n in functions)
                 if found is not None), None)
    if line is None:
        line = first_body(tree.body)
    if line is None:
        fail()
    # Include nearby context, but anchor the window on an actual body statement
    # even when an import/header/docstring is longer than the sample budget.
    start = max(1, line - 8)
    return start, min(len(_lines(source)), start + MAX_CODE_LINES - 1)


def plan(paths, snapshots, records, owners, shared):
    """Small explicit sample per existing owner when empty; evidence otherwise.

    A document sample supports the mandatory documentation judgment. Large
    evidence cannot silently be sampled: exceeding the bound fails the review.
    No source bytes are inserted into the prompt.
    """
    contract.validate_scope_paths(paths, 37)
    ranges = []

    def add(path, start, end, purpose):
        if path not in paths or not snapshots[path]['exists']:
            fail()
        lines = _lines(snapshots[path])
        if (type(start) is not int or type(end) is not int or
                not 1 <= start <= end <= len(lines) or end - start >= 256):
            fail()
        ranges.append((path, start, end, purpose))

    if records:
        for record in records:
            c = record['candidate']
            for item in c['evidence'] + c['benefit']['evidence']:
                add(item['path'], item['start_line'], item['end_line'], 'evidence')
            for path in c['edit_files']:
                if path.endswith('.md') and snapshots[path]['exists']:
                    add(path, 1, min(12, len(_lines(snapshots[path]))), 'documentation')
    else:
        for role in contract.SPECIALIST_ROLES:
            members = [p for p in owners[role] if p in paths and p not in shared and _program_path(p)]
            # Prefer production programs to tests without changing membership
            # or ownership. Domain AGENTS/config order cannot certify coverage.
            members.sort(key=lambda p: ('/tests/' in p or Path(p).name.startswith('test_')))
            if not members:
                fail()  # absent/empty/no program target is incomplete coverage
            path = members[0]
            if not snapshots[path]['exists'] or not _lines(snapshots[path]):
                fail()  # do not mask the selected program's absence with docs/tests
            start, end = _code_sample(snapshots[path])
            add(path, start, end, role)
    docs = [p for p in paths if p in shared and p.endswith('.md') and
            snapshots[p]['exists'] and _lines(snapshots[p])]
    if not docs:
        fail()
    add(docs[0], 1, min(12, len(_lines(snapshots[docs[0]]))), 'documentation')
    merged = []
    for path, start, end, purpose in sorted(ranges):
        if merged and merged[-1]['path'] == path and start <= merged[-1]['end_line'] + 1:
            merged[-1]['end_line'] = max(end, merged[-1]['end_line'])
            merged[-1]['purposes'] = sorted(set(merged[-1]['purposes'] + [purpose]))
        else:
            merged.append(dict(path=path, start_line=start, end_line=end, purposes=[purpose]))
    total = 0
    fingerprints = contract.fingerprint_sources(snapshots)
    for window in merged:
        if window['end_line'] - window['start_line'] >= 256:
            fail()
        data = ''.join(_lines(snapshots[window['path']])[window['start_line'] - 1:window['end_line']]).encode('utf-8')
        total += len(data)
        window.update(sha256=_sha(data), size=len(data), source=fingerprints[window['path']])
    if not 1 <= len(merged) <= MAX_WINDOWS or total > MAX_SOURCE:
        fail()
    return merged


class Capture:
    """One-call capability supplied by parent, never reconstructed from JSON."""
    def __init__(self, root, snapshots, windows):
        self.root = str(Path(root).absolute())
        self.snapshots = snapshots
        self.windows = windows
        self.receipts = None
        self.consumed = False

    def accept(self, stdout):
        if self.consumed:
            fail()
        self.consumed = True
        # Parse only real top-level events; strings containing traces are data.
        if not isinstance(stdout, str) or len(stdout.encode('utf-8')) > MAX_STDOUT:
            fail()
        lines = stdout.splitlines()
        if not 1 <= len(lines) <= MAX_EVENTS:
            fail()
        events = [event_json(line) for line in lines]
        pending, seen, receipts, final = {}, set(), [], None
        for event, line in zip(events, lines):
            if not isinstance(event, dict):
                fail()
            kind = event.get('type')
            if kind == 'rate_limit_event':
                _rate_limit_metadata(event, line)
                continue
            if final is not None:
                fail()
            if kind == 'result':
                if event.get('is_error') is not False or event.get('subtype') != 'success' or pending:
                    fail()
                final = event
                continue
            if kind not in ('assistant', 'user'):
                if kind != 'system':
                    fail()
                continue
            message = event.get('message')
            if not isinstance(message, dict) or message.get('role') != kind:
                fail()
            content = message.get('content')
            if not isinstance(content, list):
                fail()
            for block in content:
                if not isinstance(block, dict):
                    fail()
                if block.get('type') == 'tool_use':
                    identity = block.get('id')
                    if (kind != 'assistant' or type(identity) is not str or
                            not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identity) or identity in seen or
                            block.get('name') != 'Read'):
                        fail()
                    seen.add(identity)
                    request = block.get('input')
                    if not isinstance(request, dict) or set(request) != {'file_path', 'offset', 'limit'}:
                        fail()
                    path = request['file_path']
                    matches = [p for p in self.snapshots if path in (p, self.root + '/' + p)]
                    if len(matches) != 1:
                        fail()  # no path aliases, normalization or traversal
                    path = matches[0]
                    start, limit = request['offset'], request['limit']
                    if type(start) is not int or type(limit) is not int or not 1 <= limit <= 256:
                        fail()
                    target = [w for w in self.windows if w['path'] == path and
                              w['start_line'] == start and w['end_line'] == start + limit - 1]
                    if len(target) != 1:
                        fail()
                    pending[identity] = target[0]
                elif block.get('type') == 'tool_result':
                    identity = block.get('tool_use_id')
                    if kind != 'user' or identity not in pending or block.get('is_error', False) is not False:
                        fail()
                    window = pending.pop(identity)
                    result = event.get('tool_use_result')
                    if not isinstance(result, dict) or set(result) != {'type', 'file'} or result['type'] != 'text':
                        fail()
                    file = result['file']
                    expected_path = self.root + '/' + window['path']
                    source = _cli_lines(self.snapshots[window['path']])
                    expected = '\n'.join(source[window['start_line'] - 1:window['end_line']])
                    if (not isinstance(file, dict) or set(file) != {
                            'filePath', 'content', 'numLines', 'startLine', 'totalLines'} or
                            file['filePath'] not in (window['path'], expected_path) or
                            type(file['numLines']) is not int or type(file['startLine']) is not int or
                            type(file['totalLines']) is not int or
                            file['startLine'] != window['start_line'] or
                            file['numLines'] != window['end_line'] - window['start_line'] + 1 or
                            file['totalLines'] != len(source) or file['content'] != expected):
                        fail()
                    # Raw structured successful result is authoritative. Rendered
                    # tool text is never parsed for events, ranges or authority.
                    if any(r['window'] == window for r in receipts):
                        fail()
                    receipts.append({'window': window, 'tool_id_sha256': _sha(identity.encode('ascii'))})
                elif block.get('type') not in ('text', 'thinking'):
                    fail()
        if final is None or pending or len(receipts) != len(self.windows):
            fail()
        self.receipts = sorted(receipts, key=lambda r: self.windows.index(r['window']))
        return final


def assessments(value, windows):
    if not isinstance(value, list) or len(value) != len(windows):
        fail()
    result = []
    for index, item in enumerate(value):
        if (not isinstance(item, dict) or set(item) != {'window', 'assessment'} or
                type(item['window']) is not int or item['window'] != index or
                type(item['assessment']) is not str or not 24 <= len(item['assessment'].strip()) <= 720):
            fail()
        result.append(dict(window=index, assessment=contract.redact_text(item['assessment'].strip())))
    return result


def review_result(scan):
    return {'reviews': [dict(r['review'], candidate_id=r['id']) for r in scan['proposals']],
            'documentation': scan['documentation']}


def document_reads(review, windows):
    required = set(review['documentation']['files'])
    for item in review['reviews']:
        required.update(item['documentation']['files'])
    covered = {w['path'] for w in windows if 'documentation' in w['purposes']}
    if not required.issubset(covered):
        fail()


def attach(scan, proof):
    scan['source_review'] = proof
    scan['source_review_binding'] = binding(scan)


def binding(scan):
    return contract.digest({'scan_id': scan['scan_id'], 'proof': scan['source_review'],
                            'scope': scan['scope_fingerprint'],
                            'controls': scan.get('loop_dependencies', scan['config_fingerprint']),
                            'review': review_result(scan)})


def validate(scan, snapshots=None, owners=None, shared=None):
    """Revalidate private completion; missing legacy receipts never imply reads."""
    try:
        if scan.get('morning_aggregate') or not scan.get('review_complete'):
            fail()
        proof = scan['source_review']
        if set(proof) != {'version', 'plan', 'reads', 'assessments', 'fingerprints_digest', 'review_digest'}:
            fail()
        if proof['version'] != VERSION or proof['fingerprints_digest'] != contract.digest(scan['source_fingerprints']):
            fail()
        if 'loop_dependencies' in scan and (
                scan['loop_dependencies']['review_protocol'] != VERSION or
                scan['source_fingerprints'] != scan['loop_dependencies']['source_fingerprints'] or
                scan['scope_fingerprint'] != scan['loop_dependencies']['scope_fingerprint']):
            fail()
        windows = proof['plan']
        if not isinstance(windows, list) or not 1 <= len(windows) <= MAX_WINDOWS:
            fail()
        total = 0
        for window in windows:
            if (not isinstance(window, dict) or set(window) != {
                    'path', 'start_line', 'end_line', 'purposes', 'sha256', 'size', 'source'} or
                    window['path'] not in scan['approved_files'] or
                    contract.validate_path(window['path']) != window['path'] or
                    type(window['start_line']) is not int or type(window['end_line']) is not int or
                    not 1 <= window['start_line'] <= window['end_line'] or
                    window['end_line'] - window['start_line'] >= 256 or
                    type(window['size']) is not int or not 1 <= window['size'] <= MAX_SOURCE or
                    not re.fullmatch('[0-9a-f]{64}', window['sha256']) or
                    not isinstance(window['purposes'], list) or not window['purposes'] or
                    not set(window['purposes']).issubset(set(contract.SPECIALIST_ROLES) | {'evidence', 'documentation'})):
                fail()
            total += window['size']
        if total > MAX_SOURCE:
            fail()
        if not scan['proposals']:
            for role in contract.SPECIALIST_ROLES:
                samples = [w for w in windows if role in w['purposes']]
                if (not samples or any(not _program_path(w['path']) or
                        w['end_line'] - w['start_line'] >= MAX_CODE_LINES for w in samples)):
                    fail()
        if snapshots is not None and windows != plan(scan['approved_files'], snapshots, scan['proposals'], owners, shared):
            fail()
        if len(proof['reads']) != len(windows) or len({r['tool_id_sha256'] for r in proof['reads']}) != len(windows):
            fail()
        for window, read in zip(windows, proof['reads']):
            if read['window'] != window or not re.fullmatch('[0-9a-f]{64}', read['tool_id_sha256']):
                fail()
            if window['source'] != scan['source_fingerprints'][window['path']]:
                fail()
        assessments(proof['assessments'], windows)
        review = contract.validate_review(review_result(scan), scan['proposals'], scan['approved_files'])
        document_reads(review, windows)
        if proof['review_digest'] != contract.digest(review) or scan['source_review_binding'] != binding(scan):
            fail()
        if not any(a['role'] == 'reviewer' and a['provider'] == 'claude' and a['status'] == 'succeeded'
                   for a in scan['agents']):
            fail()
        return True
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        fail()
