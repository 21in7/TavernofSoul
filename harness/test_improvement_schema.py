"""Pure native candidate schema contracts; execution belongs to the parent."""
import json

import pytest

from harness import improvement_schema as schema, improvement_report as contract


def configuration():
    return dict(version=contract.CONFIG_VERSION, timezone='Asia/Seoul',
        scope_file='harness/scope.txt', specialist_roles=list(contract.SPECIALIST_ROLES),
        reviewer_role='reviewer', shared_files=['AGENTS.md'], limits=dict(contract.LIMIT_CEILINGS))


def prepared(root, config=None):
    snapshots = {'downloader/example.py': dict(exists=True, mode=0o644, content=b'one\ntwo\n'),
                 'AGENTS.md': dict(exists=False, mode=None, content=None)}
    return schema.prepare('downloader', root, list(snapshots), snapshots, config or configuration())


def test_full_canonical_schema_is_bounded_by_prepared_sources(tmp_path, monkeypatch):
    monkeypatch.setenv('TAVERN_IMPROVEMENT_DISCOVERY', '1')
    config = configuration()
    config['limits'].update(max_candidates_per_specialist=1, max_evidence=2,
                            max_edit_files=3, max_validation_steps=4)
    request = prepared(tmp_path, config)
    text = schema.validate_request(request, 'downloader', 'zai', tmp_path, scoped=True)
    value = json.loads(text)
    assert contract.canonical_json(value).decode() == text
    assert value['required'] == ['candidates'] and value['additionalProperties'] is False
    array = value['properties']['candidates']
    assert array['maxItems'] == 1 and array['minItems'] == 0
    candidate = array['items']
    assert set(candidate['required']) == set(contract.CANDIDATE_FIELDS)
    assert candidate['additionalProperties'] is False
    fields = candidate['properties']
    assert fields['edit_files']['items']['enum'] == ['downloader/example.py', 'AGENTS.md']
    assert fields['edit_files']['maxItems'] == 3 and fields['edit_files']['uniqueItems']
    assert fields['title']['maxLength'] == 320
    assert fields['documentation_impact']['maxLength'] == 1440
    evidence = fields['evidence']['items']['anyOf']
    assert len(evidence) == 1 and evidence[0]['additionalProperties'] is False
    assert evidence[0]['properties']['path']['enum'] == ['downloader/example.py']
    assert evidence[0]['properties']['end_line']['maximum'] == 2
    assert fields['evidence']['maxItems'] == 2
    assert fields['validation_plan']['maxItems'] == 4
    assert [b['properties']['evidence']['minItems'] for b in fields['benefit']['anyOf']] == [0, 1]


@pytest.mark.parametrize('change', ['role', 'provider', 'workspace', 'write', 'smoke', 'scoped', 'guard', 'dict'])
def test_schema_capability_cannot_expand_execution_scope(tmp_path, monkeypatch, change):
    request = prepared(tmp_path)
    monkeypatch.setenv('TAVERN_IMPROVEMENT_DISCOVERY', '1')
    options = dict(role='downloader', provider='zai', workspace=tmp_path,
                   write=False, smoke=False, scoped=True)
    if change == 'guard':
        monkeypatch.delenv('TAVERN_IMPROVEMENT_DISCOVERY')
    elif change == 'dict':
        request = {'type': 'object'}
    else:
        options[change] = dict(role='reviewer', provider='claude', workspace=tmp_path / 'other',
                               write=True, smoke=True, scoped=False)[change]
    with pytest.raises(ValueError):
        schema.validate_request(request, **options)


def test_schema_is_detached_immutable_and_rejects_tampered_schema(tmp_path, monkeypatch):
    monkeypatch.setenv('TAVERN_IMPROVEMENT_DISCOVERY', '1')
    config = configuration()
    config['limits']['max_candidates_per_specialist'] = 1
    request = prepared(tmp_path, config)
    config['limits']['max_candidates_per_specialist'] = 2
    value = json.loads(schema.validate_request(request, 'downloader', 'zai', tmp_path, scoped=True))
    assert value['properties']['candidates']['maxItems'] == 1
    with pytest.raises(ValueError):
        request._schema = b'{}'
    object.__setattr__(request, '_schema', b'{}')
    with pytest.raises(ValueError, match='schema_invalid'):
        schema.validate_request(request, 'downloader', 'zai', tmp_path, scoped=True)


@pytest.mark.parametrize('content', [b'\xff', b'x' * 131073])
def test_unavailable_or_oversize_source_cannot_build_contract(tmp_path, content):
    with pytest.raises(ValueError):
        schema.prepare('downloader', tmp_path, ['a.py'],
                       {'a.py': dict(exists=True, mode=0o644, content=content)}, configuration())


def test_schema_argument_has_an_explicit_utf8_bound(tmp_path):
    paths = ['d/' + '가' * 200 + str(i) + '.py' for i in range(64)]
    snapshots = {p: dict(exists=True, mode=0o644, content=b'line\n') for p in paths}
    with pytest.raises(ValueError, match='schema_invalid'):
        schema.prepare('downloader', tmp_path, paths, snapshots, configuration())


def test_no_available_lines_cannot_be_used_as_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv('TAVERN_IMPROVEMENT_DISCOVERY', '1')
    snapshots = {'empty.py': dict(exists=True, mode=0o644, content=b'')}
    request = schema.prepare('downloader', tmp_path, list(snapshots), snapshots, configuration())
    snapshots['empty.py']['content'] = b'added later\n'
    value = json.loads(schema.validate_request(request, 'downloader', 'zai', tmp_path, scoped=True))
    fields = value['properties']['candidates']['items']['properties']
    assert fields['evidence']['items'] is False and fields['evidence']['minItems'] == 1
    assert fields['edit_files']['items']['enum'] == ['empty.py']


def test_native_format_still_requires_semantic_and_cross_field_client_validation():
    from harness.test_improvement_loop import draft
    item = draft('a.py', start=2, end=1)
    with pytest.raises(contract.ValidationError):
        contract.validate_candidates({'candidates': [item]}, {'a.py': 'one\ntwo\n'})
    item = draft('a.py')
    item['edit_files'] = ['outside.py']
    with pytest.raises(contract.ValidationError):
        contract.validate_candidates({'candidates': [item]}, {'a.py': 'one\ntwo\n'})
