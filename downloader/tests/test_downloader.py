"""Offline download → extraction → version → retry regressions."""
from pathlib import Path
import struct
import stat
import subprocess
import sys
import urllib.error

import pytest

from downloader import blowfish
from downloader import downloader as client
from downloader import unpacker_pak

FIXTURES = Path(__file__).resolve().parents[2] / 'harness' / 'fixtures' / 'downloader'
ROOT = Path(__file__).resolve().parents[2]


def encrypted_revisions(text):
    plain = text.encode('ascii')
    padded = plain + b'\x00' * (-len(plain) % 8)
    data = list(struct.pack('<ii', len(plain), len(padded)) + padded)
    blowfish.Encipher(data, 8, len(padded))
    return bytes(value & 255 for value in data)


def patch_data():
    return client.patch_partial('../itos_patch', 'https://fixture.invalid/partial/data/',
                                '.ipf', False, 'revision.csv',
                                'https://fixture.invalid/partial/data.revision.txt', 0)


def test_real_revision_decryption_fixture():
    assert client.revision_decrypt((FIXTURES / 'revisions.bin').read_bytes()) == ['1', '2']


def test_download_extract_language_versions_and_no_changes(workspace, server):
    assert client.main(['itos']) == 0
    assert (workspace / 'itos_unpack/ies.ipf/item.ies').read_text().startswith('ClassID,')
    assert (workspace / 'itos_unpack/shared.ipf/harness.lua').read_text() == 'HARNESS_PATCH_VERSION = 1\n'
    assert (workspace / 'Translation/English/items.tsv').read_text() == 'harness_ore\tHarness Ore\n'
    assert not (workspace / 'itos_patch/Client_tos.exe').exists()
    assert client.read_version('revision.csv') == {'itos': '2', 'ktos': '99'}
    assert client.read_version('release.csv') == {'itos': '2', 'ktos': '99'}
    versions = [Path(name).read_bytes() for name in ('revision.csv', 'release.csv')]
    server.calls.clear()
    assert client.main(['itos']) == 1
    assert server.calls == ['data.revision.txt', 'release.revision.txt']
    assert [Path(name).read_bytes() for name in ('revision.csv', 'release.csv')] == versions
    assert not list((workspace / 'itos_patch').glob('*.part'))


def test_old_version_snapshot_and_server_order(server):
    server.revision = encrypted_revisions('2\r\n1\r\n2\r\n')
    old, new, changed = patch_data()
    assert old['itos'] == '0'
    assert new['itos'] == '2'
    assert changed
    assert server.calls == ['data.revision.txt', '1_001001.ipf', '2_001001.ipf']


@pytest.mark.parametrize('fault', ['network', 'empty', 'short', 'interrupted'])
def test_failed_download_preserves_version_and_retry_redownloads(workspace, server, fault):
    patch = server.routes['1_001001.ipf']
    faults = {
        'network': urllib.error.URLError('server unavailable'),
        'empty': {'data': b''},
        'short': {'data': patch[:8], 'length': len(patch)},
        'interrupted': {'data': patch, 'fail_after': 8},
    }
    server.faults['1_001001.ipf'] = faults[fault]
    old = Path('revision.csv').read_bytes()
    assert client.main(['itos']) == 2
    assert Path('revision.csv').read_bytes() == old
    assert not (workspace / 'itos_patch/1_001001.ipf').exists()
    assert not (workspace / 'itos_patch/1_001001.ipf.part').exists()
    assert not Path('tool_calls.log').exists()
    del server.faults['1_001001.ipf']
    assert client.main(['itos']) == 0
    assert server.calls.count('1_001001.ipf') == 2
    assert client.read_version('revision.csv')['itos'] == '2'


@pytest.mark.parametrize('action', ['decrypt', 'extract'])
def test_tool_failure_preserves_cache_and_retries_without_download(workspace, server, action):
    Path('fail-' + action).touch()
    assert client.main(['itos']) == 2
    assert client.read_version('revision.csv')['itos'] == '0'
    cached = workspace / 'itos_patch/1_001001.ipf'
    assert cached.read_bytes() == server.routes['1_001001.ipf']
    assert not Path('extract').exists()
    assert not Path('1_001001.ipf').exists()
    Path('fail-' + action).unlink()
    assert client.main(['itos']) == 0
    assert server.calls.count('1_001001.ipf') == 1


