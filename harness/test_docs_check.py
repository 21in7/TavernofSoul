"""Actual-change policy and local Markdown validation, without HTTP or examples."""
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import quote

import pytest

from harness import docs_check as docs, failure_feedback, workspace


def change(name='docs/guide.md', status='M', old=None, new=None):
    return {'status': status, 'old_path': None if status == 'A' else old or name,
            'new_path': None if status == 'D' else new or name,
            'old_mode': None if status == 'A' else '100644',
            'new_mode': None if status == 'D' else '100644'}


def put(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


@pytest.mark.parametrize('name', ['README.md', 'docs/guide.md', 'docs/adr/0021-decision.md'])
def test_prose_changes_select_docs(name):
    assert docs.classify([change(name)])['mode'] == 'docs'


@pytest.mark.parametrize('name', ['AGENTS.md', 'docs/AGENTS.md', 'docs/workflow.md',
                                'docs/harness-design.md', 'Makefile', 'harness/a.py',
                                '.github/workflows/harness.yml', 'docs/a.yml',
                                'docs/../README.md', '/docs/a.md', 'docs//a.md', 'unknown.md'])
def test_policy_and_unknown_paths_fail_closed(name):
    assert docs.classify([change(name)])['mode'] == 'full'


@pytest.mark.parametrize('mode', ['100755', '120000', '160000', '100600', None])
def test_type_and_mode_changes_fail_closed(mode):
    row = change()
    row['new_mode'] = mode
    assert docs.classify([row])['mode'] == 'full'


def test_empty_mixed_duplicate_and_unknown_evidence_fail_closed():
    assert docs.classify([])['mode'] == 'full'
    assert docs.classify(None)['mode'] == 'full'
    assert docs.classify([change(), change('Makefile')])['mode'] == 'full'
    assert docs.classify([change(), change()])['mode'] == 'full'
    assert docs.classify([{}])['mode'] == 'full'
    assert docs.classify([dict(change(), status='C')])['mode'] == 'full'


def test_rename_checks_both_paths_and_current_references(tmp_path):
    put(tmp_path, 'docs/new.md', '# New\n')
    old = 'docs/old.md'
    renamed = change(status='R', old=old, new='docs/new.md')
    assert docs.classify([renamed])['mode'] == 'docs'
    put(tmp_path, 'README.md', '[old](docs/old.md)\n')
    assert docs.check(tmp_path, [renamed])['status'] == 'failed'
    put(tmp_path, 'README.md', '[new](docs/new.md#new)\n')
    assert docs.check(tmp_path, [renamed])['status'] == 'passed'
    renamed['old_path'] = 'script.py'
    assert docs.classify([renamed])['mode'] == 'full'


def test_deletion_without_references_has_real_selected_coverage(tmp_path):
    put(tmp_path, 'README.md', '# Still here\n')
    report = docs.check(tmp_path, [change(status='D')])
    assert report['status'] == 'passed'
    assert failure_feedback.check_groups_passed(report['checks'])
    put(tmp_path, 'README.md', '[missing](docs/guide.md)\n')
    assert docs.check(tmp_path, [change(status='D')])['status'] == 'failed'


def test_unicode_encoded_duplicate_inline_code_and_reference_links(tmp_path):
    put(tmp_path, 'docs/target.md', '# 한국어 `함수()`\n# 같은 제목\n# 같은 제목\nTitle\n-----\n')
    encoded = quote('한국어-함수')
    put(tmp_path, 'docs/guide.md', ('# Guide\n[a](target.md#' + encoded + ')\n'
        '[b][duplicate]\n[duplicate]: target.md#같은-제목-1 "title"\n'
        '![image](../image.png)\n[setext](target.md#title)\n'
        '`[ignored](missing.md)`\n```python\n[ignored](missing.md)\n```\n'))
    (tmp_path / 'image.png').write_bytes(b'not executed')
    report = docs.check(tmp_path, [change()])
    assert report['status'] == 'passed', report


@pytest.mark.parametrize('body', ['[bad](missing.md)', '[bad](target.md#absent)',
                                 '[bad][missing]', '\0', '<<<<<<< HEAD\n',
                                 '[bad](../../outside.md)', '[bad](/etc/passwd)',
                                 '[bad](%2e%2e/%2e%2e/outside.md)',
                                 '[bad](../.agent-keys.json)', '[bad](file:///etc/passwd)',
                                 '[bad](target.md', '<img src="missing.png">',
                                 '```python\nunclosed\n'])
def test_invalid_or_unsupported_docs_never_pass(tmp_path, body):
    put(tmp_path, 'docs/target.md', '# Existing\n')
    put(tmp_path, 'docs/guide.md', '# Guide\n' + body)
    assert docs.check(tmp_path, [change()])['status'] == 'failed'


def test_nested_image_label_validates_both_destinations(tmp_path):
    put(tmp_path, 'docs/target.md', '# Target\n')
    put(tmp_path, 'docs/guide.md', '[![image](image.png)](target.md#missing)\n')
    (tmp_path / 'docs/image.png').write_bytes(b'image')
    assert docs.check(tmp_path, [change()])['status'] == 'failed'
    put(tmp_path, 'docs/guide.md', '[![image](image.png)](target.md#target)\n')
    assert docs.check(tmp_path, [change()])['status'] == 'passed'


def test_anchor_change_checks_inbound_references_without_charging_old_unrelated_errors(tmp_path):
    put(tmp_path, 'docs/guide.md', '# New heading\n')
    put(tmp_path, 'docs/unrelated.md', '[old broken](missing.md)\n<img src="old-missing.png">\n')
    put(tmp_path, 'README.md', '[guide](docs/guide.md#old-heading)\n')
    assert docs.check(tmp_path, [change()])['status'] == 'failed'
    put(tmp_path, 'README.md', '[guide](docs/guide.md#new-heading)\n[old broken](missing.md)\n')
    assert docs.check(tmp_path, [change()])['status'] == 'passed'


@pytest.mark.parametrize('kind', ['file', 'directory', 'hardlink'])
def test_symlink_escape_and_hardlinks_fail_without_reading_target(tmp_path, kind):
    external = tmp_path / 'outside'
    external.mkdir()
    (external / 'secret.md').write_text('# Secret\n')
    root = tmp_path / 'repo'
    root.mkdir()
    put(root, 'docs/guide.md', '[target](target.md#secret)\n')
    if kind == 'file':
        (root / 'docs/target.md').symlink_to(external / 'secret.md')
    elif kind == 'directory':
        (root / 'docs/link').symlink_to(external, target_is_directory=True)
        put(root, 'docs/guide.md', '[target](link/secret.md#secret)\n')
    else:
        os.link(external / 'secret.md', root / 'docs/target.md')
    assert docs.check(root, [change()])['status'] == 'failed'


def test_utf8_and_nul_validation(tmp_path):
    path = put(tmp_path, 'docs/guide.md', '# Guide\n')
    path.write_bytes(b'\xff')
    assert docs.check(tmp_path, [change()])['status'] == 'failed'
    path.write_bytes(b'abc\0def')
    assert docs.check(tmp_path, [change()])['status'] == 'failed'


def test_network_and_examples_are_never_executed(tmp_path, monkeypatch):
    put(tmp_path, 'docs/guide.md', '[remote](https://invalid.example/no-request)\n```python\nraise Exception()\n```\n')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail('external process'))
    assert docs.check(tmp_path, [change()])['status'] == 'passed'


