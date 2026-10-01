"""ToS 스킬 모션을 서버에서 렌더링해 WebM 으로 인코딩하는 시제품.

사용 예:
  python3 render_motion.py --job cleric_m --motion cleric_m_mns_skl_blessing --out out/blessing.webm
  python3 render_motion.py --job archer_m \
      --motion "archer_m_thb_skl_godarrow_cast,archer_m_thb_skl_godarrow_loop*3,archer_m_thb_skl_godarrow_shot" \
      --out out/godarrow.webm
  python3 render_motion.py --motion cleric_m_mns_skl_blessing --preview out/preview.png --time 0.3

--motion 은 쉼표로 이어 붙이고 `이름*N` 으로 반복한다(차지형 스킬 cast → loop → shot).
에셋은 cache/index_ktos.json(원격 ipf 인덱스)에서 필요한 파일만 Range 로 받아 cache/ 에 둔다.
"""
import argparse
import io
import os
import re
import shutil
import subprocess
import tempfile
import time

import numpy as np
from PIL import Image

import effects
import ipf_remote
import pose
import raster
import xac
import xsm

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')
FFMPEG = os.environ.get('FFMPEG', 'ffmpeg')

MESSY_M = {
    'head': 'char_hi.ipf/pc/faces/warrior_m/messy_m_head_std.xac',
    'hair': 'char_hi.ipf/pc/faces/warrior_m/messy_m_hair_std.xac',
    'face_tex_dir': 'char_texture.ipf/pc/face/hair_m/',
}

# 시제품: 직업별 기본 외형(xac.ies 의 *_costume01 / *_head / *_hair / *_bodybase 행 기준)
JOB_ASSETS = {
    'cleric_m': dict(
        MESSY_M,
        body='char_hi.ipf/pc/cleric_m/cleric_m_costume01.xac',
        body_tex_dir='char_texture.ipf/pc/body/cleric_m_costume01/',
        # 이펙트·무기 더미(Dummy_effect_*, Dummy_R_HAND ...)는 코스튬 모델에 없을 수 있어 기본 뼈대를 함께 포즈한다
        effect_skeleton='char_hi.ipf/pc/cleric_m/cleric_m_bodybase.xac',
        # (붙일 더미 뼈, 모델, 텍스처 폴더) — mns 자세 = 메이스 + 방패. 무기 모델은 남녀 공용(cleric_f_*)
        weapons=[
            ('Dummy_R_HAND', 'item_hi.ipf/pc_item/weapon/cleric_f_mace_mace.xac', 'item_texture.ipf/'),
            # Dummy_Shield 는 오른손 자식이라 메이스와 겹친다 → 왼손 더미에 부착(mns_astd 비교 렌더로 확인)
            ('Dummy_L_HAND', 'item_hi.ipf/pc_item/weapon/warrior_f_shield_wooden_buckler.xac', 'item_texture.ipf/'),
        ],
    ),
    'archer_m': dict(
        MESSY_M,
        body='char_hi.ipf/pc/archer_m/archer_m_costume01.xac',
        body_tex_dir='char_texture.ipf/pc/body/archer_m_costume01/',
        effect_skeleton='char_hi.ipf/pc/archer_m/archer_m_bodybase.xac',
        # 활 뼈(Dummy_body, Bone_up*, Bone_down*)가 기본 뼈대의 Dummy_R_HAND 아래에 있고 모션에도 트랙이 있다
        # → 더미 강체 부착이 아니라 뼈 이름으로 스키닝해 시위가 휘는 것까지 재현
        weapons=[
            (None, 'item_hi.ipf/pc_item/weapon/archer_f_bow_bow1.xac', 'item_texture.ipf/'),
        ],
    ),
    # 아래 세 직업은 batch_render 가 스킬 자세별 무기를 계획(skill_plan)에서 넘긴다. weapons 는 CLI 단독 실행용 기본값
    'warrior_m': dict(
        MESSY_M,
        body='char_hi.ipf/pc/warrior_m/warrior_m_costume01.xac',
        body_tex_dir='char_texture.ipf/pc/body/warrior_m_costume01/',
        effect_skeleton='char_hi.ipf/pc/warrior_m/warrior_m_bodybase.xac',
        weapons=[
            ('Dummy_R_HAND', 'item_hi.ipf/pc_item/weapon/warrior_f_sword_gladius.xac', 'item_texture.ipf/'),
            ('Dummy_L_HAND', 'item_hi.ipf/pc_item/weapon/warrior_f_shield_wooden_buckler.xac', 'item_texture.ipf/'),
        ],
    ),
    # xac.ies Mage_m_costume01 행이 mage_m_costume02 모델·텍스처를 가리킨다(mage_m_costume01.xac 없음)
    'mage_m': dict(
        MESSY_M,
        body='char_hi.ipf/pc/mage_m/mage_m_costume02.xac',
        body_tex_dir='char_texture.ipf/pc/body/mage_m_costume02/',
        effect_skeleton='char_hi.ipf/pc/mage_m/mage_m_bodybase.xac',
        weapons=[('Dummy_R_HAND', 'item_hi.ipf/pc_item/weapon/mage_f_rod_lapai.xac', 'item_texture.ipf/')],
    ),
    # xac.ies Scout_m_costume01 → scout_m_scout01
    'scout_m': dict(
        MESSY_M,
        body='char_hi.ipf/pc/scout_m/scout_m_scout01.xac',
        body_tex_dir='char_texture.ipf/pc/body/scout_m_scout01/',
        effect_skeleton='char_hi.ipf/pc/scout_m/scout_m_bodybase.xac',
        weapons=[('Dummy_R_HAND', 'item_hi.ipf/pc_item/weapon/warrior_f_dagger_dual.xac', 'item_texture.ipf/')],
    ),
}

