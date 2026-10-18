"""Offline synthetic OTLP and loopback-only peers; never a model or external host."""
import json
import socket
import time

import pytest

from harness import agent_telemetry as t


def span(identity, start=1000, kind='claude_code.llm_request', parent=None, **attrs):
    attributes = []
    for key, value in attrs.items():
        field = ('boolValue' if type(value) is bool else 'intValue' if type(value) is int
                 else 'doubleValue' if type(value) is float else 'stringValue')
        attributes.append({'key': key, 'value': {field: str(value) if field == 'intValue' else value}})
    return {'name': kind, 'traceId': 'a' * 32, 'spanId': '%016x' % identity,
            'parentSpanId': '%016x' % parent if parent else '',
            'startTimeUnixNano': str(start * 1000000),
            'endTimeUnixNano': str((start + 100) * 1000000), 'attributes': attributes,
            'events': [{'name': 'SECRET /host/private', 'attributes': []}]}


def batch(*spans):
    return json.dumps({'resourceSpans': [{'resource': {'secret': 'PROMPT /home/private'},
        'scopeSpans': [{'spans': list(spans)}]}]}).encode()


def collector():
    c = t.Collector(10)
    c.launch_ns = 0
    return c


def sample():
    c = collector()
    c.ingest(batch(span(1, ttft_ms=80, first_content_ms=82, attempt=1)))
    return c.snapshot('success')


def test_chronological_first_multiple_retry_dedup_and_unknown():
    c = collector()
    later = span(2, 2000, ttft_ms=20, attempt=3, success=False)
    early = span(1, 1000, ttft_ms=80, first_content_ms=82, success=True, input_tokens=42)
    c.ingest(batch(later, early))
    c.ingest(batch(early, later))
    value = c.snapshot('child_failed')
    assert value['logical_requests_observed'] == 2
    assert value['transport_attempts_known'] == 3 and value['retries_known'] == 2
    assert value['requests_with_unknown_attempts'] == 1
    assert value['first_request_ttft_ms'] == 80 and value['first_request_content_ms'] == 82
    assert value['launch_to_first_content_ms'] == 1082
    assert [r['success'] for r in value['requests']] == [True, False]
    assert value['requests'][1]['first_content_ms'] is None
    assert value['request_work']['duration_ms']['total'] == 200
    assert value['unexported_requests_unknown'] is True and value['completeness'] == 'partial'
    serialized = json.dumps(value)
    for secret in ('PROMPT', 'SECRET', '/home', 'traceId', 'spanId', 'events', 'a' * 32):
        assert secret not in serialized


def test_first_request_missing_ttft_never_borrows_later_measurement():
    c = collector()
    c.ingest(batch(span(2, 2000, ttft_ms=20), span(1)))
    assert c.snapshot('success')['first_request_ttft_ms'] is None


def test_out_of_order_execution_join_and_missing_execution_unknown():
    c = collector()
    c.ingest(batch(span(2, kind='claude_code.tool.execution', parent=1, duration_ms=11, success=True)))
    assert c.snapshot('timeout')['unmatched_execution_spans'] == 1
    c.ingest(batch(span(1, kind='claude_code.tool', tool_name='Read', duration_ms=23),
                   span(3, kind='claude_code.tool', tool_name_safe='Read', duration_ms=8),
                   span(4, kind='claude_code.tool', tool_name='Glob', duration_ms=9)))
    value = c.snapshot('timeout')
    read = value['tool_work']['Read']
    assert read == {'wall_known_count': 2, 'wall_total_ms': 31, 'wall_max_ms': 23,
                    'execution_count_observed': 1, 'execution_known_count': 1,
                    'execution_unknown_timing_count': 0, 'execution_total_ms': 11,
                    'execution_max_ms': 11, 'missing_execution_count': 1}
    assert value['unmatched_execution_spans'] == 0
    assert value['availability'] == 'unavailable' and value['logical_requests_observed'] is None
    assert value['tool_work']['Glob']['execution_total_ms'] is None


@pytest.mark.parametrize('bad', [True, -1, float('nan'), float('inf'), 10 ** 80, 'SECRET', 1.5])
def test_invalid_attempt_and_injected_numeric_fields_stay_unknown(bad):
    raw = sample()
    raw['requests'][0].update(attempt=bad, input_tokens=bad)
    raw['cli'] = {'duration_ms': True, 'num_turns': bad, 'secret': '/private'}
    raw['parent'] = {'context_preparation_ms': bad, 'secret': '/private'}
    raw['transport_attempts_known'] = 999
    raw['secret'] = 'PROMPT'
    safe = t.sanitize(raw)
    assert safe['transport_attempts_known'] is None
    assert safe['requests'][0]['input_tokens'] is None
    assert safe['cli']['duration_ms'] is None
    assert 'PROMPT' not in json.dumps(safe) and '/private' not in json.dumps(safe)


