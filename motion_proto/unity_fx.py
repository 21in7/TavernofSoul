"""IMC Unity 이펙트(effect.ipf/unityeffect.xml → assets.ipf/<guid>.pb) 로더 + 파티클 시뮬레이션.

.pb 는 Unity 씬 그래프(GameObject/Transform/ParticleSystem/ParticleSystemRenderer/Material/Mesh)를
IMC 가 protobuf 로 직렬화한 것이다. 스키마는 없지만 필드 번호가 Unity 직렬화 순서를 따르므로
Tackle_Normal_White_01 / BodyAura_AngelFeather_Blue_01 덤프의 값으로 역추적했다.

  ParticleSystem.2 main   : 1 duration, 3 looping, 8 startDelay, 9 startLifetime, 10 startSpeed,
                            11.1 startSize, 12.3 startRotation, 13 startColor(1 mode, 3 gradient, 5 rgba), 18 maxParticles
  ParticleSystem.3 emission: 1 rateOverTime, 3 burst(1 time, 2 count, 3 cycles, 4 interval)
  ParticleSystem.4 shape  : 1 type(0 sphere, 2 hemisphere, 4 cone, 5 box, 10 circle, 12 edge), 2.1 angle, 2.2 radius
  ParticleSystem.7 colorOverLifetime: 3 gradient(1 colorKey{1 rgba, 2 t}, 2 alphaKey{1 a, 2 t})
  ParticleSystem.8 sizeOverLifetime : 1 curve(3 key{1 t, 2 v}, 6 multiplier)
  ParticleSystem.11 textureSheetAnimation: 4 tilesX, 5 tilesY
  MinMaxCurve: 1 mode(0 상수, 3 두 상수 사이 랜덤, 1/2 곡선), 4 min, 5 max(상수), 6 multiplier
  Renderer : 2 renderMode(0 billboard, 1 stretch, 2 horizontal, 3 vertical, 4 mesh), 21 mesh GUID, 22 material GUID
  Transform: 1 gameObject, 2 localRotation(xyzw), 3 localPosition, 4 localScale, 5 parent
  Material : 1 shader, 4 color{1 name, 2 rgba}, 5 texture{1 name, 2 {1 guid}}
  Mesh     : 1 vertexCount, 3 indices(packed varint), 4 positions(f32*3), 7 uv(f32*2)

프로토버프에서 기본값(0)인 필드는 생략된다는 점에 주의(예: 알파 키 시각 0 → 필드 없음).
동작 규칙(발생·수명·크기·색 변화)은 Unity 파티클 시스템 공개 동작을 따른 재현이며,
IMC 전용 셰이더(왜곡·디졸브 등)와 곡선 탄젠트, 서브 이미터, 충돌, 노이즈는 반영하지 않는다.
"""
import io
import re
import struct
from collections import defaultdict

import numpy as np
from PIL import Image

import pose

UNIT = 10.0            # Unity 단위 → 모델 단위(캐릭터 키 ~62). 시각 보정값
MAX_PARTICLES = 150    # 시스템당 프레임 최대 파티클
MAX_MESH_PARTICLES = 24


def _varint(b, p):
    result = shift = 0
    while True:
        c = b[p]
        p += 1
        result |= (c & 0x7F) << shift
        shift += 7
        if c < 0x80:
            return result, p


def _parse(b):
    p, out = 0, []
    while p < len(b):
        key, p = _varint(b, p)
        field, wire = key >> 3, key & 7
        if field == 0 or wire not in (0, 1, 2, 5):
            raise ValueError('not protobuf')
        if wire == 0:
            v, p = _varint(b, p)
        elif wire == 1:
            v, p = b[p:p + 8], p + 8
        elif wire == 5:
            v, p = b[p:p + 4], p + 4
        else:
            n, p = _varint(b, p)
            if p + n > len(b):
                raise ValueError('truncated')
            v, p = b[p:p + n], p + n
        out.append((field, wire, v))
    return out


