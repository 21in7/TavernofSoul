"""사이트 스킬 목록 → 스킬별 렌더 계획(JSON) 자동 생성.

batch_render.py 는 이 계획 파일과 렌더용 인덱스만 보고 렌더하므로, 게임 데이터 언팩(ktos_unpack)과
사이트 JSON 은 계획을 만드는 이 서버에서만 필요하다.

모션 결정 (클라이언트 데이터에서 확인한 규칙):
  - 파일 = animation.ipf/pc/<직업>/<직업>_<자세 코드>_<애니 이름>.xsm
    자세 코드는 stance.ies Animation 열(OneHandMaceShield → mns, TwoHandBow → thb ...).
  - 시작(KeyInputStart/KeyInput): MONSKL_C_PLAY_ANIM*, MONSKL_C_CASTING_ANIM, MONSKL_C_RESERVE_ANIM 의 첫 Str,
    skill.ies CastFileName/CastLoopFileName.
  - 본 동작(MainSkl): Time<=100ms 에 재생하는 <Anim>/MONSKL_C_PLAY_ANIM* → skill.ies FileName → 나머지 재생 애니.
  - *_cast 뒤에 같은 이름 *_loop 가 있으면 loop 를 1초 이상 반복해 넣는다(차지형).
  - 자세는 ReqStance 중 모션 파일이 있는 첫 자세, 없으면 계열 기본 자세 순서. 계열 폴더에 없으면 다른 남캐 폴더도 찾는다.

이펙트 (스킬 스크립트·패드 → effects 이벤트). 인자 위치는 스크립트 샘플로 확인했지만,
투사체 비행 시간·목표 거리처럼 서버 로직(타깃 위치)에 달린 값은 추정이다:
  C_EFFECT / C_EFFECT_ATTACH / C_UNITY_EFFECT_NODE / C_ADD_UNITY_EFFECT    → 노드 부착
  C_EFFECT_POS / C_SR_EFT / EFFECT_POS_ROTATE / C_UNITY_EFFECT_POS(_ATTACH) → 캐릭터 기준 위치
  EFT_AND_HIT(_ARROW)                                                      → 지면 위치(발생 → 지연 후 타격)
  MSL_THROW / MSL_THROW_SYNC / MSL_PAD_THROW / MSL_FALL / C_FORCE_EFT        → 투사체(선형 이동) + 도착 이펙트
  MONSKL_CRE_PAD                                                           → pad_skill_list.xml createEvent 의 C_PAD_EFFECT_POS
  C_EFFECT_DETACH / C_UNITY_EFFECT_DETACH                                  → 같은 이름 부착 이펙트 종료

사용:
  python3 skill_plan.py --unpack ../ktos_unpack --site-json ../TavernofSoul/JSON_ktos \
      --out plans/ktos_m.json --render-index cache/index_ktos_render.json
"""
import argparse
import csv
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

import ipf_remote

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache')

TREE_JOB = {'Warrior': 'warrior_m', 'Wizard': 'mage_m', 'Archer': 'archer_m', 'Cleric': 'cleric_m', 'Scout': 'scout_m'}
MALE_JOBS = ['warrior_m', 'mage_m', 'archer_m', 'cleric_m', 'scout_m']

# ReqStance 가 비었거나 맞는 모션이 없을 때 시도할 자세(계열 기본 무기 순)
DEFAULT_STANCES = {
    'warrior_m': ['OneHandSwordShield', 'TwoHandSword', 'TwoHandSpear', 'OneHandSpearShield', 'RapierAndShield'],
    'mage_m': ['OneHandStaff', 'TwoHandStick'],
    'archer_m': ['TwoHandBow', 'BowAndShield', 'Musket', 'TwoHandCannon'],
    'cleric_m': ['OneHandMaceShield', 'TwoHandMace'],
    'scout_m': ['DaggerOneHandSword', 'PistolOneHandSword'],
}