@pytest.mark.parametrize('body', [b'[]', b'{}', b'{"resourceSpans":null}',
    b'{"resourceSpans":[],"resourceSpans":[]}', b'{"resourceSpans":[],"x":NaN}',
    b'{"resourceSpans":[],"x":1e999}', b'{"resourceSpans":[],"x":-1}', b'\xff'])
def test_strict_malformed_json(body):
    with pytest.raises((ValueError, TypeError, KeyError, UnicodeError)):
        collector().ingest(body)


def test_bounds_and_unknown_names_and_secret_fields():
    c = collector()
    with pytest.raises(ValueError):
        c.ingest(b' ' * (t.MAX_BODY + 1))
    assert c.limited
    c = collector()
    # Several bounded batches exhaust identities, then repeated exports exhaust spans.
    for offset in range(0, t.MAX_SPANS, 64):
        c.ingest(batch(*(span(i + 1, kind='claude_code.tool', tool_name='/secret/' + str(i))
                         for i in range(offset, offset + 64))))
    c.ingest(batch(span(10000)))
    safe = c.snapshot('timeout')
    assert c.limited and len(c.spans) <= t.MAX_IDS and len(safe['tools']) == t.MAX_ROWS
    assert '/secret/' not in json.dumps(safe)
    assert len(json.dumps(safe)) < 131072
    assert t.sanitize(dict(safe, requests=[{}] * (t.MAX_ROWS + 1))) is None


def request(c, body=b'{"resourceSpans":[]}', path=None, method='POST', headers=None):
    head = '{} {} HTTP/1.1\r\nContent-Type: application/json\r\nContent-Length: {}\r\n'.format(
        method, path or c.path, len(body))
    if headers:
        head += headers
    with socket.create_connection(('127.0.0.1', c.server.getsockname()[1]), timeout=1) as peer:
        peer.sendall(head.encode() + b'\r\n' + body)
        response = b''
        while True:
            data = peer.recv(1024)
            if not data:
                return response
            response += data


def test_listener_exact_endpoint_bounded_response_and_cleanup():
    c = t.Collector(5).start()
    try:
        assert c.endpoint and not c.setup_failed
        response = request(c)
        assert b'200 OK' in response and response.endswith(b'\r\n\r\n{}') and len(response) < 256
        for kwargs in ({'path': '/v1/traces'}, {'method': 'GET'},
                       {'headers': 'Transfer-Encoding: chunked\r\n'},
                       {'headers': 'Content-Encoding: gzip\r\n'},
                       {'headers': 'Content-Length: 5\r\n'}, {'body': b'[]'}):
            response = request(c, **kwargs)
            assert b'400 Bad Request' in response and len(response) < 256
        assert c.invalid_input
    finally:
        c.close()
    assert not c.thread.is_alive() and c.server.fileno() == -1


def test_stalled_peer_does_not_hold_close_or_deadline():
    c = t.Collector(5).start()
    peer = socket.create_connection(('127.0.0.1', c.server.getsockname()[1]), timeout=1)
    try:
        peer.sendall(('POST ' + c.path + ' HTTP/1.1\r\nContent-Length: 999\r\n'
                      'Content-Type: application/json\r\n\r\n{').encode())
        started = time.monotonic()
        c.close()
        assert time.monotonic() - started < 1.5 and not c.thread.is_alive()
    finally:
        peer.close()
        c.close()


def test_bind_failure_is_unavailable_and_exporters_disabled(monkeypatch):
    def fail(*args):
        raise OSError('SECRET host path')
    monkeypatch.setattr(t.socket, 'socket', fail)
    c = t.Collector(1).start()
    value = c.snapshot('success')
    assert c.setup_failed and c.endpoint is None
    assert value['availability'] == 'unavailable' and value['logical_requests_observed'] is None
    env = t.child_environment({'OTEL_EXPORTER_OTLP_ENDPOINT': 'https://SECRET'}, c.endpoint)
    assert env['OTEL_TRACES_EXPORTER'] == 'none'
    assert 'SECRET' not in json.dumps(value) + json.dumps(env)