def test_actual_manifest_change_ignores_read_scope_and_binds_final_bytes():
    before = {'docs/guide.md': {'sha256': 'a', 'mode': 0o644},
              'harness/runner.py': {'sha256': 'unchanged', 'mode': 0o644}}
    after = {**before, 'docs/guide.md': {'sha256': 'b', 'mode': 0o644}}
    assert docs.classify(docs.manifest_changes(before, after))['mode'] == 'docs'
    identity = docs.change_digest(before, after)
    after['harness/runner.py'] = {'sha256': 'changed', 'mode': 0o644}
    assert docs.classify(docs.manifest_changes(before, after))['mode'] == 'full'
    assert docs.change_digest(before, after) != identity


@pytest.mark.parametrize('mode', [0o664, 0o640, 0o600, 0o644, 0o666, 0o444])
@pytest.mark.parametrize('status', ['A', 'M', 'D'])
def test_local_manifest_preserves_nonexecuting_permissions(mode, status):
    before = {} if status == 'A' else {'docs/guide.md': {'sha256': 'a', 'mode': mode}}
    after = {} if status == 'D' else {'docs/guide.md': {'sha256': 'b', 'mode': mode}}
    rows = docs.manifest_changes(before, after)
    assert rows == [dict(change(status=status),
                         old_mode=None if status == 'A' else mode,
                         new_mode=None if status == 'D' else mode)]
    assert docs.classify(rows)['mode'] == 'docs'


@pytest.mark.parametrize('old,new', [(0o600, 0o644), (0o664, 0o644), (0o640, 0o600),
                                    (0o644, 0o755), (0o755, 0o755), (0o4644, 0o4644),
                                    (0o10644, 0o10644), (0o100644, 0o100644),
                                    (-1, -1), (True, True), (436.0, 436.0),
                                    ('100644', '100644'), ('0664', '0664'), (None, None)])
def test_local_permission_changes_special_and_invalid_modes_remain_full(old, new):
    before = {'docs/guide.md': {'sha256': 'a', 'mode': old}}
    after = {'docs/guide.md': {'sha256': 'b', 'mode': new}}
    assert docs.classify(docs.manifest_changes(before, after))['mode'] == 'full'


@pytest.mark.parametrize('mode', [0o755, 0o2644, -1, None, False, '100644'])
@pytest.mark.parametrize('status', ['A', 'D'])
def test_new_and_deleted_invalid_local_modes_are_full(mode, status):
    present = {'docs/guide.md': {'sha256': 'a', 'mode': mode}}
    rows = docs.manifest_changes({} if status == 'A' else present,
                                present if status == 'A' else {})
    assert docs.classify(rows)['mode'] == 'full'


