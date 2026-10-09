"""Missing or edited real source inputs cannot pass as a reviewed snapshot."""
import json
import shutil

import pytest
from harness.live_fixture import FIXTURE, verify_snapshot


def test_reviewed_snapshot_has_both_regions_and_real_inputs():
    manifest = verify_snapshot()
    for region in ('itos', 'ktos'):
        assert len(manifest['regions'][region]['unpack_commit']) == 40
        assert '11107087' in manifest['regions'][region]['selected_ids']


def test_tampered_real_lua_is_rejected_before_parsing(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / 'sample')
    sample = tmp_path / 'sample'
    (sample / 'itos/unpack/shared.ipf/shared_item_goddess_reinforce.lua').write_text('return 0')
    with pytest.raises(ValueError, match='integrity'):
        verify_snapshot(sample)


def test_missing_region_in_manifest_is_rejected(tmp_path):
    shutil.copytree(FIXTURE, tmp_path / 'sample')
    sample = tmp_path / 'sample'
    manifest = json.loads((sample / 'manifest.json').read_text())
    manifest['regions'].pop('ktos')
    (sample / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Incomplete'):
        verify_snapshot(sample)
