"""Private, bounded Claude Code OTLP traces. Python 3.8 stdlib only.

No raw payload, span identity, arbitrary text or resource attributes leave this
module. Totals are observed work, potentially overlapping, never exact overhead.
"""
import json
import math
import re
import secrets
import socket
import threading
import time

VERSION = 'glm-call-telemetry-v1'
MAX_BODY = 262144
MAX_INPUT = 4194304
MAX_SPANS = 4096
MAX_IDS = 2048
MAX_ROWS = 128
MAX_MS = 3600000
TOKENS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_creation_tokens')
REQUEST_NUMBERS = ('duration_ms', 'ttft_ms', 'first_content_ms', 'attempt') + TOKENS
OUTCOMES = ('success', 'child_failed', 'timeout', 'interrupted', 'spawn_failed', 'invalid_response')
CONTENT_FLAGS = ('USER_PROMPTS', 'ASSISTANT_RESPONSES', 'TOOL_DETAILS', 'TOOL_CONTENT',
                 'RAW_API_BODIES', 'MANAGED_SETTINGS')


def number(value, maximum=MAX_MS, integer=False, minimum=0):
    if type(value) not in ((int,) if integer else (int, float)):
        return None
    try:
        return value if minimum <= value <= maximum and math.isfinite(value) else None
    except OverflowError:
        return None


def _integer_string(value, maximum):
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,20}', value):
        value = int(value)
    return number(value, maximum, integer=True)


def child_environment(env, endpoint=None):
    """Modify this invocation's copy only; model HTTP proxy routing is unchanged."""
    env = dict(env)
    for key in list(env):
        upper = key.upper()
        if (upper.startswith(('OTEL_', 'CLAUDE_CODE_OTEL_', 'CLAUDE_CODE_TELEMETRY_',
                              'ENABLE_BETA_TRACING', 'BETA_TRACING_',
                              'ENABLE_ENHANCED_TELEMETRY', 'CLAUDE_CODE_ENHANCED_TELEMETRY',
                              'CLAUDE_CODE_TRACE', 'CLAUDE_CODE_LOG_', 'CLAUDE_CODE_DEBUG'))
                or upper in ('TRACEPARENT', 'TRACESTATE', 'BAGGAGE',
                             'CLAUDE_CODE_ENABLE_TELEMETRY', 'CLAUDE_CODE_DEBUG_LOGS_DIR',
                             'CLAUDE_CODE_DEBUG', 'DEBUG', 'DEBUG_FILE', 'ANTHROPIC_LOG',
                             'TRACE_TO_FILE', 'TRACE_FILE', 'TRACE_LOG_DIR')):
            env.pop(key, None)
    env.update(CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',
               OTEL_TRACES_EXPORTER='none', OTEL_LOGS_EXPORTER='none', OTEL_METRICS_EXPORTER='none')
    for flag in CONTENT_FLAGS:
        env['OTEL_LOG_' + flag] = 'false'
    if endpoint:
        env.update(CLAUDE_CODE_ENABLE_TELEMETRY='1', CLAUDE_CODE_ENHANCED_TELEMETRY_BETA='1',
                   OTEL_TRACES_EXPORTER='otlp', OTEL_EXPORTER_OTLP_TRACES_PROTOCOL='http/json',
                   OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=endpoint, OTEL_TRACES_EXPORT_INTERVAL='1000')
        # Preserve existing proxy bypasses and all actual model proxy variables.
        bypass = ','.join(v for v in (env.get('NO_PROXY'), env.get('no_proxy')) if v)
        env['NO_PROXY'] = env['no_proxy'] = bypass + ',127.0.0.1,localhost'
    return env


def _numeric_fields(source, fields):
    result = {}
    for field in fields:
        integer = field == 'attempt' or field in TOKENS or field == 'num_turns'
        maximum = 1000 if field == 'attempt' else (1000000000 if integer else MAX_MS)
        result[field] = number(source.get(field), maximum, integer, 1 if field == 'attempt' else 0)
    return result


