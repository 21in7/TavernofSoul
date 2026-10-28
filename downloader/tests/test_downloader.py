"""Offline download → extraction → version → retry regressions."""
from pathlib import Path
import os
import random
import shutil
import struct
import stat
import subprocess
import sys
import urllib.error
import zlib

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


# A binary IES can legitimately have zero rows and zero columns: the native
# extractor then exports exactly one line terminator. That complete file is
# real official data and must publish unchanged, advance the version and
# clean up like any other patch.
ZERO_SCHEMA_IES_CSVS = {'lf': '\n', 'crlf': '\r\n'}


@pytest.mark.parametrize('variant', sorted(ZERO_SCHEMA_IES_CSVS))
def test_ies_csv_validation_accepts_zero_schema_table_unchanged(tmp_path, variant):
    path = tmp_path / 'extract' / 'item.ies'
    path.parent.mkdir()
    path.write_bytes(ZERO_SCHEMA_IES_CSVS[variant].encode('utf-8'))
    client.validate_ies_csv(str(path))
    assert path.read_bytes() == ZERO_SCHEMA_IES_CSVS[variant].encode('utf-8')


@pytest.mark.parametrize('variant', sorted(ZERO_SCHEMA_IES_CSVS))
def test_zero_schema_ies_csv_publishes_unchanged_and_disposes_cache(workspace, server, extract_stub, variant):
    zero_schema = ZERO_SCHEMA_IES_CSVS[variant]
    extract_stub.install({'ies.ipf/item.ies': zero_schema})
    assert client.main(['itos']) == 0
    # The published table is the extracted bytes, exactly one line terminator.
    assert (workspace / 'itos_unpack/ies.ipf/item.ies').read_bytes() == zero_schema.encode('utf-8')
    assert client.read_version('revision.csv')['itos'] == '2'
    assert client.read_version('release.csv')['itos'] == '2'
    # Success cleans the temporary extraction, the local archive copy and the
    # cached download alike.
    assert not Path('extract').exists()
    assert not Path('1_001001.ipf').exists()
    assert not (workspace / 'itos_patch/1_001001.ipf').exists()
    assert not list((workspace / 'itos_patch').glob('*.part'))


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
    # A zero-schema table is exactly one line terminator: a second record, or
    # a blank header carrying fields, is a missing header again.
    'blank_lines': ('\n\n', ('record 1', 'the file has no header row')),
    'crlf_blank_lines': ('\r\n\r\n', ('record 1', 'the file has no header row')),
    'blank_header_comma_fields': ('\n,,\n', ('record 1', 'the file has no header row')),
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


def test_ies_csv_validation_rejects_invalid_utf8(tmp_path):
    path = tmp_path / 'extract' / 'item.ies'
    path.parent.mkdir()
    path.write_bytes(b'ClassID,Name,RefreshScp\n1,\xff\xfe,NO\n')
    with pytest.raises(RuntimeError) as raised:
        client.validate_ies_csv(str(path))
    message = str(raised.value)
    assert str(path) in message
    assert 'not UTF-8' in message


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
    # Exactly one line terminator is a valid zero-schema table; anything
    # beyond it (or a blank header carrying fields) must fail with all the
    # preservation and recovery guarantees below.
    'blank_lines': '\n\n',
    'crlf_blank_lines': '\r\n\r\n',
    'blank_header_comma_fields': '\n,,\n',
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
    real_copy_tree = client.copy_tree
    def fail_copy(source, destination):
        raise RuntimeError('simulated output copy failure: {}'.format(destination))
    monkeypatch.setattr(client, 'copy_tree', fail_copy)
    assert client.main(['itos']) == 2
    assert client.read_version('revision.csv')['itos'] == '0'
    assert (workspace / 'itos_patch/1_001001.ipf').exists()
    monkeypatch.setattr(client, 'copy_tree', real_copy_tree)
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


def test_version_csv_write_and_read_are_utf8_regardless_of_host_locale(tmp_path):
    # Real revision.csv/release.csv values are ASCII region names and numeric
    # revisions; the non-ASCII value here is a locale-independence probe, not
    # an expanded data contract. The exact published bytes pin explicit UTF-8
    # for both directions: a host-locale codec (for example a legacy
    # single-byte encoding) would fail this round-trip instead.
    data = {'itos': '2', 'ktos': '99', 'jtos': '일본판'}
    path = tmp_path / 'revision.csv'
    client.print_version(str(path), data)
    expected = 'itos,2\r\nktos,99\r\njtos,일본판\r\n'
    assert path.read_bytes() == expected.encode('utf-8')
    assert client.read_version(str(path)) == data


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


