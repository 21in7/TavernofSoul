"""Offline synthetic CLI receipts; fixtures are not real model observations."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import re

import pytest

from harness import review_coverage as coverage
from harness import agent_models, git_publish, improvements as imp, storage, triage, workflow

contract = coverage.contract
SOURCE_DOC = {"status": "not_required", "files": [],
              "reason": "읽기 전용 분석의 가상 지역 수정 제안으로 구조와 계약 변경이 없어 문서 수정은 필요하지 않습니다."}


def forbidden(*args, **kwargs):
    pytest.fail("Offline source fixture crossed a model/check/network boundary")


def candidate(path='harness/example.py', title='중복 점검 줄이기'):
    return {'title': title, 'priority': 'medium',
            'analogy': '정비사가 같은 나사를 두 번 살피는 점검표를 정리합니다.',
            'issue': '동일한 점검을 반복할 가능성을 검토해야 합니다.',
            'evidence': [{'path': path, 'start_line': 1, 'end_line': 2,
                          'summary': '점검 순서가 두 줄에 나뉘어 있습니다.'}],
            'benefit': {'kind': 'estimated', 'text': '미측정: 점검표를 읽는 부담 감소 예상.', 'evidence': []},
            'risk': '점검 누락 가능성을 별도 검토해야 합니다.', 'edit_files': [path],
            'validation_plan': ['해당 파일의 합성 입력으로 중복과 누락을 확인합니다.'],
            'documentation_impact': '지역 동작 보존 제안이며 구조와 권한 정책의 변경은 없습니다.'}

def add_assessments(response, capture):
    response['assessments'] = [dict(window=i, assessment=(
        '합성 소스의 지정 줄에서 입력 처리와 문서 경계를 확인했습니다. 이 표본 밖의 결함 여부는 판단하지 않습니다.'))
        for i in range(len(capture.windows))]


def read_events(capture, response='{"reviews": []}', files=None):
    """Synthetic CLI wire data, independent of production range helpers.

    Fixed contract cases supply literal file fields; integration fixtures project
    their own synthetic bytes without consulting coverage internals.
    """
    events = []
    for i, window in enumerate(capture.windows):
        path = capture.root + '/' + window['path']
        start, end = window['start_line'], window['end_line']
        if files is None:
            text = capture.snapshots[window['path']]['content'].decode('utf-8-sig')
            source = [re.sub(r'\r$', '', line) for line in text.split('\n')]
            file = dict(content='\n'.join(source[start - 1:end]),
                        numLines=end - start + 1, startLine=start, totalLines=len(source))
        else:
            file = dict(files[i])
        file['filePath'] = path
        events.append({'type': 'assistant', 'message': {'role': 'assistant', 'content': [
            {'type': 'tool_use', 'id': 'read_' + str(i), 'name': 'Read',
             'input': {'file_path': path, 'offset': start, 'limit': end - start + 1}}]}})
        events.append({'type': 'user', 'message': {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': 'read_' + str(i), 'is_error': False,
             'content': 'Synthetic rendered Read text; structured fields are authoritative.'}]},
            'tool_use_result': {'type': 'text', 'file': file}})
    if isinstance(response, bytes):
        response = response.decode('utf-8', 'replace')
    events.append({'type': 'result', 'subtype': 'success', 'is_error': False,
                   'result': response, 'total_cost_usd': .04})
    return events


def stdout(events):
    return '\n'.join(json.dumps(e, ensure_ascii=False) for e in events)


# Literal wire samples: no production parser/projection constructs expectations.
RATE_LIMIT_WIRE = r'{"type":"rate_limit_event","rate_limit_info":{"status":"allowed_warning","resetsAt":1792630800,"rateLimitType":"five_hour","utilization":0.75,"isUsingOverage":false,"errorCode":"PRIVATE_RATE_METADATA"},"uuid":"notice-uuid","session_id":"private-session"}'
READ_WIRE = r'''{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"literal_read","name":"Read","input":{"file_path":"harness/example.py","offset":1,"limit":2}}]}}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"literal_read","is_error":false,"content":"one\ntwo"}]},"tool_use_result":{"type":"text","file":{"filePath":"harness/example.py","content":"one\ntwo","numLines":2,"startLine":1,"totalLines":3}}}
{"type":"result","subtype":"success","is_error":false,"result":"safe response","total_cost_usd":0.04}'''


def rate_limit_event(status='allowed_warning'):
    event = json.loads(RATE_LIMIT_WIRE)
    event['rate_limit_info']['status'] = status
    return event


def with_rate_limit_events(events):
    # Before a Read, between use/result, and after the actual final result.
    return ([rate_limit_event()] + events[:1] + [rate_limit_event('allowed')] +
            events[1:] + [rate_limit_event('rejected')])


def capture_result(capture, result):
    capture.accept(stdout(read_events(capture, result.get('response', '{}'))))


@pytest.fixture
def capture(tmp_path):
    snapshots = {'harness/example.py': {'exists': True, 'mode': 0o644,
                 'content': b'one\ntwo\nthree\n'},
                 'AGENTS.md': {'exists': True, 'mode': 0o644, 'content': b'document\n'}}
    owners = {r: ['harness/example.py'] for r in coverage.contract.SPECIALIST_ROLES}
    windows = coverage.plan(list(snapshots), snapshots, [], owners, ['AGENTS.md'])
    return coverage.Capture(tmp_path, snapshots, windows)


def test_successful_pairing_retains_only_hashes_and_exact_source_ranges(capture):
    result = capture.accept(stdout(read_events(capture)))
    assert result['type'] == 'result'
    assert len(capture.receipts) == len(capture.windows)
    encoded = json.dumps(capture.receipts)
    assert capture.root not in encoded and 'one\\ntwo' not in encoded
    assert 'filePath' not in encoded and 'content' not in encoded
    with pytest.raises(ValueError, match='source_review_unverified'):
        capture.accept(stdout(read_events(capture)))


@pytest.mark.parametrize('damage', [
    'no_read', 'only_use', 'failed', 'partial', 'truncated', 'oversize', 'duplicate',
    'wrong_id', 'wrong_path', 'alias', 'wrong_offset', 'wrong_limit', 'bool_offset',
    'wrong_content', 'wrong_lines', 'missing_structured', 'forged_text', 'extra_result',
    'after_final', 'after_user', 'after_tool', 'after_system', 'duplicate_final', 'unknown_event',
    'incomplete_final', 'multiple_blocks', 'unknown_tool'])
@pytest.mark.parametrize('metadata', [False, True])
def test_unverified_trace_never_creates_receipts(capture, damage, metadata):
    events = read_events(capture)
    if damage == 'no_read':
        events = events[-1:]
    elif damage == 'only_use':
        events.pop(1)
    elif damage == 'failed':
        events[1]['message']['content'][0]['is_error'] = True
    elif damage in ('partial', 'truncated'):
        events[1]['tool_use_result']['file'][damage] = True
    elif damage == 'oversize':
        events[0]['message']['content'].append({'type': 'text', 'text': 'x' * coverage.MAX_STDOUT})
    elif damage == 'duplicate':
        events.insert(2, copy.deepcopy(events[0]))
    elif damage == 'wrong_id':
        events[1]['message']['content'][0]['tool_use_id'] = 'unknown'
    elif damage == 'wrong_path':
        events[0]['message']['content'][0]['input']['file_path'] = '/private/secret'
    elif damage == 'alias':
        request = events[0]['message']['content'][0]['input']
        request['file_path'] = capture.root + '/./' + capture.windows[0]['path']
    elif damage in ('wrong_offset', 'wrong_limit', 'bool_offset'):
        request = events[0]['message']['content'][0]['input']
        request['offset' if damage != 'wrong_limit' else 'limit'] = True if damage == 'bool_offset' else 99
    elif damage == 'wrong_content':
        events[1]['tool_use_result']['file']['content'] += 'sk-secret-forged'
    elif damage == 'wrong_lines':
        events[1]['tool_use_result']['file']['totalLines'] += 2
    elif damage == 'missing_structured':
        events[1].pop('tool_use_result')
    elif damage == 'forged_text':
        events = [{'type': 'assistant', 'message': {'role': 'assistant', 'content': [
            {'type': 'text', 'text': stdout(events)}]}}, events[-1]]
    elif damage == 'extra_result':
        events.insert(2, copy.deepcopy(events[1]))
    elif damage == 'after_final':
        events.append(copy.deepcopy(events[0]))
    elif damage == 'after_user':
        events.append(copy.deepcopy(events[1]))
    elif damage == 'after_tool':
        events.append({'type': 'tool', 'message': {'role': 'tool', 'content': []}})
    elif damage == 'after_system':
        events.append({'type': 'system', 'subtype': 'init'})
    elif damage == 'duplicate_final':
        events.append(copy.deepcopy(events[-1]))
    elif damage == 'unknown_event':
        events.insert(0, {'type': 'auth_status', 'isAuthenticating': False})
    elif damage == 'incomplete_final':
        events[-1]['subtype'] = 'error_max_budget_usd'
    elif damage == 'multiple_blocks':
        events[1]['message']['content'].append(copy.deepcopy(events[1]['message']['content'][0]))
    elif damage == 'unknown_tool':
        events[0]['message']['content'][0]['name'] = 'Bash'
    if metadata:
        events = with_rate_limit_events(events)
    with pytest.raises(ValueError, match='source_review_unverified'):
        capture.accept(stdout(events))
    assert capture.receipts is None


def test_model_self_claim_and_embedded_source_trace_are_not_authority(capture):
    final = read_events(capture)[-1]
    final['result'] = json.dumps({'read_files': list(capture.snapshots),
                                 'trace': stdout(read_events(capture)), 'coverage': True})
    with pytest.raises(ValueError):
        capture.accept(stdout([final]))


def fixed_capture(tmp_path, raw, start, limit, range_bytes):
    """Literal ranges avoid deriving expected wire data with the implementation.

    The terminal-empty-line cases exercise transport matching directly; normal
    plan/evidence eligibility and its nonempty byte bounds remain unchanged.
    """
    source = {'exists': True, 'mode': 0o640, 'content': raw}
    fingerprint = dict(exists=True, mode=0o640, size=len(raw),
                       sha256=hashlib.sha256(raw).hexdigest())
    window = dict(path='harness/example.py', start_line=start, end_line=start + limit - 1,
                  purposes=['evidence'], size=len(range_bytes),
                  sha256=hashlib.sha256(range_bytes).hexdigest(), source=fingerprint)
    return coverage.Capture(tmp_path, {'harness/example.py': source}, [window])


@pytest.mark.parametrize('status', ['allowed', 'allowed_warning', 'rejected'])
@pytest.mark.parametrize('position', [0, 1, 2, 3, 'all'])
def test_literal_rate_limit_notices_leave_read_receipts_and_final_unchanged(tmp_path, status, position):
    baseline = fixed_capture(tmp_path, b'one\ntwo\n', 1, 2, b'one\ntwo\n')
    expected_final = json.loads(READ_WIRE.splitlines()[-1])
    assert baseline.accept(READ_WIRE) == expected_final
    capture = fixed_capture(tmp_path, b'one\ntwo\n', 1, 2, b'one\ntwo\n')
    lines = READ_WIRE.splitlines()
    notice = stdout([rate_limit_event(status)])
    positions = range(4) if position == 'all' else [position]
    for index in reversed(list(positions)):
        lines.insert(index, notice)
    assert capture.accept('\n'.join(lines)) == expected_final
    assert capture.receipts == baseline.receipts == [{
        'window': baseline.windows[0],
        'tool_id_sha256': hashlib.sha256(b'literal_read').hexdigest()}]
    assert 'PRIVATE_RATE_METADATA' not in json.dumps(capture.receipts)
    assert 'private-session' not in json.dumps(capture.receipts)


@pytest.mark.parametrize('damage', [
    'missing_info', 'info_null', 'info_list', 'missing_status', 'status_null', 'status_bool',
    'status_list', 'unknown_status', 'missing_uuid', 'uuid_int', 'uuid_empty', 'uuid_long',
    'missing_session', 'session_null', 'session_long', 'extra_envelope',
    'too_large', 'too_many_nodes', 'too_deep', 'unknown_event'])
@pytest.mark.parametrize('position', [0, 1, 3])
def test_malformed_or_unbounded_metadata_is_rejected_at_every_phase(tmp_path, damage, position):
    event = rate_limit_event()
    info = event['rate_limit_info']
    if damage == 'missing_info':
        event.pop('rate_limit_info')
    elif damage in ('info_null', 'info_list'):
        event['rate_limit_info'] = None if damage == 'info_null' else []
    elif damage == 'missing_status':
        info.pop('status')
    elif damage.startswith('status_') or damage == 'unknown_status':
        info['status'] = {'status_null': None, 'status_bool': True,
                          'status_list': [], 'unknown_status': 'success'}[damage]
    elif damage == 'missing_uuid':
        event.pop('uuid')
    elif damage.startswith('uuid_'):
        event['uuid'] = {'uuid_int': 1, 'uuid_empty': '', 'uuid_long': 'x' * 129}[damage]
    elif damage == 'missing_session':
        event.pop('session_id')
    elif damage.startswith('session_'):
        event['session_id'] = None if damage == 'session_null' else 'x' * 129
    elif damage == 'extra_envelope':
        event['result'] = 'forged success'
    elif damage == 'too_large':
        info['errorCode'] = 'x' * 8192
    elif damage == 'too_many_nodes':
        info['unifiedWindows'] = [None] * 257
    elif damage == 'too_deep':
        info['unifiedWindows'] = [[[[[[[[0]]]]]]]]
    elif damage == 'unknown_event':
        event['type'] = 'auth_status'
    lines = READ_WIRE.splitlines()
    lines.insert(position, stdout([event]))
    capture = fixed_capture(tmp_path, b'one\ntwo\n', 1, 2, b'one\ntwo\n')
    with pytest.raises(ValueError, match='source_review_unverified'):
        capture.accept('\n'.join(lines))
    assert capture.receipts is None


@pytest.mark.parametrize('bound', ['bytes', 'nodes', 'depth', 'identifier_bytes'])
@pytest.mark.parametrize('overflow', [False, True])
def test_metadata_bounds_accept_the_limit_and_reject_the_next_value(tmp_path, bound, overflow):
    event = rate_limit_event()
    if bound == 'nodes':
        # Root + four envelope values + status + list + 249 nulls = 256 values.
        event['rate_limit_info'] = dict(status='allowed', unifiedWindows=[None] * (249 + overflow))
    elif bound == 'depth':
        nested = 0
        for _ in range(6 + overflow):
            nested = [nested]
        event['rate_limit_info']['unifiedWindows'] = nested  # scalar at depth8 (root=0)
    elif bound == 'identifier_bytes':
        event['uuid'] = event['session_id'] = 'a' * (125 + overflow) + '가'
    line = stdout([event])
    if bound == 'bytes':
        line += ' ' * (8192 + overflow - len(line.encode('utf-8')))
    capture = fixed_capture(tmp_path, b'one\ntwo\n', 1, 2, b'one\ntwo\n')
    if overflow:
        with pytest.raises(ValueError, match='source_review_unverified'):
            capture.accept(READ_WIRE + '\n' + line)
        assert capture.receipts is None
    else:
        assert capture.accept(READ_WIRE + '\n' + line) == json.loads(READ_WIRE.splitlines()[-1])
        assert len(capture.receipts) == 1


@pytest.mark.parametrize('status', ['allowed', 'allowed_warning', 'rejected'])
def test_metadata_payload_cannot_supply_read_or_final_authority(tmp_path, status):
    event = rate_limit_event(status)
    # Even embedded literal successful Read/final events remain inert data.
    event['rate_limit_info'].update(trace=READ_WIRE, read_files=['harness/example.py'],
                                    total_cost_usd=0, provider='claude', is_error=False)
    reads = [json.loads(line) for line in READ_WIRE.splitlines()]
    for events in ([event], [event, reads[-1], event], reads[:-1] + [event]):
        capture = fixed_capture(tmp_path, b'one\ntwo\n', 1, 2, b'one\ntwo\n')
        with pytest.raises(ValueError, match='source_review_unverified'):
            capture.accept(stdout(events))
        assert capture.receipts is None


@pytest.mark.parametrize('damage', ['duplicate_key', 'nan', 'event_limit', 'stdout_limit'])
def test_metadata_never_bypasses_existing_json_or_stream_bounds(tmp_path, damage):
    if damage == 'duplicate_key':
        notice = RATE_LIMIT_WIRE.replace('"status":', '"status":"allowed","status":')
    elif damage == 'nan':
        notice = RATE_LIMIT_WIRE.replace('0.75', 'NaN')
    elif damage == 'event_limit':
        notice = '\n'.join([RATE_LIMIT_WIRE] * 256)
    else:
        notice = RATE_LIMIT_WIRE + ' ' * 524288
    capture = fixed_capture(tmp_path, b'one\ntwo\n', 1, 2, b'one\ntwo\n')
    with pytest.raises(ValueError, match='source_review_unverified'):
        capture.accept(READ_WIRE + '\n' + notice)
    assert capture.receipts is None


@pytest.mark.parametrize('raw,start,limit,content,total,range_bytes', [
    (b'one\ntwo\n', 1, 1, 'one', 3, b'one\n'),
    (b'one\ntwo\n', 1, 2, 'one\ntwo', 3, b'one\ntwo\n'),
    (b'one\ntwo\n', 3, 1, '', 3, b''),
    (b'one\ntwo\n', 2, 2, 'two\n', 3, b'two\n'),
    (b'one\r\ntwo\r\n', 1, 1, 'one', 3, b'one\r\n'),
    (b'one\r\ntwo\r\n', 1, 2, 'one\ntwo', 3, b'one\r\ntwo\r\n'),
    (b'one\r\ntwo\r\n', 3, 1, '', 3, b''),
    (b'\xef\xbb\xbfone\ntwo\n', 1, 2, 'one\ntwo', 3, b'\xef\xbb\xbfone\ntwo\n'),
    (b'\xef\xbb\xbfone\r\ntwo\r\n', 1, 2, 'one\ntwo', 3, b'\xef\xbb\xbfone\r\ntwo\r\n'),
    (b'\xef\xbb\xbf\xef\xbb\xbfone', 1, 1, '\ufeffone', 1, b'\xef\xbb\xbf\xef\xbb\xbfone'),
    (b'one\ntwo', 1, 2, 'one\ntwo', 2, b'one\ntwo'),
    (b'one\ntwo', 2, 1, 'two', 2, b'two'),
    (b'one\n\ntwo\n', 2, 2, '\ntwo', 4, b'\ntwo\n'),
    (b'one\r\r\ntwo\r\n', 1, 2, 'one\r\ntwo', 3, b'one\r\r\ntwo\r\n'),
])
def test_exact_cli_projection_preserves_original_bytes_and_range_hash(
        tmp_path, raw, start, limit, content, total, range_bytes):
    capture = fixed_capture(tmp_path, raw, start, limit, range_bytes)
    original = copy.deepcopy(capture.snapshots)
    file = dict(content=content, numLines=limit, startLine=start, totalLines=total)
    events = read_events(capture, files=[file])
    # The shared engine/Store/approval fixtures must emit the same literal wire
    # representation, rather than only passing a matching production helper.
    assert read_events(capture) == events
    capture.accept(stdout(events))
    window = capture.receipts[0]['window']
    assert window['sha256'] == hashlib.sha256(range_bytes).hexdigest()
    assert window['size'] == len(range_bytes)
    assert window['source']['sha256'] == hashlib.sha256(raw).hexdigest()
    assert window['source']['mode'] == 0o640
    assert (window['start_line'], window['end_line']) == (start, start + limit - 1)
    assert capture.snapshots == original


@pytest.mark.parametrize('raw,start,limit,content,total', [
    (b'one\ntwo\n', 1, 1, 'one\n', 3),  # invented trailing LF
    (b'one\ntwo\n', 1, 2, 'one\ntwo\n', 3),
    (b'one\ntwo\n', 1, 1, 'one', 2),  # terminal empty line omitted
    (b'one\ntwo\n', 1, 2, 'one\ntwo', 4),
    (b'one\ntwo', 1, 2, 'one\ntwo', 3),  # nonexistent empty line counted
    (b'one\ntwo\n', 3, 1, '\n', 3),
    (b'one\ntwo\n', 2, 2, 'two', 3),  # real selected empty line lost
    (b'one\r\ntwo\r\n', 1, 1, 'one\r', 3),
    (b'one\r\ntwo\r\n', 1, 2, 'one\r\ntwo\r', 3),
    (b'\xef\xbb\xbfone\ntwo\n', 1, 1, '\ufeffone', 3),
    (b'\xef\xbb\xbf\xef\xbb\xbfone', 1, 1, 'one', 1),  # two BOMs removed
])
def test_noncanonical_cli_projection_is_rejected(tmp_path, raw, start, limit, content, total):
    capture = fixed_capture(tmp_path, raw, start, limit, raw)
    file = dict(content=content, numLines=limit, startLine=start, totalLines=total)
    with pytest.raises(ValueError, match='source_review_unverified'):
        capture.accept(stdout(read_events(capture, files=[file])))
    assert capture.receipts is None


@pytest.mark.parametrize('raw,content,total', [
    (b'one\ntwo\n', 'one\ntwo', 3),
    (b'one\r\ntwo\r\n', 'one\ntwo', 3),
    (b'\xef\xbb\xbfone\ntwo\n', 'one\ntwo', 3),
    (b'\xef\xbb\xbfone\r\ntwo\r\n', 'one\ntwo', 3),
    (b'one\ntwo', 'one\ntwo', 2),
])
def test_plan_binds_original_bytes_separately_from_cli_projection(tmp_path, raw, content, total):
    snapshots = {
        'harness/example.py': dict(exists=True, mode=0o640, content=raw),
        'AGENTS.md': dict(exists=True, mode=0o644, content=b'document\n'),
    }
    original = copy.deepcopy(snapshots)
    owners = {role: ['harness/example.py'] for role in coverage.contract.SPECIALIST_ROLES}
    windows = coverage.plan(list(snapshots), snapshots, [], owners, ['AGENTS.md'])
    source_window = next(w for w in windows if w['path'] == 'harness/example.py')
    assert (source_window['start_line'], source_window['end_line']) == (1, 2)
    assert source_window['size'] == len(raw)
    assert source_window['sha256'] == hashlib.sha256(raw).hexdigest()
    assert source_window['source'] == dict(exists=True, mode=0o640, size=len(raw),
                                          sha256=hashlib.sha256(raw).hexdigest())
    files = [dict(content='document', numLines=1, startLine=1, totalLines=2)
             if w['path'] == 'AGENTS.md' else
             dict(content=content, numLines=2, startLine=1, totalLines=total)
             for w in windows]
    capture = coverage.Capture(tmp_path, snapshots, windows)
    capture.accept(stdout(read_events(capture, files=files)))
    assert next(r['window'] for r in capture.receipts
                if r['window']['path'] == 'harness/example.py') == source_window
    assert snapshots == original


def test_raw_size_event_count_and_duplicate_json_keys_are_bounded(capture):
    for raw in ('x' * (coverage.MAX_STDOUT + 1),
                '\n'.join(['{}'] * (coverage.MAX_EVENTS + 1)),
                '{"type":"result","type":"result"}'):
        fresh = coverage.Capture(capture.root, capture.snapshots, capture.windows)
        with pytest.raises(ValueError):
            fresh.accept(raw)
        assert fresh.receipts is None


# Source/context ceilings stay covered here so the approved runtime test source
# remains within its unchanged per-file byte limit. No test imports back from
# test_improvements: its shared candidate/FixtureFS are re-exported from here.
@pytest.fixture
def offline_source_limits(monkeypatch):
    """Read shipped config only; never resolve operational storage or credentials."""
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(imp, 'ROOT', root)
    monkeypatch.setattr(imp, 'CONFIG', root / 'harness/improvement-config.json')
    for target, name in ((agent_models, 'load_keys'), (agent_models, 'run'),
                         (workflow, 'execute'), (workflow, 'run_check'),
                         (triage, 'observe'), (git_publish, 'prepare'),
                         (storage, 'resolve_storage'), (subprocess, 'run'),
                         (subprocess, 'Popen'), (imp.http.client, 'HTTPSConnection')):
        monkeypatch.setattr(target, name, forbidden)
    config = imp.load_config()
    assert config['limits']['max_file_bytes'] == 131072
    assert config['limits']['max_source_bytes'] == 1572864
    assert config['limits']['max_context_bytes'] == 2097152
    for key in ('max_source_bytes', 'max_context_bytes'):
        assert config['limits'][key] == contract.LIMIT_CEILINGS[key]
    return config


def test_default_project_scope_fits_configured_source_limits(offline_source_limits, tmp_path, monkeypatch):
    """Run locally in the full validation copy, never a scoped model context."""
    config = offline_source_limits
    scope, _ = imp._read_file(imp.ROOT / config['scope_file'], 65536)
    paths = contract.validate_scope_paths(scope.decode('utf-8').splitlines(),
                                          config['limits']['max_scope_files'])
    assert len(paths) == 37
    snapshots = imp.snapshot_sources(paths, config['limits'])
    fingerprints = contract.fingerprint_sources(snapshots)
    assert set(snapshots) == set(fingerprints) == set(paths)
    for path, snapshot in snapshots.items():
        assert snapshot['exists'], 'Default scope source is missing: ' + path
        content = snapshot['content']
        assert len(content) <= config['limits']['max_file_bytes']
        assert fingerprints[path] == {'exists': True, 'mode': snapshot['mode'],
                                      'size': len(content),
                                      'sha256': hashlib.sha256(content).hexdigest()}
    assert sum(item['size'] for item in fingerprints.values()) <= config['limits']['max_source_bytes']
    sources = {p: item['content'].decode('utf-8') for p, item in snapshots.items()}
    validated = contract.validate_candidate(candidate('AGENTS.md'), sources, paths)
    # Proposal construction revalidates stored source fingerprints as well.
    assert contract.proposal_record(validated, fingerprints)['source_fingerprints'] == fingerprints
    records = []
    for index in range(len(contract.SPECIALIST_ROLES) * config['limits']['max_candidates_per_specialist']):
        item = contract.validate_candidate(candidate('AGENTS.md', title='점검 제안 ' + str(index)), sources)
        records.append(contract.proposal_record(item, fingerprints))
    # Check the full reviewer context with all eight candidate slots using a
    # Python envelope only. The real snapshot is never offered to a model.
    root = tmp_path / 'sources'
    root.mkdir()
    monkeypatch.setattr(imp, 'ROOT', root)
    selected = source_limit_storage(root, tmp_path)
    spec = {'provider': 'claude', 'model': 'fixture-model'}
    monkeypatch.setattr(agent_models, 'load_config', lambda: {'roles': {'reviewer': spec}})
    context_sizes = []

    def capture_only(role, prompt, keys, **options):
        assert role == 'reviewer' and keys == {}
        assert options['write'] is False and options['scoped'] is True
        context_sizes.append(sum(len(item['content']) for item in snapshots.values()) +
                             len(prompt.encode('utf-8')))
        response = {'reviews': [dict(candidate_id=record['id'], verdict='eligible',
                                    reason='합성 후보 envelope로 실제 소스의 context 한도만 검사합니다.',
                                    documentation=SOURCE_DOC) for record in records],
                    'documentation': SOURCE_DOC}
        add_assessments(response, options['discovery_review'])
        result = dict(spec, role=role, status='passed', response=json.dumps(response, ensure_ascii=False))
        capture_result(options['discovery_review'], result)
        return result

    participation, review = imp._call_role('reviewer', paths, snapshots, config,
                                          records, {}, capture_only, selected)
    assert participation['status'] == 'succeeded'
    assert len(context_sizes) == 1 and context_sizes[0] <= config['limits']['max_context_bytes']
    assert len(review['reviews']) == len(records)


@pytest.mark.parametrize('source_bytes', [1048577, 1572864])
def test_large_source_snapshots_and_fingerprints_fit_new_ceiling(
        offline_source_limits, tmp_path, monkeypatch, source_bytes):
    limits = offline_source_limits['limits']
    root = tmp_path / 'sources'
    root.mkdir()
    monkeypatch.setattr(imp, 'ROOT', root)
    expected = {}
    remaining = source_bytes
    while remaining:
        name = 'source-{:02d}.txt'.format(len(expected))
        size = min(remaining, limits['max_file_bytes'])
        content = b'x\n' * (size // 2) + b'x' * (size % 2)
        (root / name).write_bytes(content)
        expected[name] = {'exists': True, 'mode': (root / name).stat().st_mode & 0o7777,
                          'content': content}
        remaining -= len(content)
    snapshots = imp.snapshot_sources(list(expected), limits)
    assert snapshots == expected and source_bytes > 1048576
    fingerprints = contract.fingerprint_sources(snapshots)
    assert sum(item['size'] for item in fingerprints.values()) == source_bytes
    sources = {p: item['content'].decode('utf-8') for p, item in snapshots.items()}
    validated = contract.validate_candidate(candidate(next(iter(expected))), sources)
    proposal = contract.proposal_record(validated, fingerprints)
    assert proposal['source_fingerprints'] == fingerprints
    lowered = dict(limits, max_source_bytes=1048576)
    with pytest.raises(imp.ImprovementError, match='total byte limit'):
        imp.snapshot_sources(list(expected), lowered)

    if source_bytes == limits['max_source_bytes']:
        extra = {'exists': True, 'mode': 0o644, 'content': b'x'}
        (root / 'overflow.txt').write_bytes(extra['content'])
        oversized = {**snapshots, 'overflow.txt': extra}
        with pytest.raises(imp.ImprovementError, match='total byte limit'):
            imp.snapshot_sources(list(oversized), limits)
        with pytest.raises(contract.ValidationError, match='total bound'):
            contract.fingerprint_sources(oversized)
        oversized_fingerprints = {**fingerprints, **contract.fingerprint_sources({'overflow.txt': extra})}
        with pytest.raises(contract.ValidationError, match='total bound'):
            contract.proposal_record(proposal['candidate'], oversized_fingerprints)
        with pytest.raises(contract.ValidationError, match='byte bounds'):
            contract.validate_candidate(validated, {**sources, 'overflow.txt': 'x'})


@pytest.mark.parametrize('setting', ['max_source_bytes', 'max_context_bytes'])
def test_source_and_context_configuration_cannot_exceed_hard_ceilings(offline_source_limits, setting):
    config = copy.deepcopy(offline_source_limits)
    config['limits'][setting] += 1
    with pytest.raises(contract.ValidationError):
        contract.validate_config(config)


class FixtureFS(storage.FileSystem):
    """Only this test's temporary directory acts as a mount; no host probes."""
    def __init__(self, mount):
        self.mount = mount

    def mount_ready(self, path):
        return path == self.mount

    def free_bytes(self, path):
        assert path == self.mount
        return 2 ** 40


