"""EMotionFX XAC(액터) 파서 — ToS 캐릭터 모델용 최소 구현.

청크 레이아웃 근거: 3dparser/XAC2DAE_Source.zip(XACData.java), 3dparser/Blender249 스크립트,
그리고 실제 파일 덤프(ktos Cleric_m_costume01.xac: 7,11,13,3,5,1,2).
  7  metadata            11 node hierarchy(v1)   13 material totals
  3  standard material   5  FX material(v2)      1  mesh(v1)   2 skin(v3)
"""
import re
import struct

import numpy as np


class Node:
    __slots__ = ('name', 'parent', 'rot', 'pos', 'scale', 'transform')


class SubMesh:
    __slots__ = ('indices', 'vert_start', 'num_verts', 'material_id', 'bones')


class Mesh:
    def __init__(self):
        self.node_id = 0
        self.positions = None      # (N,3)
        self.normals = None        # (N,3)
        self.uvs = None            # (N,2)
        self.influence_range = None  # (N,) 원본 정점 → influence range index
        self.submeshes = []
        self.skin = None           # (weights (N,4), bone ids (N,4)) — 정점 기준으로 펼친 값


class Actor:
    def __init__(self):
        self.nodes = []
        self.meshes = []
        self.materials = []        # material id 순서: standard(3) 먼저, FX(5) 이어서
        self.node_index = {}


def _str(d, p):
    n = struct.unpack_from('<I', d, p)[0]
    return d[p + 4:p + 4 + n].decode('latin1'), p + 4 + n


def _parse_nodes(d, p):
    num_nodes, _num_roots = struct.unpack_from('<II', d, p)
    p += 8
    nodes = []
    for _ in range(num_nodes):
        n = Node()
        n.rot = np.array(struct.unpack_from('<4f', d, p), dtype=np.float64)          # x,y,z,w
        n.pos = np.array(struct.unpack_from('<3f', d, p + 32), dtype=np.float64)
        n.scale = np.array(struct.unpack_from('<3f', d, p + 44), dtype=np.float64)
        n.parent = struct.unpack_from('<i', d, p + 76)[0]
        n.transform = np.array(struct.unpack_from('<16f', d, p + 88), dtype=np.float64).reshape(4, 4)
        n.name, p = _str(d, p + 156)
        nodes.append(n)
    return nodes


def _parse_mesh(d, p, end):
    m = Mesh()
    (m.node_id, num_ranges, nverts, _nidx, nsub, nlayers) = struct.unpack_from('<6I', d, p)
    p += 28
    for _ in range(nlayers):
        ltype, size = struct.unpack_from('<II', d, p)
        p += 12
        raw = d[p:p + nverts * size]
        p += nverts * size
        if ltype == 0 and size == 12 and m.positions is None:
            m.positions = np.frombuffer(raw, '<f4').reshape(-1, 3).astype(np.float64)
        elif ltype == 1 and size == 12 and m.normals is None:
            m.normals = np.frombuffer(raw, '<f4').reshape(-1, 3).astype(np.float64)
        elif ltype == 3 and size == 8 and m.uvs is None:
            m.uvs = np.frombuffer(raw, '<f4').reshape(-1, 2).astype(np.float64)
        elif ltype == 5 and size == 4:
            m.influence_range = np.frombuffer(raw, '<u4').astype(np.int64)
    start = 0
    for _ in range(nsub):
        s = SubMesh()
        nidx, s.num_verts, s.material_id, nbones = struct.unpack_from('<4I', d, p)
        p += 16
        s.indices = np.frombuffer(d[p:p + 4 * nidx], '<u4').astype(np.int64) + start
        p += 4 * nidx
        s.bones = list(struct.unpack_from('<%dI' % nbones, d, p))
        p += 4 * nbones
        s.vert_start = start
        start += s.num_verts
        m.submeshes.append(s)
    m._num_ranges = num_ranges
    return m


def _parse_skin(d, p, actor):
    node_id, _local_bones, ninf = struct.unpack_from('<III', d, p)
    p += 16
    inf = np.frombuffer(d[p:p + 8 * ninf], dtype=[('w', '<f4'), ('b', '<u2'), ('pad', '<u2')])
    p += 8 * ninf
    mesh = next(m for m in actor.meshes if m.node_id == node_id and m.skin is None)
    ranges = np.frombuffer(d[p:p + 8 * mesh._num_ranges], '<u4').reshape(-1, 2)
    nverts = len(mesh.positions)
    weights = np.zeros((nverts, 4))
    bones = np.zeros((nverts, 4), dtype=np.int64)
    for v in range(nverts):
        first, count = ranges[mesh.influence_range[v]]
        sel = inf[first:first + count]
        order = np.argsort(-sel['w'])[:4]
        w = sel['w'][order]
        weights[v, :len(w)] = w / max(w.sum(), 1e-8)
        bones[v, :len(w)] = sel['b'][order]
    mesh.skin = (weights, bones)


def _parse_fx_material(d, p, end):
    """FX material 은 파라미터 스키마가 복잡해 텍스처 이름만 뽑는다."""
    body = d[p:end]
    tex = {}
    for m in re.finditer(rb'(DiffuseTex|MaskTex|NormalTex|SpecularTex)', body):
        q = m.end()
        if q + 4 <= len(body):
            n = struct.unpack_from('<I', body, q)[0]
            if 0 < n < 260:
                name = body[q + 4:q + 4 + n].decode('latin1', 'replace')
                if '.' in name:
                    tex.setdefault(m.group(1).decode(), name)
    return tex


def load(path_or_bytes):
    d = path_or_bytes if isinstance(path_or_bytes, bytes) else open(path_or_bytes, 'rb').read()
    if d[:4] != b'XAC ':
        raise ValueError('not an XAC file')
    actor = Actor()
    p = 8
    while p + 12 <= len(d):
        ctype, length, _ver = struct.unpack_from('<III', d, p)
        body, end = p + 12, p + 12 + length
        if ctype == 11:
            actor.nodes = _parse_nodes(d, body)
        elif ctype == 3:
            actor.materials.append({})
        elif ctype == 5:
            actor.materials.append(_parse_fx_material(d, body, end))
        elif ctype == 1:
            actor.meshes.append(_parse_mesh(d, body, end))
        elif ctype == 2:
            _parse_skin(d, body, actor)
        p = end
    actor.node_index = {n.name: i for i, n in enumerate(actor.nodes)}
    return actor
