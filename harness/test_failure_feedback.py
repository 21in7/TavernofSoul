"""Offline privacy and attribution regressions using only synthetic source."""
import json
from pathlib import Path

import pytest

from harness import failure_feedback as feedback


SOURCE = 'def test_slice_newline():\n    text = "abc\\n"\n    assert text[:3] == "abc\\n"\n'
POLICY = {'max_file_bytes': 65536}


def newline_slice_assertion():
    text = 'abc\n'
    assert text[:3] == 'abc\n'


def test_actual_newline_slice_assertion_traceback_maps_to_approved_test_source(tmp_path):
    # This is a real isolated AssertionError in this approved test source, rather
    # than an invented runtime message or a check that always returns 'failed'.
    with pytest.raises(AssertionError) as caught:
        newline_slice_assertion()
    frame = caught.traceback[-1]
    name = 'harness/test_failure_feedback.py'
    candidate, model = tmp_path / 'local', tmp_path / 'model'
    source = Path(__file__).read_text(encoding='utf-8')
    for root in (candidate, model):
        (root / 'harness').mkdir(parents=True)
        (root / name).write_text(source, encoding='utf-8')
    entry = {'frames': [{'file': str(candidate / name), 'line': frame.lineno + 1}],
             'exception_type': 'AssertionError', 'reason': str(caught.value)}
    items = feedback.diagnostics([{'command': 'check', 'checks': {'fixture': {'failures': [entry]}}}],
                                 candidate, model, [name], POLICY)
    assert len(items) == 1 and items[0]['function'] == 'newline_slice_assertion'
    assert any("assert text[:3] == 'abc\\n'" in line for line in items[0]['excerpt'])
    assert items[0]['line'] == frame.lineno + 1


@pytest.fixture
def contexts(tmp_path):
    candidate, model = tmp_path / 'candidate', tmp_path / 'model'
    name = 'harness/test_slice.py'
    for root in (candidate, model):
        (root / 'harness').mkdir(parents=True)
        (root / name).write_text(SOURCE)
    (candidate / 'harness/unapproved.py').write_text('UNAPPROVED-SOURCE-MARKER')
    return candidate, model, name


def diagnosed(contexts, entry, category='failures'):
    candidate, model, name = contexts
    results = [{'command': 'check', 'checks': {'fixture': {category: [entry]}}}]
    return feedback.diagnostics(results, candidate, model, [name], POLICY)


def test_short_pytest_traceback_yields_real_assertion_and_verified_function(contexts):
    candidate, _, name = contexts
    items = diagnosed(contexts, {'test': name + '::test_slice_newline[SECRET-PARAM]',
                                'reason': str(candidate / name) + ':3: in untrusted_function\n'
                                '    UNAPPROVED-RUNTIME-VALUE\nE   AssertionError: SECRET-MESSAGE\n' +
                                str(candidate / name) + ':3: AssertionError'})
    assert len(items) == 1
    assert items[0]['file'] == name and items[0]['line'] == 3
    assert items[0]['exception_type'] == 'AssertionError'
    assert items[0]['function'] == 'test_slice_newline'
    assert items[0]['excerpt'][-1] == '3:     assert text[:3] == "abc\\n"'
    assert all(marker not in json.dumps(items) for marker in
               ('SECRET-PARAM', 'SECRET-MESSAGE', 'UNAPPROVED-RUNTIME-VALUE', 'untrusted_function'))


@pytest.mark.parametrize('path', ['/unrelated/harness/test_slice.py',
                                   '/unrelated/../candidate/harness/test_slice.py',
                                   '../harness/test_slice.py', './harness/test_slice.py',
                                   'harness/../harness/test_slice.py', 'harness//test_slice.py',
                                   'prefix/harness/test_slice.py', 'harness/unapproved.py',
                                   'harness/test_slice.py::test[SECRET-PARAM]',
                                   'harness\\test_slice.py', None, [], {'secret': 'SECRET'}])
def test_arbitrary_paths_never_match_by_suffix_or_leak(contexts, path):
    items = diagnosed(contexts, {'frames': [{'file': path, 'line': 3}],
                                'exception_type': 'AssertionError', 'reason': 'PRIVATE-MESSAGE'})
    assert items == [feedback.unavailable('check', 'failures')]


@pytest.mark.parametrize('line', [0, -1, True, '3', 4, 1000001, None, [], {}])
def test_invalid_or_out_of_file_lines_have_no_context(contexts, line):
    assert diagnosed(contexts, {'file': contexts[2], 'line': line}) == \
        [feedback.unavailable('check', 'failures')]