# 스킬 스크립트의 캐릭터 색 연출. bowmaster.xml BowMaster_GodArrow:
# KeyInputStart BowMaster_ActorBlend(118,124,254,255) ~ KeyInputEnd(255,255,255,255) → 차지(cast/loop) 동안만
SEGMENT_TINTS = {
    'archer_m_thb_skl_godarrow_cast': (118, 124, 254),
    'archer_m_thb_skl_godarrow_loop': (118, 124, 254),
}


class Assets:
    def __init__(self, index_path):
        self.index = ipf_remote.AssetIndex(index_path)
        self._tex = {}

    def bytes(self, key):
        return self.index.get(key.lower(), CACHE)

    def texture(self, key):
        key = key.lower()
        if key not in self._tex:
            img = Image.open(io.BytesIO(self.bytes(key))).convert('RGBA')
            self._tex[key] = np.asarray(img, dtype=np.float32) / 255.0
        return self._tex[key]


class MotionTimeline:
    """여러 xsm 을 이어 붙인 타임라인. spec: 'a,b*3,c'. 'b*auto' 는 loop_fill 초 이상 채우도록 반복(차지 loop)."""

    def __init__(self, assets, job, spec, loop_fill=1.0, max_loops=4):
        self.segments = []   # (name, tracks, start, duration)
        self.item_of = []    # segment → spec 항목 번호
        start = 0.0
        for i, item in enumerate(spec.split(',')):
            name, _, rep = item.strip().partition('*')
            tracks, dur = xsm.load(assets.bytes('animation.ipf/pc/%s/%s.xsm' % (job, name)))
            if rep == 'auto':
                count = min(max_loops, max(1, int(np.ceil(loop_fill / max(dur, 1e-3)))))
            else:
                count = int(rep or 1)
            for _ in range(count):
                self.segments.append((name, tracks, start, dur))
                self.item_of.append(i)
                start += dur
        self.duration = start

    def at(self, t):
        t = min(max(t, 0.0), self.duration)
        for seg in self.segments:
            if t <= seg[2] + seg[3]:
                return seg[0], seg[1], t - seg[2]
        name, tracks, start, _ = self.segments[-1]
        return name, tracks, t - start

    def world(self, actor, t):
        _, tracks, local_t = self.at(t)
        return pose.world_matrices(actor, tracks, local_t)


