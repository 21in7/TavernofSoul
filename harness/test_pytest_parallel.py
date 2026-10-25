"""Small real subprocess suites exercise controller evidence and worker isolation."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from harness.pytest_support import PytestResults, run_suite, worker_count

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = '''
import json, os, sys
from pathlib import Path
from harness.pytest_support import run_suite
root, output, workers = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
before = {key: os.environ.get(key) for key in (
    'PYTEST_DISABLE_PLUGIN_AUTOLOAD', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS',
    'HARNESS_WORK_DIR', 'TMPDIR', 'TMP', 'TEMP')}
before_cwd = Path.cwd()
report = run_suite([root / 'test_sample.py'], root=root,
    ini=Path(sys.argv[4]), workers=workers, basetemp=root / 'base',
    deselect=['test_sample.py::test_excluded'])
assert before == {key: os.environ.get(key) for key in before}
assert Path.cwd() == before_cwd
output.write_text(json.dumps(report), encoding='utf-8')
raise SystemExit(report['exit_code'])
'''


def suite(tmp_path, source, workers):
    project = tmp_path / ('suite-' + str(workers))
    project.mkdir()
    (project / 'test_sample.py').write_text(source, encoding='utf-8')
    output = project / 'result.json'
    env = dict(os.environ)
    for key in list(env):
        if key.startswith('PYTEST_'):
            env.pop(key)
    env.update(PYTHONPATH=os.pathsep.join((str(ROOT), env.get('PYTHONPATH', ''))),
               PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
               PYTEST_ADDOPTS='--definitely-invalid-harness-option',
               PYTEST_PLUGINS='missing_external_harness_plugin_123')
    result = subprocess.run([sys.executable, '-c', SCRIPT, str(project), str(output),
                             str(workers), str(ROOT / 'harness/pytest.ini')],
                            cwd=str(project), env=env, capture_output=True, text=True,
                            timeout=90)
    assert output.is_file(), result.stdout + result.stderr
    report = json.loads(output.read_text(encoding='utf-8'))
    assert (result.returncode == 0) == (report['status'] == 'passed')
    return report, project


def test_real_serial_parallel_ids_isolation_and_passed_cleanup(tmp_path):
    source = '''
import json, os, tempfile
from pathlib import Path
import pytest
RECORDS = Path(__file__).parent
IMPORT_CWD = str(Path.cwd())
@pytest.mark.parametrize('number', range(8))
def test_ok(tmp_path, number):
    (tmp_path / 'payload').write_text('owned scratch')
    (RECORDS / ('seen-' + str(number) + '.json')).write_text(json.dumps({
        'pid': os.getpid(), 'cwd': str(Path.cwd()), 'import_cwd': IMPORT_CWD,
        'work': os.environ.get('HARNESS_WORK_DIR'), 'tmp': tempfile.gettempdir(),
        'fixture': str(tmp_path)}))
def test_excluded():
    raise AssertionError('deselection must be preserved')
'''
    serial, serial_root = suite(tmp_path, source, 1)
    parallel, parallel_root = suite(tmp_path, source, 2)
    for report, root in ((serial, serial_root), (parallel, parallel_root)):
        assert report['status'] == 'passed'
        assert report['selected'] == report['passed'] == 8
        assert report['collection_sha256'] == report['passed_sha256']
        assert report['deselected'] == ['test_sample.py::test_excluded']
        assert not any(report[key] for key in ('skipped', 'errors', 'failures'))
        timing = report['timing']
        assert timing['pytest_elapsed_seconds'] >= 0
        assert timing['test_elapsed_seconds_sum'] >= 0
        assert len(timing['slowest_tests']) == 8
        for path in root.glob('seen-*.json'):
            record = json.loads(path.read_text())
            assert record['import_cwd'] == record['cwd']
            if report['workers'] == 1:
                assert record['cwd'] == str(root)
            assert not Path(record['fixture']).exists()
    assert serial['collection_sha256'] == parallel['collection_sha256']
    records = [json.loads(p.read_text()) for p in parallel_root.glob('seen-*.json')]
    assert len(records) == 8
    assert len({r['pid'] for r in records}) == 2
    assert len({r['work'] for r in records}) == 2
    assert len({r['tmp'] for r in records}) == 2
    for record in records:
        assert record['cwd'] == record['work']
        assert Path(record['work']).parent == Path(record['fixture']).parent
        assert Path(record['tmp']).parent == Path(record['work'])
        assert parallel_root in Path(record['work']).parents


@pytest.mark.parametrize('workers', [1, 2])
def test_real_failures_skips_xfails_and_failed_tmp_preservation(tmp_path, workers):
    report, root = suite(tmp_path, '''
from pathlib import Path
import pytest
RECORDS = Path(__file__).parent
def test_ok(tmp_path):
    (RECORDS / 'passed-path').write_text(str(tmp_path))
def test_failure(tmp_path):
    (tmp_path / 'evidence').write_text('preserve until owned-tree cleanup')
    (RECORDS / 'failed-path').write_text(str(tmp_path))
    assert False
def test_skip():
    pytest.skip('required input unavailable')
@pytest.mark.xfail(reason='known bug')
def test_xfail():
    assert False
@pytest.mark.xfail(reason='unexpected pass is still not coverage')
def test_xpass():
    pass
@pytest.fixture
def bad_setup():
    raise RuntimeError('setup failed')
def test_setup(bad_setup):
    pass
@pytest.fixture
def bad_teardown():
    yield
    raise RuntimeError('teardown failed')
def test_teardown(bad_teardown):
    pass
''', workers)
    assert report['status'] == 'failed'
    assert report['selected'] == 7 and report['passed'] == 1
    assert len(report['failures']) == 1
    assert len(report['skipped']) == 3
    error_ids = {entry['test'].split('::')[-1] for entry in report['errors']}
    assert {'test_setup', 'test_teardown'} <= error_ids <= {'', 'test_setup', 'test_teardown'}
    assert not Path((root / 'passed-path').read_text()).exists()
    failed = Path((root / 'failed-path').read_text())
    assert (failed / 'evidence').read_text() == 'preserve until owned-tree cleanup'


def test_real_worker_collection_mismatch_fails(tmp_path):
    report, _ = suite(tmp_path, '''
import os
def test_common(): pass
if os.environ.get('PYTEST_XDIST_WORKER') == 'gw1':
    def test_extra(): pass
''', 2)
    assert report['status'] == 'failed'
    assert report['selected'] == report['passed'] == 0
    assert report['errors']


def test_real_worker_crash_fails_without_restart(tmp_path):
    report, root = suite(tmp_path, '''
import os
from pathlib import Path
def test_crash(tmp_path):
    (Path(__file__).parent / 'crashed').write_text(str(tmp_path))
    (tmp_path / 'evidence').write_text('crash evidence')
    os._exit(17)
def test_other(): pass
''', 2)
    assert report['status'] == 'failed'
    assert report['passed'] < 2
    assert any('Worker crashed' in entry['reason'] for entry in report['errors'])
    assert (Path((root / 'crashed').read_text()) / 'evidence').is_file()


@pytest.mark.parametrize('source', ['# empty suite', 'import missing_parallel_dependency_123'])
def test_real_parallel_empty_or_collection_error_fails(tmp_path, source):
    report, _ = suite(tmp_path, source, 2)
    assert report['status'] == 'failed'
    assert report['selected'] == report['passed'] == 0


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'unselected', 'bad-order', 'bad-owner'])
def test_incomplete_or_duplicate_phase_evidence_cannot_be_green(damage):
    # Negative accounting tests only. Real passing evidence comes from subprocesses above.
    plugin = PytestResults()
    plugin.pytest_collection_finish(SimpleNamespace(items=[SimpleNamespace(nodeid='test_one')]))
    phases = ['setup', 'call', 'teardown']
    if damage == 'missing':
        phases.remove('teardown')
    elif damage == 'duplicate':
        phases.insert(2, 'call')
    elif damage == 'bad-order':
        phases.reverse()
    for phase in phases:
        report = pytest.TestReport(nodeid='other' if damage == 'unselected' else 'test_one',
                                   location=('', 0, ''), keywords={}, outcome='passed',
                                   longrepr=None, when=phase, duration=0.0)
        if damage == 'bad-owner':
            report.worker_id = 'unregistered'
        plugin.pytest_runtest_logreport(report)
    assert plugin.finalize(0)['status'] == 'failed'
    assert plugin.report['errors']


@pytest.mark.parametrize('value', [0, 3, -1, 'auto', '2', 'ssh=host', None, True])
def test_only_bounded_local_worker_counts_are_accepted(value):
    with pytest.raises(ValueError, match='1 .* or 2'):
        worker_count(value)


@pytest.mark.parametrize('damage,reason', [
    ('order', 'Missing or mismatched'),
    ('missing', 'Missing or mismatched'),
    ('duplicate', 'Malformed or duplicate'),
    ('completion', 'Malformed or incomplete'),
    ('deselected', 'Worker deselection evidence differs'),
    ('exit', 'Worker crashed'),
])
def test_malformed_worker_collection_evidence_is_rejected(damage, reason):
    # Negative protocol cases; these objects never establish successful execution.
    plugin = PytestResults(workers=2)
    for index in range(2):
        ids = ['test_a', 'test_b']
        if index == 1 and damage == 'order':
            ids.reverse()
        if index == 1 and damage == 'duplicate':
            ids = ['test_a', 'test_a']
        code = 17 if index == 1 and damage == 'exit' else 0
        evidence = {'ids': list(ids), 'deselected': [], 'exitstatus': code}
        if index == 1 and damage == 'deselected':
            evidence['deselected'] = ['test_excluded']
        if index == 1 and damage == 'completion':
            evidence.pop('ids')
        node = SimpleNamespace(gateway=SimpleNamespace(id='gw' + str(index)),
                               workeroutput={'harness_collection': evidence, 'exitstatus': code})
        plugin.pytest_testnodeready(node)
        if not (index == 1 and damage == 'missing'):
            plugin.pytest_xdist_node_collection_finished(node, ids)
        plugin.pytest_testnodedown(node, None)
    report = plugin.finalize(0)
    assert report['status'] == 'failed'
    assert any(reason in entry['reason'] for entry in report['errors'])


def test_empty_explicit_plan_never_collects_an_implicit_directory(tmp_path):
    report = run_suite([], root=tmp_path, ini=ROOT / 'harness/pytest.ini', workers=2)
    assert report['status'] == 'failed'
    assert report['selected'] == report['passed'] == 0
    assert any('No explicit test paths' in entry['reason'] for entry in report['errors'])