def test_symlink_files_and_ancestors_are_rejected_without_reading(contexts, tmp_path):
    candidate, model, name = contexts
    outside = tmp_path / 'outside.py'
    outside.write_text('OUTSIDE-SECRET')
    (candidate / name).unlink()
    (candidate / name).symlink_to(outside)
    assert diagnosed(contexts, {'file': name, 'line': 1})[0]['context'] == 'unavailable'
    (candidate / name).unlink()
    (candidate / name).write_text(SOURCE)
    (model / name).unlink()
    (model / name).symlink_to(outside)
    assert diagnosed(contexts, {'file': name, 'line': 1})[0]['context'] == 'unavailable'
    (candidate / name).unlink()
    (candidate / 'harness').rename(candidate / 'real')
    (candidate / 'harness').symlink_to(candidate / 'real', target_is_directory=True)
    assert diagnosed(contexts, {'file': name, 'line': 1})[0]['context'] == 'unavailable'


def test_absolute_paths_require_exact_current_candidate_root(contexts):
    candidate, _, name = contexts
    for path in (str(candidate) + '-other/' + name,
                 str(candidate / 'harness/../harness/test_slice.py'),
                 str(candidate / 'harness') + '//test_slice.py'):
        assert diagnosed(contexts, {'file': path, 'line': 3}) == \
            [feedback.unavailable('check', 'failures')]


def test_python_and_structured_frames_filter_exception_and_function_fields(contexts):
    _, _, name = contexts
    for entry in ({'traceback': '  File "' + name + '", line 3, in SECRET-FUNCTION\n'
                              'ValueError: SECRET-RUNTIME'},
                  {'traceback': [{'filename': name, 'lineno': 3, 'function': 'SECRET-FUNCTION'}],
                   'exception_type': 'ValueError'}):
        item = diagnosed(contexts, entry)[0]
        assert item['exception_type'] == 'ValueError'
        assert item['function'] == 'test_slice_newline'
        assert 'SECRET' not in json.dumps(item)
    item = diagnosed(contexts, {'file': name, 'line': 3, 'exception_type': 'SECRET-ERROR'})[0]
    assert item['exception_type'] == 'unavailable'


@pytest.mark.parametrize('category', ['failures', 'errors', 'skipped'])
def test_categories_are_fixed_and_malformed_entries_remain_unattributed(contexts, category):
    for entry in ('SECRET', None, [], {'reason': ['SECRET'], 'frames': [None, 'SECRET']}):
        assert diagnosed(contexts, entry, category) == [feedback.unavailable('check', category)]


def test_malformed_groups_and_output_limits_keep_explicit_fallback(contexts):
    candidate, model, name = contexts
    groups = {'group': {'failures': [{'file': name, 'line': 3}] * 100}}
    items = feedback.diagnostics([{'command': 'PRIVATE-COMMAND', 'checks': groups}],
                                 candidate, model, [name], POLICY)
    assert items[0]['command'] == 'unavailable'
    assert any(item.get('attribution') == 'unattributed' for item in items)
    assert len(items) <= feedback.MAX_DIAGNOSTICS
    for groups in (None, [], {'group': 'SECRET'}, {'group': {'errors': 'SECRET'}}):
        items = feedback.diagnostics([{'command': 'check', 'checks': groups}],
                                     candidate, model, [name], POLICY)
        assert items == [feedback.unavailable('check', 'errors')]


def test_line_shifts_do_not_change_fingerprint_and_task_routing_is_exact(contexts):
    _, model, name = contexts
    first = diagnosed(contexts, {'file': name, 'line': 3, 'exception_type': 'AssertionError'})
    (model / name).write_text('\n' + SOURCE)
    shifted = diagnosed(contexts, {'file': name, 'line': 4, 'exception_type': 'AssertionError'})
    assert feedback.fingerprint(first) == feedback.fingerprint(shifted)
    tasks = [{'role': 'coordinator', 'files': [name]},
             {'role': 'coordinator', 'files': ['harness/other.py']},
             {'role': 'downloader', 'files': ['downloader/expensive.py']}]
    assert feedback.route(tasks, first) == {0: first}
    missing = feedback.unavailable('check', 'errors')
    assert set(feedback.route(tasks, first + [missing])) == {0, 1, 2}
    assert feedback.route(tasks, first + [missing])[1] == [missing]


def test_source_excerpt_is_bounded(contexts):
    _, model, name = contexts
    (model / name).write_text('\n'.join(['# ' + 'x' * 1000] * 20))
    item = diagnosed(contexts, {'file': name, 'line': 10})[0]
    assert len(item['excerpt']) == 7
    assert all(len(line) <= 245 for line in item['excerpt'])


@pytest.mark.parametrize('category', ['errors', 'skipped', 'failures'])
def test_status_and_exit_zero_cannot_override_required_failure_categories(category):
    assert not feedback.check_groups_passed({'fixture': {'status': 'passed', 'selected': 1,
                                                       'passed': 1, category: [{}]}})