@pytest.mark.parametrize('extension,state,other', [
    ('ipf', 'revision.csv', 'release.csv'), ('pak', 'release.csv', 'revision.csv'),
])
def test_second_patch_failure_resumes_from_last_success(workspace, server, extension, state, other):
    failed_patch = '2_001001.' + extension
    server.faults[failed_patch] = urllib.error.URLError('second patch unavailable')
    assert client.main(['itos']) == 2
    assert client.read_version(state)['itos'] == '1'
    assert client.read_version(other)['itos'] == ('0' if extension == 'ipf' else '2')
    server.calls.clear()
    del server.faults[failed_patch]
    assert client.main(['itos']) == 0
    assert '1_001001.' + extension not in server.calls
    assert failed_patch in server.calls


def test_output_copy_failure_does_not_delete_retry_archive(workspace, server, monkeypatch):
    real_run = client.subprocess.run
    def fail_copy(args, **kwargs):
        if args[0] == 'cp':
            raise subprocess.CalledProcessError(9, args)
        return real_run(args, **kwargs)
    monkeypatch.setattr(client.subprocess, 'run', fail_copy)
    assert client.main(['itos']) == 2
    assert client.read_version('revision.csv')['itos'] == '0'
    assert (workspace / 'itos_patch/1_001001.ipf').exists()
    monkeypatch.setattr(client.subprocess, 'run', real_run)
    assert client.main(['itos']) == 0
    assert server.calls.count('1_001001.ipf') == 1


def test_version_write_failure_preserves_csv_and_can_retry(workspace, server, monkeypatch):
    real_replace = client.os.replace
    old = Path('revision.csv').read_bytes()
    def fail_version(source, destination):
        if Path(destination).name == 'revision.csv':
            raise OSError('version publication failed')
        return real_replace(source, destination)
    monkeypatch.setattr(client.os, 'replace', fail_version)
    assert client.main(['itos']) == 2
    assert Path('revision.csv').read_bytes() == old
    assert not list(Path('.').glob('.download-version-*'))
    monkeypatch.setattr(client.os, 'replace', real_replace)
    assert client.main(['itos']) == 0


def test_version_publication_preserves_existing_read_permissions(workspace):
    path = Path('revision.csv')
    path.chmod(0o640)
    client.print_version(str(path), {'itos': '1', 'ktos': '99'})
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert client.read_version(str(path)) == {'itos': '1', 'ktos': '99'}


def test_corrupt_pak_preserves_language_and_redownloads(workspace, server):
    language = workspace / 'itos_patch/languageData/English/items.tsv'
    language.parent.mkdir(parents=True)
    language.write_text('previous translation')
    client.print_version('revision.csv', {'itos': '2', 'ktos': '99'})
    server.routes['1_001001.pak'] = b'broken archive'
    assert client.main(['itos']) == 2
    assert client.read_version('release.csv')['itos'] == '0'
    assert language.read_text() == 'previous translation'
    assert not (workspace / 'itos_patch/1_001001.pak').exists()
    server.routes['1_001001.pak'] = (FIXTURES / 'release.pak').read_bytes()
    assert client.main(['itos']) == 0
    assert server.calls.count('1_001001.pak') == 2
    assert language.read_text() == 'harness_ore\tHarness Ore\n'


@pytest.mark.parametrize('damage', ['deflate', 'size', 'truncated'])
def test_pak_validation_preserves_existing_output_and_retries(workspace, server, damage):
    language = workspace / 'itos_patch/languageData/English/items.tsv'
    language.parent.mkdir(parents=True)
    language.write_text('previous translation')
    client.print_version('revision.csv', {'itos': '2', 'ktos': '99'})
    pak = bytearray((FIXTURES / 'release.pak').read_bytes())
    name_length = struct.unpack_from('<h', pak)[0]
    if damage == 'deflate':
        pak[14 + name_length] = 0xff
    elif damage == 'size':
        struct.pack_into('<i', pak, 10, 999)
    else:
        pak = pak[:14 + name_length + 2]
    server.routes['1_001001.pak'] = bytes(pak)
    assert client.main(['itos']) == 2
    assert language.read_text() == 'previous translation'
    assert client.read_version('release.csv')['itos'] == '0'
    assert not language.with_suffix('.tsv.part').exists()
    server.routes['1_001001.pak'] = (FIXTURES / 'release.pak').read_bytes()
    assert client.main(['itos']) == 0


