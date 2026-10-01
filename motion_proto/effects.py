"""스킬 이펙트 타임라인 + 근사 파티클 시뮬레이션.

이펙트 트리거 출처:
  1) 애니메이션 이벤트 xml (animation.ipf/pc/<job>/<motion>.xml) 의 <Particle frame attachNode particleName scale>
  2) skill_bytool / pad_skill_list 의 C_EFFECT_POS, C_PAD_EFFECT_POS — 스킬↔모션 매핑이 필요해 MOTION_EXTRA_EVENTS 로 수동 등록
이펙트 메타: effect.ipf/forkparticle/forkparticle.xml (<Particle name file time scale ...>)
파티클 동작은 psb.py 의 추정 필드를 쓰는 근사 재현이다(원본 Fork Particle 런타임과 다름).
"""
import io
import re
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

import psb
import unity_fx

FPS_EVENT = 30.0          # 애니메이션 이벤트 xml 의 frame 단위
UNIT = 0.25               # Fork 파티클 단위 → 모델 단위 (시각 보정값)
MAX_PARTICLES = 160       # 이미터당 프레임 최대 파티클

# skill_bytool / pad 스크립트에서 옮긴 이벤트 (time 초, 모션 시작 기준)
MOTION_EXTRA_EVENTS = {
    # priest.xml Priest_Blessing: C_EFFECT_POS Time=700 F_cleric_blessing_spread_out Arg=1.2, Pos Dist=0
    'cleric_m_mns_skl_blessing': [
        dict(time=0.7, name='F_cleric_blessing_spread_out', scale=1.2, anchor='ground', dist=0.0),
    ],
    # chaplain.xml Chaplain_MagnusExorcismus: Time=500 PAD_SEARCH_AND_CHANGE(Priest_Exorcise → Magnus, Dist=20)
    # pad_skill_list.xml Chaplain_MagnusExorcismus createEvent: burstup 1.3, explosion 1.3
    # 전제: 앞에 Priest_Exorcise 패드(F_cleric_exorcise_loop_ground 0.6)가 깔려 있어야 시전 가능
    'cleric_m_mns_skl_magnusexorcismus': [
        dict(time=0.0, name='F_cleric_exorcise_loop_ground', scale=0.6, anchor='ground', dist=20.0, until=0.5),
        dict(time=0.5, name='F_cleric_MagnusExorcismus_shot_burstup', scale=1.3, anchor='ground', dist=20.0),
        dict(time=0.5, name='F_cleric_MagnusExorcismus_shot_explosion', scale=1.3, anchor='ground', dist=20.0),
    ],
}


# 스킬 스크립트(skill_bytool) 이펙트. phase 'start' = 첫 모션 시작(KeyInputStart), 'shot' = *_shot 모션 시작(MainSkl).
# dist/height 는 캐릭터 정면 기준 오프셋, until_phase 는 C_EFFECT_DETACH 시점.
SKILL_EVENTS = {
    # skill_bytool.ipf/bowmaster.xml BowMaster_GodArrow
    'BowMaster_GodArrow': [
        dict(phase='start', time=0.0, name='eff_pc_elementalist_attack_projectile', scale=1.5,
             anchor='node:Dummy_R_HAND', until_phase='shot'),
        dict(phase='start', time=0.0, name='BodyAura_AngelFeather_Blue_01', scale=2.5,
             anchor='node:Dummy_R_HAND', until_phase='shot'),
        dict(phase='start', time=0.0, name='SpinningSwing_Normal_Cyan_01', scale=4.0,
             anchor='node:Dummy_emitter', until_phase='shot'),
        dict(phase='start', time=0.0, name='GroundAura_AngelFeather_Blue_01', scale=0.5,
             anchor='node:Dummy_emitter', until_phase='shot'),
        dict(phase='start', time=0.0, name='ShieldSphere_Galaxy_Purple_02', scale=0.5,
             anchor='node:Dummy_R_HAND', until_phase='shot'),
        dict(phase='start', time=0.0, name='eff_monster_velclipse_sealed_map_projectile_01', scale=0.5,
             anchor='node:Dummy_R_HAND', dist=15.0, height=3.0, until_phase='shot'),
        dict(phase='shot', time=0.0, name='Shockwave_Wind_White_02', scale=1.5, anchor='node:Dummy_emitter'),
        dict(phase='shot', time=0.0, name='eff_pc_archer_hit_blue', scale=1.2, anchor='node:Dummy_R_HAND'),
        dict(phase='shot', time=0.0, name='eff_pc_archer_hit_blue', scale=0.8, anchor='node:Dummy_L_HAND'),
        dict(phase='shot', time=0.0, name='eff_vehicle_helio_griffin_born_01', scale=1.0, anchor='node:Dummy_emitter'),
        dict(phase='shot', time=0.0, name='eff_pc_wizard_energyblast', scale=0.8, anchor='node:Dummy_emitter'),
        dict(phase='shot', time=0.1, name='AerialExplosion_AngelFeather_White_01', scale=1.5,
             anchor='node:Dummy_emitter', dist=-20.0, height=20.0),
        dict(phase='shot', time=0.2, name='AerialExplosion_AngelFeather_White_01', scale=1.5,
             anchor='node:Dummy_emitter', dist=-10.0, height=20.0),
        dict(phase='shot', time=0.2, name='Tackle_Normal_White_01', scale=1.1, anchor='node:Dummy_emitter', dist=30.0),
        dict(phase='shot', time=0.45, name='Tackle_Normal_White_01', scale=1.0, anchor='node:Dummy_emitter', dist=60.0),
        dict(phase='shot', time=0.6, name='Tackle_Normal_White_01', scale=0.9, anchor='node:Dummy_emitter', dist=90.0),
    ],
}