# Synthetic archives for the streaming PAK unpacker. The pak_io_guard fixture
# (conftest.py) proves the bounded-memory contract from the outside: every
# archive read() must be positive and capped, every inflate call must pass a
# positive bounded max_length and return at most that much, and the unbounded
# decompressor.flush() must never be called. The unpacker exposes its chunk
# globals exactly so tests can shrink them to drive the chunked loops with
# small fixed inputs. Failures must preserve the archive and the existing
# destination bytes and leave no .part behind.
def raw_deflate(data):
    # zlib.compress gained its wbits argument only in Python 3.11, so build
    # the raw deflate stream with compressobj. flush() here finishes the
    # test-side compressor; the unbounded production decompressor.flush()
    # that pak_io_guard forbids stays forbidden.
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    return compressor.compress(data) + compressor.flush()


def pak_header(name_length, checksum, size_compressed, size_uncompressed):
    # Exactly the 14 native signed header bytes unpacker_pak.unpack() parses.
    return (struct.pack('@h', name_length) + struct.pack('@i', checksum) +
            struct.pack('@i', size_compressed) + struct.pack('@i', size_uncompressed))


def pak_record(name, member, size_uncompressed, checksum=0):
    encoded = name if isinstance(name, bytes) else name.encode('utf-8')
    return pak_header(len(encoded), checksum, len(member), size_uncompressed) + encoded + member


def test_pak_large_member_streams_through_bounded_reads_and_inflate(tmp_path, pak_io_guard, monkeypatch):
    monkeypatch.setattr(unpacker_pak, '_READ_CHUNK_SIZE', 16)
    monkeypatch.setattr(unpacker_pak, '_INFLATE_CHUNK_SIZE', 32)

    reads, inflates = [], []

    def counting_open(file, mode, *args, **kwargs):
        handle = pak_io_guard.open(file, mode, *args, **kwargs)
        if mode == 'rb':
            guarded_read = handle.read

            def counted_read(size):
                reads.append(size)
                return guarded_read(size)
            handle.read = counted_read
        return handle

    def counting_decompressobj(*args, **kwargs):
        decompressor = pak_io_guard.decompressobj(*args, **kwargs)
        guarded_decompress = decompressor.decompress

        def counted_decompress(data, max_length):
            inflates.append(max_length)
            return guarded_decompress(data, max_length)
        decompressor.decompress = counted_decompress
        return decompressor

    # Counting sits on top of the guard, so every recorded call still runs
    # the fixture's positive/bounded assertions.
    monkeypatch.setattr(unpacker_pak, 'open', counting_open, raising=False)
    monkeypatch.setattr(unpacker_pak.zlib, 'decompressobj', counting_decompressobj)
    # Fixed-seed pseudorandom bytes are incompressible: the compressed member
    # must span several read chunks and the decoded output several inflates.
    # One seeded RNG is reused, so the bytes differ; a fresh Random per byte
    # would repeat one value and deflate it far below the read chunk size.
    rng = random.Random(20261014)
    payload = bytes(rng.getrandbits(8) for _ in range(200))
    member = raw_deflate(payload)
    assert len(member) > 16 and len(payload) > 32
    destination = tmp_path / 'unpack'
    destination.mkdir()
    archive = destination / 'bounded.pak'
    archive.write_bytes(pak_record('items.bin', member, len(payload)))
    unpacker_pak.unpack('bounded.pak', str(destination))
    assert (destination / 'items.bin').read_bytes() == payload
    assert len(reads) > 1 and max(reads) <= 16
    assert len(inflates) > 1 and set(inflates) == {32}
    assert not archive.exists()
    assert not list(destination.rglob('*.part'))


def test_pak_short_reads_empty_member_blacklist_and_trailing_bytes(tmp_path, pak_io_guard):
    pak_io_guard.short_reads = True
    destination = tmp_path / 'unpack'
    destination.mkdir()
    archive = destination / 'records.pak'
    archive.write_bytes(
        pak_record('multi/first.txt', raw_deflate(b'first\n'), 6) +
        # A zero-byte decoded member is a complete valid file.
        pak_record('multi/empty.txt', raw_deflate(b''), 0) +
        # The blacklist matches raw bytes before UTF-8 decoding: this invalid
        # name is skipped undecoded and unwritten, and later records stay valid.
        pak_record(b'xigncode\xff.lua', raw_deflate(b'skipped\n'), 8) +
        # Trailing bytes after the deflate stream are ignored, and the next
        # record starts at the declared compressed size, not at stream end.
        pak_record('multi/trailing.txt', raw_deflate(b'trailing\n') + b'ignored-trailing', 9) +
        pak_record('multi/last.txt', raw_deflate(b'last\n'), 5))
    unpacker_pak.unpack('records.pak', str(destination))
    published = sorted(str(path.relative_to(destination))
                       for path in destination.rglob('*') if path.is_file())
    assert published == ['multi/empty.txt', 'multi/first.txt', 'multi/last.txt', 'multi/trailing.txt']
    assert (destination / 'multi/first.txt').read_bytes() == b'first\n'
    assert (destination / 'multi/empty.txt').read_bytes() == b''
    assert (destination / 'multi/trailing.txt').read_bytes() == b'trailing\n'
    assert (destination / 'multi/last.txt').read_bytes() == b'last\n'
    assert not list(destination.rglob('*.part'))


