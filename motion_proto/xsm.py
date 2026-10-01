"""EMotionFX XSM(스켈레탈 모션) 파서.

실제 파일(ktos cleric_m_mns_skl_blessing.xsm) 덤프 기준 레이아웃:
  'XSM ' + ver(4B)
  chunk 201 metadata
  chunk 202 v2: numSubMotions(u32) + SubMotion 반복
    SubMotion:
      +0   poseRot     int16*4 (압축 쿼터니언, /32767)
      +8   bindRot     int16*4
      +16  poseScaleRot int16*4
      +24  bindScaleRot int16*4
      +32  posePos f3, +44 poseScale f3, +56 bindPos f3, +68 bindScale f3
      +80  numPosKeys, numRotKeys, numScaleKeys, numScaleRotKeys (u32*4)
      +96  maxError f4
      +100 name(u32 len + bytes)
      keys: pos(f3+time) / rot(int16*4+time) / scale(f3+time) / scaleRot(int16*4+time)
"""
import struct

import numpy as np


class Track:
    __slots__ = ('name', 'pose_rot', 'pose_pos', 'pose_scale', 'pos_times', 'pos_keys',
                 'rot_times', 'rot_keys', 'scale_times', 'scale_keys')


def _quat16(vals):
    q = np.asarray(vals, dtype=np.float64).reshape(-1, 4) / 32767.0
    return q / np.linalg.norm(q, axis=1, keepdims=True).clip(1e-8)


def _scale(v):
    """무기를 숨기는 0 스케일이 일부 모션(엑소시스트 계열 7개)에는 NaN 으로 들어 있다 — 0 으로 본다."""
    return np.nan_to_num(v, nan=0.0, posinf=0.0, neginf=0.0)


def load(path_or_bytes):
    d = path_or_bytes if isinstance(path_or_bytes, bytes) else open(path_or_bytes, 'rb').read()
    if d[:4] != b'XSM ':
        raise ValueError('not an XSM file')
    tracks = {}
    p = 8
    while p + 12 <= len(d):
        ctype, length, _ver = struct.unpack_from('<III', d, p)
        q, end = p + 12, p + 12 + length
        if ctype == 202:
            count = struct.unpack_from('<I', d, q)[0]
            q += 4
            for _ in range(count):
                t = Track()
                t.pose_rot = _quat16(struct.unpack_from('<4h', d, q))[0]
                t.pose_pos = np.array(struct.unpack_from('<3f', d, q + 32))
                t.pose_scale = _scale(np.array(struct.unpack_from('<3f', d, q + 44)))
                npos, nrot, nscale, nsrot = struct.unpack_from('<4I', d, q + 80)
                n = struct.unpack_from('<I', d, q + 100)[0]
                t.name = d[q + 104:q + 104 + n].decode('latin1')
                q += 104 + n
                pk = np.frombuffer(d[q:q + 16 * npos], '<f4').reshape(-1, 4).astype(np.float64)
                q += 16 * npos
                rk = np.frombuffer(d[q:q + 12 * nrot], dtype=[('q', '<i2', 4), ('t', '<f4')])
                q += 12 * nrot
                sk = np.frombuffer(d[q:q + 16 * nscale], '<f4').reshape(-1, 4).astype(np.float64)
                q += 16 * nscale + 12 * nsrot
                t.scale_times, t.scale_keys = sk[:, 3], _scale(sk[:, :3])
                t.pos_times, t.pos_keys = pk[:, 3], pk[:, :3]
                t.rot_times = rk['t'].astype(np.float64)
                t.rot_keys = _quat16(rk['q']) if nrot else np.zeros((0, 4))
                tracks[t.name] = t
        p = end
    duration = max([t.pos_times[-1] for t in tracks.values() if len(t.pos_times)] +
                   [t.rot_times[-1] for t in tracks.values() if len(t.rot_times)] + [0.0])
    return tracks, duration


def _slerp(a, b, u):
    dot = np.dot(a, b)
    if dot < 0:
        b, dot = -b, -dot
    if dot > 0.9995:
        r = a + u * (b - a)
        return r / np.linalg.norm(r)
    th = np.arccos(dot)
    return (np.sin((1 - u) * th) * a + np.sin(u * th) * b) / np.sin(th)


def sample(track, time):
    """시각 time 의 (pos, rot, scale) — 키가 없으면 pose 값."""
    def interp(times, keys, lerp):
        if len(times) == 0:
            return None
        if time <= times[0]:
            return keys[0]
        if time >= times[-1]:
            return keys[-1]
        i = int(np.searchsorted(times, time)) - 1
        u = (time - times[i]) / max(times[i + 1] - times[i], 1e-8)
        return lerp(keys[i], keys[i + 1], u)

    lerp = lambda a, b, u: a + (b - a) * u  # noqa: E731
    pos = interp(track.pos_times, track.pos_keys, lerp)
    rot = interp(track.rot_times, track.rot_keys, _slerp)
    scale = interp(track.scale_times, track.scale_keys, lerp)
    return ((track.pose_pos if pos is None else pos),
            (track.pose_rot if rot is None else rot),
            (track.pose_scale if scale is None else scale))
