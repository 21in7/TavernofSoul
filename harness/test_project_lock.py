"""Offline concurrency specifications; collected by runner's existing test_*.py glob.

Workers do not execute these. All subprocesses below use disposable files and
synthetic data. No models, scheduler, remote Git or operator configuration.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import fcntl
import http.client
import json
import multiprocessing
import os
import socket
import subprocess
import sys
from threading import Event

import pytest

from harness import agent_models, improvement_loop as loop, improvements as imp
from harness import improvement_report as contract, local_model, project_lock, storage, triage, workflow, workspace
from harness.test_improvement_loop import lab, FILES, encode, SECRET, FixtureFS, forbidden
from harness.test_workflow import runner_for, successful_check


@pytest.fixture(autouse=True)
def isolated_controllers(monkeypatch):
    # Importing Lab does not import its module's autouse fixture. These tests
    # need real workflow/flock/subprocess paths, so retain those synthetic seams
    # while isolating parent authority, storage selection, models and network.
    for key in ('TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
                'TAVERN_IMPROVEMENT_UNATTENDED', local_model.CONFIG_ENV,
                storage.CONFIG_ENV, storage.REPORT_ENV,
                'ANTHROPIC_API_KEY', 'ZAI_API_KEY', 'OPENAI_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    for obj, name in ((agent_models, 'run'), (agent_models, 'load_keys'),
                      (storage, 'resolve_storage'), (workflow, 'run_check'),
                      (workflow.git_publish, 'prepare'),
                      (http.client, 'HTTPConnection'), (http.client, 'HTTPSConnection'),
                      (socket, 'socket'), (socket, 'create_connection'),
                      (socket, 'getaddrinfo'), (local_model, 'http_transport')):
        monkeypatch.setattr(obj, name, forbidden)


@contextmanager
def legacy_holder(path):
    """Independent interpreter/handle; no PID-file guess or inherited flock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    child = subprocess.Popen([sys.executable, '-c',
        'import fcntl,sys; h=open(sys.argv[1], "a"); '
        'fcntl.flock(h, fcntl.LOCK_EX); print("held", flush=True); sys.stdin.read(1)', str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline() == 'held\n'
        yield
    finally:
        child.communicate('x', timeout=5)
        assert child.returncode == 0


def test_independent_process_and_handles_keep_legacy_inode_across_policy_changes(tmp_path):
    root = tmp_path / 'sources'
    root.mkdir()
    first = storage.Storage(root=root, env={})
    second = storage.Storage(root=root, env={})
    path = first.project_lock_path
    with legacy_holder(path):
        inode = path.stat().st_ino
        for selected in (first, second):
            with pytest.raises(BlockingIOError):
                with project_lock.hold(selected, reentrant=False):
                    pytest.fail('Legacy source owner was bypassed')
        assert path.stat().st_ino == inode
    with project_lock.hold(second, reentrant=False):
        with path.open('a') as independent:
            with pytest.raises(BlockingIOError):
                fcntl.flock(independent, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with project_lock.hold(second):
            assert path.stat().st_ino == inode
        with pytest.raises(BlockingIOError):
            with project_lock.hold(first, reentrant=False):
                pytest.fail('Independent controller borrowed another controller lock')
    assert path.stat().st_ino == inode


def prepare_workflow(lab, monkeypatch):
    monkeypatch.setattr(workflow, 'ROOT', lab.root)
    monkeypatch.setattr(workflow, 'REPORTS', lab.root / 'logs/harness/workflows')
    monkeypatch.setattr(workflow, 'storage_policy', lambda: lab.selected)
    monkeypatch.setattr(storage, 'resolve_storage', lambda *a, **kw: lab.selected)
    monkeypatch.setattr(workflow.git_publish, 'load_config', lambda: {'enabled': False})
    monkeypatch.setattr(agent_models, 'connection_status', lambda *a: {'status': 'ready'})
    monkeypatch.setattr(triage, 'observe', lambda *a, **kw: {
        'status': 'passed', 'source': 'fixture',
        'recommendation': {'role': 'parser', 'required_checks': ['check-parser']}})
    # Exact fixture membership; real capture, model projection, manifest and
    # full baseline comparison still execute. Never enumerate the real repo.
    names = list(FILES) + ['harness/improvement-scope.txt',
        'harness/improvement-config.json', 'harness/improvement-loop-config.json']
    monkeypatch.setattr(workspace, 'source_names', lambda root: names)
    for name in ('TAVERN_WORKFLOW_CHILD', 'TAVERN_IMPROVEMENT_DISCOVERY',
                 'TAVERN_IMPROVEMENT_UNATTENDED'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)


def transport_publisher(lab, monkeypatch):
    calls, payloads = [], []
    monkeypatch.setattr(imp, '_inbox_config', lambda path: ('https://synthetic.invalid', SECRET))
    def http(method, origin, path, headers, body, timeout, max_bytes):
        calls.append(method)
        if method == 'POST':
            payloads.append(contract.validate_web_report(json.loads(body)))
            return 200, b'{}'
        return 200, encode(payloads[-1])
    def publish(date, *, selected):
        return imp.deliver_report(date, selected=selected, transport=http)
    return publish, calls, payloads


@pytest.mark.parametrize('read_only', [False, True])
@pytest.mark.parametrize('blocked_at', ['model', 'checker'])
def test_real_workflow_long_phase_allows_tick_freeze_and_same_digest_http_readback(
        lab, monkeypatch, read_only, blocked_at):
    lab.hours()
    prepare_workflow(lab, monkeypatch)
    entered, release = Event(), Event()
    model = runner_for([])
    def runner(*args, **kwargs):
        if blocked_at == 'model' and not entered.is_set():
            entered.set()
            assert release.wait(10)
        return model(*args, **kwargs)
    def checker(*args):
        if blocked_at == 'checker' and not entered.is_set():
            entered.set()
            assert release.wait(10)
        return successful_check(*args)
    sender, calls, payloads = transport_publisher(lab, monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(workflow.execute, 'Explicit synthetic request.',
            ['parser_tidy/example.py'], read_only=read_only, rules_only=True,
            keys={}, runner=runner, checker=checker, no_git=True)
        try:
            assert entered.wait(10)
            with project_lock.hold(lab.selected, reentrant=False):
                pass  # Models/checks own only their isolated source copies.
            with pytest.raises(ValueError, match='Another workflow'):
                workflow.execute('Duplicate.', ['parser_tidy/example.py'],
                    keys={}, runner=runner, checker=checker, no_git=True)
            result = lab.tick(9, publisher=sender)
            assert result['publication']['status'] == 'delivered'
            assert calls == ['POST', 'GET']
            assert not future.done()
            frozen = lab.store.path('web/2026-10-15.json').read_bytes()
            assert contract.verify_web_digest(payloads[0], '2026-10-15')
            lab.tick(10, publisher=sender)
            assert calls == ['POST', 'GET']
            assert lab.store.path('web/2026-10-15.json').read_bytes() == frozen
        finally:
            release.set()
        report = future.result(timeout=10)
    assert report['status'] == 'passed', report.get('error')
    assert report['applied'] == ([] if read_only else ['parser_tidy/example.py'])
    assert 'diagnostic' not in json.dumps(payloads)


def test_apply_mid_replacement_refuses_live_snapshot_and_freezes_truthful_failure(lab, monkeypatch):
    prepare_workflow(lab, monkeypatch)
    entered, release = Event(), Event()
    replace = workspace.replace_file
    def pause_after_replace(source, target, mode):
        replace(source, target, mode)
        if target == lab.root / 'parser_tidy/example.py':
            entered.set()
            assert release.wait(10)
    monkeypatch.setattr(workspace, 'replace_file', pause_after_replace)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(workflow.execute, 'Synthetic apply.', ['parser_tidy/example.py'],
            rules_only=True, keys={}, runner=runner_for([]), checker=successful_check, no_git=True)
        try:
            assert entered.wait(10)
            result = lab.tick(9)
            assert result['reason'] == 'project_lock_busy'
            assert result['diagnostic']['holder_pid'] is None
            assert lab.events == [] and lab.ledger()['calls'] == 0
            report = lab.store.read('days/2026-10-15.json')
            assert report['review_complete'] is False and report['status'] == 'failed'
            assert report['readiness_reason'] == 'project_lock_busy'
            assert report['proposals'] == []
            with pytest.raises(BlockingIOError):
                imp.snapshot_sources(FILES, selected=lab.selected)
        finally:
            release.set()
        assert future.result(timeout=10)['status'] == 'passed'
    assert lab.tick(9)['reason'] == 'slot_already_claimed'


@pytest.mark.parametrize('edit', ['bytes', 'mode', 'delete', 'add'])
def test_user_edit_during_unlocked_check_is_preserved_by_entire_baseline_gate(lab, monkeypatch, edit):
    prepare_workflow(lab, monkeypatch)
    dependency = lab.root / 'downloader/example.py'
    addition = lab.root / 'harness/new-dependency.py'
    names = workspace.source_names(lab.root)
    monkeypatch.setattr(workspace, 'source_names', lambda root:
                        names + (['harness/new-dependency.py'] if addition.exists() else []))
    changed = False
    def checker(*args):
        nonlocal changed
        if not changed:
            # Unscoped source dependency: apply must compare the entire baseline.
            if edit == 'bytes':
                dependency.write_text('external user edit\n')
            elif edit == 'mode':
                dependency.chmod(0o600)
            elif edit == 'delete':
                dependency.unlink()
            else:
                addition.write_text('external new dependency\n')
            changed = True
        return successful_check(*args)
    original = (lab.root / 'parser_tidy/example.py').read_bytes()
    report = workflow.execute('Synthetic conflict.', ['parser_tidy/example.py'],
        rules_only=True, keys={}, runner=runner_for([]), checker=checker, no_git=True)
    assert report['status'] == 'failed' and report['applied'] == []
    if edit == 'bytes':
        assert dependency.read_text() == 'external user edit\n'
    elif edit == 'mode':
        assert dependency.stat().st_mode & 0o777 == 0o600
    elif edit == 'delete':
        assert not dependency.exists()
    else:
        assert addition.read_text() == 'external new dependency\n'
    assert (lab.root / 'parser_tidy/example.py').read_bytes() == original


def test_review_diff_uses_captured_input_when_live_source_changes_during_model(lab, monkeypatch):
    prepare_workflow(lab, monkeypatch)
    name = 'parser_tidy/example.py'
    captured = (lab.root / name).read_text()
    reviewed = []
    external = 'external edit while the implementation model was running\n'
    def mutate(_):
        (lab.root / name).write_text(external)
    model = runner_for([], mutate=mutate)
    def runner(role, prompt, *args, **kwargs):
        if role == 'reviewer':
            reviewed.append(prompt.split('\nDiff:\n', 1)[1])
        return model(role, prompt, *args, **kwargs)
    report = workflow.execute('Synthetic immutable review diff.', [name], rules_only=True,
        keys={}, runner=runner, checker=successful_check, no_git=True)
    assert len(reviewed) == 1
    assert all('-' + line in reviewed[0] for line in captured.splitlines())
    assert '+validated edit' in reviewed[0] and external.strip() not in reviewed[0]
    assert report['status'] == 'failed' and report['applied'] == []
    assert (lab.root / name).read_text() == external


def test_duplicate_tick_in_another_process_cannot_reserve_or_call_twice(lab):
    actual = lab.local
    context = multiprocessing.get_context('fork')
    queue = context.Queue()
    def duplicate():
        # fork happens inside a modeled discovery call; represent a separate
        # scheduler parent, not a model child with orchestration authority.
        os.environ.pop('TAVERN_IMPROVEMENT_DISCOVERY', None)
        queue.put(lab.tick())
    def local(*args, **kwargs):
        child = context.Process(target=duplicate)
        child.start()
        try:
            other = queue.get(timeout=5)
            assert other['reason'] == 'discovery_lock_busy'
        finally:
            child.join(timeout=5)
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
        assert child.exitcode == 0
        return actual(*args, **kwargs)
    try:
        first = lab.tick(0, local_runner=local)
    finally:
        queue.close()
    assert first['calls_today'] == 1 and len(lab.events) == 1
    assert lab.tick(0)['reason'] == 'slot_already_claimed'


def test_frozen_publication_and_settlement_do_not_acquire_source_lock(lab, monkeypatch):
    lab.tick(9)
    sender, calls, payloads = transport_publisher(lab, monkeypatch)
    with legacy_holder(lab.selected.project_lock_path):
        result = loop.publish(now=lab.clock(), selected=lab.selected, publisher=sender)
    assert result['status'] == 'delivered' and calls == ['POST', 'GET']
    assert result['digest'] == payloads[0]['digest']


def test_sender_mutex_excludes_another_thread_during_post(lab, monkeypatch):
    lab.tick(9)
    sender, calls, _ = transport_publisher(lab, monkeypatch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        def post(date, **kwargs):
            other = pool.submit(loop.publish, now=lab.clock(), selected=lab.selected,
                                publisher=sender, reconcile=True)
            with pytest.raises(loop.LoopError, match='publication_busy'):
                other.result(timeout=5)
            return sender(date, **kwargs)
        assert loop.publish(now=lab.clock(), selected=lab.selected, publisher=post)['status'] == 'delivered'
    assert calls == ['POST', 'GET']


def test_legacy_artifact_mutex_still_excludes_new_discovery(lab):
    lab.store.prepare()
    with legacy_holder(lab.store.path('.lock')):
        result = lab.tick(9)
    assert result['reason'] == 'discovery_lock_busy'
    assert not lab.store.exists(loop.STATE_FILE) and lab.events == []
    assert lab.tick(9)['calls_today'] == 1


@pytest.mark.parametrize('version', [1, 2])
def test_storage_switch_cannot_restart_empty_ledger_or_republish_frozen_day(lab, version):
    lab.tick(9)
    original_state = lab.store.path(loop.STATE_FILE).read_bytes()
    original_report = lab.store.path('web/2026-10-15.json').read_bytes()
    mount = lab.root.parent
    other = storage.Storage(root=lab.root, version=version,
        artifacts=storage.DirectorySpec(mount / 'other-artifacts', mount, 0),
        temporary=storage.DirectorySpec(mount / 'other-contexts', mount, 0),
        config_path=mount / 'other-policy.json', env={}, fs=FixtureFS(mount))
    result = lab.tick(10, selected=other)
    assert result['reason'] == 'storage_binding_invalid'
    assert not imp.Store(other).exists(loop.STATE_FILE)
    assert lab.store.path(loop.STATE_FILE).read_bytes() == original_state
    assert lab.store.path('web/2026-10-15.json').read_bytes() == original_report
    assert len(lab.events) == 1


def test_duplicate_tick_during_post_in_another_process_never_posts_or_calls(lab, monkeypatch):
    lab.tick(9)
    sender, calls, _ = transport_publisher(lab, monkeypatch)
    context = multiprocessing.get_context('fork')
    queue = context.Queue()
    def duplicate():
        attempts = []
        def forbidden_post(*a, **kw):
            attempts.append('post')
            raise AssertionError('Duplicate sender was admitted')
        result = lab.tick(9, publisher=forbidden_post)
        queue.put((result, attempts))
    def send(date, **kwargs):
        child = context.Process(target=duplicate)
        child.start()
        try:
            other, attempts = queue.get(timeout=5)
            assert other['reason'] == 'sender_lock_busy' and attempts == []
        finally:
            child.join(timeout=5)
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
        assert child.exitcode == 0
        return sender(date, **kwargs)
    try:
        result = loop.publish(now=lab.clock(), selected=lab.selected, publisher=send)
    finally:
        queue.close()
    assert result['status'] == 'delivered' and calls == ['POST', 'GET']
    assert lab.ledger()['calls'] == 1 and len(lab.events) == 1


def test_snapshot_rejects_external_edit_of_earlier_source_during_capture(lab, monkeypatch):
    read = imp._read_file
    first, second = FILES[:2]
    changed = False
    def edit_earlier(path, *a, **kw):
        nonlocal changed
        value = read(path, *a, **kw)
        if path == lab.root / second and not changed:
            changed = True
            (lab.root / first).write_text('external edit during capture\n')
        return value
    monkeypatch.setattr(imp, '_read_file', edit_earlier)
    with pytest.raises(imp.ImprovementError, match='Sources changed'):
        imp.snapshot_sources(FILES, selected=lab.selected)
    assert (lab.root / first).read_text() == 'external edit during capture\n'


def test_apply_rollback_preserves_external_edit_after_own_replacement(lab, monkeypatch):
    prepare_workflow(lab, monkeypatch)
    first, second = 'parser_tidy/example.py', 'downloader/example.py'
    original_second = (lab.root / second).read_bytes()
    replace = workspace.replace_file
    def interrupt(source, target, mode):
        if target == lab.root / first:
            (lab.root / second).write_text('external edit after replacement\n')
            raise OSError('synthetic apply interruption')
        return replace(source, target, mode)
    monkeypatch.setattr(workspace, 'replace_file', interrupt)
    report = workflow.execute('Synthetic two-file rollback.', [first, second],
        rules_only=True, keys={}, runner=runner_for([]), checker=successful_check, no_git=True)
    assert report['status'] == 'failed' and report['applied'] == []
    assert original_second != (lab.root / second).read_bytes()
    assert (lab.root / second).read_text() == 'external edit after replacement\n'


def test_interrupted_apply_restores_own_partial_changes_and_releases_source_mutex(lab, monkeypatch):
    prepare_workflow(lab, monkeypatch)
    names = ['downloader/example.py', 'parser_tidy/example.py']
    before = {name: (lab.root / name).read_bytes() for name in names}
    replace = workspace.replace_file
    def interrupt_second(source, target, mode):
        if target == lab.root / names[1]:
            raise KeyboardInterrupt()
        return replace(source, target, mode)
    monkeypatch.setattr(workspace, 'replace_file', interrupt_second)
    report = workflow.execute('Synthetic interrupted apply.', names, rules_only=True,
        keys={}, runner=runner_for([]), checker=successful_check, no_git=True)
    assert report['status'] == 'interrupted' and report['applied'] == []
    assert {name: (lab.root / name).read_bytes() for name in names} == before
    with project_lock.hold(lab.selected, reentrant=False):
        pass