INVALID_PAKS = {
    'empty_archive': (b'', ValueError),
    'truncated_header': (b'\x01\x02\x03', ValueError),
    # A positive name length declared past the archive end: the record
    # boundary check must reject it before any name byte is read.
    'truncated_name': (pak_header(4, 0, 0, 0), ValueError),
    'negative_name_length': (pak_header(-1, 0, 0, 0), ValueError),
    'empty_name': (pak_header(0, 0, 0, 0), ValueError),
    # A zero-length compressed member can never reach the deflate stream's
    # eof, so declaring non-empty output must fail instead of publishing.
    'empty_member': (pak_record('name', b'', 1), zlib.error),
    'negative_size_compressed': (pak_header(4, 0, -1, 0) + b'name', ValueError),
    'negative_size_uncompressed': (pak_header(4, 0, 0, -1) + b'name', ValueError),
    'member_past_end': (pak_header(4, 0, 999, 0) + b'name', ValueError),
    # Invalid UTF-8 outside the blacklist must fail the decode without ever
    # opening a .part or discarding the archive.
    'invalid_utf8_name': (pak_record(b'bad\xff\xfe.txt', raw_deflate(b'x'), 1), UnicodeDecodeError),
    # A decoded name must stay inside patch_destination: '..' components,
    # absolute paths and backslashes are rejected before any directory or
    # .part file is created, so a damaged archive can never write outside it.
    # The members themselves are valid, so only the name rule can reject
    # these records.
    'dotdot_name': (pak_record('../escaped.bin', raw_deflate(b'x'), 1), ValueError),
    'climbing_dotdot_name': (pak_record('a/../../b.bin', raw_deflate(b'x'), 1), ValueError),
    # Built per-test from tmp_path: still an absolute name, but a hypothetical
    # guard failure would then write inside tmp_path, never at a real
    # absolute location.
    'absolute_name': (lambda destination: pak_record(
        str(destination.parent / 'escaped.bin'), raw_deflate(b'x'), 1), ValueError),
    'backslash_name': (pak_record('sub\\escaped.bin', raw_deflate(b'x'), 1), ValueError),
}


@pytest.mark.parametrize('damage', sorted(INVALID_PAKS))
def test_pak_invalid_record_preserves_archive_and_publishes_nothing(tmp_path, pak_io_guard, damage):
    damaged, expected = INVALID_PAKS[damage]
    destination = tmp_path / 'unpack'
    destination.mkdir()
    if callable(damaged):
        damaged = damaged(destination)
    archive = destination / 'damaged.pak'
    archive.write_bytes(damaged)
    with pytest.raises(expected):
        unpacker_pak.unpack('damaged.pak', str(destination))
    assert archive.read_bytes() == damaged
    published = [path for path in destination.rglob('*')
                 if path.is_file() and path.name != 'damaged.pak']
    assert not published
    assert not list(destination.rglob('*.part'))
    # A rejected name must also never escape the destination: no file or
    # directory at all may appear anywhere else under tmp_path, so a '..'
    # climb, an absolute name or a backslash cannot write outside the unpack
    # directory, and no .part residue survives anywhere either.
    escaped = [str(path.relative_to(tmp_path)) for path in tmp_path.rglob('*')
               if path != destination and path != archive]
    assert escaped == []


DAMAGED_SECOND_RECORDS = {
    'incomplete_deflate': (raw_deflate(b'second\n')[:-1], len(b'second\n'), zlib.error),
    'corrupt_deflate': (b'\xff\x00\x00\x00\x00\x00\x00\x00', len(b'second\n'), zlib.error),
    'declared_size_mismatch': (raw_deflate(b'second\n'), len(b'second\n') + 1, ValueError),
}