@pytest.mark.parametrize('entry', [None, {}, {'sha256': 'a'}, False])
@pytest.mark.parametrize('status', ['A', 'D'])
def test_malformed_manifest_entries_cannot_disappear_beside_valid_docs(entry, status):
    before = {'docs/guide.md': {'sha256': 'a', 'mode': 0o664}}
    after = {'docs/guide.md': {'sha256': 'b', 'mode': 0o664}}
    (after if status == 'A' else before)['docs/unknown.md'] = entry
    assert docs.classify(docs.manifest_changes(before, after))['mode'] == 'full'


@pytest.mark.parametrize('old,new', [(None, None), ('100644', '100644'),
                                    (0o100644, 0o100644), (0o664, 436.0), (False, 0)])
def test_equal_but_invalid_mode_evidence_cannot_hide_in_unchanged_entries(old, new):
    before = {'docs/guide.md': {'sha256': 'a', 'mode': 0o664},
              'docs/unknown.md': {'sha256': 'same', 'mode': old}}
    after = {'docs/guide.md': {'sha256': 'b', 'mode': 0o664},
             'docs/unknown.md': {'sha256': 'same', 'mode': new}}
    assert docs.classify(docs.manifest_changes(before, after))['mode'] == 'full'


@pytest.fixture(params=[0o002, 0o022, 0o077])
def creation_umask(request):
    previous = os.umask(request.param)
    try:
        yield request.param
    finally:
        os.umask(previous)


@pytest.mark.parametrize('status', ['A', 'M', 'D'])
@pytest.mark.parametrize('mixed', [False, True])
def test_actual_created_permissions_add_delete_and_mixed_scope(tmp_path, creation_umask, status, mixed):
    policy = {'max_file_bytes': docs.MAX_BYTES, 'max_snapshot_bytes': docs.MAX_BYTES * 2}
    name = 'docs/guide.md'
    code = put(tmp_path, 'harness/example.py', 'unchanged\n')
    if status != 'A':
        put(tmp_path, name, '# Before\n')
    before = workspace.manifest(tmp_path, policy)
    if status == 'D':
        (tmp_path / name).unlink()
    else:
        put(tmp_path, name, '# After\n')
    if mixed:
        code.write_text('changed\n')
    after = workspace.manifest(tmp_path, policy)
    expected = 0o666 & ~creation_umask
    for manifest in (before, after):
        if name in manifest:
            assert manifest[name]['mode'] == expected
    rows = docs.manifest_changes(before, after)
    assert docs.classify(rows)['mode'] == ('full' if mixed else 'docs')
    assert docs.change_digest(before, after) != docs.change_digest(before, before)
    if not mixed:
        assert docs.check(tmp_path, rows)['status'] == 'passed'


@pytest.mark.parametrize('old_umask,new_umask', [(0o077, 0o022), (0o002, 0o022), (0o022, 0o077)])
def test_actual_permission_only_changes_are_full_without_git_normalization(tmp_path, old_umask, new_umask):
    policy = {'max_file_bytes': docs.MAX_BYTES, 'max_snapshot_bytes': docs.MAX_BYTES}
    previous = os.umask(old_umask)
    try:
        path = put(tmp_path, 'docs/guide.md', '# Same bytes\n')
        before = workspace.manifest(tmp_path, policy)
        path.unlink()
        os.umask(new_umask)
        put(tmp_path, 'docs/guide.md', '# Same bytes\n')
        after = workspace.manifest(tmp_path, policy)
    finally:
        os.umask(previous)
    assert before['docs/guide.md']['sha256'] == after['docs/guide.md']['sha256']
    assert before['docs/guide.md']['mode'] == 0o666 & ~old_umask
    assert after['docs/guide.md']['mode'] == 0o666 & ~new_umask
    assert docs.classify(docs.manifest_changes(before, after))['mode'] == 'full'
    assert docs.change_digest(before, after) != docs.change_digest(before, before)


def test_local_modes_cannot_be_mixed_with_git_modes_or_hide_in_rename():
    row = dict(change(), old_mode=0o644)
    assert docs.classify([row])['mode'] == 'full'
    renamed = dict(change(status='R', old='docs/old.md', new='docs/new.md'),
                   old_mode=0o600, new_mode=0o600)
    assert docs.classify([renamed])['mode'] == 'docs'
    renamed['new_mode'] = 0o644
    assert docs.classify([renamed])['mode'] == 'full'


@pytest.mark.parametrize('body', [
    '`warnings=[{"fake":"[bad](missing.md)"},\n{"open":"["}]`',
    '``literal ` [bad](missing.md)\nmore ``` [ ``',
    '\\`literal [real](target.md) ` [bad](missing.md)\nend`',
    '\\\\`[bad](missing.md)\nend`',
    '`[bad](missing.md)\\`',
    '\\``[bad](missing.md)`',
    '- `list [bad](missing.md)\n  continued`',
    '> `quote [bad](missing.md)\n> continued`',
    '`warnings=["[bad](missing.md)",\n    "["]`',
])
def test_multiline_code_exact_runs_and_backslash_semantics(tmp_path, body):
    put(tmp_path, 'docs/target.md', '# Target\n')
    put(tmp_path, 'docs/guide.md', body + ' [real](target.md#target)\n')
    assert docs.check(tmp_path, [change()])['status'] == 'passed'
    put(tmp_path, 'docs/guide.md', body + ' [broken](target.md#absent)\n')
    report = docs.check(tmp_path, [change()])
    assert report['status'] == 'failed'
    assert report['checks']['docs']['failures'][0]['line'] == body.count('\n') + 1


