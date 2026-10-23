"""Private bounded failure metadata. Never interpret exception text or attributes.

The active trace belongs to one CLI/API invocation. Its first failure survives
failed settlement/diagnostic writes; no alternate storage or state write occurs
here. The returned private result is also the observation path before Store is
available. Public report projection must never include this object.
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


def bounded_integer(value, maximum):
    return value if type(value) is int and 0 <= value <= maximum else None


def event(boundary, kind, *, stage=None, slot=None, errno=None, elapsed_ms=None):
    if type(boundary) is not str or boundary not in BOUNDARIES or type(kind) is not str or kind not in KINDS:
        raise ValueError('Invalid private diagnostic code.')
    # slot is an hour index, never an untrusted timestamp/string from a model.
    return {'version': 'improvement-diagnostic-v1',
            'at': datetime.now(timezone.utc).isoformat(),
            'reason': boundary + '_' + kind, 'boundary': boundary,
            'lock_kind': {'project_lock': 'source', 'workflow_lock': 'workflow',
                          'discovery_lock': 'discovery', 'sender_lock': 'sender'}.get(boundary),
            'stage': stage if type(stage) is str and stage in STAGES else None,
            'slot': bounded_integer(slot, 23), 'errno': bounded_integer(errno, 4095),
            'elapsed_ms': bounded_integer(elapsed_ms, 86400000), 'holder_pid': None}


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
            kind = kind or ('busy' if isinstance(exc, BlockingIOError) else
                            'timeout' if isinstance(exc, TimeoutError) else
                            'interrupted' if isinstance(exc, KeyboardInterrupt) else
                            'io' if isinstance(exc, OSError) else 'invalid')
            self.first = event(boundary, kind, stage=self.stage, slot=self.slot,
                errno=exc.errno if isinstance(exc, OSError) else None,
                elapsed_ms=int((time.monotonic() - started) * 1000) if started is not None else None)
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