class NodeResolver:
    """노드 이름 → 월드 행렬. 몸통(코스튬)에 없으면 같은 모션으로 포즈한 기본 뼈대에서 찾는다."""

    def __init__(self, body, skeleton=None):
        self.skeleton = skeleton
        self.body_index = {n.name.lower(): i for i, n in enumerate(body.nodes)}
        self.skel_index = {n.name.lower(): i for i, n in enumerate(skeleton.nodes)} if skeleton else {}

    def posed(self, timeline, t):
        if self.skeleton is None:
            return None
        return timeline.world(self.skeleton, t) if timeline is not None else pose.world_matrices(self.skeleton)

    def world(self, name, anim, skel_anim):
        key = name.lower()
        if key in self.body_index:
            return anim[self.body_index[key]]
        if skel_anim is not None and key in self.skel_index:
            return skel_anim[self.skel_index[key]]
        return None

    def skin_by_name(self, actor, mesh, anim, skel_anim):
        """무기 메시의 스킨 뼈를 이름으로 몸통/기본 뼈대 포즈에 연결해 스키닝. 못 찾는 뼈가 있으면 None."""
        weights, bones = mesh.skin
        used = {int(b) for b in bones[weights > 0]}
        bind = pose.world_matrices(actor)
        animated = bind.copy()
        for i, n in enumerate(actor.nodes):
            m = self.world(n.name, anim, skel_anim)
            if m is not None:
                animated[i] = m
            elif i in used:
                return None
        return pose.skin_mesh(mesh, bind, animated)


def build_parts(assets, job, weapons=None):
    """weapons: [(더미, 모델, 텍스처 폴더)] — None 이면 JOB_ASSETS 기본 무기."""
    spec = JOB_ASSETS[job]
    body = xac.load(assets.bytes(spec['body']))
    head = xac.load(assets.bytes(spec['head']))
    hair = xac.load(assets.bytes(spec['hair']))

    def tex_for(actor, material_id, tex_dir):
        mat = actor.materials[material_id] if material_id < len(actor.materials) else {}
        name = mat.get('DiffuseTex')
        return assets.texture(tex_dir + name) if name else None

    parts = []
    for mesh in body.meshes:
        if mesh.skin is None:
            # scout_m_scout01 등: 트위스트 뼈에 붙은 24정점 보조 박스(로컬 좌표) — 그리지 않는다
            continue
        for sub in mesh.submeshes:
            parts.append(('skin', body, mesh, sub, tex_for(body, sub.material_id, spec['body_tex_dir'])))
    for actor in (head, hair):
        for mesh in actor.meshes:
            for sub in mesh.submeshes:
                parts.append(('head', actor, mesh, sub, tex_for(actor, sub.material_id, spec['face_tex_dir'])))
    for dummy, model, tex_dir in (spec.get('weapons', []) if weapons is None else weapons):
        actor = xac.load(assets.bytes(model))
        for mesh in actor.meshes:
            for sub in mesh.submeshes:
                parts.append(('weapon:' + (dummy or ''), actor, mesh, sub, tex_for(actor, sub.material_id, tex_dir)))
    return body, parts


def part_geometry(kind, actor, mesh, body, bind, anim, billboard, resolver=None, skel_anim=None):
    """파트 종류별 월드 좌표 (positions, normals)."""
    if kind == 'skin':
        return pose.skin_mesh(mesh, bind, anim)
    if kind.startswith('weapon:'):
        resolver = resolver or NodeResolver(body)
        if mesh.skin is not None:
            skinned = resolver.skin_by_name(actor, mesh, anim, skel_anim)
            if skinned is not None:
                return skinned
        dummy = kind.split(':', 1)[1]
        attach = resolver.world(dummy, anim, skel_anim) if dummy else None
        if attach is None:
            attach = anim[body.node_index['Bip01 R Hand']]
        return pose.rigid_attach(mesh, actor, attach, actor.nodes[mesh.node_id].name)
    return pose.billboard_attach(mesh, *billboard)


def camera_dir(yaw, pitch):
    """타깃 → 카메라 단위벡터."""
    y, p = np.radians(yaw), np.radians(pitch)
    return np.array([np.sin(y) * np.cos(p), np.sin(p), np.cos(y) * np.cos(p)])