@pytest.mark.parametrize('damage', sorted(DAMAGED_SECOND_RECORDS))
def test_pak_failure_in_second_record_publishes_first_and_preserves_rest(tmp_path, pak_io_guard, damage):
    member, size_uncompressed, expected = DAMAGED_SECOND_RECORDS[damage]
    destination = tmp_path / 'unpack'
    existing = destination / 'multi'
    existing.mkdir(parents=True)
    (existing / 'second.txt').write_bytes(b'PREVIOUS\n')
    archive = destination / 'tworecords.pak'
    damaged = (pak_record('multi/first.txt', raw_deflate(b'first\n'), 6) +
               pak_record('multi/second.txt', member, size_uncompressed))
    archive.write_bytes(damaged)
    with pytest.raises(expected):
        unpacker_pak.unpack('tworecords.pak', str(destination))
    # The record before the failure stays published; the failed record's old
    # destination bytes, the archive and no .part survive for the retry.
    assert (destination / 'multi/first.txt').read_bytes() == b'first\n'
    assert (destination / 'multi/second.txt').read_bytes() == b'PREVIOUS\n'
    assert archive.read_bytes() == damaged
    assert not list(destination.rglob('*.part'))


def test_pak_retry_with_good_bytes_at_same_archive_path_recovers(tmp_path, pak_io_guard):
    destination = tmp_path / 'unpack'
    destination.mkdir()
    archive = destination / 'release.pak'
    archive.write_bytes(b'broken archive bytes')
    with pytest.raises(ValueError):
        unpacker_pak.unpack('release.pak', str(destination))
    assert archive.exists()
    # The same path refilled with good bytes recovers with no leftover state
    # from the failed attempt: correct output, archive discarded.
    payload = b'harness_ore\tHarness Ore\n'
    archive.write_bytes(pak_record('languageData/English/items.tsv', raw_deflate(payload), len(payload)))
    unpacker_pak.unpack('release.pak', str(destination))
    assert (destination / 'languageData/English/items.tsv').read_bytes() == payload
    assert not archive.exists()
    assert not list(destination.rglob('*.part'))


@pytest.mark.parametrize('failure', ['fsync', 'replace'])
def test_pak_publication_failure_preserves_output_and_archive(tmp_path, pak_io_guard, monkeypatch, failure):
    if failure == 'fsync':
        def failing(*args, **kwargs):
            raise OSError('simulated fsync failure')
        monkeypatch.setattr(unpacker_pak.os, 'fsync', failing)
    else:
        def failing(source, target):
            raise OSError('simulated replace failure')
        monkeypatch.setattr(unpacker_pak.os, 'replace', failing)
    destination = tmp_path / 'unpack'
    existing = destination / 'languageData' / 'English'
    existing.mkdir(parents=True)
    (existing / 'items.tsv').write_bytes(b'PREVIOUS\n')
    archive = destination / 'release.pak'
    payload = b'next\n'
    archive.write_bytes(pak_record('languageData/English/items.tsv', raw_deflate(payload), len(payload)))
    with pytest.raises(OSError):
        unpacker_pak.unpack('release.pak', str(destination))
    # The already published member is untouched, the archive survives for the
    # retry, and the failed .part publication is removed again.
    assert (destination / 'languageData/English/items.tsv').read_bytes() == b'PREVIOUS\n'
    assert archive.exists()
    assert not list(destination.rglob('*.part'))


def test_translation_copy_failure_keeps_release_pending_for_retry(workspace, server, monkeypatch):
    real_copy_tree = client.copy_tree
    def fail_language(source, destination):
        if 'languageData' in source:
            raise RuntimeError('simulated translation copy failure: {}'.format(source))
        return real_copy_tree(source, destination)
    monkeypatch.setattr(client, 'copy_tree', fail_language)
    assert client.main(['itos']) == 2
    assert client.read_version('revision.csv')['itos'] == '2'
    assert client.read_version('release.csv')['itos'] == '0'
    monkeypatch.setattr(client, 'copy_tree', real_copy_tree)
    server.calls.clear()
    assert client.main(['itos']) == 0
    assert server.calls == ['data.revision.txt', 'release.revision.txt', '1_001001.pak', '2_001001.pak']
    assert (workspace / 'Translation/English/items.tsv').read_text() == 'harness_ore\tHarness Ore\n'


# The in-process copy helper replaced the two external 'cp -r' calls. These
# assertions pin the filesystem semantics the copy must keep: regular-file
# overwrite, directory merge retaining unrelated entries, source symlinks
# (dangling ones included) recreated as symlinks, directory access modes of
# newly created directories, and the destination conflicts that must fail
# without unintended side effects — at the top level and at nested levels.