def sanitize(value):
    """Revalidate an untrusted runner contract; unknown keys vanish, totals rebuild.

    Omitted/invalid numeric observations stay null. Invalid enums/collections
    reject the contract. No arbitrary diagnostic strings can survive this gate.
    """
    if not isinstance(value, dict) or value.get('version') != VERSION:
        return None
    if value.get('outcome') not in OUTCOMES:
        return None
    requests, tools = value.get('requests'), value.get('tools')
    if (not isinstance(requests, list) or len(requests) > MAX_ROWS or
            not isinstance(tools, list) or len(tools) > MAX_ROWS):
        return None
    result = {'version': VERSION, 'outcome': value['outcome'],
              'completeness': 'partial', 'unexported_requests_unknown': True}
    for field in ('setup_failed', 'invalid_input', 'limited'):
        if type(value.get(field)) is not bool:
            return None
        result[field] = value[field]
    result['requests'], result['tools'] = [], []
    for row in requests:
        if not isinstance(row, dict):
            return None
        safe = _numeric_fields(row, REQUEST_NUMBERS)
        safe['start_offset_ms'] = number(row.get('start_offset_ms'))
        safe['success'] = row.get('success') if type(row.get('success')) is bool else None
        result['requests'].append(safe)
    # Collector emits chronological rows. Re-sort at the untrusted loop boundary.
    result['requests'].sort(key=lambda r: (r['start_offset_ms'] is None,
                                          r['start_offset_ms'] or 0))
    for row in tools:
        if not isinstance(row, dict) or row.get('category') not in ('Read', 'Glob', 'Grep', 'other'):
            return None
        observed = row.get('execution_observed') is True
        result['tools'].append({'category': row['category'],
            'wall_ms': number(row.get('wall_ms')),
            'execution_observed': True if observed else None,
            'execution_ms': number(row.get('execution_ms')) if observed else None,
            'success': row.get('success') if observed and type(row.get('success')) is bool else None})
    result['unmatched_execution_spans'] = number(value.get('unmatched_execution_spans'), MAX_IDS, True)
    result['cli_wall_ms'] = number(value.get('cli_wall_ms'))
    parent = value.get('parent', {})
    result['parent'] = {k: number(parent.get(k)) for k in
                        ('context_preparation_ms', 'source_verification_ms')} if isinstance(parent, dict) else {}
    cli = value.get('cli', {})
    result['cli'] = _numeric_fields(cli, ('duration_ms', 'duration_api_ms', 'num_turns') + TOKENS) \
        if isinstance(cli, dict) else {}
    rows = result['requests']
    result['availability'] = 'observed' if rows else 'unavailable'
    result['logical_requests_observed'] = len(rows) if rows else None
    attempts = [r['attempt'] for r in rows if r['attempt'] is not None]
    result['transport_attempts_known'] = sum(attempts) if attempts else None
    result['retries_known'] = sum(n - 1 for n in attempts) if attempts else None
    result['requests_with_unknown_attempts'] = sum(r['attempt'] is None for r in rows) if rows else None
    first = rows[0] if rows else {}
    result['first_request_ttft_ms'] = first.get('ttft_ms')
    result['first_request_content_ms'] = first.get('first_content_ms')
    offset = first.get('start_offset_ms')
    result['launch_to_first_ttft_ms'] = (offset + first['ttft_ms']
        if offset is not None and first.get('ttft_ms') is not None else None)
    result['launch_to_first_content_ms'] = (offset + first['first_content_ms']
        if offset is not None and first.get('first_content_ms') is not None else None)
    result['request_work'] = {}
    for field in ('duration_ms', 'ttft_ms', 'first_content_ms') + TOKENS:
        observed = [r[field] for r in rows if r[field] is not None]
        result['request_work'][field] = {'known_count': len(observed),
            'total': sum(observed) if observed else None, 'max': max(observed) if observed else None}
    result['tool_work'] = {}
    for category in ('Read', 'Glob', 'Grep', 'other'):
        group = [t for t in result['tools'] if t['category'] == category]
        execution_count = sum(t['execution_observed'] is True for t in group)
        execution = [t['execution_ms'] for t in group if t['execution_ms'] is not None]
        wall = [t['wall_ms'] for t in group if t['wall_ms'] is not None]
        result['tool_work'][category] = {'wall_known_count': len(wall),
            'wall_total_ms': sum(wall) if wall else None, 'wall_max_ms': max(wall) if wall else None,
            'execution_count_observed': execution_count,
            'execution_known_count': len(execution),
            'execution_unknown_timing_count': execution_count - len(execution),
            'execution_total_ms': sum(execution) if execution else None,
            'execution_max_ms': max(execution) if execution else None,
            'missing_execution_count': len(group) - execution_count}
    return result


def _json_integer(value):
    if len(value) > 20 or value.startswith('-'):
        raise ValueError('number')
    decoded = int(value)
    if decoded > 2 ** 64 - 1:
        raise ValueError('number')
    return decoded


def _json_float(value):
    decoded = float(value)
    if number(decoded, 2 ** 64 - 1) is None:
        raise ValueError('number')
    return decoded


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate')
        result[key] = value
    return result


def _array(value):
    if not isinstance(value, list) or len(value) > MAX_SPANS:
        raise ValueError('shape')
    return value


def _id(value, length):
    return value if isinstance(value, str) and re.fullmatch('[0-9a-fA-F]{%d}' % length, value) \
        and int(value, 16) else None