# 무기 종류 → 후보 모델(인덱스에 있는 첫 모델). 무기 모델은 남녀 공용(*_f_*)
# 크기(모델 최대 길이)를 재서 기본 무기(글라디우스 61, 메이스 54, 활 53)와 비슷한 것을 골랐다 — 솔미키 단검(59)·로드는 과하게 크다
WEAPON_MODELS = {
    'sword': ['warrior_f_sword_gladius', 'solmiki_sword'],
    'thsword': ['warrior_f_thsword_barbar', 'solmiki_sword_twohand'],
    'spear': ['warrior_f_spear_pilum', 'solmiki_spear'],
    'thspear': ['warrior_f_thspear_halbert', 'solmiki_spear_twohand'],
    'rapier': ['warrior_f_rapier_01'],
    'rod': ['mage_f_rod_lapai', 'solmiki_rod'],
    'staff': ['mage_f_staff_lapai', 'solmiki_staff_twohand'],
    'mace': ['cleric_f_mace_mace', 'solmiki_hammer'],
    'thmace': ['cleric_f_mace_maul_twohand', 'solmiki_hammer_twohand'],
    'bow': ['archer_f_bow_bow1', 'solmiki_bow'],
    'crossbow': ['archer_f_crossbow_crossbow', 'solmiki_crossbow'],
    'musket': ['archer_f_musket_dreyse', 'solmiki_rifle'],
    'cannon': ['archer_f_cannon_cannon', 'solmiki_cannon'],
    'pistol': ['archer_f_pistol_chassepot_1', 'solmiki_pistol'],
    'dagger': ['warrior_f_dagger_dual', 'solmiki_dagger'],
    'shield': ['warrior_f_shield_wooden_buckler', 'solmiki_shied'],
}
CODE_MAIN_WEAPON = {'ths': 'thsword', 'sms': 'sword', 'jns': 'spear', 'tsp': 'thspear', 'rap': 'rapier',
                    'tsf': 'rod', 'tst': 'staff', 'mns': 'mace', 'thm': 'thmace', 'thb': 'bow',
                    'bow': 'crossbow', 'mus': 'musket', 'can': 'cannon'}

IGNORE_ANIMS = {'', 'none', 'astd', 'std', 'arun', 'run', 'wlk'}
PROJECTILE_SCPS = {'MSL_THROW', 'MSL_THROW_SYNC', 'MSL_PAD_THROW', 'MSL_FALL', 'MSL_THROW_SYNC_PAD'}
MAX_EVENTS = 24
LOOP_FILL = 1.0     # 차지 loop 를 채울 최소 시간(초) — 렌더러가 xsm 길이로 반복 횟수를 정한다


