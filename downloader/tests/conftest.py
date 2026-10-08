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
