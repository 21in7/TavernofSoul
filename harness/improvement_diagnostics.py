"""Private bounded failure metadata. Never interpret exception text or attributes.

The active trace belongs to one CLI/API invocation. Its first failure survives
failed settlement/diagnostic writes; no alternate storage or state write occurs
here. The returned private result is also the observation path before Store is
available. Public report projection must never include this object. Separately
authorized improvement-health-v1 selects only fixed cloud failure codes, never
this private object's numeric observations or trace events.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import time

BOUNDARIES = frozenset(('config', 'store', 'storage_readiness', 'project_lock',
    'workflow_lock', 'discovery_lock', 'sender_lock', 'state_read', 'state_save',
    'dependencies', 'snapshot', 'seal', 'stage', 'deadline', 'publication', 'storage_binding',
    'publication_settlement', 'settlement', 'diagnostic_save'))
KINDS = frozenset(('busy', 'timeout', 'interrupted', 'io', 'invalid'))
STAGES = frozenset(('prepare', 'local_explorer', 'specialist', 'independent_reviewer',
                    'apply', 'github', 'settlement', 'publication'))
REASONS = frozenset(a + '_' + b for a in BOUNDARIES for b in KINDS)
_active = ContextVar('improvement_diagnostic_trace', default=None)

# PRIVATE ONLY. Codes are selected at trusted occurrence boundaries, never by
# parsing messages or accepting runner diagnostic/reason dictionaries. Serialized
# details require revalidation but are not proof of their own provenance.
DETAIL_VERSION = 'improvement-failure-v1'
MAX_DETAIL_BYTES = 512  # The fixed keys, code lengths and integer ceilings fit.
DETAIL_REASONS = frozenset(('unknown', 'candidate_invalid', 'review_invalid',
    'candidate_edit_files_invalid', 'candidate_edit_files_duplicate',
    'candidate_edit_files_outside_scope', 'role_preparation_failed',
    'role_execution_failed', 'role_result_invalid', 'role_identity_mismatch',
    'role_context_changed', 'role_json_invalid', 'source_review_unverified',
    'role_context_cleanup_failed', 'role_interrupted', 'role_failed',
    'config_invalid', 'config_unavailable', 'config_permissions', 'endpoint_invalid',
    'input_invalid', 'feedback_invalid', 'feedback_too_large', 'context_too_large',
    'transport_failed', 'timeout', 'response_too_large', 'headers_too_large',
    'response_malformed', 'redirect_refused', 'http_failed', 'model_mismatch',
    'response_incomplete', 'tools_refused', 'empty_response', 'evidence_outside_window'))
CAUSES = frozenset(('unavailable', 'validation', 'missing_cli', 'runtime_unavailable',
    'unsafe_workspace', 'auth_file_unavailable', 'authentication_failed',
    'path_aliases_read_only', 'timeout', 'spawn_failed', 'cli_failed',
    'invalid_response', 'probe_mismatch', 'json_invalid', 'envelope_invalid',
    'quota', 'identity_mismatch', 'context_changed', 'context_cleanup_failed',
    'interrupted', 'transport_failed', 'http_failed', 'evidence_outside_window',
    'source_review_unverified', 'response_too_large', 'context_too_large',
    'response_incomplete', 'tools_refused', 'empty_response', 'io'))
PHASES = frozenset(('preparation', 'runtime', 'authentication', 'execution',
    'response', 'json', 'candidate', 'review', 'identity', 'context', 'cleanup',
    'transport', 'http', 'window', 'deadline'))
FIELDS = frozenset(('schema', 'sources', 'scope', 'candidates', 'title', 'priority',
    'analogy', 'issue', 'evidence', 'evidence.path', 'evidence.start_line',
    'evidence.end_line', 'evidence.summary', 'benefit', 'benefit.kind',
    'benefit.text', 'benefit.evidence', 'benefit.evidence.path',
    'benefit.evidence.start_line', 'benefit.evidence.end_line',
    'benefit.evidence.summary', 'risk', 'edit_files', 'validation_plan',
    'documentation_impact', 'review.plan', 'review.capture', 'review.stream',
    'review.metadata', 'review.read_request', 'review.read_pair', 'review.read_content',
    'review.result', 'review.coverage', 'review.assessments', 'review.documentation',
    'review.proof'))
RULES = frozenset(('type', 'fields', 'empty', 'length', 'control', 'encoding',
    'range', 'allowlist', 'duplicate', 'path', 'outside_scope',
    'source_unavailable', 'korean', 'byte_limit'))
NUMBER_BOUNDS = {'exit_code': (0, 255), 'errno': (0, 4095), 'http_status': (100, 599)}
_DETAIL_KEYS = frozenset(('version', 'reason', 'cause', 'phase', 'field', 'rule')) | frozenset(NUMBER_BOUNDS)


def _code(value, allowed):
    return type(value) is str and len(value) <= 64 and value in allowed


def _empty_detail():
    return dict(version=DETAIL_VERSION, reason='unknown', cause='unavailable',
                phase=None, field=None, rule=None, exit_code=None, errno=None, http_status=None)


def sanitize_detail(value):
    """Return a detached fixed-size dict; legacy/malformed causes are unavailable.

    Only exact dict/str/int types are accepted. Unknown keys/schema/codes fail
    closed; invalid numbers become null (no coercion, bool or negative exits).
    Missing field/rule makes validation unavailable, retaining a known reason
    and phase. Non-validation causes never carry field/rule guesses.
    This is a storage/feedback filter, NEVER runner authentication.
    """
    empty = _empty_detail()
    if type(value) is not dict or len(value) != len(_DETAIL_KEYS):
        return empty
    if any(type(key) is not str for key in value) or set(value) != _DETAIL_KEYS:
        return empty
    if (type(value['version']) is not str or value['version'] != DETAIL_VERSION or
            not _code(value['reason'], DETAIL_REASONS) or not _code(value['cause'], CAUSES) or
            (value['phase'] is not None and not _code(value['phase'], PHASES))):
        return empty
    result = dict(empty, reason=value['reason'], cause=value['cause'], phase=value['phase'])
    if value['cause'] == 'validation':
        if _code(value['field'], FIELDS) and _code(value['rule'], RULES):
            result.update(field=value['field'], rule=value['rule'])
        else:
            result['cause'] = 'unavailable'
    for key, (minimum, maximum) in NUMBER_BOUNDS.items():
        number = value[key]
        if type(number) is int and minimum <= number <= maximum:
            result[key] = number
    return result


class _Detail:
    def __init__(self, value):
        try:
            self.value = sanitize_detail(value)
        except (Exception, KeyboardInterrupt):
            self.value = _empty_detail()


def detail(reason='unknown', cause='unavailable', *, phase=None, field=None,
           rule=None, exit_code=None, errno=None, http_status=None):
    """Mint an in-process capability at a trusted observed failure boundary.

    Use attach(error, detail(...)); persist exception_detail(error). No strings
    other than the constants above can survive. Do not mint from runner metadata.
    """
    return _Detail(dict(version=DETAIL_VERSION, reason=reason, cause=cause, phase=phase,
        field=field, rule=rule, exit_code=exit_code, errno=errno, http_status=http_status))


class _Link:
    def __init__(self, owner, value):
        self.owner, self.value = owner, value


def _attributes(value):
    if type(value) is _Result:
        attrs = object.__getattribute__(value, '__dict__')
    else:
        # Bypass subclass __dict__ properties and __getattribute__ hooks.
        attrs = BaseException.__dict__['__dict__'].__get__(value)
    # Reject hostile key equality hooks before looking up or setting our key.
    if type(attrs) is dict and len(attrs) <= 64 and all(type(key) is str for key in attrs):
        return attrs
    return None


def _linked(exc):
    # Bind to exception identity: copying an attribute/token from another error
    # or manufacturing a JSON diagnostic cannot impersonate a trusted catch.
    attrs = _attributes(exc)
    if type(attrs) is not dict:
        return None
    link = attrs.get('_improvement_failure')
    return link.value if type(link) is _Link and link.owner is exc and type(link.value) is _Detail else None


def attach(exc, value):
    """Attach only a minted capability, keeping the first link; return exc.

    Best effort and no storage/global registry. The per-error cycle is garbage
    collected with the exception. Metadata failure never replaces that exception.
    """
    try:
        if type(value) is _Detail and _linked(exc) is None:
            attrs = _attributes(exc)
            if type(attrs) is dict and len(attrs) < 64:
                attrs['_improvement_failure'] = _Link(exc, value)
    except (Exception, KeyboardInterrupt):
        pass
    return exc


def exception_detail(exc):
    """Read our identity-bound link only, else explicit unknown/unavailable."""
    try:
        value = _linked(exc)
        return sanitize_detail(value.value if value is not None else None)
    except (Exception, KeyboardInterrupt):
        return _empty_detail()


def inherit(exc, original):
    """Transfer an exception/result link to a wrapper; ignore foreign metadata."""
    try:
        attach(exc, _linked(original))
    except (Exception, KeyboardInterrupt):
        pass
    return exc


class _Result(dict):
    """JSON-compatible adapter result with an in-process provenance link."""


def attach_result(result, value=None, *, source=None):
    """Return a result copy with private failure_detail and hidden provenance.

    Pass a minted value OR source=original_exception to preserve its link without
    reclassification. Trusted adapters call this at their catch boundary. Validate
    role/provider/model identity BEFORE result_detail. JSON round trips erase
    provenance; sanitize_detail is only for already trusted private storage.
    """
    try:
        if source is not None:
            value = _linked(source)
        if type(value) is _Detail and type(result) is dict:
            linked = _Result(result)
            linked['failure_detail'] = sanitize_detail(value.value)
            linked._improvement_failure = _Link(linked, value)
            return linked
    except (Exception, KeyboardInterrupt):
        pass
    return result


def result_detail(result):
    """Ignore arbitrary runner dicts/diagnostics, including valid-looking codes."""
    if type(result) is _Result:
        return exception_detail(result)
    return _empty_detail()


def bounded_integer(value, maximum):
    return value if type(value) is int and 0 <= value <= maximum else None


def event(boundary, kind, *, stage=None, slot=None, errno=None, elapsed_ms=None, detail=None):
    result = _base_event(boundary, kind, stage=stage, slot=slot, errno=errno, elapsed_ms=elapsed_ms)
    try:
        result['detail'] = sanitize_detail(detail)
    except (Exception, KeyboardInterrupt):
        pass  # Keep the broad event if optional metadata cannot be processed.
    return result


def _base_event(boundary, kind, *, stage=None, slot=None, errno=None, elapsed_ms=None):
    if type(boundary) is not str or boundary not in BOUNDARIES or type(kind) is not str or kind not in KINDS:
        raise ValueError('Invalid private diagnostic code.')
    try:
        at = datetime.now(timezone.utc).isoformat()
    except (Exception, KeyboardInterrupt):
        at = None  # Do not invent an occurrence time if the clock is unavailable.
    # slot is an hour index, never an untrusted timestamp/string from a model.
    return {'version': 'improvement-diagnostic-v1',
            'at': at,
            'reason': boundary + '_' + kind, 'boundary': boundary,
            'lock_kind': {'project_lock': 'source', 'workflow_lock': 'workflow',
                          'discovery_lock': 'discovery', 'sender_lock': 'sender'}.get(boundary),
            'stage': stage if type(stage) is str and stage in STAGES else None,
            'slot': bounded_integer(slot, 23), 'errno': bounded_integer(errno, 4095),
            'elapsed_ms': bounded_integer(elapsed_ms, 86400000), 'holder_pid': None,
            'detail': _empty_detail()}


class Trace:
    def __init__(self):
        self.first = None
        self.stage = self.slot = None

    def __enter__(self):
        self.token = _active.set(self)
        return self

    def __exit__(self, *exc):
        _active.reset(self.token)

    def capture(self, boundary, exc, started=None, kind=None):
        if self.first is None:
            try:
                kind = kind or ('busy' if isinstance(exc, BlockingIOError) else
                                'timeout' if isinstance(exc, TimeoutError) else
                                'interrupted' if isinstance(exc, KeyboardInterrupt) else
                                'io' if isinstance(exc, OSError) else 'invalid')
                # Reserve the broad first failure before optional metadata work.
                self.first = _base_event(boundary, kind, stage=self.stage, slot=self.slot)
                self.first['detail'] = exception_detail(exc)
                self.first['errno'] = bounded_integer(
                    OSError.errno.__get__(exc) if isinstance(exc, OSError) else None, 4095)
                if started is not None:
                    self.first['elapsed_ms'] = bounded_integer(int((time.monotonic() - started) * 1000), 86400000)
            except (Exception, KeyboardInterrupt):
                pass  # Diagnostic construction cannot hide the caught failure.
        return self.first


def position(stage=None, slot=None):
    trace = _active.get()
    if trace is not None:
        trace.stage, trace.slot = stage, slot


def current():
    return _active.get()


def record(name, exc, started=None):
    """Observe a caught failure without changing its existing recovery contract."""
    if type(name) is not str or name not in BOUNDARIES:
        raise ValueError('Invalid diagnostic boundary.')
    trace = _active.get()
    return trace.capture(name, exc, started) if trace is not None else None


@contextmanager
def boundary(name):
    if type(name) is not str or name not in BOUNDARIES:
        raise ValueError('Invalid diagnostic boundary.')
    started = time.monotonic()
    try:
        yield
    except (Exception, KeyboardInterrupt) as exc:
        trace = _active.get()
        if trace is not None:
            trace.capture(name, exc, started)
        raise


def at(name):
    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            with boundary(name):
                return function(*args, **kwargs)
        return call
    return decorate


def timeout():
    # Called only by the trusted alarm handler, never inferred from LoopError text.
    trace = _active.get()
    if trace is not None:
        trace.capture('deadline', TimeoutError(), kind='timeout')


def safe_reason(value, fallback='stage_invalid'):
    if type(fallback) is not str or fallback not in REASONS:
        raise ValueError('Invalid diagnostic fallback.')
    return value if type(value) is str and value in REASONS else fallback