def fnum(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def read_ies(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- 스크립트 파싱

def parse_xml(raw):
    text = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else raw
    text = text.lstrip('﻿')
    text = re.sub(r'^<\?xml[^>]*\?>', '', text.strip())
    # Frame ScriptName 속성에 쓰레기 제어문자(\x01 등)가 들어간 파일이 있다(inquisitor.xml 등)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        # 속성값 밖의 맨 & 등 IMC 수작업 XML 오류 보정
        text = re.sub(r'&(?!(amp|lt|gt|quot|apos|#\d+);)', '&amp;', text)
        return ET.fromstring(text)


def scp_args(el):
    """스크립트 인자를 문서 순서대로 [(kind, value, arg)]. kind: s(문자열) n(숫자) p(위치) a(각도)."""
    out = []
    for c in el:
        a = c.attrib
        if c.tag == 'Str':
            out.append(('s', a.get('Str', ''), None))
        elif c.tag == 'Str_Arg':
            out.append(('s', a.get('Str', ''), fnum(a.get('Arg'), 1.0)))
        elif c.tag == 'Num':
            out.append(('n', fnum(a.get('Num')), None))
        elif c.tag == 'Pos':
            out.append(('p', dict(angle=fnum(a.get('Angle')), dist=fnum(a.get('Dist')),
                                  height=fnum(a.get('Height')), postype=fnum(a.get('PosType'))), None))
        elif c.tag in ('Angle', 'Angle_Abs'):
            out.append(('a', fnum(a.get('Angle')), None))
    return out


def split_effect(s):
    """'name#node' / 'name##1' → (name, node or None)."""
    parts = s.split('#')
    name = parts[0].strip()
    node = next((p for p in parts[1:] if p and not p.isdigit()), None)
    return name, node


def usable_effect(name):
    n = (name or '').lower()
    return n not in ('', 'none') and '_sys_' not in n and not n.startswith('i_sys')


def skill_sections(skill):
    """(phase, section element) — 시작 단계 스크립트와 본 동작 스크립트."""
    for tag in ('KeyInputStart', 'KeyInput'):
        for sec in skill.findall(tag):
            yield 'start', sec
    for main in skill.findall('MainSkl'):
        for sec in main.findall('EtcList'):
            yield 'main', sec


def script_time(el):
    return fnum(el.get('Time'), 0.0) / 1000.0


def collect_anims(skill):
    """{'start': [anim...], 'main': [(time, anim)...]}"""
    out = {'start': [], 'main': []}
    for phase, sec in skill_sections(skill):
        for el in sec:
            name = None
            if el.tag == 'Anim':
                name = el.get('Anim')
            elif el.tag in ('Scp', 'ToolScp'):
                scp = el.get('Scp', '')
                if scp.startswith('MONSKL_C_PLAY_ANIM') or scp in ('MONSKL_C_RESERVE_ANIM', 'MONSKL_C_CASTING_ANIM'):
                    strs = [v for k, v, _ in scp_args(el) if k == 's' and v.lower() not in IGNORE_ANIMS]
                    name = strs[0] if strs else None
            if not name or name.lower() in IGNORE_ANIMS:
                continue
            if phase == 'start':
                out['start'].append(name)
            else:
                out['main'].append((script_time(el), name))
    return out


class EventBuilder:
    def __init__(self, pads):
        self.pads = pads
        self.events = []
        self.detach = []   # (phase, time, name)

    def add(self, phase, t, name, scale, anchor, **kw):
        if not usable_effect(name):
            return None
        ev = dict(phase=phase, time=round(t, 3), name=name, scale=round(scale or 1.0, 3), anchor=anchor)
        ev.update({k: round(v, 3) if isinstance(v, float) else v for k, v in kw.items() if v not in (None, 0, 0.0)})
        self.events.append(ev)
        return ev

    @staticmethod
    def offsets(pos, prefix=''):
        if not pos:
            return {}
        return {prefix + 'dist': pos['dist'], prefix + 'angle': pos['angle'], prefix + 'height': pos['height']}

    def script(self, phase, el):
        scp = el.get('Scp', '')
        if scp.startswith(('TOOLTIP_',)) or scp.endswith('_RANGE_PREVIEW'):
            return
        t = script_time(el)
        args = scp_args(el)
        strs = [(v, a) for k, v, a in args if k == 's']
        nums = [v for k, v, _ in args if k == 'n']
        poses = [v for k, v, _ in args if k == 'p']
        pos = poses[0] if poses else None

        if scp in ('C_EFFECT', 'C_EFFECT_ATTACH'):
            if not strs:
                return
            name, node = split_effect(strs[0][0])
            if scp == 'C_EFFECT' and len(strs) > 1 and strs[1][0].lower() not in ('', 'none'):
                node = strs[1][0]
            ev = self.add(phase, t, name, strs[0][1], 'node:' + node if node else 'root')
            if ev is not None and scp == 'C_EFFECT_ATTACH':
                ev['attached'] = True
        elif scp in ('C_EFFECT_POS', 'C_SR_EFT', 'EFFECT_POS_ROTATE'):
            if strs:
                self.add(phase, t, strs[0][0], strs[0][1], 'ground', **self.offsets(pos))
        elif scp in ('C_EFFECT_DETACH', 'C_UNITY_EFFECT_DETACH'):
            if strs:
                self.detach.append((phase, t, split_effect(strs[0][0])[0].lower()))
        elif scp == 'C_UNITY_EFFECT_NODE':
            if not strs:
                return
            name, node = split_effect(strs[0][0])
            node = node or next((v for v, _ in strs[1:] if v.lower() not in ('', 'none')), None)
            ev = self.add(phase, t, name, strs[0][1] if strs[0][1] is not None else 1.0,
                          'node:' + node if node else 'root')
            if ev is not None:
                ev['attached'] = True
        elif scp == 'C_UNITY_EFFECT_ATTACH':
            if not strs:
                return
            where = next((v.upper() for v, _ in strs[1:] if v.upper() in ('BOT', 'MID', 'TOP')), 'BOT')
            anchor = {'BOT': 'ground', 'MID': 'root', 'TOP': 'node:Bip01 Head'}[where]
            ev = self.add(phase, t, strs[0][0], strs[0][1] if strs[0][1] is not None else 1.0, anchor)
            if ev is not None:
                ev['attached'] = True
        elif scp == 'C_UNITY_EFFECT_POS':
            if strs:
                self.add(phase, t, strs[0][0], strs[0][1] if strs[0][1] is not None else 1.0, 'ground',
                         **self.offsets(pos))
        elif scp == 'C_ADD_UNITY_EFFECT':
            if not strs:
                return
            name, node = split_effect(strs[0][0])
            self.add(phase, t, name, strs[0][1], 'node:' + node if node else 'root', **self.offsets(pos))
        elif scp in ('EFT_AND_HIT', 'EFT_AND_HIT_ARROW'):
            effs = [(v, a) for v, a in strs if usable_effect(v)]
            if scp == 'EFT_AND_HIT_ARROW' and len(poses) >= 2:
                src, dst = poses[0], poses[1]
                fly = 0.3
                if effs:
                    self.add(phase, t, effs[0][0], effs[0][1], 'lerp', src='ground', fly=fly, until=t + fly,
                             **self.offsets(src, 'src_'), **self.offsets(dst, 'dst_'))
                for v, a in effs[1:2]:
                    self.add(phase, t + fly, v, a, 'ground', **self.offsets(dst))
                return
            delay = nums[0] / 1000.0 if nums and 50 <= nums[0] <= 1500 else 0.0
            for i, (v, a) in enumerate(effs[:2]):
                self.add(phase, t + (delay if i else 0.0), v, a, 'ground', **self.offsets(pos))
        elif scp in PROJECTILE_SCPS or scp == 'C_FORCE_EFT':
            self.projectile(phase, t, scp, strs, nums, pos)
        elif scp == 'MONSKL_CRE_PAD':
            pad = next((v for v, _ in strs if v), None)
            self.pad(phase, t, pad, pos)

    def projectile(self, phase, t, scp, strs, nums, pos):
        if not strs:
            return
        missile, node = split_effect(strs[0][0])
        if scp == 'C_FORCE_EFT':
            hit = next(((v, a) for v, a in strs[1:] if usable_effect(split_effect(v)[0])), None)
            fly = 0.35
            dst = dict(dist=80.0, angle=0.0, height=10.0)
        else:
            hit = strs[1] if len(strs) > 1 else None
            fly = nums[1] if len(nums) > 1 and 0.1 <= nums[1] <= 3.0 else 0.5
            fly = min(max(fly, 0.15), 1.2)
            dst = dict(pos or {}, dist=(pos or {}).get('dist') or 60.0)
            dst.setdefault('angle', 0.0)
            dst.setdefault('height', 0.0)
        if scp == 'MSL_FALL':
            self.add(phase, t, missile, strs[0][1], 'lerp', src='above', fly=fly, until=t + fly,
                     **self.offsets(dst, 'dst_'))
        else:
            self.add(phase, t, missile, strs[0][1], 'lerp', src='node:' + (node or 'Dummy_R_HAND'),
                     fly=fly, until=t + fly, **self.offsets(dst, 'dst_'))
        if hit is not None:
            self.add(phase, t + fly, split_effect(hit[0])[0], hit[1], 'ground', **self.offsets(dst))
        if scp == 'MSL_PAD_THROW':
            pad = next((v for v, _ in reversed(strs) if v in self.pads), None)
            if pad:
                self.pad(phase, t + fly, pad, dst)

    def pad(self, phase, t, pad, pos):
        for name, scale, ppos in self.pads.get(pad or '', []):
            off = dict(pos or dict(dist=0.0, angle=0.0, height=0.0))
            off['dist'] = off.get('dist', 0.0) + ppos.get('dist', 0.0)
            off['height'] = off.get('height', 0.0) + ppos.get('height', 0.0)
            self.add(phase, t, name, scale, 'ground', **self.offsets(off))

    def finish(self):
        """부착 이펙트 종료 시각: 같은 이름 DETACH, 시작 단계 부착은 본 동작 시작에서 끝낸다."""
        order = {'start': 0, 'main': 1}
        for ev in self.events:
            if not ev.pop('attached', False):
                continue
            for phase, t, name in self.detach:
                if name == ev['name'].lower() and (order[phase], t) >= (order[ev['phase']], ev['time']):
                    ev['until_phase'], ev['until'] = phase, round(t, 3)
                    break
            else:
                if ev['phase'] == 'start':
                    ev['until_phase'], ev['until'] = 'main', 0.0
        self.events.sort(key=lambda e: (e['phase'] != 'start', e['time']))
        return self.events[:MAX_EVENTS]


def load_pads(raw):
    pads = defaultdict(list)
    root = parse_xml(raw)
    for pad in root.iter('PadSkill'):
        for ev in pad.findall('createEvent'):
            for el in ev:
                if el.get('Scp') == 'C_PAD_EFFECT_POS':
                    args = scp_args(el)
                    strs = [(v, a) for k, v, a in args if k == 's']
                    poses = [v for k, v, _ in args if k == 'p']
                    if strs and usable_effect(strs[0][0]):
                        pads[pad.get('Name')].append((strs[0][0], strs[0][1] or 1.0,
                                                      poses[0] if poses else dict(dist=0.0, height=0.0)))
    return pads


# ---------------------------------------------------------------- 모션 결정

class MotionResolver:
    def __init__(self, index_keys, stances):
        self.names = defaultdict(set)
        for k in index_keys:
            m = re.match(r'animation\.ipf/pc/([a-z]+_m)/([^/]+)\.xsm$', k)
            if m and m.group(1) in MALE_JOBS:
                self.names[m.group(1)].add(m.group(2))
        self.stances = stances   # ClassName → Animation code

    def codes(self, job, req_stances):
        seen, out = set(), []
        for st in list(req_stances) + DEFAULT_STANCES[job]:
            code = self.stances.get(st)
            if code and code != 'NoStance' and code not in seen:
                seen.add(code)
                out.append((code, st))
        return out

    def resolve(self, job, code, anim):
        a = anim.lower()
        for n in ('%s_%s_%s' % (job, code, a), '%s_%s' % (job, a)):
            if n in self.names[job]:
                return n
        return None

    def plan(self, home_job, req_stances, anims, file_names, cast_names, charge):
        main_cands = [n for t, n in sorted(anims['main']) if t <= 0.1] + file_names + [n for _, n in sorted(anims['main'])]
        start_cands = anims['start'] + cast_names
        for job in [home_job] + [j for j in MALE_JOBS if j != home_job]:
            for code, stance in self.codes(job, req_stances):
                main = next((r for r in (self.resolve(job, code, n) for n in main_cands) if r), None)
                starts = []
                for n in start_cands:
                    r = self.resolve(job, code, n)
                    if r and r != main and r not in starts:
                        starts.append(r)
                if main is None and not starts:
                    continue
                segs = []
                for r in starts:
                    segs.append([r, 'auto' if r.endswith('_loop') else 1])
                    if r.endswith('_cast'):
                        loop = r[:-5] + '_loop'
                        if loop in self.names[job] and loop not in starts:
                            segs.append([loop, 'auto'])
                if main is None:
                    base = starts[-1].rsplit('_', 1)[0]
                    main = next((base + s for s in ('_shot', '_end') if base + s in self.names[job]), None)
                elif charge and not segs and main.endswith('_shot'):
                    base = main[:-5]
                    if base + '_cast' in self.names[job]:
                        segs.append([base + '_cast', 1])
                    if base + '_loop' in self.names[job]:
                        segs.append([base + '_loop', 'auto'])
                if main is not None:
                    segs.append([main, 1])
                return dict(job=job, stance=stance, code=code, segments=segs[-4:],
                            main_index=len(segs[-4:]) - 1 if main is not None else None)
        return None


def stance_weapons(stance, code, weapon_keys):
    main = CODE_MAIN_WEAPON.get(code)
    sub = None
    if stance.startswith('Dagger'):
        main = 'dagger'
    elif stance.startswith('Pistol'):
        main = 'pistol'
    if 'Shield' in stance:
        sub = 'shield'
    elif stance.endswith('Dagger') and main != 'dagger':
        sub = 'dagger'
    elif stance.endswith('Pistol') and main != 'pistol':
        sub = 'pistol'
    elif stance == 'BowAndCannon':
        sub = 'cannon'
    elif stance == 'BowAndSword':
        sub = 'sword'
    out = []
    for kind, dummy in ((main, 'Dummy_R_HAND'), (sub, 'Dummy_L_HAND')):
        if not kind:
            continue
        model = next((m for m in WEAPON_MODELS[kind]
                      if 'item_hi.ipf/pc_item/weapon/%s.xac' % m in weapon_keys), None)
        if model:
            out.append([dummy, 'item_hi.ipf/pc_item/weapon/%s.xac' % model, 'item_texture.ipf/'])
    return out


# ---------------------------------------------------------------- 렌더 인덱스

def render_index_keys(items, jobs, job_assets):
    prefixes = ['effect.ipf/', 'assets.ipf/', 'item_hi.ipf/pc_item/weapon/', 'item_texture.ipf/',
                'char_hi.ipf/pc/faces/warrior_m/', 'char_texture.ipf/pc/face/hair_m/']
    for job in jobs:
        prefixes += ['animation.ipf/pc/%s/' % job, 'char_hi.ipf/pc/%s/' % job]
        tex = job_assets.get(job, {}).get('body_tex_dir')
        if tex:
            prefixes.append(tex.lower())
    prefixes = tuple(prefixes)
    return {k: v for k, v in items.items() if k.startswith(prefixes)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--unpack', default=os.path.join(HERE, '..', 'ktos_unpack'))
    ap.add_argument('--site-json', default=os.path.join(HERE, '..', 'TavernofSoul', 'JSON_ktos'))
    ap.add_argument('--index', default=os.path.join(CACHE, 'index_ktos.json'))
    ap.add_argument('--out', default=os.path.join(HERE, 'plans', 'ktos_m.json'))
    ap.add_argument('--render-index', help='렌더에 필요한 엔트리만 남긴 인덱스를 이 경로에 쓴다(배포 패키지용)')
    args = ap.parse_args()

    index = ipf_remote.AssetIndex(args.index)
    stances = {r['ClassName']: r['Animation'] for r in read_ies(os.path.join(args.unpack, 'ies.ipf', 'stance.ies'))}
    skill_ies = {r['ClassName']: r for r in read_ies(os.path.join(args.unpack, 'ies.ipf', 'skill.ies'))}
    with open(os.path.join(args.unpack, 'xml.ipf', 'pad_skill_list.xml'), 'rb') as f:
        pads = load_pads(f.read())

    scripts = {}
    bad = []
    for key in sorted(k for k in index.items if k.startswith('skill_bytool.ipf/') and k.endswith('.xml')):
        try:
            root = parse_xml(index.get(key, CACHE))
        except ET.ParseError as e:
            bad.append((key, str(e)))
            continue
        for sk in root.iter('Skill'):
            scripts.setdefault(sk.get('Name', ''), sk)

    with open(os.path.join(args.site_json, 'skills.json'), encoding='utf-8') as f:
        site_skills = json.load(f)
    with open(os.path.join(args.site_json, 'jobs.json'), encoding='utf-8') as f:
        jobs = json.load(f)
    site_skills = list(site_skills.values()) if isinstance(site_skills, dict) else site_skills
    jobs = {str(j['$ID']): j for j in (jobs.values() if isinstance(jobs, dict) else jobs)}

    resolver = MotionResolver(index.items.keys(), stances)
    weapon_keys = {k for k in index.items if k.startswith('item_hi.ipf/pc_item/weapon/')}

    plans, stats, reasons = [], Counter(), Counter()
    for s in site_skills:
        cls = s['$ID_NAME']
        tree = jobs.get(str(s.get('Link_Job')), {}).get('JobTree')
        entry = dict(skill=cls, id=str(s['$ID']), name=s.get('Name'), icon=s.get('Icon'), tree=tree)
        home = TREE_JOB.get(tree)
        ies = skill_ies.get(cls, {})
        script = scripts.get(cls)
        if home is None:
            entry.update(status='skip', reason='계열 없음')
        else:
            anims = collect_anims(script) if script is not None else {'start': [], 'main': []}
            tokens = lambda v: [t for t in re.split(r'[\s@]+', v or '') if t and not t.isdigit()]
            file_names = tokens(ies.get('FileName'))
            cast_names = tokens(ies.get('CastFileName')) + tokens(ies.get('CastLoopFileName'))
            charge = script is not None and (script.find('KeyInputStart') is not None or script.find('KeyInput') is not None)
            req = [x for x in (s.get('RequiredStance') or ies.get('ReqStance') or '').split(';') if x]
            motion = resolver.plan(home, req, anims, file_names, cast_names, charge)
            if motion is None:
                entry.update(status='skip', reason='모션 없음' if (anims['main'] or anims['start'] or file_names)
                             else '재생 모션 정의 없음(패시브/토글 등)')
            else:
                eb = EventBuilder(pads)
                if script is not None:
                    for phase, sec in skill_sections(script):
                        for el in sec:
                            if el.tag in ('Scp', 'ToolScp'):
                                eb.script(phase, el)
                events = eb.finish()
                # 앞으로 멀리 나가는 이펙트(투사체·전방 지면)가 있으면 옆에서 보는 각도로 이동 방향이 보이게 한다
                far = any(abs(e.get(k, 0.0)) >= 30 for e in events for k in ('dist', 'dst_dist'))
                entry.update(status='ok', motion_job=motion['job'], stance=motion['stance'],
                             segments=motion['segments'], main_index=motion['main_index'],
                             weapons=stance_weapons(motion['stance'], motion['code'], weapon_keys),
                             yaw=250.0 if far else 215.0, events=events)
                if motion['job'] != home:
                    entry['note'] = '계열 폴더(%s)에 모션이 없어 %s 폴더 사용' % (home, motion['job'])
        stats[(tree, entry['status'])] += 1
        if entry['status'] != 'ok':
            reasons[entry['reason']] += 1
        plans.append(entry)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(plans, f, ensure_ascii=False, indent=1)
    ok = [p for p in plans if p['status'] == 'ok']
    print('skills', len(plans), 'ok', len(ok), 'skip', len(plans) - len(ok), dict(reasons))
    print('by tree', sorted(stats.items(), key=str))
    print('with events', sum(1 for p in ok if p['events']), 'events', sum(len(p['events']) for p in ok),
          'no weapons', sum(1 for p in ok if not p['weapons']), 'job fallback', sum(1 for p in ok if 'note' in p))
    if bad:
        print('xml parse errors', len(bad), bad[:3])

    if args.render_index:
        import render_motion
        used = sorted({p['motion_job'] for p in ok})
        items = render_index_keys(index.items, used, render_motion.JOB_ASSETS)
        with open(args.render_index, 'w', encoding='utf-8') as f:
            json.dump(items, f)
        print('render index', len(items), 'entries', os.path.getsize(args.render_index), 'bytes')


if __name__ == '__main__':
    main()
