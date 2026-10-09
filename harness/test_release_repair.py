"""Explicit repairs use source denominators; they never alter the live inputs."""
import json
from pathlib import Path

import pytest

from harness.parser_fixture import prepare_world_workspace, parse_workspace
from harness.release_repair import prepare_release
from ipfparser.contracts import ContractError, load_release


def test_source_repair_preserves_input_and_version(tmp_path):
    root = prepare_world_workspace(tmp_path / 'project')
    db = parse_workspace(root, 'drop-fixture-v1', include_world=True)
    release = Path(db.BASE_PATH_OUTPUT)
    path = root / 'itos_unpack/ies_drop.ipf/zonedrop/ZoneDropItemList_harness_field.ies'
    path.write_text('ItemClassName,BaseRatio,DropRatio,DropGroup\nharness_ore,1000000,32000,\n')
    drops = release / 'map_item.json'
    legacy = json.loads(drops.read_text())
    legacy[0]['Chance'] = 320
    drops.write_text(json.dumps(legacy))
    before = {path.name: path.read_bytes() for path in release.glob('*.json')}
    destination = tmp_path / 'repaired'
    report = prepare_release(release, destination, root, 'itos')
    load_release(destination)
    fixed = json.loads((destination / 'map_item.json').read_text())
    assert next(row['Chance'] for row in fixed if row['Map'] == '900') == 3.2
    assert report['version'] == {'version': 'drop-fixture-v1'}
    assert {path.name: path.read_bytes() for path in release.glob('*.json')} == before
    with pytest.raises(ValueError, match='new directory'):
        prepare_release(release, destination, root, 'itos')


@pytest.mark.parametrize('empty_map_item', [False, True])
def test_source_repair_reports_previous_versions_from_both_collections(tmp_path, empty_map_item):
    root = prepare_world_workspace(tmp_path / 'project')
    db = parse_workspace(root, 'drop-fixture-v1', include_world=True)
    release = Path(db.BASE_PATH_OUTPUT)
    previous_versions = {
        'item_monster': ['old-v2', 'old-v10', 'old-v2'],
        'map_item': [] if empty_map_item else ['old-v1', 'old-v2'],
    }
    for name, versions in previous_versions.items():
        path = release / (name + '.json')
        rows = json.loads(path.read_text())
        assert rows
        path.write_text(json.dumps([dict(rows[0], InputVersion=version) for version in versions]))
    before = {path.name: path.read_bytes() for path in release.glob('*.json')}
    destination = tmp_path / 'repaired'

    report = prepare_release(release, destination, root, 'itos')

    load_release(destination)
    expected = ['old-v10', 'old-v2'] if empty_map_item else ['old-v1', 'old-v10', 'old-v2']
    assert report['previous_source_versions'] == expected
    assert report['version'] == {'version': 'drop-fixture-v1'}
    assert {path.name: path.read_bytes() for path in release.glob('*.json')} == before


def test_source_repair_rejects_missing_collection_and_wrong_revision(tmp_path):
    root = prepare_world_workspace(tmp_path / 'project')
    db = parse_workspace(root, 'wrong-version', include_world=True)
    release = Path(db.BASE_PATH_OUTPUT)
    output = tmp_path / 'output'
    with pytest.raises(ValueError, match='revision'):
        prepare_release(release, output, root, 'itos')
    assert not output.exists()
    (release / 'buff.json').unlink()
    with pytest.raises(ContractError, match='missing release collection'):
        prepare_release(release, output, root, 'itos')
    assert not output.exists()