@pytest.mark.parametrize('body', ['\\`[bad](missing.md)\\`',
                                 '``[bad](missing.md)`', '`[bad](missing.md)``'])
def test_escaped_or_unequal_delimiters_do_not_hide_real_links(tmp_path, body):
    put(tmp_path, 'docs/guide.md', body + '\n')
    assert docs.check(tmp_path, [change()])['status'] == 'failed'


def test_indented_blocks_and_paragraph_continuations_have_distinct_boundaries():
    text = ('    [code](ignored.md)\n\n# Heading\n    [code](ignored.md)\n\n'
            'Paragraph\n    [real](target.md)\n')
    assert list(docs.links(docs.visible_lines(text))) == [(7, 'target.md')]


@pytest.mark.parametrize('boundary', ['\n\n', '\n```text\n[fenced](ignored.md)\n```\n',
                                     '\n# Heading\n', '\n---\n', '\n***\n', '\n___\n',
                                     '\n- New item\n'])
def test_code_spans_cannot_cross_paragraph_heading_or_fence_boundaries(boundary):
    text = '`[first](first.md)' + boundary + '` [last](last.md)\n'
    references = list(docs.links(docs.visible_lines(text)))
    assert [target for _, target in references] == ['first.md', 'last.md']
    assert references[-1][0] == text.count('\n')


def test_code_heading_content_keeps_literal_markup_and_exact_delimiters():
    text = '# ``한국어 `함수()` [label](path) &amp;``\n# ``한국어 `함수()` [label](path) &amp;``\n'
    assert docs.anchors(docs.visible_lines(text)) == {
        '한국어-함수-labelpath-amp', '한국어-함수-labelpath-amp-1'}
    assert docs.inline_text('` a\nb `') == 'a b'
    assert docs.inline_text('[`text`](target.md)') == 'text'


def test_approved_workflow_warnings_multiline_code_reproduction():
    text = (Path(__file__).parents[1] / 'docs/workflow.md').read_text(encoding='utf-8')
    start = text.index('`warnings=[')
    end = text.index('`', start + 1) + 1
    snippet = text[start:end]
    assert '\n' in snippet
    assert list(docs.links(docs.visible_lines(snippet + '\n[real](guide.md)\n'))) == [(3, 'guide.md')]


def test_reverse_scan_ignores_valid_multiline_code_but_checks_following_link(tmp_path):
    put(tmp_path, 'docs/guide.md', '# New heading\n')
    code = '`warnings=["[fake](docs/guide.md#absent)",\n"["]`'
    put(tmp_path, 'docs/unrelated.md', code + '\n')
    put(tmp_path, 'README.md', code + ' [guide](docs/guide.md#new-heading)\n')
    assert docs.check(tmp_path, [change()])['status'] == 'passed'
    put(tmp_path, 'README.md', code + ' [guide](docs/guide.md#old-heading)\n')
    report = docs.check(tmp_path, [change()])
    assert report['status'] == 'failed'
    assert report['checks']['docs']['failures'][0]['line'] == 2


@pytest.mark.parametrize('tail', ['[bad\n](target.md)', '<img src="missing.png">',
                                 '[bad](target.md\n)'])
def test_valid_multiline_code_does_not_relax_unsupported_syntax(tmp_path, tail):
    put(tmp_path, 'docs/guide.md', '`[ignored\ncode]` ' + tail + '\n')
    assert docs.check(tmp_path, [change()])['status'] == 'failed'


def test_raw_git_diff_preserves_rename_deletion_and_modes():
    raw = (':100644 100644 ' + 'a' * 40 + ' ' + 'b' * 40 + ' R100\0docs/old.md\0docs/new.md\0' +
           ':100644 000000 ' + 'c' * 40 + ' ' + '0' * 40 + ' D\0docs/deleted.md\0').encode()
    records = docs.raw_changes(raw)
    assert records[0] == change(status='R', old='docs/old.md', new='docs/new.md')
    assert records[1] == change('docs/deleted.md', status='D')
    assert docs.classify(records)['mode'] == 'docs'
    with pytest.raises((ValueError, IndexError)):
        docs.raw_changes(raw[:-1])


@pytest.mark.parametrize('event_name', ['workflow_dispatch', 'unknown', '', None])
def test_unknown_ci_events_are_full(tmp_path, event_name):
    assert docs.ci_selection(tmp_path, event_name, {})['mode'] == 'full'