def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_copy_tree_merges_directories_and_overwrites_regular_files(tmp_path):
    source = tmp_path / 'source'
    write_file(source / 'kept.txt', b'new kept\n')
    write_file(source / 'replaced.txt', b'new replaced\n')
    write_file(source / 'nested' / 'inner.txt', b'new inner\n')
    destination = tmp_path / 'output' / 'source'
    write_file(destination / 'unrelated.txt', b'unrelated\n')
    write_file(destination / 'replaced.txt', b'old replaced\n')
    write_file(destination / 'nested' / 'inner.txt', b'old inner\n')

    client.copy_tree(str(source), str(destination))

    assert (destination / 'unrelated.txt').read_bytes() == b'unrelated\n'
    assert (destination / 'kept.txt').read_bytes() == b'new kept\n'
    assert (destination / 'replaced.txt').read_bytes() == b'new replaced\n'
    assert (destination / 'nested' / 'inner.txt').read_bytes() == b'new inner\n'
    assert not (destination / 'kept.txt').is_symlink()


def test_copy_tree_identical_nested_link_trees_copy_twice(tmp_path):
    source = tmp_path / 'source'
    write_file(source / 'nested' / 'real.txt', b'real\n')
    (source / 'nested' / 'alias.txt').symlink_to('real.txt')
    (source / 'nested' / 'dangling.txt').symlink_to('nowhere.txt')
    destination = tmp_path / 'output' / 'source'
    destination.parent.mkdir()

    client.copy_tree(str(source), str(destination))
    # The second copy applies the same tree over its own previous output.
    client.copy_tree(str(source), str(destination))

    alias = destination / 'nested' / 'alias.txt'
    assert os.path.islink(alias)
    assert os.readlink(alias) == 'real.txt'
    assert alias.read_bytes() == b'real\n'
    dangling = destination / 'nested' / 'dangling.txt'
    assert os.path.islink(dangling)
    assert os.readlink(dangling) == 'nowhere.txt'
    assert not dangling.exists()
    assert (destination / 'nested' / 'real.txt').read_bytes() == b'real\n'


def test_copy_tree_source_symlink_replaces_destination_file_and_link(tmp_path):
    target = write_file(tmp_path / 'target.txt', b'target\n')
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'link.txt').symlink_to(target)
    (source / 'dangling.txt').symlink_to('missing.txt')
    destination = tmp_path / 'output' / 'source'
    write_file(destination / 'link.txt', b'old file\n')
    (destination / 'dangling.txt').symlink_to('other.txt')

    client.copy_tree(str(source), str(destination))

    assert os.path.islink(destination / 'link.txt')
    assert os.readlink(destination / 'link.txt') == str(target)
    assert (destination / 'link.txt').read_bytes() == b'target\n'
    assert os.path.islink(destination / 'dangling.txt')
    assert os.readlink(destination / 'dangling.txt') == 'missing.txt'
    assert not (destination / 'dangling.txt').exists()


def test_copy_tree_updates_target_of_live_destination_file_symlink(tmp_path):
    source = write_file(tmp_path / 'source.bin', b'next\n')
    target = write_file(tmp_path / 'output' / 'target.txt', b'old\n')
    destination = tmp_path / 'output' / 'link.bin'
    destination.symlink_to(target)

    client.copy_tree(str(source), str(destination))

    assert destination.is_symlink()
    assert os.readlink(destination) == str(target)
    assert target.read_bytes() == b'next\n'


def test_copy_tree_preserves_new_directory_access_modes(tmp_path):
    source = tmp_path / 'source'
    write_file(source / 'nested' / 'file.txt', b'content\n')
    os.chmod(source, 0o755)
    os.chmod(source / 'nested', 0o750)
    destination = tmp_path / 'output' / 'source'
    destination.parent.mkdir()

    client.copy_tree(str(source), str(destination))

    assert stat.S_IMODE(destination.stat().st_mode) == 0o755
    assert stat.S_IMODE((destination / 'nested').stat().st_mode) == 0o750


@pytest.mark.parametrize('nested', [False, True])
def test_copy_tree_file_over_destination_directory_fails_without_side_effects(tmp_path, nested):
    source = tmp_path / 'source'
    write_file(source / 'child', b'next\n')
    write_file(source / 'aaaa_first.txt', b'first\n')
    destination = tmp_path / 'output' / 'source'
    conflicting = destination / 'child'
    write_file(conflicting / 'original.txt', b'original\n')
    write_file(destination / 'keep.txt', b'keep\n')

    source_path, destination_path = str(source / 'child'), str(conflicting)
    if nested:
        source_path, destination_path = str(source), str(destination)
    with pytest.raises(RuntimeError):
        client.copy_tree(source_path, destination_path)

    assert (conflicting / 'original.txt').read_bytes() == b'original\n'
    assert not (conflicting / 'child').exists()
    assert (destination / 'keep.txt').read_bytes() == b'keep\n'
    if nested:
        # Entries reached before the conflict are already applied, like cp -r.
        assert (destination / 'aaaa_first.txt').read_bytes() == b'first\n'


