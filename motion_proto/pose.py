"""스켈레톤 포즈·스키닝.

규약(스킨 정점 중심 ↔ bind 뼈 위치 거리로 검증, median 3 unit):
  - 쿼터니언 (x, y, z, w) 표준 회전행렬, 켤레 없음
  - 열벡터, world = parent_world @ local
"""
import numpy as np

import xsm


def quat_to_mat3(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def local_matrix(pos, rot, scale=None):
    """T · R · S. 오른쪽 치마 체인처럼 음수 스케일(미러)로 만든 뼈가 있어 스케일을 빼면 안 된다."""
    m = np.eye(4)
    m[:3, :3] = quat_to_mat3(rot) if scale is None else quat_to_mat3(rot) * np.asarray(scale)[None, :]
    m[:3, 3] = pos
    return m


def world_matrices(actor, tracks=None, time=0.0):
    # xac/xsm 뼈 이름 대소문자가 다르다(예: Bone_cloak_all ↔ Bone_cloak_All, Clavicle Twist ↔ twist)
    by_name = {k.lower(): v for k, v in tracks.items()} if tracks is not None else {}
    out = [None] * len(actor.nodes)
    for i, n in enumerate(actor.nodes):
        pos, rot, scale = n.pos, n.rot, n.scale
        track = by_name.get(n.name.lower())
        if track is not None:
            pos, rot, scale = xsm.sample(track, time)
        local = local_matrix(pos, rot, scale)
        out[i] = local if n.parent < 0 else out[n.parent] @ local
    return np.stack(out)


def skin_mesh(mesh, bind_world, anim_world):
    """선형 블렌드 스키닝 → (positions, normals)."""
    skin_mats = anim_world @ np.linalg.inv(bind_world)          # (B,4,4)
    weights, bones = mesh.skin
    m = np.einsum('vk,vkij->vij', weights, skin_mats[bones])   # (V,4,4)
    p = np.einsum('vij,vj->vi', m[:, :3, :3], mesh.positions) + m[:, :3, 3]
    nrm = np.einsum('vij,vj->vi', m[:, :3, :3], mesh.normals)
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True).clip(1e-8)
    return p, nrm


def billboard_attach(mesh, head_pos, cam_right, cam_up, to_camera, mirror=False):
    """ToS 머리/헤어는 2D 그림 조각을 겹친 판이다 — 머리 뼈 위치에서 카메라를 향하게 세운다.

    파일 내 좌표: X = 위, Y = 가로, Z = 레이어 깊이(클수록 앞).
    """
    x, y, z = mesh.positions[:, 0], mesh.positions[:, 1], mesh.positions[:, 2]
    side = -y if mirror else y
    p = head_pos + np.outer(side, cam_right) + np.outer(x, cam_up) + np.outer(z, to_camera)
    nrm = np.tile(to_camera, (len(p), 1))
    return p, nrm


def rigid_attach(mesh, attach_actor, attach_world, bone_name='Bip01 Head'):
    """머리/헤어 xac 처럼 뼈 하나에 붙는 메시: 파일 내 bind 루트 → 몸통의 애니메이션 뼈."""
    local_bind = world_matrices(attach_actor)[attach_actor.node_index[bone_name]]
    m = attach_world @ np.linalg.inv(local_bind)
    p = mesh.positions @ m[:3, :3].T + m[:3, 3]
    if mesh.normals is not None:
        nrm = mesh.normals @ m[:3, :3].T
    else:
        nrm = np.tile(m[:3, 2], (len(p), 1))
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True).clip(1e-8)
    return p, nrm