class Collector:
    """Single bounded listener thread; no per-peer threads or raw logging."""
    def __init__(self, timeout):
        self.deadline = time.monotonic() + min(number(timeout, MAX_MS / 1000) or 300, 3600) + 1
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.server = self.peer = self.thread = None
        self.endpoint = None
        self.path = '/' + secrets.token_hex(24) + '/v1/traces'
        self.spans = {}
        self.total_input = self.total_spans = 0
        self.invalid_input = self.limited = self.setup_failed = False
        self.launch_ns = time.time_ns()
        self.started = time.monotonic()
        self.wall_ms = None

    def start(self):
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.bind(('127.0.0.1', 0))
            self.server.listen(4)
            self.server.settimeout(.05)
            self.endpoint = 'http://127.0.0.1:{}{}'.format(self.server.getsockname()[1], self.path)
            self.thread = threading.Thread(target=self._serve, name='private-glm-traces', daemon=True)
            self.thread.start()
        except Exception:
            self.setup_failed = True
            self.endpoint = None
            self.close()
        return self

    def close(self):
        self.stop.set()
        with self.lock:
            for sock in (self.peer, self.server):
                if sock is not None:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    try:
                        sock.close()
                    except OSError:
                        pass
        if self.thread is not None and self.thread.ident is not None:
            self.thread.join(timeout=1)
        # No daemon may continue handling data after close: all socket reads use
        # the stop flag and absolute peer deadline; CPU work is body/span bounded.

    def finish(self, outcome, cli=None):
        try:
            self.close()
            return self.snapshot(outcome, cli) or unavailable(outcome)
        except Exception:
            # Telemetry must not replace model execution's original outcome.
            return unavailable(outcome)

    def _serve(self):
        try:
            while not self.stop.is_set() and time.monotonic() < self.deadline:
                try:
                    peer, _ = self.server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                with self.lock:
                    self.peer = peer
                try:
                    peer.settimeout(.1)
                    self._handle(peer)
                except Exception:
                    self.invalid_input = True
                finally:
                    peer.close()
                    with self.lock:
                        self.peer = None
                if self.total_input >= MAX_INPUT or self.total_spans >= MAX_SPANS:
                    self.limited = True
                    break
        except Exception:
            self.invalid_input = True
        finally:
            try:
                self.server.close()
            except OSError:
                pass

    def _handle(self, peer):
        until = min(self.deadline, time.monotonic() + .5)
        data = bytearray()

        def receive(count):
            if self.stop.is_set() or time.monotonic() >= until:
                raise ValueError('deadline')
            remaining = MAX_INPUT - self.total_input
            if remaining <= 0:
                self.limited = True
                raise ValueError('limit')
            chunk = peer.recv(min(count, remaining))
            if not chunk:
                raise ValueError('short')
            self.total_input += len(chunk)
            if self.total_input > MAX_INPUT:
                self.limited = True
                raise ValueError('limit')
            return chunk

        try:
            while b'\r\n\r\n' not in data:
                if len(data) >= 8192:
                    raise ValueError('headers')
                data.extend(receive(min(1024, 8192 - len(data))))
            head, body = bytes(data).split(b'\r\n\r\n', 1)
            lines = head.decode('ascii').split('\r\n')
            if lines[0] not in ('POST ' + self.path + ' HTTP/1.1', 'POST ' + self.path + ' HTTP/1.0'):
                raise ValueError('endpoint')
            headers = {}
            for line in lines[1:]:
                key, value = line.split(':', 1)
                if key.lower() in headers or not re.fullmatch('[A-Za-z0-9-]+', key):
                    raise ValueError('headers')
                headers[key.lower()] = value.strip()
            if any(k in headers for k in ('transfer-encoding', 'content-encoding', 'expect')):
                raise ValueError('framing')
            if headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                raise ValueError('type')
            length = _integer_string(headers.get('content-length'), MAX_BODY)
            if length is None or length == 0 or len(body) > length:
                raise ValueError('length')
            if self.total_input + length - len(body) > MAX_INPUT:
                self.limited = True
                raise ValueError('limit')
            while len(body) < length:
                body += receive(min(8192, length - len(body)))
            self.ingest(body)
            response = b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}'
        except (ValueError, UnicodeError, TypeError, KeyError, RecursionError):
            self.invalid_input = True
            response = b'HTTP/1.1 400 Bad Request\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}'
        peer.sendall(response)

    def ingest(self, body):
        """Strict parser seam for offline fixtures; no body is retained."""
        if len(body) > MAX_BODY:
            self.limited = True
            raise ValueError('limit')
        batch = json.loads(body.decode('utf-8'), object_pairs_hook=_pairs,
                           parse_int=_json_integer, parse_float=_json_float,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('number')))
        if not isinstance(batch, dict):
            raise ValueError('shape')
        spans = []
        for resource in _array(batch['resourceSpans']):
            for scope in _array(resource['scopeSpans']):
                spans.extend(_array(scope['spans']))
                if len(spans) > MAX_SPANS:
                    raise ValueError('limit')
        for span in spans:
            if self.stop.is_set() or time.monotonic() >= self.deadline:
                self.limited = True
                break
            if self.total_spans >= MAX_SPANS:
                self.limited = True
                break
            self.total_spans += 1
            self._span(span)

    def _span(self, span):
        if not isinstance(span, dict):
            raise ValueError('shape')
        kind = span.get('name')
        if kind not in ('claude_code.llm_request', 'claude_code.tool', 'claude_code.tool.execution'):
            return
        trace, identity = _id(span.get('traceId'), 32), _id(span.get('spanId'), 16)
        start = _integer_string(span.get('startTimeUnixNano'), 2 ** 64 - 1)
        end = _integer_string(span.get('endTimeUnixNano'), 2 ** 64 - 1)
        if not trace or not identity or start is None or end is None or end < start or end == 0:
            self.invalid_input = True
            return
        key = (trace.lower(), identity.lower())
        if key in self.spans:
            return
        if len(self.spans) >= MAX_IDS:
            self.limited = True
            return
        attributes = {}
        for attr in _array(span.get('attributes', [])):
            if not isinstance(attr, dict):
                raise ValueError('shape')
            field, value = attr.get('key'), attr.get('value')
            if field not in REQUEST_NUMBERS + ('success', 'tool_name', 'tool_name_safe'):
                continue
            if field in attributes or not isinstance(value, dict) or len(value) != 1:
                self.invalid_input = True
                return
            if field == 'success':
                decoded = value.get('boolValue')
                decoded = decoded if type(decoded) is bool else None
            elif field in ('tool_name', 'tool_name_safe'):
                decoded = value.get('stringValue')
                decoded = decoded if decoded in ('Read', 'Glob', 'Grep') else 'other'
            elif 'intValue' in value:
                decoded = _integer_string(value['intValue'], 1000000000)
            else:
                decoded = number(value.get('doubleValue'), 1000000000)
            attributes[field] = decoded
        row = _numeric_fields(attributes, REQUEST_NUMBERS)
        # Timestamp lifecycle is available even if the duration attribute is absent.
        if 'duration_ms' not in attributes:
            row['duration_ms'] = number((end - start) / 1000000)
        if any(field in attributes and row[field] is None for field in REQUEST_NUMBERS):
            self.invalid_input = True
        row['success'] = attributes.get('success')
        row['start_offset_ms'] = number((start - self.launch_ns) / 1000000)
        if row['start_offset_ms'] is None or end - start > MAX_MS * 1000000:
            self.invalid_input = True
            return
        parent = _id(span.get('parentSpanId'), 16)
        category = attributes.get('tool_name_safe', attributes.get('tool_name', 'other'))
        self.spans[key] = (kind, start, row, parent.lower() if parent else None, category)

    def snapshot(self, outcome, cli=None):
        requests, tools = [], []
        executions = {}
        ordered = sorted(self.spans.items(), key=lambda item: (item[1][1], item[0]))
        for (trace, identity), (kind, start, row, parent, category) in ordered:
            if kind == 'claude_code.tool.execution':
                executions.setdefault((trace, parent), []).append(row)
        matched = 0
        for key, (kind, start, row, parent, category) in ordered:
            if kind == 'claude_code.llm_request':
                requests.append(row)
            elif kind == 'claude_code.tool':
                children = executions.get(key, [])
                child = children[0] if len(children) == 1 else {}
                matched += len(children)
                tools.append({'category': category, 'wall_ms': row['duration_ms'],
                              'execution_observed': True if len(children) == 1 else None,
                              'execution_ms': child.get('duration_ms'), 'success': child.get('success')})
        raw = {'version': VERSION, 'outcome': outcome, 'setup_failed': self.setup_failed,
               'invalid_input': self.invalid_input, 'limited': self.limited or
               len(requests) > MAX_ROWS or len(tools) > MAX_ROWS,
               'requests': requests[:MAX_ROWS], 'tools': tools[:MAX_ROWS],
               'unmatched_execution_spans': sum(map(len, executions.values())) - matched,
               'cli_wall_ms': self.wall_ms if self.wall_ms is not None else
               (time.monotonic() - self.started) * 1000, 'cli': cli or {}}
        return sanitize(raw)


def unavailable(outcome='spawn_failed'):
    return sanitize({'version': VERSION, 'outcome': outcome, 'setup_failed': True,
                     'invalid_input': False, 'limited': False, 'requests': [], 'tools': [],
                     'unmatched_execution_spans': None})