@pytest.mark.parametrize('nested', [False, True])
def test_copy_tree_directory_over_destination_directory_symlink_fails_without_side_effects(tmp_path, nested):
    source = tmp_path / 'source'
    write_file(source / 'child' / 'inner.txt', b'next\n')
    elsewhere = tmp_path / 'elsewhere'
    write_file(elsewhere / 'guarded.txt', b'guarded\n')
    destination = tmp_path / 'output' / 'source'
    destination.mkdir(parents=True)
    link = destination / 'child'
    link.symlink_to(elsewhere)

    source_path, destination_path = str(source / 'child'), str(link)
    if nested:
        source_path, destination_path = str(source), str(destination)
    with pytest.raises(RuntimeError):
        client.copy_tree(source_path, destination_path)

    assert link.is_symlink()
    assert os.readlink(link) == str(elsewhere)
    assert (elsewhere / 'guarded.txt').read_bytes() == b'guarded\n'
    assert not (elsewhere / 'inner.txt').exists()


@pytest.mark.parametrize('nested', [False, True])
def test_copy_tree_file_over_dangling_destination_symlink_fails_without_side_effects(tmp_path, nested):
    source = tmp_path / 'source'
    write_file(source / 'child', b'next\n')
    destination = tmp_path / 'output' / 'source'
    destination.mkdir(parents=True)
    link = destination / 'child'
    link.symlink_to('missing_target.txt')

    source_path, destination_path = str(source / 'child'), str(link)
    if nested:
        source_path, destination_path = str(source), str(destination)
    with pytest.raises(RuntimeError):
        client.copy_tree(source_path, destination_path)

    assert link.is_symlink()
    assert os.readlink(link) == 'missing_target.txt'
    assert not link.exists()
    # Neither the link path nor its dangling target text gained a file.
    assert not (destination / 'missing_target.txt').exists()


def test_translation_merge_retains_unrelated_entries_and_overwrites(workspace, server):
    existing = workspace / 'Translation' / 'English'
    existing.mkdir(parents=True)
    (existing / 'items.tsv').write_bytes(b'PREVIOUS\n')
    (existing / 'custom.txt').write_bytes(b'custom\n')

    assert client.main(['itos']) == 0

    assert (workspace / 'Translation/English/items.tsv').read_bytes() == b'harness_ore\tHarness Ore\n'
    assert (workspace / 'Translation/English/custom.txt').read_bytes() == b'custom\n'


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


# The three patch-skip rules and their application modes, pinned at their
# boundaries: IPF_BLACKLIST applies to the full path only, error_ipf fails
# both modes (the blocked-patch test above), and partial revision 147674 is
# skipped silently. The reason for skipping 147674 is recorded nowhere in
# the source, so these tests pin the behavior, never a reason.

def test_partial_revision_147674_is_skipped_silently(server):
    assert '147674' in client.PARTIAL_REVISION_BLACKLIST
    server.revision = encrypted_revisions('147674\r\n')
    # No download, no failure and no version advance: unchanged exit code.
    assert client.main(['itos']) == 1
    assert server.calls == ['data.revision.txt', 'release.revision.txt']
    assert client.read_version('revision.csv')['itos'] == '0'
    assert client.read_version('release.csv')['itos'] == '0'


def test_partial_revision_147674_skip_does_not_block_other_revisions(server):
    server.revision = encrypted_revisions('1\r\n147674\r\n2\r\n')
    old, new, changed = patch_data()
    assert server.calls == ['data.revision.txt', '1_001001.ipf', '2_001001.ipf']
    assert old['itos'] == '0'
    # The skipped revision must not advance the version cursor either.
    assert new['itos'] == '2'
    assert changed


def test_partial_revision_147674_skip_survives_repatch(server):
    server.revision = encrypted_revisions('147674\r\n')
    old, new, changed = client.patch_partial(
        '../itos_patch', 'https://fixture.invalid/partial/data/', '.ipf', False,
        'revision.csv', 'https://fixture.invalid/partial/data.revision.txt', 1)
    assert server.calls == ['data.revision.txt']
    assert new['itos'] == '0'
    assert not changed


