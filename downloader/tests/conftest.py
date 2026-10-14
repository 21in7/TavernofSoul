"""All downloader checks use local fixtures, temporary paths, and blocked sockets."""
import io
from pathlib import Path
import socket
import sys
import urllib.error
import urllib.request
import zlib

import pytest

from downloader import downloader as client
from downloader import unpacker_pak

FIXTURES = Path(__file__).resolve().parents[2] / 'harness' / 'fixtures' / 'downloader'


class LocalResponse(io.BytesIO):
    def __init__(self, data, length=None, fail_after=None):
        super().__init__(data)
        self.headers = {'Content-Length': str(len(data) if length is None else length)}
        self.fail_after = fail_after

    def read(self, size=-1):
        if self.fail_after is not None:
            if self.tell() >= self.fail_after:
                raise urllib.error.URLError('simulated interrupted transfer')
            size = min(size, self.fail_after - self.tell()) if size >= 0 else self.fail_after - self.tell()
        return super().read(size)


class LocalServer:
    def __init__(self):
        self.revision = (FIXTURES / 'revisions.bin').read_bytes()
        self.routes = {
            '1_001001.ipf': (FIXTURES / 'ipf_patch.json').read_bytes(),
            '2_001001.ipf': (FIXTURES / 'ipf_patch.json').read_bytes(),
            '1_001001.pak': (FIXTURES / 'release.pak').read_bytes(),
            '2_001001.pak': (FIXTURES / 'release.pak').read_bytes(),
        }
        self.calls = []
        self.faults = {}

    def urlopen(self, request, timeout=None):
        url = request.full_url if isinstance(request, urllib.request.Request) else request
        name = url.rsplit('/', 1)[-1]
        self.calls.append(name)
        if name in self.faults:
            fault = self.faults[name]
            if isinstance(fault, Exception):
                raise fault
            return LocalResponse(**fault)
        if name in ('data.revision.txt', 'release.revision.txt'):
            return LocalResponse(self.revision)
        if name not in self.routes:
            raise AssertionError('Unmapped URL: ' + url)
        return LocalResponse(self.routes[name])


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Downloader tests must not connect to a network')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setattr(urllib.request, 'urlopen', blocked)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    working = tmp_path / 'downloader'
    working.mkdir()
    (tmp_path / 'itos_patch').mkdir()
    (tmp_path / 'itos_unpack').mkdir()
    tool = tmp_path / 'IPFUnpacker' / 'ipf_unpack'
    tool.parent.mkdir()
    tool.write_text('#!' + sys.executable + '\n' +
                    (FIXTURES / 'ipf_unpack_stub.py').read_text(), encoding='utf-8')
    tool.chmod(0o755)
    monkeypatch.chdir(working)
    monkeypatch.setattr(client, 'region', 'itos')
    client.print_version('revision.csv', {'itos': '0', 'ktos': '99'})
    client.print_version('release.csv', {'itos': '0', 'ktos': '99'})
    return tmp_path


@pytest.fixture
def server(workspace, monkeypatch):
    local = LocalServer()
    monkeypatch.setattr(urllib.request, 'urlopen', local.urlopen)
    return local


SYNTHETIC_EXTRACT_STUB = '''import os, sys
FILES = {files}
if sys.argv[2] == 'decrypt':
    raise SystemExit(0)
if sys.argv[2] != 'extract':
    raise SystemExit('unexpected stub invocation: ' + repr(sys.argv))
for name, content in FILES.items():
    path = os.path.join('extract', name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(content)
'''


class SyntheticExtractStub:
    """Same stub-tool subprocess flow, with the extract output chosen per test."""

    def __init__(self, tool):
        self.tool = tool
        self.original = tool.read_text(encoding='utf-8')

    def install(self, files):
        body = SYNTHETIC_EXTRACT_STUB.format(files=repr(files))
        self.tool.write_text('#!' + sys.executable + '\n' + body, encoding='utf-8')
        self.tool.chmod(0o755)

    def restore(self):
        self.tool.write_text(self.original, encoding='utf-8')
        self.tool.chmod(0o755)


@pytest.fixture
def extract_stub(workspace):
    # Each test gets its own workspace tool copy, so swapping the script
    # never leaks into other tests.
    return SyntheticExtractStub(workspace / 'IPFUnpacker' / 'ipf_unpack')


# Test-only IO guards for the streaming PAK unpacker: they let tests prove the
# bounded-memory contract from the outside. Every guarded archive read() must
# ask for a positive size no larger than a fixed cap (never an unbounded
# read-all), the guarded inflate must always receive a positive bounded
# max_length and may return no more bytes than that, and decompressor.flush()
# (whose output is unbounded) must never be called. short_reads lets a test
# answer every read with fewer bytes than requested, so the exact-read loops
# must keep looping. unpack() opens the archive and its decompressor through
# the module seams patched below; monkeypatch restores both at teardown and no
# production behavior changes.
IO_GUARD_MAX_READ = 65536
IO_GUARD_MAX_INFLATE = 1 << 20


class GuardedSource:
    """File wrapper asserting positive, bounded read(size) requests."""

    def __init__(self, file, short_reads=False):
        self._file = file
        self._short_reads = short_reads

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return self._file.__exit__(*exc_info)

    def fileno(self):
        return self._file.fileno()

    def seek(self, *args):
        return self._file.seek(*args)

    def read(self, size):
        assert 0 < size <= IO_GUARD_MAX_READ, size
        if self._short_reads:
            size = max(1, size // 2)
        return self._file.read(size)


class GuardedDecompressor:
    """Real decompressobj wrapper asserting bounded inflate calls and output."""

    def __init__(self, decompressor):
        self._decompressor = decompressor

    @property
    def eof(self):
        return self._decompressor.eof

    @property
    def unconsumed_tail(self):
        return self._decompressor.unconsumed_tail

    def decompress(self, data, max_length):
        assert 0 < max_length <= IO_GUARD_MAX_INFLATE, max_length
        piece = self._decompressor.decompress(data, max_length)
        assert len(piece) <= max_length, len(piece)
        return piece

    def flush(self):
        raise AssertionError('unbounded decompressor.flush() must not be called')


class PakIoGuard:
    """Guards unpacker_pak.unpack()'s archive reads and its decompressor for
    one test. Write-mode handles (the .part destination) pass through as-is."""

    def __init__(self):
        self.short_reads = False
        self._real_decompressobj = zlib.decompressobj

    def open(self, file, mode, *args, **kwargs):
        handle = open(file, mode, *args, **kwargs)
        if mode == 'rb':
            return GuardedSource(handle, self.short_reads)
        return handle

    def decompressobj(self, *args, **kwargs):
        return GuardedDecompressor(self._real_decompressobj(*args, **kwargs))


@pytest.fixture
def pak_io_guard(monkeypatch):
    guard = PakIoGuard()
    # 'open' only exists as a builtin fallback, never as a module attribute,
    # so it is added with raising=False and deleted again at teardown. The
    # patched zlib attribute is restored to the real decompressobj.
    monkeypatch.setattr(unpacker_pak, 'open', guard.open, raising=False)
    monkeypatch.setattr(unpacker_pak.zlib, 'decompressobj', guard.decompressobj)
    return guard