class Msg:
    def __init__(self, data=b''):
        self.fields = defaultdict(list)
        try:
            for field, wire, v in _parse(data):
                self.fields[field].append((wire, v))
        except (ValueError, IndexError):
            self.fields.clear()

    def msgs(self, n):
        return [Msg(v) for w, v in self.fields.get(n, []) if w == 2]

    def msg(self, n):
        items = self.msgs(n)
        return items[0] if items else None

    def f32(self, n, default=0.0):
        for w, v in self.fields.get(n, []):
            if w == 5:
                return struct.unpack('<f', v)[0]
        return default

    def int(self, n, default=0):
        for w, v in self.fields.get(n, []):
            if w == 0:
                return v
        return default

    def raw(self, n):
        for w, v in self.fields.get(n, []):
            if w == 2:
                return v
        return b''

    def str(self, n, default=''):
        raw = self.raw(n)
        try:
            return raw.decode('utf-8') if raw else default
        except UnicodeDecodeError:
            return default


def _minmax(m, rng, n):
    if m is None:
        return np.zeros(n)
    mode, lo, hi, mul = m.int(1), m.f32(4), m.f32(5), m.f32(6, 1.0)
    if mode == 3:
        return lo + (hi - lo) * rng.random(n)
    if mode in (1, 2):
        return np.full(n, mul)          # 곡선 모드: 곡선 대신 multiplier 로 근사
    return np.full(n, hi)


def _gradient(m):
    if m is None:
        return None
    colors = sorted((k.f32(2), [k.msg(1).f32(i) if k.msg(1) else 0.0 for i in (1, 2, 3)]) for k in m.msgs(1))
    alphas = sorted((k.f32(2), k.f32(1)) for k in m.msgs(2))
    if not colors and not alphas:
        return None
    return colors or [(0.0, [1.0, 1.0, 1.0])], alphas or [(0.0, 1.0)]


def _eval_gradient(g, u):
    colors, alphas = g
    ct = np.array([c[0] for c in colors])
    cv = np.array([c[1] for c in colors])
    rgb = np.stack([np.interp(u, ct, cv[:, i]) for i in range(3)], axis=-1)
    a = np.interp(u, [a[0] for a in alphas], [a[1] for a in alphas])
    return np.concatenate([rgb, a[:, None]], axis=-1)


def _curve(m):
    """AnimationCurve 키 [(t, v)] 와 multiplier. 탄젠트는 무시하고 선형 보간."""
    if m is None:
        return None
    keys = sorted((k.f32(1), k.f32(2)) for k in m.msgs(3))
    if not keys:
        return None
    return keys, m.f32(6, 1.0)


def _eval_curve(c, u):
    keys, mul = c
    return np.interp(u, [k[0] for k in keys], [k[1] for k in keys]) * mul