@pytest.mark.parametrize('event_name', ['push', 'pull_request'])
def test_ci_uses_exact_event_commit_range_and_complete_git_evidence(tmp_path, monkeypatch, event_name):
    calls = []
    base, head = 'a' * 40, 'b' * 40
    def fake_git(root, args):
        calls.append(args)
        if args == ['rev-parse', 'HEAD']:
            return head.encode()
        if args == ['rev-parse', '--is-shallow-repository']:
            return b'false\n'
        if args[:2] == ['rev-parse', '--verify']:
            return args[2][:40].encode()
        if args == ['diff', '--raw', '-z', '--no-abbrev', head, '--'] or args[0] == 'ls-files':
            return b''
        return (':100644 100644 ' + base + ' ' + head + ' M\0docs/guide.md\0').encode()
    monkeypatch.setattr(docs, 'git', fake_git)
    event = {'before': base, 'after': head, 'pull_request': {'base': {'sha': base}, 'head': {'sha': head}}}
    assert docs.ci_selection(tmp_path, event_name, event)['mode'] == 'docs'
    assert ['diff', '--raw', '-z', '--no-abbrev', '--find-renames', base, head, '--'] in calls
    event['before'] = '0' * 40
    event['pull_request']['base']['sha'] = '$(echo unsafe)'
    assert docs.ci_selection(tmp_path, event_name, event)['mode'] == 'full'


def test_ci_shallow_or_missing_objects_is_full(tmp_path, monkeypatch):
    head = 'b' * 40
    monkeypatch.setattr(docs, 'git', lambda root, args: head.encode() if args == ['rev-parse', 'HEAD'] else b'true')
    assert docs.ci_selection(tmp_path, 'push', {'before': 'a' * 40, 'after': head})['mode'] == 'full'


def test_ci_keeps_three_required_names_and_propagates_evidence_failure():
    # Source contract only; actual Actions validation belongs to the main run.
    text = (Path(__file__).parents[1] / '.github/workflows/harness.yml').read_text()
    for name in ('Offline harness (SQLite)', 'MySQL harness', 'Chromium browser harness'):
        assert '- name: ' + name in text
    assert 'needs: [selection, offline, mysql, browser]' in text
    assert "SELECTION_RESULT: ${{ needs.selection.result }}" in text
    assert 'EXECUTION_RESULTS:' in text
    assert '${{ needs.offline.result }}' in text
    assert '${{ needs.mysql.result }}' in text
    assert '${{ needs.browser.result }}' in text
    assert "LIVE_RESULT: ${{ needs.offline.result == 'skipped' && 'skipped' || needs.offline.outputs.live_result }}" in text
    helper = (Path(__file__).parents[1] / 'harness/check_selection.py').read_text()
    assert 'report.get(\'selection\') == selection' in helper
    assert 'uses: actions/checkout@v6' in text
    assert 'fetch-depth: 0' in text
    assert 'persist-credentials: false' in text
    assert 'contents: read' in text
    assert 'ref: ${{ github.event.pull_request.head.sha || github.sha }}' in text
    assert '--changes-file validation-selection.json --report docs-result.json' in text
    assert "if: always()\n    needs: [selection, offline, mysql, browser]" in text
    assert "if os.environ['SELECTION_RESULT'] != 'success':" in helper
    assert 'harness.check_selection --verify' in text
    assert '--plan-file evidence/execution-plan.json' in text
    assert "expected = 'success' if plan[name] else 'skipped'" in helper
    assert "if results[name] != expected:" in helper
    assert "g['selected'] > 0" in helper
    assert "g.get('skipped') == []" in helper


def test_public_ci_source_link_is_distinct_from_hidden_credentials(tmp_path):
    put(tmp_path, '.github/workflows/harness.yml', 'name: Development harness\n')
    put(tmp_path, 'docs/guide.md', '[CI](../.github/workflows/harness.yml)\n')
    assert docs.check(tmp_path, [change()])['status'] == 'passed'
    assert docs.classify([change('.github/workflows/harness.yml')])['mode'] == 'full'
    for private in ('.github/token.json', '.github/workflows/private.yml', '.git/config',
                    'logs/harness/storage-local.json'):
        put(tmp_path, private, 'private\n')
        put(tmp_path, 'docs/guide.md', '[private](../' + private + ')\n')
        assert docs.check(tmp_path, [change()])['status'] == 'failed'


def test_public_ci_link_still_rejects_a_symlink(tmp_path):
    target = put(tmp_path, 'public.yml', 'name: public\n')
    path = tmp_path / '.github/workflows/harness.yml'
    path.parent.mkdir(parents=True)
    path.symlink_to(target)
    put(tmp_path, 'docs/guide.md', '[CI](../.github/workflows/harness.yml)\n')
    assert docs.check(tmp_path, [change()])['status'] == 'failed'


@pytest.mark.parametrize('link', ['[old](docs/guide\\.md)', '[old](docs/%67uide.md)',
                                 '[old\n](docs/guide.md)',
                                 '<a href = "docs/guide.md">old</a>'])
def test_affected_reverse_references_cannot_disappear_in_unsupported_or_escaped_syntax(tmp_path, link):
    put(tmp_path, 'README.md', link + '\n')
    assert docs.check(tmp_path, [change(status='D')])['status'] == 'failed'


