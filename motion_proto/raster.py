"""GPU 없는 서버용 numpy 소프트웨어 래스터라이저.

삼각형 단위 바운딩박스 안에서 무게중심 좌표를 벡터 연산으로 구해
z-buffer + 원근 보정 UV + 알파 테스트 + 간단한 램버트/툰 셰이딩을 한다.
"""
import numpy as np


def look_at(eye, target, up=(0.0, 1.0, 0.0)):
    eye, target, up = (np.asarray(v, dtype=np.float64) for v in (eye, target, up))
    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


def perspective(fovy_deg, aspect, near, far):
    f = 1.0 / np.tan(np.radians(fovy_deg) / 2)
    m = np.zeros((4, 4))
    m[0, 0], m[1, 1] = f / aspect, f
    m[2, 2], m[2, 3] = (far + near) / (near - far), 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


class Canvas:
    def __init__(self, width, height, background=(0, 0, 0, 0)):
        self.w, self.h = width, height
        self.color = np.zeros((height, width, 4), dtype=np.float32)
        self.color[:] = np.asarray(background, dtype=np.float32) / 255.0
        self.depth = np.full((height, width), np.inf, dtype=np.float64)

    def draw(self, verts, normals, uvs, tris, texture, mvp, light_dir,
             alpha_test=0.35, double_sided=True, ambient=0.55, shade=0.45):
        """verts/normals: (N,3) 월드 좌표, uvs (N,2), tris (M,3), texture (H,W,4) float 0..1."""
        n = len(verts)
        clip = np.hstack([verts, np.ones((n, 1))]) @ mvp.T
        wc = clip[:, 3]
        ndc = clip[:, :3] / wc[:, None]
        sx = (ndc[:, 0] * 0.5 + 0.5) * self.w
        sy = (1 - (ndc[:, 1] * 0.5 + 0.5)) * self.h
        light = np.asarray(light_dir, dtype=np.float64)
        light /= np.linalg.norm(light)
        lam = normals @ light
        th, tw = texture.shape[:2]

        t = tris[(wc[tris] > 1e-4).all(axis=1)]
        x0, x1, x2 = sx[t[:, 0]], sx[t[:, 1]], sx[t[:, 2]]
        y0, y1, y2 = sy[t[:, 0]], sy[t[:, 1]], sy[t[:, 2]]
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        keep = np.abs(area) > 1e-9
        if not double_sided:
            keep &= area < 0
        t, area = t[keep], area[keep]
        minx = np.clip(np.floor(np.minimum(np.minimum(sx[t[:, 0]], sx[t[:, 1]]), sx[t[:, 2]])), 0, self.w - 1).astype(int)
        maxx = np.clip(np.ceil(np.maximum(np.maximum(sx[t[:, 0]], sx[t[:, 1]]), sx[t[:, 2]])), 0, self.w - 1).astype(int)
        miny = np.clip(np.floor(np.minimum(np.minimum(sy[t[:, 0]], sy[t[:, 1]]), sy[t[:, 2]])), 0, self.h - 1).astype(int)
        maxy = np.clip(np.ceil(np.maximum(np.maximum(sy[t[:, 0]], sy[t[:, 1]]), sy[t[:, 2]])), 0, self.h - 1).astype(int)

        for k in range(len(t)):
            if maxx[k] < minx[k] or maxy[k] < miny[k]:
                continue
            i0, i1, i2 = t[k]
            xs = np.arange(minx[k], maxx[k] + 1) + 0.5
            ys = np.arange(miny[k], maxy[k] + 1) + 0.5
            px, py = np.meshgrid(xs, ys)
            a = area[k]
            w0 = ((sx[i1] - px) * (sy[i2] - py) - (sx[i2] - px) * (sy[i1] - py)) / a
            w1 = ((sx[i2] - px) * (sy[i0] - py) - (sx[i0] - px) * (sy[i2] - py)) / a
            w2 = 1 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not inside.any():
                continue
            z = w0 * ndc[i0, 2] + w1 * ndc[i1, 2] + w2 * ndc[i2, 2]
            region = self.depth[miny[k]:maxy[k] + 1, minx[k]:maxx[k] + 1]
            mask = inside & (z < region)
            if not mask.any():
                continue
            # 원근 보정 보간
            iw0, iw1, iw2 = w0 / wc[i0], w1 / wc[i1], w2 / wc[i2]
            s = iw0 + iw1 + iw2
            u = (iw0 * uvs[i0, 0] + iw1 * uvs[i1, 0] + iw2 * uvs[i2, 0]) / s
            v = (iw0 * uvs[i0, 1] + iw1 * uvs[i1, 1] + iw2 * uvs[i2, 1]) / s
            tu = np.clip((u % 1.0) * tw, 0, tw - 1).astype(int)
            tv = np.clip((v % 1.0) * th, 0, th - 1).astype(int)
            texel = texture[tv, tu]
            mask &= texel[..., 3] > alpha_test
            if not mask.any():
                continue
            l = (iw0 * lam[i0] + iw1 * lam[i1] + iw2 * lam[i2]) / s
            if double_sided:
                l = np.abs(l)
            # 2단 툰 느낌: 부드러운 램버트를 살짝 계단화
            l = np.clip(l, 0, 1)
            l = np.round(l * 3) / 3 * 0.6 + l * 0.4
            lit = ambient + shade * l
            rgb = np.clip(texel[..., :3] * lit[..., None], 0, 1)
            region[mask] = z[mask]
            out = self.color[miny[k]:maxy[k] + 1, minx[k]:maxx[k] + 1]
            out[mask, :3] = rgb[mask]
            out[mask, 3] = 1.0

    def draw_sprites(self, centers, sizes, colors, texture, mvp, additive=True):
        """카메라를 향한 정사각 파티클. 깊이 테스트만 하고 깊이는 쓰지 않는다(반투명).

        centers (N,3) 월드 좌표, sizes (N,) 월드 단위 지름, colors (N,4) 0..1, texture (H,W,4).
        """
        if len(centers) == 0:
            return
        clip = np.hstack([centers, np.ones((len(centers), 1))]) @ mvp.T
        wc = clip[:, 3]
        th, tw = texture.shape[:2]
        for i in np.nonzero(wc > 1e-3)[0]:
            ndc = clip[i, :3] / wc[i]
            cx = (ndc[0] * 0.5 + 0.5) * self.w
            cy = (1 - (ndc[1] * 0.5 + 0.5)) * self.h
            half = 0.5 * sizes[i] * mvp[1, 1] / wc[i] * (self.h / 2)
            if half < 0.5 or colors[i, 3] <= 1e-3:
                continue
            x0, x1 = int(max(np.floor(cx - half), 0)), int(min(np.ceil(cx + half), self.w - 1))
            y0, y1 = int(max(np.floor(cy - half), 0)), int(min(np.ceil(cy + half), self.h - 1))
            if x1 < x0 or y1 < y0:
                continue
            u = ((np.arange(x0, x1 + 1) + 0.5) - (cx - half)) / (2 * half)
            v = ((np.arange(y0, y1 + 1) + 0.5) - (cy - half)) / (2 * half)
            tu = np.clip((u * tw).astype(int), 0, tw - 1)
            tv = np.clip((v * th).astype(int), 0, th - 1)
            inside = ((u >= 0) & (u <= 1))[None, :] & ((v >= 0) & (v <= 1))[:, None]
            texel = texture[tv[:, None], tu[None, :]]
            visible = inside & (ndc[2] < self.depth[y0:y1 + 1, x0:x1 + 1])
            a = texel[..., 3] * colors[i, 3] * visible
            rgb = texel[..., :3] * colors[i, :3]
            self._blend(self.color[y0:y1 + 1, x0:x1 + 1], rgb, a, additive)

    @staticmethod
    def _blend(out, rgb, a, additive):
        if additive:
            out[..., :3] += rgb * a[..., None]
            out[..., 3] = np.maximum(out[..., 3], np.clip(a * rgb.max(axis=-1), 0, 1))
        else:
            out[..., :3] = out[..., :3] * (1 - a[..., None]) + rgb * a[..., None]
            out[..., 3] = out[..., 3] + a * (1 - out[..., 3])

    def draw_quad(self, corners, texture, color, mvp, additive=True):
        """월드 좌표 사각형(corners (4,3), UV 0,0→1,0→1,1→0,1)을 블렌딩해 그린다. 깊이는 쓰지 않는다."""
        uvs = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
        clip = np.hstack([corners, np.ones((4, 1))]) @ mvp.T
        wc = clip[:, 3]
        if (wc <= 1e-3).any() or color[3] <= 1e-3:
            return
        ndc = clip[:, :3] / wc[:, None]
        sx = (ndc[:, 0] * 0.5 + 0.5) * self.w
        sy = (1 - (ndc[:, 1] * 0.5 + 0.5)) * self.h
        th, tw = texture.shape[:2]
        for i0, i1, i2 in ((0, 1, 2), (0, 2, 3)):
            tri = [i0, i1, i2]
            area = (sx[i1] - sx[i0]) * (sy[i2] - sy[i0]) - (sx[i2] - sx[i0]) * (sy[i1] - sy[i0])
            if abs(area) < 1e-9:
                continue
            x0, x1 = int(max(np.floor(sx[tri].min()), 0)), int(min(np.ceil(sx[tri].max()), self.w - 1))
            y0, y1 = int(max(np.floor(sy[tri].min()), 0)), int(min(np.ceil(sy[tri].max()), self.h - 1))
            if x1 < x0 or y1 < y0:
                continue
            px, py = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            w0 = ((sx[i1] - px) * (sy[i2] - py) - (sx[i2] - px) * (sy[i1] - py)) / area
            w1 = ((sx[i2] - px) * (sy[i0] - py) - (sx[i0] - px) * (sy[i2] - py)) / area
            w2 = 1 - w0 - w1
            inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not inside.any():
                continue
            z = w0 * ndc[i0, 2] + w1 * ndc[i1, 2] + w2 * ndc[i2, 2]
            iw0, iw1, iw2 = w0 / wc[i0], w1 / wc[i1], w2 / wc[i2]
            s = iw0 + iw1 + iw2
            u = (iw0 * uvs[i0, 0] + iw1 * uvs[i1, 0] + iw2 * uvs[i2, 0]) / s
            v = (iw0 * uvs[i0, 1] + iw1 * uvs[i1, 1] + iw2 * uvs[i2, 1]) / s
            texel = texture[np.clip((v * th).astype(int), 0, th - 1), np.clip((u * tw).astype(int), 0, tw - 1)]
            visible = inside & (z < self.depth[y0:y1 + 1, x0:x1 + 1])
            a = texel[..., 3] * color[3] * visible
            self._blend(self.color[y0:y1 + 1, x0:x1 + 1], texel[..., :3] * color[:3], a, additive)

    def draw_tris(self, verts, uvs, tris, texture, color, mvp, additive=True):
        """블렌딩 텍스처 삼각형 메시(메시형 파티클). 깊이 테스트만 하고 깊이는 쓰지 않는다."""
        clip = np.hstack([verts, np.ones((len(verts), 1))]) @ mvp.T
        wc = clip[:, 3]
        if color[3] <= 1e-3:
            return
        th, tw = texture.shape[:2]
        for i0, i1, i2 in tris:
            if min(wc[i0], wc[i1], wc[i2]) <= 1e-3:
                continue
            tri = [i0, i1, i2]
            ndc = clip[tri, :3] / wc[tri, None]
            sx = (ndc[:, 0] * 0.5 + 0.5) * self.w
            sy = (1 - (ndc[:, 1] * 0.5 + 0.5)) * self.h
            area = (sx[1] - sx[0]) * (sy[2] - sy[0]) - (sx[2] - sx[0]) * (sy[1] - sy[0])
            if abs(area) < 1e-9:
                continue
            x0, x1 = int(max(np.floor(sx.min()), 0)), int(min(np.ceil(sx.max()), self.w - 1))
            y0, y1 = int(max(np.floor(sy.min()), 0)), int(min(np.ceil(sy.max()), self.h - 1))
            if x1 < x0 or y1 < y0:
                continue
            px, py = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            w0 = ((sx[1] - px) * (sy[2] - py) - (sx[2] - px) * (sy[1] - py)) / area
            w1 = ((sx[2] - px) * (sy[0] - py) - (sx[0] - px) * (sy[2] - py)) / area
            w2 = 1 - w0 - w1
            inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not inside.any():
                continue
            z = w0 * ndc[0, 2] + w1 * ndc[1, 2] + w2 * ndc[2, 2]
            iw = [w0 / wc[i0], w1 / wc[i1], w2 / wc[i2]]
            s = iw[0] + iw[1] + iw[2]
            u = (iw[0] * uvs[i0, 0] + iw[1] * uvs[i1, 0] + iw[2] * uvs[i2, 0]) / s
            v = (iw[0] * uvs[i0, 1] + iw[1] * uvs[i1, 1] + iw[2] * uvs[i2, 1]) / s
            texel = texture[np.clip(((v % 1.0) * th).astype(int), 0, th - 1),
                            np.clip(((u % 1.0) * tw).astype(int), 0, tw - 1)]
            visible = inside & (z < self.depth[y0:y1 + 1, x0:x1 + 1])
            a = texel[..., 3] * color[3] * visible
            self._blend(self.color[y0:y1 + 1, x0:x1 + 1], texel[..., :3] * color[:3], a, additive)

    def to_image(self):
        from PIL import Image
        return Image.fromarray((np.clip(self.color, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGBA')
