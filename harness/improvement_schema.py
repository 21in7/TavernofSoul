"""Bounded native discovery schema, built only from prepared approved inputs.

The CLI schema constrains syntax and ranges, not semantic correctness. The
caller must still verify identity/context and run validate_candidates afterwards.
No source reads, model calls, credentials or fallback live in this module.
"""
import os
from pathlib import Path

from harness import improvement_report as contract

_PREPARED = object()
MAX_SCHEMA_BYTES = 65536  # Bound the single native CLI argument, including UTF-8 paths.


def _object(properties):
    return dict(type='object', properties=properties, required=list(properties),
                additionalProperties=False)


def _array(items, maximum, minimum=0):
    return dict(type='array', items=items, minItems=minimum, maxItems=maximum)


def _text(field):
    return dict(type='string', minLength=1, pattern='[가-힣]' if field in ('title', 'analogy') else r'\S', maxLength=(
        contract.CANDIDATE_DISPLAY_LIMITS[field] * contract.PRIVATE_PROSE_MULTIPLIER))


def candidate_schema(paths, sources, limits):
    """Full candidates root; cross-field/semantic constraints remain client-side."""
    evidence = []
    for path in paths:
        source = sources[path]
        if source is None or not source.splitlines():
            continue
        end = min(len(source.splitlines()), 1000000)
        evidence.append(_object(dict(
            path=dict(type='string', enum=[path]),
            start_line=dict(type='integer', minimum=1, maximum=end),
            end_line=dict(type='integer', minimum=1, maximum=end),
            summary=_text('evidence_summary'))))
    # An impossible item schema allows only empty arrays for no available source.
    evidence_item = dict(anyOf=evidence) if evidence else False
    def evidence_list(minimum):
        return _array(evidence_item, limits['max_evidence'], minimum)
    fields = dict(
        title=_text('title'), priority=dict(type='string', enum=['high', 'medium', 'low']),
        analogy=_text('analogy'), issue=_text('issue'), evidence=evidence_list(1),
        benefit={'anyOf': [ _object(dict(
            kind=dict(type='string', enum=[kind]), text=_text('benefit'),
            evidence=evidence_list(1 if kind == 'measured' else 0)))
            for kind in ('estimated', 'measured')]},
        risk=_text('risk'),
        edit_files=dict(_array(dict(type='string', enum=list(paths)),
                              limits['max_edit_files'], 1), uniqueItems=True),
        validation_plan=_array(_text('validation_step'), limits['max_validation_steps'], 1),
        documentation_impact=_text('documentation_impact'))
    return _object(dict(candidates=dict(_array(_object(fields),
                             limits['max_candidates_per_specialist']), uniqueItems=True)))


class DiscoverySchema:
    """Prepared context capability; arbitrary caller JSON is never a schema input.

    Serialized inputs are detached. Validation rebuilds the entire canonical
    schema, so changing a schema property cannot weaken the CLI contract.
    """
    __slots__ = ('_binding', '_inputs', '_schema')

    def __init__(self, role, root, paths, sources, config, *, _prepared=None):
        if _prepared is not _PREPARED:
            raise ValueError('discovery_schema_invalid')
        object.__setattr__(self, '_binding', (role, str(Path(root).absolute())))
        object.__setattr__(self, '_inputs', contract.canonical_json(
            dict(paths=paths, sources=sources, config=config)))
        schema = contract.canonical_json(candidate_schema(paths, sources, config['limits']))
        if len(schema) > MAX_SCHEMA_BYTES:
            raise ValueError('discovery_schema_invalid')
        object.__setattr__(self, '_schema', schema)

    def __setattr__(self, name, value):
        raise ValueError('discovery_schema_invalid')


def prepare(role, root, paths, snapshots, config):
    if role not in contract.SPECIALIST_ROLES:
        raise ValueError('discovery_schema_scope_invalid')
    paths = contract.validate_scope_paths(paths)
    config = contract.validate_config(config)
    if set(snapshots) != set(paths) or len(paths) > config['limits']['max_scope_files']:
        raise ValueError('discovery_schema_scope_invalid')
    contract.fingerprint_sources(snapshots)
    sources = {}
    total = 0
    for path in paths:
        content = snapshots[path]['content'] if snapshots[path]['exists'] else None
        if content is not None:
            total += len(content)
            if len(content) > config['limits']['max_file_bytes']:
                raise ValueError('discovery_schema_scope_invalid')
        sources[path] = content.decode('utf-8', 'strict') if content is not None else None
    if total > config['limits']['max_source_bytes']:
        raise ValueError('discovery_schema_scope_invalid')
    return DiscoverySchema(role, root, paths, sources, config, _prepared=_PREPARED)


def validate_request(request, role, provider, workspace, *, write=False, smoke=False,
                     scoped=False):
    if (type(request) is not DiscoverySchema or
            os.environ.get('TAVERN_IMPROVEMENT_DISCOVERY') != '1' or
            role not in contract.SPECIALIST_ROLES or provider != 'zai' or
            write or smoke or not scoped or workspace is None or
            request._binding != (role, str(Path(workspace).absolute()))):
        raise ValueError('discovery_schema_scope_invalid')
    # Inputs can include the approved 1.5MiB snapshot; no transport parser is
    # used here. They are canonical private bytes created by prepare, not output.
    import json
    data = json.loads(request._inputs)
    config = contract.validate_config(data['config'])
    paths = contract.validate_scope_paths(data['paths'])
    if set(paths) != set(data['sources']):
        raise ValueError('discovery_schema_scope_invalid')
    expected = contract.canonical_json(candidate_schema(paths, data['sources'], config['limits']))
    if len(expected) > MAX_SCHEMA_BYTES or request._schema != expected:
        raise ValueError('discovery_schema_invalid')
    return expected.decode('utf-8')


def response_limit(request):
    import json
    if type(request) is not DiscoverySchema:
        raise ValueError('discovery_schema_invalid')
    return contract.validate_config(json.loads(request._inputs)['config'])['limits']['max_response_bytes']