def test_new_branch_push_without_metadata_requires_full_without_diff_execution(tmp_path, monkeypatch):
    head = 'b' * 40
    calls = []
    def current_head(root, args):
        calls.append(args)
        assert args == ['rev-parse', 'HEAD']
        return head.encode()
    monkeypatch.setattr(docs, 'git', current_head)
    assert docs.ci_selection(tmp_path, 'push', {'before': '0' * 40, 'after': head})['mode'] == 'full'
    assert calls == [['rev-parse', 'HEAD']]


class BranchRepository:
    """Small local Git history; no remote, network or third-party Git library."""

    def __init__(self, root, default='main'):
        self.root, self.default = root, default
        root.mkdir()
        self.run('init', '-q')
        self.run('symbolic-ref', 'HEAD', 'refs/heads/' + default)
        put(root, 'README.md', '# Repository\n')
        put(root, 'docs/guide.md', '# Guide\n')
        put(root, 'docs/old.md', '# Old\n')
        put(root, 'docs/deleted.md', '# Deleted\n')
        put(root, 'source.py', 'value = 1\n')
        self.base = self.commit('base')
        self.remote = 'refs/remotes/origin/' + default
        self.run('update-ref', self.remote, self.base)
        self.run('checkout', '-qb', 'docs/new')

    def run(self, *args, **kwargs):
        env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
                   GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid',
                   GIT_TERMINAL_PROMPT='0')
        return subprocess.run(
            ['git', '-c', 'core.hooksPath=' + os.devnull, '-c', 'commit.gpgSign=false',
             '-c', 'core.autocrlf=false', '-c', 'core.filemode=true', *args],
            cwd=str(self.root), env=env, check=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, **kwargs).stdout.decode().strip()

    def commit(self, message):
        self.run('add', '-A')
        self.run('commit', '--allow-empty', '-qm', message)
        return self.run('rev-parse', 'HEAD')

    def event(self):
        return {'before': '0' * 40, 'after': self.run('rev-parse', 'HEAD'),
                'created': True, 'deleted': False, 'forced': False,
                'ref': 'refs/heads/docs/new', 'repository': {'default_branch': self.default}}


@pytest.fixture
def branch_repo(tmp_path):
    repo = BranchRepository(tmp_path / 'repo')
    put(repo.root, 'docs/guide.md', '# Updated guide\n')
    repo.commit('docs')
    return repo


@pytest.mark.parametrize('commits,default,advance', [
    (1, 'main', False), (3, 'main', False), (2, 'release/stable', True)])
def test_new_branch_complete_docs_range_and_report_survives_default_advance(
        tmp_path, monkeypatch, capsys, commits, default, advance):
    repo = BranchRepository(tmp_path / 'repo', default)
    for index in range(commits):
        put(repo.root, 'docs/part-{}.md'.format(index), '# Part {}\n'.format(index))
        repo.commit('docs {}'.format(index))
    event = repo.event()
    if advance:
        repo.run('checkout', '-q', default)
        put(repo.root, 'source.py', 'value = 2\n')
        tip = repo.commit('default code after divergence')
        repo.run('update-ref', repo.remote, tip)
        repo.run('checkout', '-q', 'docs/new')
    selection = docs.ci_selection(repo.root, 'push', event)
    assert selection == docs.classify(docs.git_changes(repo.root, repo.base, event['after']))
    assert selection['mode'] == 'docs'
    assert len(selection['changes']) == commits
    # Persist the established complete range, then move the default again. The
    # validation consumer must use the selection rows, never resolve it anew.
    selection_file, report_file = tmp_path / 'selection.json', tmp_path / 'report.json'
    selection_file.write_text(json.dumps(selection), encoding='utf-8')
    repo.run('update-ref', repo.remote, event['after'])
    monkeypatch.setattr(docs, '__file__', str(repo.root / 'harness/docs_check.py'))
    assert docs.main(['--changes-file', str(selection_file), '--report', str(report_file)]) == 0
    report = json.loads(report_file.read_text(encoding='utf-8'))
    assert report['selection'] == selection
    assert failure_feedback.check_groups_passed(report['checks'])
    capsys.readouterr()


def test_new_branch_includes_earlier_code_even_when_latest_commit_is_docs(branch_repo):
    repo = branch_repo
    put(repo.root, 'source.py', 'value = 2\n')
    repo.commit('feature code')
    put(repo.root, 'docs/guide.md', '# Latest docs\n')
    repo.commit('latest docs')
    selection = docs.ci_selection(repo.root, 'push', repo.event())
    assert selection['mode'] == 'full'
    assert 'source.py' in {row['new_path'] for row in selection['changes']}


