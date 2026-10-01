"""Fork Particle .psb (ToS effect.ipf/forkparticle/psb) 근사 파서.

공개 포맷 문서가 없어 샘플 561개(레코드 3,745개) 통계와 레코드 간 비교로 추정한 레이아웃이다.
**확실한 것**: 64B 헤더('PSB\\0', ver 100, dataLen, 64, 16) + 가변 길이 이미터 레코드 체인
(레코드 크기 @+0x100), 이름 @+0, 텍스처 이름 @(size-284), 이미터 로컬 4x4 행렬 @+0x2b8(행 우선, 이동 @+0x2e8).
**추정(근사)**: 색·알파 키, 크기 키, 수명, 발생량, 속도, 퍼짐 각도, 파티클 범위(bbox).
"""
import re
import struct

import numpy as np

HEADER = 64


class Emitter:
    def __init__(self):
        self.name = ''
        self.texture = ''
        self.local = np.eye(4)
        self.color_keys = []      # [(t, (r, g, b, a))]
        self.size_keys = []       # [(t, size)]
        self.life = 1.0
        self.rate = 1.0
        self.speed = 0.0
        self.spread_deg = 0.0
        self.gravity = 0.0
        self.bbox = None          # (min xyz, max xyz) 또는 None
        self.additive = True
        self.flat = False         # 바닥에 눕는 판(@0x178 bit 0x40, 'badak*' 이미터에서 확인)
        self.raw = b''


def _f(rec, off):
    return struct.unpack_from('<f', rec, off)[0]


def _vec(rec, off, n):
    return np.array(struct.unpack_from('<%df' % n, rec, off), dtype=np.float64)


def _clean(x, lo, hi, default):
    return x if np.isfinite(x) and lo <= x <= hi else default


def parse_record(rec):
    size = len(rec)
    e = Emitter()
    e.raw = rec
    e.name = rec[:64].split(b'\0')[0].decode('latin1')
    tex = rec[size - 284:size - 24].split(b'\0')[0].decode('latin1')
    if not re.search(r'\.(tga|dds|png)$', tex, re.I):
        # 일부 가변 레코드는 텍스처 칸이 비어 있다 → 레코드 안 마지막 이미지 파일명
        names = re.findall(rb'[\w\-. ]+\.(?:tga|dds|png)', rec, re.I)
        tex = names[-1].decode('latin1') if names else ''
    e.texture = re.split(r'[\\/]', tex)[-1]
    # 로컬 변환(행 우선 저장 → 열벡터 규약으로 전치)
    m = _vec(rec, 0x2b8, 16).reshape(4, 4).T
    if np.isfinite(m).all() and abs(m[3, 3] - 1) < 1e-3:
        e.local = m

    # 색 키: RGB+A 4개 슬롯(@0x120/0x130/0x140/0x150), 중간 키 시각 @0x160, @0x164
    t1 = _clean(_f(rec, 0x160), 0.0, 1.0, 0.3)
    t2 = _clean(_f(rec, 0x164), t1, 1.0, 0.6)
    slots = [_vec(rec, 0x120 + 16 * i, 4) for i in range(4)]
    times = [0.0, t1, t2, 1.0]
    used = 4 if np.abs(slots[3]).sum() > 0 else 3
    if used == 3:
        times = [0.0, t1, 1.0]
    for t, s in zip(times, slots[:used]):
        rgb = np.clip(np.nan_to_num(s[:3]), 0, 1)
        a = float(np.clip(np.nan_to_num(s[3]), 0, 1))
        e.color_keys.append((t, (rgb[0], rgb[1], rgb[2], a)))
    # 전부 투명으로 읽히면 알파 필드 해석이 틀린 레코드 — 부드러운 페이드로 대체
    if max(k[1][3] for k in e.color_keys) < 0.05:
        e.color_keys = [(t, (r, g, b, a)) for (t, (r, g, b, _)), a in zip(e.color_keys, [0.0, 1.0, 0.6, 0.0])]

    # 크기 키 @0x17c/0x180/0x184, 중간 시각 @0x168
    tm = _clean(_f(rec, 0x168), 0.05, 0.95, 0.5)
    sizes = [_clean(_f(rec, o), 0.0, 2000.0, 10.0) for o in (0x17c, 0x180, 0x184)]
    e.size_keys = [(0.0, sizes[0]), (tm, sizes[1]), (1.0, sizes[2])]

    e.life = _clean(_f(rec, 0x1e4), 0.05, 30.0, 1.0)
    e.rate = _clean(_f(rec, 0x1f4), 0.5, 1000.0, 4.0)
    e.speed = _clean(_f(rec, 0x1dc), 0.0, 5000.0, 0.0)
    e.spread_deg = _clean(_f(rec, 0x1a8), -360.0, 360.0, 0.0)
    e.gravity = _clean(_f(rec, 0x170), -1000.0, 1000.0, 0.0)
    lo, hi = _vec(rec, 0x1fc, 3), _vec(rec, 0x208, 3)
    if np.isfinite(lo).all() and np.isfinite(hi).all() and (hi > lo).all() and (hi - lo).max() < 5e4:
        e.bbox = (lo, hi)
    # '_alpha' 텍스처도 RGB 가 알파 마스크와 같은 밝은 그림이라 가산 합성이 원래 의도에 가깝다
    e.additive = True
    e.flat = bool(struct.unpack_from('<I', rec, 0x178)[0] & 0x40)
    return e


def load(data):
    if data[:4] != b'PSB\0':
        raise ValueError('not a PSB file')
    emitters, off = [], HEADER
    while off + 0x104 <= len(data):
        size = struct.unpack_from('<I', data, off + 0x100)[0]
        if size < 0x4b8 or off + size > len(data):
            break
        emitters.append(parse_record(data[off:off + size]))
        off += size
    return emitters


def interp_keys(keys, u):
    """keys [(t, value)] 선형 보간. value 는 스칼라 또는 튜플."""
    if u <= keys[0][0]:
        return np.asarray(keys[0][1], dtype=np.float64)
    for (ta, va), (tb, vb) in zip(keys, keys[1:]):
        if u <= tb:
            w = (u - ta) / max(tb - ta, 1e-6)
            return np.asarray(va, dtype=np.float64) * (1 - w) + np.asarray(vb, dtype=np.float64) * w
    return np.asarray(keys[-1][1], dtype=np.float64)