def test_ipf_blacklist_skips_only_the_full_download(server, monkeypatch):
    server.revision = encrypted_revisions('1\r\n2\r\n')
    requested = []
    monkeypatch.setattr(client, 'patch_process',
                        lambda patch_file, patch_name, *args: requested.append(patch_name))
    # repatch=1 mirrors do_patch_full, so the blacklist is the only remaining
    # full-mode skip; the revision URL keeps the fixture-served suffix. Full
    # names are revision + patch_ext ('1.ipf', '2.ipf'), not the partial
    # '<rev>_001001.ipf' used by the test below.
    full = ('../itos_patch', 'https://fixture.invalid/full/data/', '.ipf', False,
            'https://fixture.invalid/full/data.revision.txt')
    client.patch_full(*full, 1)
    assert requested == ['1.ipf', '2.ipf']
    monkeypatch.setattr(client, 'IPF_BLACKLIST', ['1.ipf'])
    client.patch_full(*full, 1)
    assert requested == ['1.ipf', '2.ipf', '2.ipf']


def test_ipf_blacklist_does_not_block_partial_downloads(server, monkeypatch):
    # The blacklist is read only in patch_full: the same name still downloads
    # and advances the version in partial mode.
    monkeypatch.setattr(client, 'IPF_BLACKLIST', ['1_001001.ipf'])
    old, new, changed = patch_data()
    assert server.calls == ['data.revision.txt', '1_001001.ipf', '2_001001.ipf']
    assert old['itos'] == '0'
    assert new['itos'] == '2'
    assert changed


# Full mode (the optional 'full' CLI argument): _run checks 'full' before the
# partial branch, so do_patch_full runs alone and main returns EXIT_CHANGED.
# These regressions call do_patch_full and patch_full directly beyond the CLI
# and exercise the real processing path with encrypted CRLF revision
# responses built through the existing fixture seams.

def install_full_routes(server, revision_text='1\r\n2\r\n', patch_names=('1.ipf', '2.ipf')):
    # The shared LocalServer knows only the partial revision names and patch
    # routes. Its faults entries are answered before the named revision
    # routes, so the test supplies the encrypted CRLF full list there, and
    # each full patch name is routed to the same fixture archive bytes the
    # partial routes serve. server.calls keeps URL basenames such as
    # 'data.file.list.txt' and '1.ipf'.
    server.faults['data.file.list.txt'] = {'data': encrypted_revisions(revision_text)}
    for name in patch_names:
        server.routes[name] = server.routes['1_001001.ipf']


def test_do_patch_full_forwards_region_paths_and_repatch(workspace, monkeypatch):
    captured = []
    monkeypatch.setattr(client, 'patch_full', lambda *args: captured.append(args))
    # do_patch_full takes only the patch base URL: the patch directory is
    # derived from the region, and repatch is forwarded as literal True.
    client.do_patch_full('https://fixture.invalid/patch/')
    assert captured == [(os.path.join('..', 'itos_patch'),
                         'https://fixture.invalid/patch/full/data/',
                         '.ipf',
                         False,
                         'https://fixture.invalid/patch/full/data.file.list.txt',
                         True)]
    assert captured[0][5] is True


def test_full_mode_processes_encrypted_revisions_and_disposes_cache(workspace, server, extract_stub, monkeypatch):
    install_full_routes(server)
    extract_stub.install({'ies.ipf/item.ies': VALID_ITEM_CSV})

    def refuse_partial(*args, **kwargs):
        raise AssertionError('full mode must not run partial processing')
    monkeypatch.setattr(client, 'patch_partial', refuse_partial)

    assert client.main(['itos', 'full']) == client.EXIT_CHANGED == 0
    # The decrypted CRLF list is processed in server order under full patch
    # names (<revision>.ipf); no partial revision request ever appears.
    assert server.calls == ['data.file.list.txt', '1.ipf', '2.ipf']
    assert (workspace / 'itos_unpack/ies.ipf/item.ies').read_bytes() == VALID_ITEM_CSV.encode('utf-8')
    # Full processing never advances the version CSVs and never publishes
    # translations: the partial branch is unreachable in full mode.
    assert client.read_version('revision.csv') == {'itos': '0', 'ktos': '99'}
    assert client.read_version('release.csv') == {'itos': '0', 'ktos': '99'}
    assert not (workspace / 'Translation').exists()
    # Success disposes the cached archive, the working copy and the
    # temporary extraction.
    assert not (workspace / 'itos_patch/1.ipf').exists()
    assert not (workspace / 'itos_patch/2.ipf').exists()
    assert not Path('1.ipf').exists() and not Path('2.ipf').exists()
    assert not Path('extract').exists()
    assert not list((workspace / 'itos_patch').glob('*.part'))