def test_new_branch_pins_exact_default_sha_before_resolving_ancestry(branch_repo, monkeypatch):
    repo = branch_repo
    event, calls = repo.event(), []
    real_git = docs.git
    def advance_after_read(root, args):
        calls.append(args)
        result = real_git(root, args)
        if args == ['show-ref', '--verify', '--hash', repo.remote]:
            repo.run('update-ref', repo.remote, event['after'])
        return result
    monkeypatch.setattr(docs, 'git', advance_after_read)
    selection = docs.ci_selection(repo.root, 'push', event)
    assert selection['mode'] == 'docs'
    assert calls.count(['show-ref', '--verify', '--hash', repo.remote]) == 1
    assert ['merge-base', '--all', repo.base, event['after']] in calls
    assert ['diff', '--raw', '-z', '--no-abbrev', '--find-renames', repo.base, event['after'], '--'] in calls


@pytest.mark.parametrize('kind', ['policy', 'ci', 'permission', 'type', 'non_doc_rename'])
def test_new_branch_uses_existing_conservative_classifier(branch_repo, kind):
    repo = branch_repo
    if kind == 'policy':
        put(repo.root, 'docs/workflow.md', '# Policy\n')
    elif kind == 'ci':
        put(repo.root, '.github/workflows/harness.yml', 'name: CI\n')
    elif kind == 'permission':
        (repo.root / 'docs/guide.md').chmod(0o755)
    elif kind == 'type':
        (repo.root / 'docs/guide.md').unlink()
        (repo.root / 'docs/guide.md').symlink_to('old.md')
    else:
        repo.run('mv', 'source.py', 'docs/source.md')
    repo.commit(kind)
    selection = docs.ci_selection(repo.root, 'push', repo.event())
    assert selection['mode'] == 'full'
    assert selection['changes']  # complete evidence reached the classifier
    if kind == 'non_doc_rename':
        assert change(status='R', old='source.py', new='docs/source.md') in selection['changes']


def test_new_branch_raw_rename_deletion_and_surviving_reverse_references(branch_repo):
    repo = branch_repo
    repo.run('mv', 'docs/old.md', 'docs/new.md')
    (repo.root / 'docs/deleted.md').unlink()
    repo.commit('rename and delete')
    selection = docs.ci_selection(repo.root, 'push', repo.event())
    assert selection['mode'] == 'docs'
    assert change(status='R', old='docs/old.md', new='docs/new.md') in selection['changes']
    assert change('docs/deleted.md', status='D') in selection['changes']
    report = docs.check(repo.root, selection['changes'])
    assert report['selection'] == selection
    assert failure_feedback.check_groups_passed(report['checks'])
    # A surviving reference predates the branch, so it is not itself a changed
    # document in the complete raw diff. It must still fail validation.
    repo.run('checkout', '-q', repo.default)
    put(repo.root, 'README.md', '[old](docs/old.md) [deleted](docs/deleted.md)\n')
    repo.base = repo.commit('existing references')
    repo.run('update-ref', repo.remote, repo.base)
    repo.run('checkout', '-q', 'docs/new')
    repo.run('merge', '--no-edit', repo.default)
    selection = docs.ci_selection(repo.root, 'push', repo.event())
    assert selection['mode'] == 'docs'
    assert all(row['new_path'] != 'README.md' for row in selection['changes'])
    report = docs.check(repo.root, selection['changes'])
    assert report['selection'] == selection
    assert report['status'] == 'failed'
    assert len(report['checks']['docs']['failures']) == 2


@pytest.mark.parametrize('field,value', [
    ('created', None), ('created', 1), ('created', False),
    ('deleted', None), ('deleted', 0), ('deleted', True),
    ('forced', 'false'), ('forced', 0), ('forced', None),
    ('ref', None), ('ref', 1), ('ref', 'refs/tags/v1'), ('ref', 'refs/heads/main'),
    ('ref', 'refs/heads/'), ('ref', 'refs/heads/a..b'), ('ref', 'refs/heads/a\nname'),
    ('ref', '--help'), ('ref', 'refs/heads/$(touch injected)'),
    ('after', '0' * 40), ('after', 'a' * 39), ('after', None), ('after', 1),
    ('before', '0' * 39), ('before', None), ('before', 0),
    ('repository', None), ('repository', {}), ('repository', {'default_branch': 1}),
    ('repository', {'default_branch': ''}), ('repository', {'default_branch': '../main'}),
    ('repository', {'default_branch': 'main^{commit}'}),
])
def test_new_branch_rejects_untrustworthy_event_metadata(branch_repo, field, value):
    event = branch_repo.event()
    event[field] = value
    assert docs.ci_selection(branch_repo.root, 'push', event)['mode'] == 'full'
    assert not (branch_repo.root / 'injected').exists()


@pytest.mark.parametrize('field', ['created', 'deleted', 'ref', 'repository', 'after', 'before'])
def test_new_branch_missing_required_metadata_is_full(branch_repo, field):
    event = branch_repo.event()
    del event[field]
    assert docs.ci_selection(branch_repo.root, 'push', event)['mode'] == 'full'


@pytest.mark.parametrize('forced', [None, False, True])
def test_new_branch_optional_boolean_forced_is_not_a_previous_tip(branch_repo, forced):
    event = branch_repo.event()
    if forced is None:
        del event['forced']
    else:
        event['forced'] = forced
    assert docs.ci_selection(branch_repo.root, 'push', event)['mode'] == 'docs'


