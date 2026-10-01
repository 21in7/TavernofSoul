"""원격 IPF(패치 CDN)에서 필요한 파일만 HTTP Range 로 뽑아오는 유틸.

IPF 구조(IPFUnpacker/src/ipf_unpack/ipf.c 참고):
  - 파일 끝 24B: ArchiveHeader (fileCount u16 은 65535 초과 시 넘치므로 쓰지 않음)
  - filetableOffset ~ EOF-24: IpfInfo(20B) + archiveName + fileName 반복
  - 각 엔트리 데이터: 짝수 바이트만 XOR 하는 PKZIP 계열 스트림 암호 → raw deflate
"""
import binascii
import json
import os
import struct
import time
import urllib.request
import zlib

USER_AGENT = {"User-Agent": "tos"}
_PASSWORD = bytes([0x6F, 0x66, 0x4F, 0x31, 0x61, 0x30, 0x75, 0x65, 0x58, 0x41,
                   0x3F, 0x20, 0x5B, 0xFF, 0x73, 0x20, 0x68, 0x20, 0x25, 0x3F])
# IPFUnpacker 기준: 이 확장자들은 암호화/압축되어 있지 않다
_PLAIN_EXT = ('.mp3', '.fsb', '.jpg')


def _request(url, rng=None, method='GET', retries=5):
    headers = dict(USER_AGENT)
    if rng:
        headers['Range'] = rng
    last = None
    for i in range(retries):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, None, headers, method=method), timeout=120)
        except Exception as e:  # 네트워크 일시 오류 재시도(병렬 워커가 몰릴 때를 대비해 점점 길게 쉰다)
            last = e
            time.sleep(min(2 ** i, 20))
    raise last


def read_table(url):
    """원격 ipf 의 파일 테이블을 [(archive, name, crc, csize, usize, offset)] 로 반환."""
    size = int(_request(url, method='HEAD').headers['Content-Length'])
    header = _request(url, 'bytes=%d-%d' % (size - 24, size - 1)).read()
    _, table_off, _, _, magic, _, _ = struct.unpack('<HIHIIII', header)
    if magic != 0x06054B50:
        raise ValueError('bad ipf magic: %s' % url)
    raw = _request(url, 'bytes=%d-%d' % (table_off, size - 25)).read()
    entries, p = [], 0
    while p + 20 <= len(raw):
        name_len, crc, csize, usize, offset, arch_len = struct.unpack_from('<HIIIIH', raw, p)
        p += 20
        archive = raw[p:p + arch_len].decode('latin1')
        p += arch_len
        name = raw[p:p + name_len].decode('latin1')
        p += name_len
        entries.append((archive, name, crc, csize, usize, offset))
    return entries


def _crc_update(crc, b):
    return binascii.crc32(bytes([b]), crc ^ 0xFFFFFFFF) ^ 0xFFFFFFFF


def _keys_update(keys, b):
    keys[0] = _crc_update(keys[0], b)
    keys[1] = (0x8088405 * ((keys[0] & 0xFF) + keys[1]) + 1) & 0xFFFFFFFF
    keys[2] = _crc_update(keys[2], (keys[1] >> 24) & 0xFF)


def decrypt(data):
    keys = [0x12345678, 0x23456789, 0x34567890]
    for b in _PASSWORD:
        _keys_update(keys, b)
    buf = bytearray(data)
    for i in range(0, len(buf), 2):
        v = (keys[2] & 0xFFFD) | 2
        buf[i] ^= ((v * (v ^ 1)) >> 8) & 0xFF
        _keys_update(keys, buf[i])
    return bytes(buf)


def fetch_entry(url, entry):
    """테이블 엔트리 하나를 받아 복호화·해제 후 CRC 까지 검증해 bytes 로 반환."""
    _, name, crc, csize, usize, offset = entry
    data = _request(url, 'bytes=%d-%d' % (offset, offset + csize - 1)).read()
    if name.lower().endswith(_PLAIN_EXT):
        return data
    data = zlib.decompress(decrypt(data), -15)
    if len(data) != usize or (binascii.crc32(data) & 0xFFFFFFFF) != crc:
        raise ValueError('crc/size mismatch: %s' % name)
    return data


class AssetIndex:
    """full + partial 테이블을 합친 인덱스. 같은 경로는 나중 리비전이 이긴다.

    index 파일 포맷: {"archive/name(lower)": [url, archive, name, crc, csize, usize, offset]}
    """

    def __init__(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            self.items = json.load(f)

    def find(self, pattern):
        import re
        rx = re.compile(pattern, re.I)
        return sorted(k for k in self.items if rx.search(k))

    def get(self, key, cache_dir):
        url, archive, name, crc, csize, usize, offset = self.items[key.lower()]
        local = os.path.join(cache_dir, archive, name)
        if os.path.exists(local) and os.path.getsize(local) == usize:
            with open(local, 'rb') as f:
                return f.read()
        data = fetch_entry(url, (archive, name, crc, csize, usize, offset))
        os.makedirs(os.path.dirname(local), exist_ok=True)
        # 병렬 렌더 워커가 같은 파일을 동시에 받을 수 있어 임시 파일에 쓰고 교체한다
        tmp = '%s.%d.tmp' % (local, os.getpid())
        with open(tmp, 'wb') as f:
            f.write(data)
        try:
            os.replace(tmp, local)
        except PermissionError:
            # 윈도우: 다른 워커가 같은 파일을 이미 써서 읽는 중이면 교체가 막힌다 → 그쪽 파일을 쓴다
            os.remove(tmp)
        return data


def build_index(full_tables, partial_tables, out_path):
    """full_tables: {ipf_basename: (url, entries)}, partial_tables: [(url, entries)] (리비전 오름차순)."""
    items = {}
    for ipf, (url, entries) in full_tables.items():
        for archive, name, crc, csize, usize, offset in entries:
            archive = archive or ipf + '.ipf'
            items[(archive + '/' + name).lower()] = [url, archive, name, crc, csize, usize, offset]
    for url, entries in partial_tables:
        for archive, name, crc, csize, usize, offset in entries:
            items[(archive + '/' + name).lower()] = [url, archive, name, crc, csize, usize, offset]
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(items, f)
    return items
