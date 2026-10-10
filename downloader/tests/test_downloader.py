"""Offline download → extraction → version → retry regressions."""
from pathlib import Path
import shutil
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


VALID_ITEM_CSV = (
    'ClassID,Name,RefreshScp\n'
    '1,plain,NO\n'
    '2,"comma, inside",NO\n'
    '3,"doubled ""quote"" inside",NO\n'
    '4,"multi\nline value",NO\n'
)
HEADER_ONLY_CSV = 'ClassID,Name,RefreshScp\n'


def tree_snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob('*')) if path.is_file()}


def test_valid_ies_csv_quoting_multiline_and_header_only_reach_output(workspace, server, extract_stub):
    extract_stub.install({'ies.ipf/item.ies': VALID_ITEM_CSV,
                          'ies.ipf/nested/header_only.ies': HEADER_ONLY_CSV})
    assert client.main(['itos']) == 0
    # The published bytes are the independent expectation: strict validation
    # must keep quoted commas, doubled quotes, multiline records and a
    # header-only table byte-for-byte intact.
    assert (workspace / 'itos_unpack/ies.ipf/item.ies').read_bytes() == VALID_ITEM_CSV.encode('utf-8')
    assert (workspace / 'itos_unpack/ies.ipf/nested/header_only.ies').read_bytes() == HEADER_ONLY_CSV.encode('utf-8')
    assert client.read_version('revision.csv')['itos'] == '2'
    assert not Path('extract').exists()
    assert not Path('1_001001.ipf').exists()


INVALID_IES_CSVS = {
    # What the old installed ipf_unpack shipped: a raw quote inside a quoted
    # field shifts every later column (RefreshScp became YES).
    'raw_inner_quote': ('ClassID,Name,RefreshScp\n1,"raw "inner" quote",YES\n',
                        ('record 2', 'text follows the closing quote')),
    'unterminated_quote': ('ClassID,Name,RefreshScp\n1,"never terminated,YES\n',
                           ('record 2', 'quoted field is not terminated')),
    'unquoted_inner_quote': ('ClassID,Name,RefreshScp\n1,say "hello",YES\n',
                             ('record 2', 'quote inside an unquoted field')),
    'short_row': ('ClassID,Name,RefreshScp\n1,short\n', ('record 2', 'has 2 fields, expected 3')),
    'overflow_row': ('ClassID,Name,RefreshScp\n1,plain,NO,extra\n', ('record 2', 'has 4 fields, expected 3')),
    'empty_file': ('', ('is empty',)),
    'missing_header': ('\n1,plain,NO\n', ('record 1', 'the file has no header row')),
}


@pytest.mark.parametrize('damage', sorted(INVALID_IES_CSVS))
def test_ies_csv_validation_error_names_file_record_and_cause(tmp_path, damage):
    content, fragments = INVALID_IES_CSVS[damage]
    path = tmp_path / 'extract' / 'item.ies'
    path.parent.mkdir()
    path.write_text(content, encoding='utf-8')
    with pytest.raises(RuntimeError) as raised:
        client.validate_ies_csv(str(path))
    message = str(raised.value)
    assert str(path) in message
    for fragment in fragments:
        assert fragment in message


HEADER_ONLY_VARIANTS = {
    'without_final_newline': 'ClassID,Name,RefreshScp',
    'crlf': 'ClassID,Name,RefreshScp\r\n',
}


@pytest.mark.parametrize('variant', sorted(HEADER_ONLY_VARIANTS))
def test_ies_csv_validation_accepts_header_only_variants(tmp_path, variant):
    path = tmp_path / 'extract' / 'item.ies'
    path.parent.mkdir()
    path.write_text(HEADER_ONLY_VARIANTS[variant], encoding='utf-8')
    client.validate_ies_csv(str(path))


DAMAGED_HEADER = 'ClassID,Name,RefreshScp\n'
# Every value is the whole extracted file. Prefixing the header would turn
# empty_file into a valid header-only table and blank_header into an
# ordinary short-row failure, hiding the cases they exist to cover.
DAMAGED_IES_FILES = {
    'raw_inner_quote': DAMAGED_HEADER + '1,"described as "EP12_TRK04_001" in game",YES\n',
    'unterminated_quote': DAMAGED_HEADER + '1,"never terminated,YES\n',
    'unquoted_inner_quote': DAMAGED_HEADER + '1,say "hello",YES\n',
    'short_row': DAMAGED_HEADER + '1,only-two\n',
    'overflow_row': DAMAGED_HEADER + '1,plain,NO,extra\n',
    'empty_file': '',
    'blank_header': '\n1,plain,NO\n',
}