def test_new_branch_valid_shell_metacharacters_remain_literal_git_refs(tmp_path):
    # These are legal ref characters, so rejection alone is not the boundary.
    # Any shell interpolation would attempt to create the marker file.
    repo = BranchRepository(tmp_path / 'repo', 'release/$(touch${IFS}injected)')
    put(repo.root, 'docs/guide.md', '# Literal refs\n')
    repo.commit('docs')
    event = repo.event()
    event['ref'] = 'refs/heads/$(touch${IFS}injected)'
    assert docs.ci_selection(repo.root, 'push', event)['mode'] == 'docs'
    assert not (repo.root / 'injected').exists()


@pytest.mark.parametrize('problem', ['missing_default', 'noncommit_default', 'unrelated',
                                    'shallow', 'dirty', 'staged', 'untracked',
                                    'head_mismatch', 'empty', 'missing_tree'])
def test_new_branch_incomplete_repository_evidence_is_full(branch_repo, problem):
    repo = branch_repo
    event = repo.event()
    if problem == 'missing_default':
        repo.run('update-ref', '-d', repo.remote)
    elif problem == 'noncommit_default':
        blob = repo.run('hash-object', '-w', '--stdin', input=b'not a commit\n')
        repo.run('update-ref', repo.remote, blob)
    elif problem == 'unrelated':
        tree = repo.run('rev-parse', repo.base + '^{tree}')
        unrelated = repo.run('commit-tree', tree, '-m', 'unrelated root')
        repo.run('update-ref', repo.remote, unrelated)
    elif problem == 'shallow':
        (repo.root / '.git/shallow').write_text(repo.base + '\n', encoding='ascii')
    elif problem in ('dirty', 'staged'):
        put(repo.root, 'docs/guide.md', '# Uncommitted\n')
        if problem == 'staged':
            repo.run('add', 'docs/guide.md')
    elif problem == 'untracked':
        put(repo.root, 'docs/untracked.md', '# Untracked\n')
    elif problem == 'head_mismatch':
        event['after'] = repo.base
    elif problem == 'empty':
        repo.run('checkout', '-q', repo.base)
        repo.commit('empty branch commit')
        event = repo.event()
    else:
        tree = repo.run('rev-parse', 'HEAD^{tree}')
        (repo.root / '.git/objects' / tree[:2] / tree[2:]).unlink()
    assert docs.ci_selection(repo.root, 'push', event)['mode'] == 'full'


def test_new_branch_rejects_multiple_real_best_common_ancestors(branch_repo):
    repo = branch_repo
    tree = repo.run('rev-parse', repo.base + '^{tree}')
    left = repo.run('commit-tree', tree, '-p', repo.base, '-m', 'left')
    right = repo.run('commit-tree', tree, '-p', repo.base, '-m', 'right')
    default_tip = repo.run('commit-tree', tree, '-p', left, '-p', right, '-m', 'merge one')
    head_tree = repo.run('rev-parse', 'HEAD^{tree}')
    head = repo.run('commit-tree', head_tree, '-p', right, '-p', left, '-m', 'merge two')
    repo.run('update-ref', repo.remote, default_tip)
    repo.run('reset', '--hard', head)
    assert set(repo.run('merge-base', '--all', default_tip, head).splitlines()) == {left, right}
    assert docs.ci_selection(repo.root, 'push', repo.event())['mode'] == 'full'


@pytest.mark.parametrize('bad_output', [b'', b'not-a-sha\n', b'0' * 40 + b'\n',
                                        b'a' * 40 + b'\n' + b'b' * 40 + b'\n'])
@pytest.mark.parametrize('command', ['show-ref', 'merge-base'])
def test_new_branch_rejects_invalid_or_ambiguous_resolution(branch_repo, monkeypatch, command, bad_output):
    real_git = docs.git
    def damaged_evidence(root, args):
        return bad_output if args[0] == command else real_git(root, args)
    monkeypatch.setattr(docs, 'git', damaged_evidence)
    assert docs.ci_selection(branch_repo.root, 'push', branch_repo.event())['mode'] == 'full'


@pytest.mark.parametrize('event_name', ['push', 'pull_request'])
def test_existing_event_ranges_remain_exact_with_real_history(branch_repo, event_name):
    repo = branch_repo
    put(repo.root, 'source.py', 'value = 2\n')
    previous = repo.commit('earlier code')
    put(repo.root, 'docs/guide.md', '# Last commit docs\n')
    head = repo.commit('docs only at tip')
    event = {'before': previous, 'after': head,
             'pull_request': {'base': {'sha': previous}, 'head': {'sha': head}}}
    selection = docs.ci_selection(repo.root, event_name, event)
    assert selection == docs.classify(docs.git_changes(repo.root, previous, head))
    assert selection['mode'] == 'docs'


def test_deleted_document_cannot_leave_a_broken_policy_reference(tmp_path):
    put(tmp_path, 'AGENTS.md', '[Required design](docs/guide.md)\n')
    assert docs.check(tmp_path, [change(status='D')])['status'] == 'failed'
    assert docs.classify([change('AGENTS.md')])['mode'] == 'full'