def test_full_keeps_decrypted_list_order_and_lines_verbatim(server, monkeypatch):
    install_full_routes(server, revision_text='10\r\n2 001001\r\n', patch_names=())
    requested = []
    monkeypatch.setattr(client, 'patch_process',
                        lambda patch_file, patch_name, *args: requested.append(patch_name))
    client.patch_full('../itos_patch', 'https://fixture.invalid/full/data/', '.ipf', False,
                      'https://fixture.invalid/full/data.file.list.txt', 0)
    # Unlike patch_partial, the full path neither sorts by numeric revision
    # nor token-parses the lines: each decrypted line is used verbatim as
    # '<line>.ipf' in server order.
    assert requested == ['10.ipf', '2 001001.ipf']


def test_full_repatch_false_skips_existing_and_true_reprocesses(server, monkeypatch):
    install_full_routes(server)
    (Path('../itos_patch') / '1.ipf').write_bytes(b'cached bytes')
    requested = []
    monkeypatch.setattr(client, 'patch_process',
                        lambda patch_file, patch_name, *args: requested.append(patch_name))
    call = ('../itos_patch', 'https://fixture.invalid/full/data/', '.ipf', False,
            'https://fixture.invalid/full/data.file.list.txt')
    client.patch_full(*call, 0)
    # repatch=0 skips the existing path entirely: revision 1 is not processed.
    assert requested == ['2.ipf']
    requested.clear()
    client.patch_full(*call, 1)
    # repatch=1 reprocesses the already existing revision too.
    assert requested == ['1.ipf', '2.ipf']


def test_full_processing_failure_retains_cache_and_retry_reuses_it(workspace, server, extract_stub):
    install_full_routes(server)
    extract_stub.install({'ies.ipf/item.ies': DAMAGED_IES_FILES['short_row']})
    assert client.main(['itos', 'full']) == client.EXIT_FAILED == 2
    # The failed run keeps the downloaded cache for the retry and cleans only
    # its temporaries.
    cached = workspace / 'itos_patch/1.ipf'
    assert cached.read_bytes() == server.routes['1.ipf']
    assert client.read_version('revision.csv')['itos'] == '0'
    assert not Path('extract').exists()
    assert not Path('1.ipf').exists()
    assert not list((workspace / 'itos_patch').glob('*.part'))
    assert server.calls == ['data.file.list.txt', '1.ipf']
    # With the tool restored, the retained nonempty cache is reused instead
    # of downloaded again; processing then succeeds and disposes the cache.
    extract_stub.restore()
    assert client.main(['itos', 'full']) == client.EXIT_CHANGED == 0
    assert server.calls == ['data.file.list.txt', '1.ipf', 'data.file.list.txt', '2.ipf']
    assert not cached.exists()
    assert not (workspace / 'itos_patch/2.ipf').exists()


def test_full_revision_failure_fails_before_any_download(workspace, server):
    server.faults['data.file.list.txt'] = {'data': b'bad'}
    assert client.main(['itos', 'full']) == client.EXIT_FAILED == 2
    assert server.calls == ['data.file.list.txt']
    assert client.read_version('revision.csv')['itos'] == '0'


def test_full_mode_ipf_blacklist_skips_download_and_processing(workspace, server, monkeypatch):
    # With the full list and patch routes installed, the skipped name never
    # reaches a download or patch_process: the blacklist alone removes it from
    # patch_full's download condition while the other revision is fully
    # processed and its cache disposed.
    install_full_routes(server)
    monkeypatch.setattr(client, 'IPF_BLACKLIST', ['1.ipf'])
    assert client.main(['itos', 'full']) == client.EXIT_CHANGED == 0
    assert server.calls == ['data.file.list.txt', '2.ipf']
    assert not (workspace / 'itos_patch/1.ipf').exists()
    assert not (workspace / 'itos_patch/2.ipf').exists()
    assert client.read_version('revision.csv')['itos'] == '0'


def test_full_mode_error_ipf_fails_before_download(workspace, server, monkeypatch):
    # error_ipf blocks patch_process in both modes. With the full routes
    # installed the failure cannot come from an unmapped URL: patch_process
    # raises RuntimeError for the blocked name before any download, so only
    # the revision list is ever requested and versions stay untouched.
    install_full_routes(server)
    monkeypatch.setattr(client, 'error_ipf', ['1.ipf'])
    assert client.main(['itos', 'full']) == client.EXIT_FAILED == 2
    assert server.calls == ['data.file.list.txt']
    assert not (workspace / 'itos_patch/1.ipf').exists()
    assert client.read_version('revision.csv')['itos'] == '0'


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