def phase_events(events, phases):
    """단계 기준 이벤트를 절대 시각으로. phases: {'start': 0.0, 'shot'|'main': 초}.
    until_phase 만 있으면 그 단계 시작, until 도 있으면 그 단계 기준 시각에 끝낸다."""
    out = []
    for ev in events:
        e = {k: v for k, v in ev.items() if k not in ('phase', 'until_phase')}
        base = phases.get(ev.get('phase', 'start'), 0.0)
        e['time'] = base + ev['time']
        if 'until_phase' in ev:
            e['until'] = max(phases.get(ev['until_phase'], e['time']) + ev.get('until', 0.0), e['time'])
        elif 'until' in ev:
            e['until'] = base + ev['until']
        out.append(e)
    return out


def skill_events(skill, phases):
    """SKILL_EVENTS 를 절대 시각 이벤트로. phases: {'start': 0.0, 'shot': 초}"""
    return phase_events(SKILL_EVENTS.get(skill, []), phases)


class EffectLibrary:
    def __init__(self, assets):
        self.assets = assets
        self.unity = unity_fx.UnityLibrary(assets)
        self.meta = {}
        raw = assets.bytes('effect.ipf/forkparticle/forkparticle.xml').decode('utf-8', 'replace')
        for m in re.finditer(r'<Particle\s+([^>]*?)/>', raw):
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            if 'name' in attrs:
                self.meta.setdefault(attrs['name'].lower(), attrs)
        self._psb = {}
        self._tex = {}

    def info(self, name):
        attrs = self.meta.get(name.lower(), {})

        def num(key, default):
            try:
                return float(attrs.get(key, default))
            except ValueError:
                return default
        return dict(file=attrs.get('file', name), time=num('time', 0.0), scale=num('scale', 1.0),
                    looptime=num('looptime', 0.0))

    def emitters(self, name):
        f = self.info(name)['file'].lower()
        if f not in self._psb:
            try:
                self._psb[f] = psb.load(self.assets.bytes('effect.ipf/forkparticle/psb/%s.psb' % f))
            except KeyError:
                self._psb[f] = []
        return self._psb[f]

    def texture(self, name):
        key = name.lower()
        if key not in self._tex:
            tex = None
            for folder in ('effect.ipf/forkparticle/texture/', 'effect.ipf/high/texture/'):
                try:
                    img = Image.open(io.BytesIO(self.assets.bytes(folder + key))).convert('RGBA')
                    tex = np.asarray(img, dtype=np.float32) / 255.0
                    break
                except (KeyError, OSError):
                    continue
            self._tex[key] = tex
        return self._tex[key]


def animation_events(assets, job, motion):
    """애니메이션 이벤트 xml 의 Particle 트리거."""
    try:
        raw = assets.bytes('animation.ipf/pc/%s/%s.xml' % (job, motion))
    except KeyError:
        return []
    events = []
    root = ET.fromstring(raw.decode('utf-8', 'replace').split('?>', 1)[-1])
    for p in root.iter('Particle'):
        attach = p.get('attachNode', 'None')
        events.append(dict(time=float(p.get('frame', 0)) / FPS_EVENT, name=p.get('particleName'),
                           scale=float(p.get('scale', 1)),
                           anchor=('node:' + attach) if attach not in ('None', '') else 'root', dist=0.0))
    return events


def motion_events(assets, job, motion, extra=True):
    """extra=False: 스킬 스크립트 이벤트를 계획(skill_plan)에서 따로 받을 때 수동 등록분을 빼서 중복을 막는다."""
    events = animation_events(assets, job, motion)
    return events + MOTION_EXTRA_EVENTS.get(motion.lower(), []) if extra else events


