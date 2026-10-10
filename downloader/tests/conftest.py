"""All downloader checks use local fixtures, temporary paths, and blocked sockets."""
import io
from pathlib import Path
import socket
import sys
import urllib.error
import urllib.request

import pytest

from downloader import downloader as client

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