def effect_points(body, timeline, events, max_dist=120.0):
    """지면·투사체 이펙트 위치(캐릭터 정면 기준 오프셋) 대표 점 — 카메라 범위에 넣는다. 멀면 max_dist 로 자른다."""
    pts = []
    for ev in events:
        for prefix in ('', 'dst_', 'src_'):
            if prefix + 'dist' not in ev and not (prefix == '' and ev['anchor'] == 'ground'):
                continue
            dist = float(np.clip(ev.get(prefix + 'dist', 0.0), -max_dist, max_dist))
            ang = ev.get(prefix + 'angle', 0.0)
            basis = facing_basis(body, timeline, ev['time'])
            p = (ground_anchor(body, timeline, ev['time'], 0.0)
                 + (basis[:, 2] * np.cos(ang) + basis[:, 0] * np.sin(ang)) * dist
                 + basis[:, 1] * (ev.get(prefix + 'height', 0.0) + 10.0))
            pts.append(p)
    return np.array(pts) if pts else None


def fit_camera(body, parts, timeline, yaw, pitch, aspect, fov=30.0, samples=12, margin=1.1, resolver=None,
               extra=None):
    """모션 전체(샘플 프레임)의 화면 범위에 맞춰 (target, distance) 를 구한다. extra: 함께 담을 점(이펙트 위치)."""
    bind = pose.world_matrices(body)
    hi = body.node_index['Bip01 Head']
    duration = timeline.duration if timeline is not None else 0.0
    pts = []
    for t in np.linspace(0.0, duration, samples):
        anim = timeline.world(body, t) if timeline is not None else bind
        skel_anim = resolver.posed(timeline, t) if resolver is not None else None
        for kind, actor, mesh, _sub, _tex in parts:
            if kind != 'head':
                pts.append(part_geometry(kind, actor, mesh, body, bind, anim, None, resolver, skel_anim)[0][::5])
        # 머리/헤어 판(뼈 기준 위로 ~19, 옆으로 ~12)은 구로 근사
        head = anim[hi][:3, 3] + np.array([0.0, 5.0, 0.0])
        pts.append(head + 15.0 * np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]]))
    if extra is not None:
        pts.append(extra)
    pts = np.concatenate(pts)
    view = raster.look_at(camera_dir(yaw, pitch), np.zeros(3))
    right, up, back = view[0, :3], view[1, :3], view[2, :3]
    r, u, z = pts @ right, pts @ up, pts @ back
    target = right * (r.min() + r.max()) / 2 + up * (u.min() + u.max()) / 2 + back * (z.min() + z.max()) / 2
    half_h = max((u.max() - u.min()) / 2, (r.max() - r.min()) / 2 / aspect) * margin
    distance = half_h / np.tan(np.radians(fov) / 2) + (z.max() - z.min()) / 2
    return target, distance


_VARIANT_RX = re.compile(r'_c(\d\d)_(face|hair)', re.I)
_grid_cache = {}
_tint_cache = {}


def atlas_grid(tex, max_cells=8, min_strength=0.55):
    """표정 아틀라스의 (cols, rows).

    - cols: 귀가 칸 경계를 넘어 투명한 세로 경계선이 없어서, 가로 알파 프로필의 자기상관 주기로 추정.
      주기가 약하면(단일 그림, 예: c07 뒷모습) 1x1.
    - rows: 마지막 줄이 비어 있어 전체 주기가 약하므로, 첫 열 띠에서 첫 얼굴 아래의 알파 최저점을 칸 높이로 본다.
    """
    key = id(tex)
    if key in _grid_cache:
        return _grid_cache[key]
    alpha = tex[..., 3]
    h, w = alpha.shape
    grid = (1, 1)
    x = alpha.mean(axis=0) - alpha.mean()
    ac = np.correlate(x, x, 'full')[len(x) - 1:]
    if ac[0] > 0:
        ac = ac / ac[0]
        cols, strength = 1, 0.0
        for c in range(2, max_cells + 1):
            lag = w / c
            s = ac[max(int(np.floor(lag)) - 1, 1):int(np.ceil(lag)) + 2].max()
            if s > strength + 0.05:
                cols, strength = c, s
        if strength >= min_strength:
            cw = w / cols
            strip = alpha[:, :int(round(cw))].mean(axis=1)
            lo, hi = int(0.6 * cw), min(int(1.6 * cw), h - 1)
            rows = 1
            if hi > lo:
                ch = lo + int(np.argmin(strip[lo:hi + 1]))
                rows = max(1, int(round(h / max(ch, 1))))
            grid = (cols, rows)
    _grid_cache[key] = grid
    return grid