def event_duration(lib, ev, default_life):
    info = lib.info(ev['name'])
    dur = info['time'] if info['time'] > 0 else default_life
    if 'until' in ev:
        dur = min(dur, ev['until'] - ev['time'])
    return dur


class Simulator:
    """이벤트별 파티클을 결정적(시드 고정)으로 생성해 프레임마다 그린다."""

    def __init__(self, lib, events):
        self.lib = lib
        self.events = []
        for i, ev in enumerate(events):
            unity = lib.unity.effect(ev['name'])
            if unity is not None:
                dur = unity.natural_duration()
                if 'until' in ev:
                    dur = ev['until'] - ev['time']
                if dur > 0:
                    self.events.append(dict(ev, unity=unity, emitters=[], duration=dur, seed=1000 + i))
                continue
            ems = lib.emitters(ev['name'])
            if not ems:
                continue
            life = max(e.life for e in ems)
            self.events.append(dict(ev, emitters=ems, duration=event_duration(lib, ev, life),
                                    scale=ev['scale'] * lib.info(ev['name'])['scale'], seed=1000 + i))

    def end_time(self):
        return max([ev['time'] + ev['duration'] for ev in self.events] + [0.0])

    def particles(self, ev, anchor_pos, t):
        """시각 t 에 살아 있는 파티클 [(emitter, centers, sizes, colors)]."""
        local_t = t - ev['time']
        if local_t < 0 or local_t > ev['duration']:
            return []
        out = []
        s = ev['scale'] * UNIT
        for k, em in enumerate(ev['emitters']):
            life = min(em.life, max(ev['duration'], 0.1))
            rate = em.rate
            n_total = int(np.ceil(ev['duration'] * rate)) + 1
            births = np.arange(n_total) / rate
            alive = (births <= local_t) & (local_t - births < life)
            idx = np.nonzero(alive)[0][-MAX_PARTICLES:]
            if len(idx) == 0:
                continue
            rng = np.random.default_rng(ev['seed'] * 31 + k)
            dirs = rng.normal(size=(n_total, 3))
            dirs /= np.linalg.norm(dirs, axis=1, keepdims=True).clip(1e-6)
            if em.bbox is not None:
                lo, hi = em.bbox
                targets = lo + (hi - lo) * rng.random((n_total, 3))
            else:
                # 범위 정보가 없는 이미터는 속도×수명이 과하게 커서(화면 밖으로 튐) 이동량을 줄인다
                targets = dirs * min(em.speed * life * 0.15, 40.0)
            age = (local_t - births[idx]) / life
            offset = em.local[:3, 3]
            # 파티클은 이미터 위치에서 목표점(범위 안 임의 점)으로 감속 이동
            travel = 1 - (1 - age) ** 2
            pos = offset + targets[idx] * travel[:, None]
            if em.flat:
                pos[:, 1] = offset[1]   # 바닥 판은 높이를 이미터 높이에 고정
            centers = anchor_pos + pos * s
            sizes = np.array([psb.interp_keys(em.size_keys, a) for a in age]).reshape(-1) * s
            colors = np.array([psb.interp_keys(em.color_keys, a) for a in age]).reshape(-1, 4)
            # 이벤트 끝 0.25초 페이드아웃
            fade = np.clip((ev['duration'] - local_t) / 0.25, 0, 1)
            colors[:, 3] *= fade
            out.append((em, centers, sizes, colors))
        return out

    def draw(self, canvas, mvp, anchors, t):
        """anchors: callable(event) → (월드 위치, 3x3 기준 축[right, up, forward] 열벡터)."""
        for ev in self.events:
            local_t = t - ev['time']
            if local_t < 0 or local_t > ev['duration']:
                continue
            origin, basis = anchors(ev)
            if ev.get('unity') is not None:
                ev['unity'].draw(canvas, mvp, origin, basis, ev['scale'], local_t, ev['duration'], ev['seed'])
                continue
            for em, centers, sizes, colors in self.particles(ev, origin, t):
                tex = self.lib.texture(em.texture) if em.texture else None
                if tex is None:
                    continue
                if em.flat:
                    for c, size, col in zip(centers, sizes, colors):
                        h = size / 2
                        corners = c + np.array([[-h, 0.3, -h], [h, 0.3, -h], [h, 0.3, h], [-h, 0.3, h]])
                        canvas.draw_quad(corners, tex, col, mvp, additive=em.additive)
                else:
                    canvas.draw_sprites(centers, sizes, colors, tex, mvp, additive=em.additive)
