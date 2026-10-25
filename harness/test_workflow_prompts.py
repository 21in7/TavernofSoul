"""Lossless prompt composition and bounded review history, without model calls."""
import copy
import json

import pytest

from harness import workflow_prompts as prompts


@pytest.mark.parametrize('assigned', ['한국어 원요청\n끝', '한국어 원요청\n끝 ', '서로 다른 배정\n전체 보존'])
def test_request_dedup_is_exact_and_preserves_feedback_scope_and_documentation(assigned):
    request = '한국어 원요청\n끝'
    paths = ['문서/나.md', 'harness/space name.py']
    feedback = 'Required correction;\n한글 진단\n전체 feedback'
    task = {'task': assigned, 'files': paths}
    text = prompts.implement(request, task, False, feedback) + prompts.readable_scope(paths, paths)
    assert 'Original request:\n' + request + '\n' in text
    if request == assigned:
        assert 'Assigned task:\n' not in text and text.count(request) == 1
    else:
        assert 'Assigned task:\n' + assigned + '\n' in text
    assert feedback in text and prompts.DOCUMENTATION_GUIDANCE in text
    assert json.loads(text.split('Allowed edit files (exact paths): ')[1].splitlines()[0]) == paths
    assert text.count(prompts.compact(paths)) == 1
    assert 'Implement the assigned change only in the allowed files.' in text
    assert 'Do not run checks' in text
    assert '\\u' not in text


def test_distinct_read_and_edit_scopes_and_path_order_are_preserved():
    readable = ['문서/나.md', 'harness/space name.py', '참고.md']
    edits = readable[:1]
    text = prompts.implement('요청', {'task': '다른 지시', 'files': edits}, True, '')
    text += prompts.readable_scope(readable, edits)
    assert 'Do not edit any files; this is analysis only.' in text
    assert 'Allowed edit files (exact paths): ' + prompts.compact(edits) in text
    assert 'Approved readable files (exact paths): ' + prompts.compact(readable) in text
    assert prompts.compact(readable) == '["문서/나.md","harness/space name.py","참고.md"]'
    assert 'Owners: {"문서/나.md":"coordinator","parser_tidy/a.py":"parser"}' in prompts.plan(
        '요청', {'문서/나.md': 'coordinator', 'parser_tidy/a.py': 'parser'})


def test_latest_each_task_preserves_all_legacy_unknown_and_original_audit_records():
    def result(response, **extra):
        return {'phase': 'implement', 'response': response, **extra}
    agents = [result('old-zero', task_id=0), result('legacy-a'),
              result('one-final', task_id=1), result('legacy-b'),
              result('unknown-a', task_id=None), result('unknown-b', task_id=None),
              result('bool-a', task_id=True), result('bool-b', task_id=True),
              result('foreign-a', task_id=999), result('foreign-b', task_id=999),
              result('string-a', task_id='0'), result('string-b', task_id='0'),
              {'phase': 'review', 'response': 'old-review'}, result('zero-final', task_id=0)]
    original = copy.deepcopy(agents)
    selected = prompts.latest_implementations(agents, [0, 1])
    assert [item['response'] for item in selected] == [
        'legacy-a', 'one-final', 'legacy-b', 'unknown-a', 'unknown-b',
        'bool-a', 'bool-b', 'foreign-a', 'foreign-b', 'string-a', 'string-b', 'zero-final']
    assert agents == original
    assert [item['task_id'] for item in selected if item['response'] in ('one-final', 'zero-final')] == [1, 0]
    assert selected[0] == {'response': 'legacy-a'}


def test_review_and_git_keep_full_current_diff_request_and_contract():
    request = '전체 한국어 원요청'
    diff = '--- 문서/나.md\n+++ 문서/나.md\n' + '-이전\n+현재\n' * 2000 + '+끝\n'
    results = [{'task_id': 0, 'response': '첫 구현'}, {'task_id': 1, 'response': '둘째 구현'}]
    files = ['문서/나.md', 'harness/space name.py']
    text = prompts.review(request, False, results, diff, files) + prompts.readable_scope(files)
    assert diff in text and text.count(diff) == 1 and request in text
    assert 'Implementation results: ' + prompts.compact(results) in text
    assert 'documentation has exactly status, files, reason.' in text
    assert 'Independently judge the final full diff, code and documentation afresh' in text
    assert prompts.DOCUMENTATION_GUIDANCE in text
    assert text.count('Approved readable files (exact paths): ') == 1 and '\nScope: ' not in text
    review = {'documentation': {'status': 'updated', 'files': files[:1], 'reason': '계약 변경'}}
    git = prompts.github(request, files, review, [{'command': 'check', 'status': 'passed'}], diff)
    assert diff in git and request in git and prompts.compact(review) in git
    assert '[{"command":"check","status":"passed"}]' in git


def test_repair_builders_keep_complete_original_request_scope_and_feedback_payload():
    original = prompts.plan('한국어 원요청', {'문서/가.md': 'coordinator'})
    diagnostic = {'category': 'json_syntax', 'line': 2, 'column': 3, 'position': 4}
    repair = prompts.repair_plan(original, diagnostic)
    assert repair.startswith(original + '\nTrusted plan diagnostic: ' + prompts.compact(diagnostic))
    assert 'fresh short complete valid JSON object' in repair
    payload = {'task_id': 0, 'files': ['문서/가.md'], 'diagnostics': [{'message': '누락 없이 보존'}]}
    feedback = prompts.correction(payload, True, False)
    assert prompts.compact(payload) in feedback and 'Required correction;' in feedback
    assert 'The same failure recurred.' in feedback
    assert 'The preceding implementation attempt made no assigned source change.' in feedback