@pytest.mark.parametrize('damage', sorted(DAMAGED_IES_FILES))
def test_damaged_ies_csv_fails_after_extract_and_preserves_state(workspace, server, extract_stub, damage):
    extract_stub.install({'ies.ipf/item.ies': DAMAGED_IES_FILES[damage]})
    (workspace / 'itos_unpack/ies.ipf').mkdir(parents=True)
    (workspace / 'itos_unpack/ies.ipf/previous.ies').write_bytes(b'PREVIOUS\n')
    (workspace / 'Translation/English').mkdir(parents=True)
    (workspace / 'Translation/English/items.tsv').write_bytes(b'PREVIOUS\n')
    published = {name: tree_snapshot(workspace / name) for name in ('itos_unpack', 'Translation')}
    versions = [Path(name).read_bytes() for name in ('revision.csv', 'release.csv')]

    assert client.main(['itos']) == 2

    # Damage found after a successful extraction must not advance versions,
    # touch existing unpack output or Translation, discard the cached
    # archive, or leave the temporary extract behind.
    assert {name: tree_snapshot(workspace / name) for name in ('itos_unpack', 'Translation')} == published
    assert [Path(name).read_bytes() for name in ('revision.csv', 'release.csv')] == versions
    assert (workspace / 'itos_patch/1_001001.ipf').read_bytes() == server.routes['1_001001.ipf']
    assert not list((workspace / 'itos_patch').glob('*.part'))
    assert not Path('extract').exists()
    assert not Path('1_001001.ipf').exists()
    assert server.calls == ['data.revision.txt', '1_001001.ipf']
    # The cached archive is still good: with a correct tool the same patch
    # completes without being downloaded again.
    extract_stub.restore()
    assert client.main(['itos']) == 0
    assert server.calls.count('1_001001.ipf') == 1
    assert client.read_version('revision.csv')['itos'] == '2'


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
    # Only the tracked .example is read: operational cron_*.sh stay untracked
    # local files, so a fresh checkout must pass without them. A missing or
    # guard-less example raises here (FileNotFoundError/ValueError): it fails
    # the test, it is never skipped.
    source = (ROOT / ('cron_' + region + '.sh.example')).read_text(encoding='utf-8')
    start = source.index('download_result=$?')
    end = source.index('\nfi', start) + len('\nfi')
    # Execute just the failure guard; cron itself and webhooks never run.
    block = source[start:end]
    result = subprocess.run(['bash', '-c', '(exit %d)\n%s\nprintf reached_followup' % (code, block)],
                            capture_output=True, text=True)
    assert result.returncode == (code if code > 1 else 0)
    assert ('reached_followup' in result.stdout) == (code <= 1)


PREPARE_TARGET = 'prepare-ipf-unpacker'

# A tiny synthetic stand-in for the native project: "release" always rebuilds
# the tool at the exact path the downloader executes and logs each rebuild so
# the forced (-B) behaviour is observable. No compiler and no native source.
SYNTHETIC_RELEASE_MAKEFILE = '''\
../../ipf_unpack:
\t@printf 'release\\n' >> build.log
\t@printf '#!/bin/sh\\n' > $@
\t@chmod 755 $@

.PHONY: release
release: ../../ipf_unpack
'''

FAILING_RELEASE_MAKEFILE = '''\
../../ipf_unpack:
\t@printf 'release\\n' >> build.log
\t@exit 7

.PHONY: release
release: ../../ipf_unpack
'''


def synthetic_native_project(tmp_path, native_makefile):
    native = tmp_path / 'IPFUnpacker' / 'src' / 'ipf_unpack'
    native.mkdir(parents=True)
    (native / 'Makefile').write_text(native_makefile, encoding='utf-8')
    # The real root Makefile drives a throwaway copy of the synthetic project,
    # so the repository checkout is never used as native source or built.
    shutil.copyfile(ROOT / 'Makefile', tmp_path / 'Makefile')
    return native


def run_prepare(tmp_path):
    return subprocess.run(['make', '-C', str(tmp_path), PREPARE_TARGET],
                          capture_output=True, text=True)


def prepare_target_block():
    lines = (ROOT / 'Makefile').read_text(encoding='utf-8').splitlines()
    start = lines.index(PREPARE_TARGET + ':')
    block = [lines[start]]
    for line in lines[start + 1:]:
        if not line.startswith('\t'):
            break
        block.append(line)
    return block


def test_prepare_ipf_unpacker_runs_only_the_exact_forced_release_command():
    assert prepare_target_block() == ['prepare-ipf-unpacker:',
                                      '\t$(MAKE) -C IPFUnpacker/src/ipf_unpack -B release']


def test_prepare_ipf_unpacker_is_in_phony_and_help_but_wired_nowhere_else():
    mentions = [line for line in (ROOT / 'Makefile').read_text(encoding='utf-8').splitlines()
                if PREPARE_TARGET in line]
    phony = [line for line in mentions if line.startswith('.PHONY:')]
    targets = [line for line in mentions if line.startswith(PREPARE_TARGET + ':')]
    echoed = [line for line in mentions if line.lstrip().startswith(('@echo', '@printf'))]
    # Declared in .PHONY, documented in help and its own target line: no other
    # target depends on it, and doctor/check/downloader never invoke it.
    assert len(phony) == 1
    assert targets == [PREPARE_TARGET + ':']
    assert len(echoed) == 1
    assert len(mentions) == 3


def test_prepare_ipf_unpacker_links_release_tool_at_exact_path_and_forces_rebuild(tmp_path):
    native = synthetic_native_project(tmp_path, SYNTHETIC_RELEASE_MAKEFILE)
    first = run_prepare(tmp_path)
    assert first.returncode == 0, first.stdout + first.stderr
    tool = tmp_path / 'IPFUnpacker' / 'ipf_unpack'
    assert tool.is_file()
    # The tool is linked exactly where the downloader executes it: no
    # bin/Release tree and no separate installed copy next to it.
    assert sorted(path.name for path in (tmp_path / 'IPFUnpacker').iterdir()) == ['ipf_unpack', 'src']
    # The second prepare must run the release target again although the tool
    # is already up to date: that is the forced -B in the exact command.
    second = run_prepare(tmp_path)
    assert second.returncode == 0, second.stdout + second.stderr
    assert (native / 'build.log').read_text(encoding='utf-8') == 'release\nrelease\n'


def test_prepare_ipf_unpacker_propagates_release_failure(tmp_path):
    synthetic_native_project(tmp_path, FAILING_RELEASE_MAKEFILE)
    result = run_prepare(tmp_path)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not (tmp_path / 'IPFUnpacker' / 'ipf_unpack').exists()