def test_translation_copy_failure_keeps_release_pending_for_retry(workspace, server, monkeypatch):
    real_run = client.subprocess.run
    def fail_language(args, **kwargs):
        if args[0] == 'cp' and 'languageData' in args[2]:
            raise subprocess.CalledProcessError(9, args)
        return real_run(args, **kwargs)
    monkeypatch.setattr(client.subprocess, 'run', fail_language)
    assert client.main(['itos']) == 2
    assert client.read_version('revision.csv')['itos'] == '2'
    assert client.read_version('release.csv')['itos'] == '0'
    monkeypatch.setattr(client.subprocess, 'run', real_run)
    server.calls.clear()
    assert client.main(['itos']) == 0
    assert server.calls == ['data.revision.txt', 'release.revision.txt', '1_001001.pak', '2_001001.pak']
    assert (workspace / 'Translation/English/items.tsv').read_text() == 'harness_ore\tHarness Ore\n'


@pytest.mark.parametrize('bad_bytes', [b'', b'bad', struct.pack('<ii', 8, 16) + b'12345678'])
def test_invalid_revision_response_fails_before_download(workspace, server, bad_bytes):
    server.revision = bad_bytes
    assert client.main(['itos']) == 2
    assert client.read_version('revision.csv')['itos'] == '0'
    assert server.calls == ['data.revision.txt']


def test_nonnumeric_revision_is_failure_before_any_download(workspace, server):
    server.revision = encrypted_revisions('1\r\ninvalid\r\n')
    assert client.main(['itos']) == 2
    assert client.read_version('revision.csv')['itos'] == '0'
    assert server.calls == ['data.revision.txt']


def test_blocked_patch_does_not_advance_version(workspace, server, monkeypatch):
    monkeypatch.setattr(client, 'error_ipf', ['1_001001.ipf'])
    assert client.main(['itos']) == 2
    assert client.read_version('revision.csv')['itos'] == '0'
    assert server.calls == ['data.revision.txt']


@pytest.mark.parametrize('args', [[], ['unsupported']])
def test_invalid_cli_arguments_are_failure(workspace, server, args):
    assert client.main(args) == 2
    assert not server.calls


@pytest.mark.parametrize('mode,expected', [('changed', 0), ('unchanged', 1), ('failed', 2)])
def test_actual_cli_exit_codes_with_blocked_network(workspace, mode, expected):
    if mode == 'unchanged':
        for name in ('revision.csv', 'release.csv'):
            client.print_version(name, {'itos': '2', 'ktos': '99'})
    script = '''
from pathlib import Path
import io, runpy, socket, sys, urllib.request, urllib.error
root, fixtures, mode = sys.argv[1:]
def blocked(*args, **kwargs): raise AssertionError('real network is blocked')
socket.socket.connect = blocked
class Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {'Content-Length': str(len(data))}
def local_open(request, timeout=None):
    if mode == 'failed': raise urllib.error.URLError('simulated failure')
    url = request.full_url if isinstance(request, urllib.request.Request) else request
    name = url.rsplit('/', 1)[-1]
    if name.endswith('.revision.txt'): file = 'revisions.bin'
    elif name.endswith('.ipf'): file = 'ipf_patch.json'
    elif name.endswith('.pak'): file = 'release.pak'
    else: raise AssertionError('unmapped request')
    return Response((Path(fixtures) / file).read_bytes())
urllib.request.urlopen = local_open
sys.path.insert(0, str(Path(root) / 'downloader'))
sys.argv = ['downloader.py', 'itos']
runpy.run_path(str(Path(root) / 'downloader/downloader.py'), run_name='__main__')
'''
    result = subprocess.run([sys.executable, '-c', script, str(ROOT), str(FIXTURES), mode],
                            capture_output=True, text=True)
    assert result.returncode == expected, result.stdout + result.stderr


@pytest.mark.parametrize('region', ['itos', 'ktos', 'jtos', 'ktest', 'twtos'])
@pytest.mark.parametrize('code', [0, 1, 2, 7])
def test_cron_download_failure_blocks_followup(region, code):
    source = (ROOT / ('cron_' + region + '.sh')).read_text()
    start = source.index('download_result=$?')
    end = source.index('\nfi', start) + len('\nfi')
    # Execute just the failure guard; cron itself and webhooks never run.
    block = source[start:end]
    result = subprocess.run(['bash', '-c', '(exit %d)\n%s\nprintf reached_followup' % (code, block)],
                            capture_output=True, text=True)
    assert result.returncode == (code if code > 1 else 0)
    assert ('reached_followup' in result.stdout) == (code <= 1)