def tinted(tex, tint):
    if tint is None:
        return tex
    key = (id(tex), tint)
    if key not in _tint_cache:
        out = tex.copy()
        out[..., :3] *= np.asarray(tint, dtype=np.float32) / 255.0
        _tint_cache[key] = out
    return _tint_cache[key]


def head_view(head_mat, eye):
    """머리 정면(로컬 +Z)과 카메라 방향 사이의 수평 각도(도, 부호 포함)."""
    fwd = head_mat[:3, :3] @ np.array([0.0, 0.0, 1.0])
    to_cam = eye - head_mat[:3, 3]
    cross = fwd[0] * to_cam[2] - fwd[2] * to_cam[0]
    dot = fwd[0] * to_cam[0] + fwd[2] * to_cam[2]
    return np.degrees(np.arctan2(cross, dot))


def pick_variant(available, angle):
    """0°=c01(정면) 45°=c03 90°=c05 135°=c07 180°=c09, 없는 변형은 가장 가까운 아래 단계로."""
    desired = 1 + 2 * min(4, int((abs(angle) + 22.5) // 45))
    lower = [c for c in available if c <= desired]
    return max(lower) if lower else min(available)


def facing_basis(body, timeline, t_event):
    """이벤트 시각 캐릭터 정면 기준 축 (열: right, up, forward). 스킬 스크립트의 Dist/Height 기준."""
    bind_root = pose.world_matrices(body)[body.node_index['Bip01']]
    root = timeline.world(body, t_event)[body.node_index['Bip01']] if timeline is not None else bind_root
    fwd = root[:3, :3] @ bind_root[:3, :3].T @ np.array([0.0, 0.0, -1.0])
    fwd[1] = 0.0
    fwd /= max(np.linalg.norm(fwd), 1e-6)
    up = np.array([0.0, 1.0, 0.0])
    return np.stack([np.cross(up, fwd), up, fwd], axis=1)


def ground_anchor(body, timeline, t_event, dist):
    """패드/지면 이펙트 위치: 이벤트 시각의 루트 XZ + 캐릭터 정면(-Z 기준) 방향 dist."""
    bind_root = pose.world_matrices(body)[body.node_index['Bip01']]
    root = timeline.world(body, t_event)[body.node_index['Bip01']] if timeline is not None else bind_root
    fwd = root[:3, :3] @ bind_root[:3, :3].T @ np.array([0.0, 0.0, -1.0])
    fwd[1] = 0.0
    fwd /= max(np.linalg.norm(fwd), 1e-6)
    p = root[:3, 3].copy()
    p[1] = 0.0
    return p + fwd * dist


def render_frame(body, parts, timeline, time, size, yaw, pitch, distance, target_y, fov=30.0, mirror_head=False,
                 sim=None, effect_time=None, background=(0, 0, 0, 0), ground_cache=None, resolver=None, tint=None):
    bind = pose.world_matrices(body)
    anim = timeline.world(body, time) if timeline is not None else bind
    resolver = resolver or NodeResolver(body)
    skel_anim = resolver.posed(timeline, time)
    head_mat = anim[body.node_index['Bip01 Head']]
    head_pos = head_mat[:3, 3]

    w, h = size
    target = np.array([0.0, target_y, 0.0]) if np.isscalar(target_y) else np.asarray(target_y, dtype=np.float64)
    eye = target + distance * camera_dir(yaw, pitch)
    view = raster.look_at(eye, target)
    mvp = raster.perspective(fov, w / h, 1.0, 2000.0) @ view
    cam_right, cam_up, to_camera = view[0, :3], view[1, :3], view[2, :3]
    light = eye - target + np.array([30.0, 80.0, 0.0])

    angle = head_view(head_mat, eye)
    mirror = (angle < 0) != mirror_head
    available = {}
    for kind, actor, mesh, sub, tex in parts:
        m = _VARIANT_RX.search(actor.nodes[mesh.node_id].name) if kind == 'head' else None
        if m:
            available.setdefault(m.group(2).lower(), set()).add(int(m.group(1)))
    chosen = {k: pick_variant(v, angle) for k, v in available.items()}

    canvas = raster.Canvas(w, h, background)
    cache = {}
    for kind, actor, mesh, sub, tex in parts:
        if tex is None:
            continue
        uvs = mesh.uvs
        if kind == 'head':
            m = _VARIANT_RX.search(actor.nodes[mesh.node_id].name)
            if m and int(m.group(1)) != chosen[m.group(2).lower()]:
                continue
            if m and m.group(2).lower() == 'face':
                cols, rows = atlas_grid(tex)
                uvs = uvs / np.array([cols, rows])
        key = id(mesh)
        if key not in cache:
            cache[key] = part_geometry(kind, actor, mesh, body, bind, anim,
                                       (head_pos, cam_right, cam_up, to_camera, mirror), resolver, skel_anim)
        p, n = cache[key]
        tris = sub.indices.reshape(-1, 3)
        canvas.draw(p, n, uvs, tris, tinted(tex, tint), mvp, light)

    if sim is not None:
        ground_cache = {} if ground_cache is None else ground_cache
        now = time if effect_time is None else effect_time

        def basis_at(t_ev):
            key = ('basis', t_ev)
            if key not in ground_cache:
                ground_cache[key] = facing_basis(body, timeline, t_ev)
            return ground_cache[key]

        def ground(t_ev):
            key = ('ground', t_ev)
            if key not in ground_cache:
                ground_cache[key] = ground_anchor(body, timeline, t_ev, 0.0)
            return ground_cache[key]

        def offset(ev, basis, prefix=''):
            """캐릭터 정면 기준 오프셋: angle(라디안, 정면에서 회전)·dist 수평 거리, height 높이."""
            dist, ang = ev.get(prefix + 'dist', 0.0), ev.get(prefix + 'angle', 0.0)
            return ((basis[:, 2] * np.cos(ang) + basis[:, 0] * np.sin(ang)) * dist
                    + basis[:, 1] * ev.get(prefix + 'height', 0.0))

        def node_pos(spec, pose_anim, pose_skel):
            m = resolver.world(spec[5:], pose_anim, pose_skel) if spec.startswith('node:') else None
            return m[:3, 3] if m is not None else pose_anim[body.node_index['Bip01']][:3, 3]

        def anchor(ev):
            basis = basis_at(ev['time'])
            spec = ev['anchor']
            if spec == 'ground':
                return ground(ev['time']) + offset(ev, basis), basis
            if spec == 'lerp':
                # 투사체: 발사 시각의 출발점 → 목표 지점(dst_*)을 fly 초 동안 선형 이동
                key = ('lerp', ev['seed'])
                if key not in ground_cache:
                    dst = ground(ev['time']) + offset(ev, basis, 'dst_')
                    src = ev.get('src', 'root')
                    if src == 'above':
                        src_pos = dst + np.array([0.0, 150.0, 0.0])
                    elif src == 'ground':
                        src_pos = ground(ev['time']) + offset(ev, basis, 'src_')
                    else:
                        launch = timeline.world(body, ev['time']) if timeline is not None else anim
                        src_pos = node_pos(src, launch, resolver.posed(timeline, ev['time']))
                    ground_cache[key] = (src_pos, dst)
                src_pos, dst = ground_cache[key]
                u = np.clip((now - ev['time']) / max(ev.get('fly', 0.5), 1e-3), 0.0, 1.0)
                return src_pos + (dst - src_pos) * u, basis
            return node_pos(spec, anim, skel_anim) + offset(ev, basis), basis

        sim.draw(canvas, mvp, anchor, now)
    return canvas


def encode_webm(frame_dir, fps, out_path, size, codec='vp9', crf=40, background='ffffff', alpha=False, threads=0):
    """PNG 프레임 → WebM.

    기본은 배경색 합성(불투명). ktos MagnusExorcismus 37프레임 360x480 기준
    VP9 알파 CRF34 198KB / 불투명 CRF40 58KB. AV1(libaom)은 같은 조건 비교에서 VP9 와 용량이 거의 같았다.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    pattern = os.path.join(frame_dir, '%04d.png')
    if codec == 'av1':
        if alpha:
            raise SystemExit('투명 배경(--alpha)은 VP9 만 지원합니다')
        vargs = ['-c:v', 'libaom-av1', '-strict', '-2', '-crf', str(crf), '-b:v', '0', '-cpu-used', '6', '-row-mt', '1']
    else:
        vargs = ['-c:v', 'libvpx-vp9', '-crf', str(crf), '-b:v', '0', '-row-mt', '1', '-deadline', 'good']
    if alpha:
        filters, pix = [], 'yuva420p'
    else:
        w, h = size
        # color 소스 기본 25fps 라 r 을 안 주면 30fps 프레임이 overlay 에서 버려진다
        filters = ['-filter_complex',
                   'color=c=0x%s:s=%dx%d:r=%d[bg];[bg][0:v]overlay=shortest=1,format=yuv420p'
                   % (background, w, h, fps)]
        pix = 'yuv420p'
    if threads:
        vargs += ['-threads', str(threads)]
    cmd = [FFMPEG, '-y', '-nostdin', '-loglevel', 'error', '-framerate', str(fps), '-i', pattern,
           *filters, *vargs, '-pix_fmt', pix, '-an', out_path]
    # 맥미니(ffmpeg 9.0.1, 병렬 렌더로 스왑이 찬 상태)에서 가끔 SIGSEGV — 같은 명령을 다시 돌리면 성공해서 재시도한다
    for attempt in range(3):
        try:
            subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)
            return
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--job', default='cleric_m')
    ap.add_argument('--motion', default='cleric_m_mns_skl_blessing', help="쉼표로 이어 붙이기, '이름*N' 반복")
    ap.add_argument('--index', default=os.path.join(CACHE, 'index_ktos.json'))
    ap.add_argument('--size', default='360x480')
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--yaw', type=float, default=215.0, help='캐릭터 정면은 -Z(yaw 180)')
    ap.add_argument('--mirror-head', action='store_true')
    ap.add_argument('--pitch', type=float, default=18.0)
    ap.add_argument('--distance', type=float, default=None, help='생략하면 모션 범위에 맞춰 자동')
    ap.add_argument('--target-y', type=float, default=None)
    ap.add_argument('--loops', type=int, default=1)
    ap.add_argument('--codec', choices=['vp9', 'av1'], default='vp9')
    ap.add_argument('--crf', type=int, default=40)
    ap.add_argument('--background', default=None,
                    help='배경색(hex). 기본: 이펙트 있으면 1d2026(가산 이펙트가 보이도록), 없으면 ffffff')
    ap.add_argument('--no-effects', action='store_true')
    ap.add_argument('--skill', help='스킬 스크립트 이펙트 이벤트(effects.SKILL_EVENTS 키, 예: BowMaster_GodArrow)')
    ap.add_argument('--no-weapons', action='store_true')
    ap.add_argument('--max-duration', type=float, default=3.0, help='이펙트 꼬리 포함 최대 영상 길이(초)')
    ap.add_argument('--alpha', action='store_true', help='투명 배경 VP9(용량 약 4배)')
    ap.add_argument('--supersample', type=int, default=2)
    ap.add_argument('--frames-dir', help='렌더한 PNG 프레임을 지우지 않고 이 폴더에 남긴다(코덱 비교용)')
    ap.add_argument('--out')
    ap.add_argument('--preview')
    ap.add_argument('--time', type=float, default=None, help='--preview 시각(초). 생략하면 bind pose')
    args = ap.parse_args()
    render(args)


def render(args, assets=None, log=print):
    """main() 옵션으로 렌더. batch_render 는 계획 값(weapons, events, main_index, threads)을 더 채워 부른다."""
    w, h = (int(x) for x in args.size.split('x'))
    ss = max(1, args.supersample)
    assets = assets or Assets(args.index)
    weapons = [] if args.no_weapons else getattr(args, 'weapons', None)
    plan_events = getattr(args, 'events', None)
    body, parts = build_parts(assets, args.job, weapons)
    job_dir = args.job.lower()
    timeline = MotionTimeline(assets, job_dir, args.motion)
    duration = timeline.duration
    skel_key = JOB_ASSETS[args.job].get('effect_skeleton')
    resolver = NodeResolver(body, xac.load(assets.bytes(skel_key)) if skel_key else None)

    sim = None
    total = duration
    if not args.no_effects:
        events = []
        for name, _tracks, start, seg_dur in timeline.segments:
            for ev in effects.motion_events(assets, job_dir, name, extra=plan_events is None):
                ev = dict(ev, time=ev['time'] + start)
                if 'until' in ev:
                    ev['until'] += start
                events.append(ev)
        if args.skill:
            shot = next((s[2] for s in timeline.segments if s[0].endswith('_shot')), duration)
            events += effects.skill_events(args.skill, {'start': 0.0, 'shot': shot})
        if plan_events:
            main_index = getattr(args, 'main_index', None)
            main_start = next((seg[2] for seg, item in zip(timeline.segments, timeline.item_of)
                               if item == main_index), 0.0)
            events += effects.phase_events(plan_events, {'start': 0.0, 'main': main_start})
        sim = effects.Simulator(effects.EffectLibrary(assets), events)
        total = min(max(duration, sim.end_time()), max(args.max_duration, duration))
        log('effects:', [(round(e['time'], 2), e['name'], round(e['duration'], 2),
                            len(e['unity'].systems) if e.get('unity') is not None else len(e['emitters']))
                           for e in sim.events])
    background = args.background or ('1d2026' if sim is not None and sim.events else 'ffffff')
    bg_rgba = (0, 0, 0, 0) if args.alpha else tuple(int(background.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)) + (255,)

    target, distance = fit_camera(body, parts, timeline, args.yaw, args.pitch, w / h,
                                  margin=1.45 if sim is not None and sim.events else 1.1, resolver=resolver,
                                  extra=effect_points(body, timeline, sim.events) if sim is not None else None)
    if args.distance is not None:
        distance = args.distance
    if args.target_y is not None:
        target = args.target_y
    cam = dict(yaw=args.yaw, pitch=args.pitch, distance=distance, target_y=target,
               mirror_head=args.mirror_head)
    ground_cache = {}

    def frame_image(t):
        # 모션이 끝난 뒤에는 마지막 포즈를 유지하고 이펙트만 계속 진행
        pose_t = min(t or 0.0, duration)
        tint = SEGMENT_TINTS.get(timeline.at(pose_t)[0]) if t is not None else None
        c = render_frame(body, parts, timeline if t is not None else None, pose_t, (w * ss, h * ss),
                         sim=sim, effect_time=t or 0.0, background=bg_rgba, ground_cache=ground_cache,
                         resolver=resolver, tint=tint, **cam)
        img = c.to_image()
        return img.resize((w, h), Image.LANCZOS) if ss > 1 else img

    if args.preview:
        os.makedirs(os.path.dirname(os.path.abspath(args.preview)), exist_ok=True)
        frame_image(args.time).save(args.preview)
        log('preview', args.preview, 'motion', round(duration, 3), 'total', round(total, 3))
        return dict(motion=round(duration, 3), total=round(total, 3))

    nframes = max(1, int(round(total * args.fps)) + 1)
    tmp = args.frames_dir or tempfile.mkdtemp(prefix='motion_')
    os.makedirs(tmp, exist_ok=True)
    try:
        k = 0
        for _ in range(args.loops):
            for f in range(nframes):
                frame_image(min(f / args.fps, total)).save(os.path.join(tmp, '%04d.png' % k))
                k += 1
        encode_webm(tmp, args.fps, args.out, (w, h), args.codec, args.crf,
                    background.lstrip('#'), args.alpha, getattr(args, 'threads', 0))
    finally:
        if not args.frames_dir:
            shutil.rmtree(tmp, ignore_errors=True)
    log('wrote', args.out, os.path.getsize(args.out), 'bytes', k, 'frames',
        'motion', round(duration, 3), 'total', round(total, 3))
    return dict(bytes=os.path.getsize(args.out), frames=k, motion=round(duration, 3), total=round(total, 3),
                effects=len(sim.events) if sim is not None else 0)


if __name__ == '__main__':
    main()