def test_child_environment_drops_all_inherited_destinations_content_and_raw_logging():
    inherited = {k: 'SECRET' for k in ('OTEL_RESOURCE_ATTRIBUTES', 'OTEL_EXPORTER_OTLP_HEADERS',
        'OTEL_EXPORTER_OTLP_ENDPOINT', 'OTEL_LOG_RAW_API_BODIES', 'OTEL_TRACES_SAMPLER',
        'ENABLE_BETA_TRACING_DETAILED', 'BETA_TRACING_ENDPOINT', 'ENABLE_ENHANCED_TELEMETRY_BETA',
        'TRACEPARENT', 'TRACESTATE', 'BAGGAGE', 'CLAUDE_CODE_DEBUG_LOGS_DIR', 'DEBUG_FILE')}
    inherited.update(HTTP_PROXY='http://model-proxy', HTTPS_PROXY='http://model-proxy', NO_PROXY='existing')
    env = t.child_environment(inherited, 'http://127.0.0.1:123/token/v1/traces')
    assert 'SECRET' not in json.dumps(env)
    assert env['HTTP_PROXY'] == env['HTTPS_PROXY'] == 'http://model-proxy'
    assert '127.0.0.1' in env['NO_PROXY'] and 'existing' in env['no_proxy']
    assert env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] == '1'
    assert all(env['OTEL_LOG_' + flag] == 'false' for flag in t.CONTENT_FLAGS)
    assert env['OTEL_TRACES_EXPORT_INTERVAL'] == '1000'
    assert env['OTEL_LOGS_EXPORTER'] == env['OTEL_METRICS_EXPORTER'] == 'none'
    assert inherited['OTEL_RESOURCE_ATTRIBUTES'] == 'SECRET'


def test_incomplete_or_implausible_span_never_becomes_a_completed_request():
    c = collector()
    unfinished = span(1)
    unfinished['endTimeUnixNano'] = '0'
    distant = span(2)
    distant['startTimeUnixNano'] = str(2 ** 64 - 2)
    distant['endTimeUnixNano'] = str(2 ** 64 - 1)
    c.ingest(batch(unfinished, distant))
    safe = c.snapshot('timeout')
    assert safe['logical_requests_observed'] is None and safe['invalid_input']
    c.ingest(batch(span(3, ttft_ms=20)))
    assert c.snapshot('timeout')['logical_requests_observed'] == 1


def test_input_budget_listener_stops_without_retaining_excess():
    c = t.Collector(5).start()
    try:
        c.total_input = t.MAX_INPUT - 1
        # Use a raw socket: after exhausting input the server can reset unread bytes.
        with socket.create_connection(('127.0.0.1', c.server.getsockname()[1]), timeout=1) as peer:
            peer.sendall(b'X')
            response = peer.recv(256)
            assert b'400 Bad Request' in response
        assert c.total_input == t.MAX_INPUT and c.limited
    finally:
        c.close()
    assert not c.thread.is_alive()


def test_silent_collector_has_no_fabricated_calls_or_first_response():
    c = t.Collector(1).start()
    c.close()
    safe = c.snapshot('success', {'duration_ms': 2000, 'num_turns': 2})
    assert safe['availability'] == 'unavailable' and safe['logical_requests_observed'] is None
    assert safe['first_request_ttft_ms'] is None and safe['first_request_content_ms'] is None
    assert safe['cli']['num_turns'] == 2


@pytest.mark.parametrize('field', ['duration_ms', 'ttft_ms', 'first_content_ms', 'input_tokens'])
@pytest.mark.parametrize('bad', [True, -1, float('nan'), float('inf'), 10 ** 100, 'secret'])
def test_untrusted_numeric_contract_never_keeps_invalid_metrics(field, bad):
    raw = sample()
    raw['requests'][0][field] = bad
    safe = t.sanitize(raw)
    assert safe['requests'][0][field] is None
    assert 'secret' not in json.dumps(safe)


def test_read_execution_count_is_distinct_from_unknown_body_duration():
    c = collector()
    c.ingest(batch(span(1, kind='claude_code.tool', tool_name='Read'),
                   span(2, kind='claude_code.tool.execution', parent=1, duration_ms=True)))
    read = c.snapshot('success')['tool_work']['Read']
    assert read['execution_count_observed'] == 1
    assert read['execution_known_count'] == 0 and read['execution_total_ms'] is None
    assert read['execution_unknown_timing_count'] == 1 and read['missing_execution_count'] == 0