def source_limit_storage(root, tmp_path):
    return storage.Storage(root=root,
        artifacts=storage.DirectorySpec(tmp_path / 'artifacts', tmp_path, 0),
        temporary=storage.DirectorySpec(tmp_path / 'contexts', tmp_path, 0),
        config_path=tmp_path / 'synthetic-storage-policy.json', env={}, fs=FixtureFS(tmp_path))


@pytest.mark.parametrize('overflow', [0, 1])
def test_context_byte_ceiling_includes_sources_and_prompt_without_models(
        offline_source_limits, tmp_path, monkeypatch, overflow):
    config = offline_source_limits
    limits = config['limits']
    root = tmp_path / 'sources'
    root.mkdir()
    monkeypatch.setattr(imp, 'ROOT', root)
    # Keep the exact byte ceiling while providing a real body for every owner
    # and separate shared documentation. Padding remains outside the sample.
    names = ['AGENTS.md', 'harness/example.py', 'downloader/example.py',
             'parser_tidy/example.py', 'TavernofSoul/example.py']
    names += ['source-{:02d}.txt'.format(i) for i in range(
        limits['max_source_bytes'] // limits['max_file_bytes'] - len(names))]
    prefix = b'value = 1\n' * 96
    snapshots = {name: {'exists': True, 'mode': 0o644,
                       'content': prefix + b'#' * (limits['max_file_bytes'] - len(prefix))}
                 for name in names}
    source_bytes = sum(len(item['content']) for item in snapshots.values())
    assert source_bytes == limits['max_source_bytes'] > 1048576
    selected = source_limit_storage(root, tmp_path)
    spec = {'provider': 'claude', 'model': 'fixture-model'}
    monkeypatch.setattr(agent_models, 'load_config', lambda: {'roles': {'reviewer': spec}})
    prompt_sizes = []

    def capture_only(role, prompt, keys, **options):
        # Pure Python envelope; no model, credentials, network or workflow.
        assert options['write'] is False and options['scoped'] is True and keys == {}
        prompt_sizes.append(len(prompt.encode('utf-8')))
        response = {'reviews': [], 'documentation': SOURCE_DOC}
        add_assessments(response, options['discovery_review'])
        result = dict(spec, role=role, status='passed', response=json.dumps(response, ensure_ascii=False))
        capture_result(options['discovery_review'], result)
        return result

    monkeypatch.setattr(imp, 'REVIEW_PROMPT', '')
    participation, _ = imp._call_role('reviewer', list(snapshots), snapshots,
                                     config, [], {}, capture_only, selected)
    assert participation['status'] == 'succeeded'
    padding = limits['max_context_bytes'] - source_bytes - prompt_sizes[0]
    assert padding > 0
    # Non-ASCII padding catches accidental character counts in a byte contract.
    monkeypatch.setattr(imp, 'REVIEW_PROMPT', '가' * (padding // 3) + 'x' * (padding % 3 + overflow))
    prompt_sizes.clear()
    participation, review = imp._call_role('reviewer', list(snapshots), snapshots,
                                          config, [], {}, capture_only, selected)
    if overflow:
        assert prompt_sizes == [] and review is None
        assert participation['status'] == 'unavailable'
        assert participation['error_type'] == 'ImprovementError'
    else:
        assert participation['status'] == 'succeeded'
        assert source_bytes + prompt_sizes[0] == limits['max_context_bytes']
        assert review['reviews'] == []




def owner_programs():
    snapshots = {'AGENTS.md': dict(exists=True, mode=0o644, content=b'shared document\n')}
    owners = {}
    raw = (b'# header\n' * 120 + b'import os\n\ndef compute(value):\n'
           b'    result = value + 1\n    return result\n' + b'# tail\n' * 120)
    for role, root in zip(contract.SPECIALIST_ROLES,
                          ('harness', 'downloader', 'parser_tidy', 'TavernofSoul')):
        paths = [root + '/AGENTS.md', root + '/config.json', root + '/settings.py',
                 root + '/tests/test_first.py', root + '/program.py']
        for path in paths:
            snapshots[path] = dict(exists=True, mode=0o644, content=(
                raw if path.endswith('/program.py') else b'value = 1\n'))
        owners[role] = paths + ['AGENTS.md']
    return snapshots, owners


def test_empty_plan_prefers_owner_program_body_to_domain_agents_config_and_tests(tmp_path):
    snapshots, owners = owner_programs()
    windows = coverage.plan(list(snapshots), snapshots, [], owners, ['AGENTS.md'])
    assert len(windows) == 5
    for role, paths in owners.items():
        window = next(w for w in windows if role in w['purposes'])
        assert window['path'] == paths[-2]  # production program before earlier test
        assert (window['start_line'], window['end_line']) == (116, 211)
        # Literal expected range/body: 120 header, import, blank, def, body.
        assert window['start_line'] <= 124 < 125 <= window['end_line']
        assert window['end_line'] - window['start_line'] + 1 == 96
    assert [w['path'] for w in windows if 'documentation' in w['purposes']] == ['AGENTS.md']
    capture = coverage.Capture(tmp_path, snapshots, windows)
    capture.accept(stdout(read_events(capture)))
    assert len(capture.receipts) == 5
    assert len(snapshots['downloader/program.py']['content'].splitlines()) > 96


@pytest.mark.parametrize('damage', ['docs_config_only', 'outside_membership', 'shared_only',
    'missing', 'empty', 'whitespace', 'header_only', 'invalid_utf8', 'invalid_program'])
def test_unavailable_owner_program_never_becomes_false_empty_success(damage):
    snapshots, owners = owner_programs()
    path = 'downloader/program.py'
    if damage == 'docs_config_only':
        owners['downloader'] = owners['downloader'][:3] + ['AGENTS.md']
    elif damage == 'outside_membership':
        owners['downloader'] = ['downloader/AGENTS.md', 'harness/not-approved.py']
    elif damage == 'shared_only':
        owners['downloader'] = ['AGENTS.md']
    elif damage == 'missing':
        snapshots[path] = dict(exists=False, mode=None, content=None)
    else:
        snapshots[path]['content'] = {
            'empty': b'', 'whitespace': b'\n  \n',
            'header_only': b'"""guide"""\nimport os\n# no executable body\n',
            'invalid_utf8': b'\xff', 'invalid_program': b'def broken(:\n',
        }[damage]
    # A test/document may still be readable; it cannot conceal the selected
    # production target's unavailability. No model or partial proof is admitted.
    with pytest.raises(ValueError):
        coverage.plan(list(snapshots), snapshots, [], owners, ['AGENTS.md'])


@pytest.mark.parametrize('excess', [0, 1])
def test_empty_code_sample_keeps_exact_32kib_bound_and_rejects_long_line_excess(excess):
    document = b'shared document\n'
    prefix = b'value = 1 #'
    raw = prefix + b'x' * (32768 - len(document) - len(prefix) - 1 + excess) + b'\n'
    snapshots = {'harness/program.py': dict(exists=True, mode=0o644, content=raw),
                 'AGENTS.md': dict(exists=True, mode=0o644, content=document)}
    owners = {r: ['harness/program.py'] for r in contract.SPECIALIST_ROLES}
    if excess:
        with pytest.raises(ValueError):
            coverage.plan(list(snapshots), snapshots, [], owners, ['AGENTS.md'])
    else:
        windows = coverage.plan(list(snapshots), snapshots, [], owners, ['AGENTS.md'])
        assert sum(w['size'] for w in windows) == 32768


@pytest.mark.parametrize('count', [31, 32])
def test_evidence_plus_separate_document_respects_32_window_limit(count):
    snapshots = {'harness/program.py': dict(exists=True, mode=0o644, content=b'value = 1\n' * 100),
                 'AGENTS.md': dict(exists=True, mode=0o644, content=b'shared document\n')}
    items = [dict(path='harness/program.py', start_line=2 * i + 1, end_line=2 * i + 1)
             for i in range(count)]
    records = [dict(candidate=dict(evidence=items[i:i + 6], benefit=dict(evidence=[]), edit_files=[]))
               for i in range(0, count, 6)]
    if count == 32:
        with pytest.raises(ValueError):
            coverage.plan(list(snapshots), snapshots, records, {}, ['AGENTS.md'])
    else:
        assert len(coverage.plan(list(snapshots), snapshots, records, {}, ['AGENTS.md'])) == 32


def test_candidate_plan_keeps_all_benefit_evidence_and_required_document_reads():
    snapshots, owners = owner_programs()
    c = candidate('downloader/program.py')
    c['benefit']['evidence'] = [dict(path='parser_tidy/program.py', start_line=124, end_line=125)]
    c['edit_files'].append('downloader/AGENTS.md')
    windows = coverage.plan(list(snapshots), snapshots, [dict(candidate=c)], owners, ['AGENTS.md'])
    assert {(w['path'], w['start_line'], w['end_line']) for w in windows} == {
        ('downloader/program.py', 1, 2), ('parser_tidy/program.py', 124, 125),
        ('downloader/AGENTS.md', 1, 1), ('AGENTS.md', 1, 1)}
    review = dict(reviews=[dict(documentation=dict(files=['downloader/AGENTS.md']))],
                  documentation=dict(files=['AGENTS.md']))
    coverage.document_reads(review, windows)
    review['documentation']['files'] = ['parser_tidy/AGENTS.md']
    with pytest.raises(ValueError):
        coverage.document_reads(review, windows)
    c['benefit']['evidence'][0]['end_line'] = 381  # never trim oversized evidence
    with pytest.raises(ValueError):
        coverage.plan(list(snapshots), snapshots, [dict(candidate=c)], owners, ['AGENTS.md'])


@pytest.mark.parametrize('end', [256, 257])
def test_candidate_evidence_line_bound_is_not_reduced_to_a_sample(end):
    snapshots = {'harness/program.py': dict(exists=True, mode=0o644, content=b'value = 1\n' * 300),
                 'AGENTS.md': dict(exists=True, mode=0o644, content=b'shared document\n')}
    c = candidate('harness/program.py')
    c['evidence'][0]['end_line'] = end
    if end == 257:
        with pytest.raises(ValueError):
            coverage.plan(list(snapshots), snapshots, [dict(candidate=c)], {}, ['AGENTS.md'])
    else:
        windows = coverage.plan(list(snapshots), snapshots, [dict(candidate=c)], {}, ['AGENTS.md'])
        source = next(w for w in windows if w['path'] == 'harness/program.py')
        assert (source['start_line'], source['end_line'], source['size']) == (1, 256, 2560)