class UnitySystem:
    def __init__(self):
        self.name = ''
        self.matrix = np.eye(4)
        self.texture = None
        self.additive = True
        self.tint = np.ones(4, dtype=np.float32)
        self.render_mode = 0
        self.mesh = None
        self.tiles = (1, 1)
        self._births = {}

    # ----- 생성 규칙 -----
    def births(self, t_end):
        key = round(float(t_end), 3)
        if key in self._births:
            return self._births[key]
        emit_until = t_end if self.looping else min(t_end, self.delay + self.duration)
        out = []
        if self.rate > 0 and emit_until > self.delay:
            out.append(self.delay + np.arange(0.0, emit_until - self.delay, 1.0 / self.rate))
        period = self.duration if self.looping and self.duration > 0 else 1e9
        for when, count, cycles, interval in self.bursts:
            first = self.delay + when
            repeats = int(np.floor((emit_until - first) / period)) + 1 if self.looping else 1
            for r in range(max(repeats, 1)):
                for c in range(max(cycles, 1)):
                    at = first + r * period + c * interval
                    if at <= emit_until and count >= 1:
                        out.append(np.full(int(round(count)), at))
        births = np.sort(np.concatenate(out))[:4000] if out else np.zeros(0)
        self._births[key] = births
        return births

    def _shape(self, rng, n):
        d = rng.normal(size=(n, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True).clip(1e-6)
        if not self.has_shape:
            return np.zeros((n, 3)), np.tile([0.0, 0.0, 1.0], (n, 1))
        t, radius, angle = self.shape_type, self.radius, np.radians(self.angle)
        if t in (4, 7):   # cone: 밑면 원 위 점, +Z 축에서 각도만큼 퍼짐
            r = radius * np.sqrt(rng.random(n))
            phi = rng.random(n) * 2 * np.pi
            pos = np.stack([r * np.cos(phi), r * np.sin(phi), np.zeros(n)], axis=1)
            spread = (r / max(radius, 1e-6)) * np.tan(angle) if radius > 0 else rng.random(n) * np.tan(angle)
            dirs = np.stack([np.cos(phi) * spread, np.sin(phi) * spread, np.ones(n)], axis=1)
            dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
            return pos, dirs
        if t == 10:       # circle (XY 평면)
            phi = rng.random(n) * 2 * np.pi
            r = radius * np.sqrt(rng.random(n))
            ring = np.stack([np.cos(phi), np.sin(phi), np.zeros(n)], axis=1)
            return ring * r[:, None], ring
        if t == 12:       # edge
            return np.stack([(rng.random(n) * 2 - 1) * radius, np.zeros(n), np.zeros(n)], axis=1), \
                np.tile([0.0, 1.0, 0.0], (n, 1))
        if t == 5:        # box
            return rng.random((n, 3)) - 0.5, np.tile([0.0, 0.0, 1.0], (n, 1))
        if t == 2:        # hemisphere
            d[:, 2] = np.abs(d[:, 2])
        return d * radius * np.cbrt(rng.random(n))[:, None], d

    def _start_colors(self, rng, n):
        if self.start_color_mode in (1, 4) and self.start_gradient is not None:
            u = rng.random(n) if self.start_color_mode == 4 else np.zeros(n)
            return _eval_gradient(self.start_gradient, u)
        return np.tile(self.start_color, (n, 1))

    def particles(self, t, t_end, seed):
        births = self.births(t_end)
        n = len(births)
        if n == 0:
            return None
        rng = np.random.default_rng(seed)
        life = np.maximum(_minmax(self.lifetime, rng, n), 1e-3)
        speed = _minmax(self.speed, rng, n)
        size = _minmax(self.size, rng, n)
        pos0, dir0 = self._shape(rng, n)
        col0 = self._start_colors(rng, n)
        age = t - births
        idx = np.nonzero((age >= 0) & (age < life))[0][-self.max_particles:][-MAX_PARTICLES:]
        if len(idx) == 0:
            return None
        u = age[idx] / life[idx]
        local = pos0[idx] + dir0[idx] * (speed[idx] * age[idx])[:, None]
        pos = local @ self.matrix[:3, :3].T + self.matrix[:3, 3]
        size = size[idx] * self.scale_factor
        if self.size_curve is not None:
            size = size * np.clip(_eval_curve(self.size_curve, u), 0, None)
        color = col0[idx]
        if self.color_over_life is not None:
            color = color * _eval_gradient(self.color_over_life, u)
        color = np.clip(color * self.tint, 0, 1)
        tx, ty = self.tiles
        frame = np.minimum((u * tx * ty).astype(int), tx * ty - 1)
        return pos, size, color, frame

    def frame_texture(self, frame):
        tx, ty = self.tiles
        if tx * ty <= 1:
            return self.texture
        h, w = self.texture.shape[:2]
        fw, fh = w // tx, h // ty
        col, row = frame % tx, frame // tx
        return self.texture[row * fh:(row + 1) * fh, col * fw:(col + 1) * fw]


class UnityEffect:
    def __init__(self, data, load_asset):
        records = [r for r in Msg(data).msgs(1)]
        gameobjects, transforms, systems, renderers = {}, {}, {}, {}
        for rec in records:
            file_id = rec.int(1)
            comp = rec.msg(2)
            if comp is None:
                continue
            kind, payload = comp.str(1), comp.msg(2) or Msg()
            if kind == 'imc.protobuf.GameObject':
                gameobjects[file_id] = payload.str(1)
            elif kind == 'imc.protobuf.Transform':
                transforms[file_id] = payload
            elif kind == 'imc.protobuf.ParticleSystem':
                systems[payload.int(1)] = payload
            elif kind == 'imc.protobuf.ParticleSystemRenderer':
                renderers[payload.int(1)] = payload
        by_go = {t.int(1): (fid, t) for fid, t in transforms.items()}

        def local(t):
            rot = t.msg(2)
            q = [rot.f32(i) for i in (1, 2, 3)] + [rot.f32(4, 0.0)] if rot else [0, 0, 0, 1]
            if not any(q):
                q = [0, 0, 0, 1]
            pos = t.msg(3)
            scl = t.msg(4)
            return pose.local_matrix([pos.f32(i) for i in (1, 2, 3)] if pos else [0, 0, 0], np.array(q, dtype=float),
                                     [scl.f32(i, 1.0) for i in (1, 2, 3)] if scl else [1, 1, 1])

        def world_of(go):
            fid, t = by_go.get(go, (None, None))
            m = np.eye(4)
            guard = 0
            while t is not None and guard < 32:
                m = local(t) @ m
                parent = t.int(5)
                t = transforms.get(parent) if parent else None
                guard += 1
            return m

        self.systems = []
        for go, ps in systems.items():
            s = UnitySystem()
            s.name = gameobjects.get(go, '')
            s.matrix = world_of(go)
            # Unity 기본 scalingMode(Local): 자식 파티클 시스템은 부모(루트) 스케일을 무시한다
            # → 스킬 스크립트의 크기 인자(Arg)는 루트 오브젝트에 붙은 시스템에만 적용
            _fid, _t = by_go.get(go, (None, None))
            s.is_root = _t is None or not _t.int(5)
            main = ps.msg(2) or Msg()
            s.duration = main.f32(1, 5.0)
            s.looping = bool(main.int(3))
            s.delay = float(_minmax(main.msg(8), np.random.default_rng(0), 1)[0])
            s.lifetime, s.speed = main.msg(9), main.msg(10)
            size_msg = main.msg(11)
            s.size = size_msg.msg(1) if size_msg else None
            s.max_particles = max(main.int(18, 1000), 1)
            sc = main.msg(13)
            s.start_color_mode = sc.int(1) if sc else 0
            s.start_gradient = _gradient(sc.msg(3)) if sc else None
            rgba = sc.msg(5) if sc else None
            s.start_color = np.array([rgba.f32(i) for i in (1, 2, 3, 4)] if rgba else [1, 1, 1, 1], dtype=np.float64)
            broken = (not np.isfinite(s.start_color).all() or np.abs(s.start_color).max() > 10
                      or np.abs(s.start_color).max() < 1e-6)
            if broken and s.start_color_mode not in (1, 4):
                # 모드 필드가 생략(0)됐는데 5번이 다른 의미로 채워진 경우 — 그라디언트가 있으면 그걸, 없으면 흰색
                if s.start_gradient is not None:
                    s.start_color_mode = 4
                else:
                    s.start_color = np.ones(4)
            emission = ps.msg(3) or Msg()
            s.rate = float(_minmax(emission.msg(1), np.random.default_rng(0), 1)[0]) if emission.msg(1) else 0.0
            s.bursts = []
            for b in emission.msgs(3):
                count = float(_minmax(b.msg(2), np.random.default_rng(0), 1)[0]) if b.msg(2) else 0.0
                s.bursts.append((b.f32(1), count, b.int(3, 1), b.f32(4)))
            shape = ps.msg(4)
            s.has_shape = shape is not None
            geom = shape.msg(2) if shape else None
            s.shape_type = shape.int(1) if shape else 0
            s.angle = geom.f32(1) if geom else 0.0
            s.radius = geom.f32(2) if geom else 0.0
            col = ps.msg(7)
            s.color_over_life = _gradient(col.msg(3)) if col else None
            sol = ps.msg(8)
            s.size_curve = _curve(sol.msg(1)) if sol else None
            sheet = ps.msg(11)
            s.tiles = (max(sheet.int(4, 1), 1), max(sheet.int(5, 1), 1)) if sheet else (1, 1)
            s.scale_factor = float(np.cbrt(abs(np.linalg.det(s.matrix[:3, :3]))) or 1.0)
            r = renderers.get(go)
            if r is None:
                continue
            s.render_mode = r.int(2)
            mat_ref, mesh_ref = r.msg(22), r.msg(21)
            material = load_asset(mat_ref.str(1)) if mat_ref else None
            if material is not None:
                self._apply_material(s, material, load_asset)
            if s.render_mode == 4 and mesh_ref is not None:
                s.mesh = self._load_mesh(load_asset(mesh_ref.str(1)))
            if s.texture is not None and not getattr(s, 'skip', False):
                self.systems.append(s)

    @staticmethod
    def _apply_material(s, data, load_asset):
        rec = Msg(data).msg(1)
        comp = rec.msg(2) if rec else None
        mat = comp.msg(2) if comp else None
        if mat is None:
            return
        shader = mat.str(1)
        s.shader = shader
        # UVdistortion 은 배경을 굴절시키는 셰이더(색을 그리지 않음) → 렌더 제외
        s.skip = 'distortion' in shader.lower()
        legacy = shader.startswith('Particles/') or shader.startswith('MTOS/')
        s.additive = 'add' in shader.lower()
        for c in mat.msgs(4):
            if c.str(1) in ('_TintColor', '_Color'):
                rgba = c.msg(2)
                if rgba:
                    tint = np.array([rgba.f32(i, 0.0) for i in (1, 2, 3, 4)], dtype=np.float32)
                    s.tint = np.clip(tint * (2.0 if legacy else 1.0), 0, 4)
                break
        textures = mat.msgs(5)
        main = next((t for t in textures if t.str(1) == '_MainTex'), textures[0] if textures else None)
        ref = main.msg(2) if main else None
        if ref is not None:
            img = load_asset(ref.str(1), image=True)
            if img is not None:
                if img[..., 3].min() > 0.85:
                    # 알파가 전부 불투명한 텍스처(MTOS 셰이더는 _OpacityType/_OpacityIndex 로 색 채널을 불투명도로 씀)
                    # → 밝기를 알파로 사용
                    img = img.copy()
                    img[..., 3] = img[..., :3].max(axis=-1)
                s.texture = img

    @staticmethod
    def _load_mesh(data):
        if data is None:
            return None
        rec = Msg(data).msg(1)
        comp = rec.msg(2) if rec else None
        mesh = comp.msg(2) if comp else None
        if mesh is None:
            return None
        pos_raw, uv_raw, idx_raw = mesh.raw(4), mesh.raw(7), mesh.raw(3)
        if not pos_raw or not idx_raw:
            return None
        verts = np.frombuffer(pos_raw, '<f4').reshape(-1, 3).astype(np.float64)
        uvs = np.frombuffer(uv_raw, '<f4').reshape(-1, 2).astype(np.float64) if uv_raw else np.zeros((len(verts), 2))
        indices, p = [], 0
        while p < len(idx_raw):
            v, p = _varint(idx_raw, p)
            indices.append(v)
        tris = np.array(indices[:len(indices) // 3 * 3], dtype=np.int64).reshape(-1, 3)
        if len(tris) == 0 or tris.max() >= len(verts):
            return None
        uvs[:, 1] = 1.0 - uvs[:, 1]     # Unity UV 원점은 왼쪽 아래
        return verts, uvs, tris

    def natural_duration(self, cap=3.0):
        ends = []
        for s in self.systems:
            life_max = max(float(_minmax(s.lifetime, np.random.default_rng(0), 1)[0]),
                           s.lifetime.f32(5) if s.lifetime else 0.0, 0.05)
            ends.append(cap if s.looping else s.delay + s.duration + life_max)
        return min(max(ends + [0.1]), cap)

    def draw(self, canvas, mvp, origin, basis, scale, t, t_end, seed):
        fade = float(np.clip((t_end - t) / 0.15, 0.0, 1.0))
        for k, sys_ in enumerate(self.systems):
            res = sys_.particles(t, t_end, seed * 7919 + k)
            if res is None:
                continue
            s_units = UNIT * (scale if sys_.is_root else 1.0)
            pos, size, color, frame = res
            color = color.copy()
            color[:, 3] *= fade
            world = origin + (pos @ basis.T) * s_units
            sizes = size * s_units
            if sys_.render_mode == 4 and sys_.mesh is not None:
                verts, uvs, tris = sys_.mesh
                rot = basis @ sys_.matrix[:3, :3]
                for c, sz, col in list(zip(world, sizes, color))[-MAX_MESH_PARTICLES:]:
                    canvas.draw_tris(c + (verts * sz) @ rot.T, uvs, tris, sys_.texture, col, mvp, sys_.additive)
            elif sys_.render_mode == 2:
                for c, sz, col, f in zip(world, sizes, color, frame):
                    h = sz / 2
                    corners = c + np.array([[-h, 0.3, -h], [h, 0.3, -h], [h, 0.3, h], [-h, 0.3, h]])
                    canvas.draw_quad(corners, sys_.frame_texture(f), col, mvp, additive=sys_.additive)
            else:
                for f in np.unique(frame):
                    sel = frame == f
                    canvas.draw_sprites(world[sel], sizes[sel], color[sel], sys_.frame_texture(int(f)), mvp,
                                        additive=sys_.additive)


class UnityLibrary:
    """unityeffect.xml 이름 → 에셋 GUID, assets.ipf 의 pb/png/tga 를 GUID 로 찾는다."""

    def __init__(self, assets):
        self.assets = assets
        raw = assets.bytes('effect.ipf/unityeffect.xml').decode('utf-8', 'replace')
        self.names = {}
        for m in re.finditer(r'<Effect Name="([^"]+)" Asset="([^"]+)"', raw):
            guid = re.split(r'[\\/]', m.group(2))[-1].split('.')[0].lower()
            self.names.setdefault(m.group(1).lower(), guid)
        self.files = defaultdict(list)
        for key in assets.index.items:
            if key.startswith('assets.ipf/') and not key.endswith('.meta'):
                self.files[key.rsplit('/', 1)[-1].split('.')[0]].append(key)
        self._effects = {}
        self._images = {}

    def load_asset(self, guid, image=False):
        guid = (guid or '').lower()
        keys = self.files.get(guid, [])
        if image:
            if guid in self._images:
                return self._images[guid]
            img = None
            for k in keys:
                if k.endswith(('.png', '.tga')):
                    try:
                        src = Image.open(io.BytesIO(self.assets.bytes(k)))
                        has_alpha = src.mode in ('RGBA', 'LA') or 'transparency' in src.info
                        img = np.asarray(src.convert('RGBA'), dtype=np.float32) / 255.0
                        if not has_alpha:
                            # 알파 없는 RGB 텍스처(가산용 그림)는 검정이 투명이 되도록 밝기를 알파로
                            img = img.copy()
                            img[..., 3] = img[..., :3].max(axis=-1)
                    except OSError:
                        img = None
                    break
            self._images[guid] = img
            return img
        pb = [k for k in keys if k.endswith('.pb')]
        return self.assets.bytes(pb[0]) if pb else None

    def effect(self, name):
        key = name.lower()
        if key not in self.names:
            return None
        if key not in self._effects:
            data = self.load_asset(self.names[key])
            self._effects[key] = UnityEffect(data, self.load_asset) if data else None
        return self._effects[key]
