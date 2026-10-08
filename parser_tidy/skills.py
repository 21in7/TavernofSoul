# -*- coding: utf-8 -*-
"""
Created on Thu Sep 23 08:55:17 2021
@author: CPPG02619
"""

import csv
import logging
import math
import os
import re
import io
from os.path import exists
from DB import ToS_DB as constants
from DB import TOSElement, TOSAttackType
import luautil
import json

EFFECT_DEPRECATE = {
    'SkillAtkAdd': 'SkillFactor'
}

EFFECTS = []
class TOSRequiredStanceCompanion():
    BOTH = 0
    NO = 1
    SELF = 2
    YES = 3

    @staticmethod
    def value_of(string):
        return {
            'BOTH': TOSRequiredStanceCompanion.BOTH,
            '': TOSRequiredStanceCompanion.NO,
            'SELF': TOSRequiredStanceCompanion.SELF,
            'YES': TOSRequiredStanceCompanion.YES,
        }[string.upper()]


def parse(c = None):
    
    is_rebuild = True
    if c == None:
        c = constants()
        c.build('ktest')
        luautil.init(c)
    c.skills={}
    c.skills_by_name={}
    
    # xml_skills가 없으면 초기화
    if 'xml_skills' not in c.data:
        c.data['xml_skills'] = {}
    
    parse_skills(is_rebuild,c)
    # Ensure all skills referenced by skilltree.ies exist in skills_by_name
    fill_missing_skills_from_skilltree(c)
    # Normalize non-numeric/too-long IDs to numeric ClassID
    normalize_skill_ids(c)
    # Ensure Name length fits DB constraints
    normalize_skill_names(c)
    parse_skills_overheats(c)
    parse_skills_simony(c)
    # parse_skills_stances(c)
    parse_links_jobs(c)
    parse_skills_script(c)
    ensure_skill_icons(c)
    fill_missing_from_fallback_regions(c)
    

def fill_missing_skills_from_skilltree(constants):
    """
    Some regions may include new skills referenced in skilltree.ies that don't have
    fully defined base entries during the initial parse. To prevent downstream
    linkages from dropping these skills, synthesize minimal entries using
    available data from skill.ies when possible, otherwise safe defaults.
    """
    try:
        skilltree_path = constants.file_dict['skilltree.ies']['path']
    except Exception:
        return
    try:
        skill_ies_path = constants.file_dict['skill.ies']['path']
    except Exception:
        skill_ies_path = None

    # Index skill.ies rows by ClassName for richer defaults
    skill_rows_by_name = {}
    if skill_ies_path and exists(skill_ies_path):
        with io.open(skill_ies_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f, delimiter=',', quotechar='"'):
                skill_rows_by_name[row['ClassName']] = row

    # Walk skilltree and backfill
    with io.open(skilltree_path, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f, delimiter=',', quotechar='"'):
            if row.get('Type') != 'Skill':
                continue
            skill_name = row['SkillName']
            if skill_name in constants.data['skills_by_name']:
                continue

            src = skill_rows_by_name.get(skill_name)

            obj = {}
            obj['$ID_NAME'] = skill_name
            obj['$ID'] = src['ClassID'] if src and 'ClassID' in src else row.get('ClassID', skill_name)
            obj['Name'] = constants.translate(src['Name']) if src and 'Name' in src else skill_name
            # Try original icon; if missing, will be filled later
            obj['Icon'] = constants.parse_entity_icon(src['Icon']) if src and 'Icon' in src else None
            obj['Description'] = constants.translate(src['Caption']) if src and 'Caption' in src else ''
            obj['Effect'] = constants.translate(src['Caption2']) if src and 'Caption2' in src else ''
            # Basic numerics
            def to_int(val, default=0):
                try:
                    return int(float(val))
                except Exception:
                    return default
            obj['BasicCoolDown'] = to_int(src['BasicCoolDown'], 0) if src and 'BasicCoolDown' in src else 0
            obj['BasicPoison'] = to_int(src['BasicPoison'], 0) if src and 'BasicPoison' in src else 0
            obj['BasicSP'] = to_int(src['BasicSP'], 0) if src and 'BasicSP' in src else 0
            obj['OverHeat'] = 0
            obj['LvUpSpendPoison'] = to_int(src['LvUpSpendPoison'], 0) if src and 'LvUpSpendPoison' in src else 0
            obj['LvUpSpendSp'] = float(src['LvUpSpendSp']) if src and 'LvUpSpendSp' in src and src['LvUpSpendSp'] else 0.0
            obj['SklAtkAdd'] = float(src['SklAtkAdd']) if src and 'SklAtkAdd' in src and src['SklAtkAdd'] else 0.0
            obj['SklAtkAddByLevel'] = float(src['SklAtkAddByLevel']) if src and 'SklAtkAddByLevel' in src and src['SklAtkAddByLevel'] else 0.0
            obj['SklFactor'] = float(src['SklFactor']) if src and 'SklFactor' in src and src['SklFactor'] else 0.0
            obj['SklFactorByLevel'] = float(src['SklFactorByLevel']) if src and 'SklFactorByLevel' in src and src['SklFactorByLevel'] else 0.0
            obj['SklSR'] = float(src['SklSR']) if src and 'SklSR' in src and src['SklSR'] else 0.0
            obj['SpendItemBaseCount'] = to_int(src['SpendItemBaseCount'], 0) if src and 'SpendItemBaseCount' in src else 0
            obj['RequiredStance'] = src['ReqStance'] if src and 'ReqStance' in src else ''
            obj['RequiredStanceCompanion'] = src['EnableCompanion'] if src and 'EnableCompanion' in src else ''
            obj['Keyword'] = src['Keyword'] if src and 'Keyword' in src else ''
            obj['CoolDown'] = src['CoolDown'] if src and 'CoolDown' in src else ''
            obj['IsEnchanter'] = False
            obj['IsPardoner'] = False
            obj['IsRunecaster'] = False
            obj['MaxLevel'] = -1
            obj['UnlockClassLevel'] = -1
            obj['SP'] = None
            obj['TypeAttack'] = []
            # Element
            try:
                obj['Element'] = TOSElement.value_of(src['Attribute']) if src and 'Attribute' in src else TOSElement.MELEE
            except Exception:
                obj['Element'] = TOSElement.MELEE
            obj['Link_Attributes'] = []
            obj['Link_Gem'] = None
            obj['Link_Job'] = None
            obj['other'] = []
            obj['TargetBuffs'] = []

            constants.data['skills'][obj['$ID']] = obj
            constants.data['skills_by_name'][obj['$ID_NAME']] = obj
            if skill_name.startswith('Common_'):
                logging.debug("[FALLBACK] Synthesized missing skill '%s' from skilltree.ies", skill_name)
            else:
                logging.info("[FALLBACK] Synthesized missing skill '%s' from skilltree.ies", skill_name)


def ensure_skill_icons(constants):
    """Guarantee every skill has a non-null Icon. Fill blanks with a safe default."""
    # Prefer using a known generic icon present in assets; fall back to raw key
    default_icon_key_candidates = [
        'icon_common_velcoffer_tiksline',
        'skill_common_unknown',
        'icon_item_skillbook'
    ]
    default_icon_val = None
    for key in default_icon_key_candidates:
        if key in constants.data['assets_icons']:
            default_icon_val = constants.data['assets_icons'][key]
            break
    # If not found in assets, keep the first candidate as plain string
    if default_icon_val is None:
        default_icon_val = default_icon_key_candidates[0]

    for skill in constants.data['skills'].values():
        if not skill.get('Icon'):
            # Store resolved asset value if we have one, else the key string
            skill['Icon'] = default_icon_val
            constants.data['skills_by_name'][skill['$ID_NAME']] = skill
            constants.data['skills'][skill['$ID']] = skill


def fill_missing_from_fallback_regions(constants):
    """Fill missing or placeholder skill Description and Icon using other regions.

    Priority: ktos -> ktest. This helps itos when new content is not yet
    translated or icons are not shipped, so the site can still show rich data.
    """
    # Fallback releases belong to the input project, including isolated builds.
    project_root = os.path.dirname(os.path.normpath(constants.PATH_INPUT_DATA))
    fallback_regions = ['ktos', 'ktest']

    # Preload fallback skill maps and icon maps
    fallback_skills_by_name = {}
    fallback_assets_icons = {}
    for region in fallback_regions:
        try:
            skills_path = os.path.join(project_root, 'TavernofSoul', f'JSON_{region}', 'skills_by_name.json')
            icons_path = os.path.join(project_root, 'TavernofSoul', f'JSON_{region}', 'assets_icons.json')
            with open(skills_path, 'r', encoding='utf-8') as f:
                fb_skills = json.load(f)
            with open(icons_path, 'r', encoding='utf-8') as f:
                fb_icons = json.load(f)
            # Keep first region as higher priority; don't overwrite
            for k, v in fb_skills.items():
                if k not in fallback_skills_by_name:
                    fallback_skills_by_name[k] = v
            for k, v in fb_icons.items():
                if k not in fallback_assets_icons:
                    fallback_assets_icons[k] = v
        except Exception:
            continue

    if not fallback_skills_by_name:
        return

    # Helper to detect untranslated dic tokens
    def looks_like_dic_token(text):
        if text is None:
            return True
        if not isinstance(text, str):
            return False
        lowered = text.lower()
        return lowered.startswith('@dicid_') or lowered.startswith('{@dicid_')

    # Apply fallbacks
    default_icon_key_candidates = [
        'icon_common_velcoffer_tiksline', 'skill_common_unknown', 'icon_item_skillbook'
    ]
    default_icon_set = set(
        [constants.data['assets_icons'].get(k, k) for k in default_icon_key_candidates]
    )

    applied_count = 0
    for skill_name, skill in list(constants.data['skills_by_name'].items()):
        fb = fallback_skills_by_name.get(skill_name)
        if not fb:
            continue

        changed = False
        # Description/Effect fallback: avoid copying KToS text into iTOS; keep empty for EN
        if str(getattr(constants, 'region', '')).lower() not in ('itos',):
            # Only non-itos regions may borrow text
            if (not skill.get('Description')) or looks_like_dic_token(skill.get('Description')):
                if fb.get('Description'):
                    skill['Description'] = fb['Description']
                    changed = True
            if (not skill.get('Effect')) or looks_like_dic_token(skill.get('Effect')):
                if fb.get('Effect'):
                    skill['Effect'] = fb['Effect']
                    changed = True

        # Icon fallback if missing or default placeholder or not in current assets map
        icon_val = skill.get('Icon')
        needs_icon_fb = (
            (not icon_val)
            or (isinstance(icon_val, str) and icon_val in default_icon_set)
            or (isinstance(icon_val, str) and icon_val not in constants.data['assets_icons'])
        )
        if needs_icon_fb and fb.get('Icon'):
            fb_icon = fb['Icon']
            # Merge fallback icon key into current assets if missing
            if isinstance(fb_icon, str) and fb_icon not in constants.data['assets_icons']:
                if fb_icon in fallback_assets_icons:
                    constants.data['assets_icons'][fb_icon] = fallback_assets_icons[fb_icon]
            skill['Icon'] = fb_icon
            changed = True

        if changed:
            applied_count += 1

        # Persist back into both maps
        constants.data['skills_by_name'][skill_name] = skill
        constants.data['skills'][skill['$ID']] = skill

    if applied_count:
        logging.info('[SKILL-FALLBACK] Applied fallback data to %d skills', applied_count)

def normalize_skill_ids(constants):
    """Ensure every skill has numeric $ID (<= 30 chars) using ClassID from skilltree."""
    try:
        skilltree_path = constants.file_dict['skilltree.ies']['path']
    except Exception:
        return
    name_to_classid = {}
    with io.open(skilltree_path, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f, delimiter=',', quotechar='"'):
            if row.get('Type') == 'Skill':
                name_to_classid[row['SkillName']] = str(row['ClassID'])

    rebuilt = {}
    for k, skill in list(constants.data['skills'].items()):
        sid = str(skill.get('$ID', ''))
        if len(sid) > 30 or not sid.isdigit():
            new_id = name_to_classid.get(skill['$ID_NAME'])
            if not new_id:
                digits = ''.join(ch for ch in sid if ch.isdigit())
                new_id = digits if digits else '0'
            skill['$ID'] = str(new_id)
        rebuilt[skill['$ID']] = skill
    constants.data['skills'] = rebuilt


def normalize_skill_names(constants):
    """Clamp overly long Name values (varchar(30)) and prettify from $ID_NAME when needed."""
    def prettify_from_id(id_name):
        # Drop the first segment (usually job prefix) and humanize
        parts = id_name.split('_')
        pretty = ' '.join(parts[1:]) if len(parts) > 1 else id_name
        pretty = pretty.replace('  ', ' ').strip()
        # Title case, keep reasonable length
        pretty = pretty.title()
        return pretty

    for skill in constants.data['skills'].values():
        name = str(skill.get('Name', ''))
        if len(name) <= 30 and name:
            continue
        # Build a better candidate from ID_NAME
        candidate = prettify_from_id(skill.get('$ID_NAME', ''))
        if not candidate:
            candidate = name or skill.get('$ID_NAME', '')
        if len(candidate) > 30:
            candidate = candidate[:30]
        if not candidate:
            candidate = 'Skill'
        skill['Name'] = candidate
        constants.data['skills_by_name'][skill['$ID_NAME']] = skill
        constants.data['skills'][skill['$ID']] = skill


def parse_skills(is_rebuild, constants):
    logging.debug('Parsing skills...')

    LUA_RUNTIME = luautil.LUA_RUNTIME
    LUA_SOURCE = luautil.LUA_SOURCE

    # Preload set of skills referenced by skilltree to decide whether to include Common_ skills
    referenced_by_skilltree = set()
    try:
        st_path = constants.file_dict['skilltree.ies']['path']
        if exists(st_path):
            with io.open(st_path, 'r', encoding='utf-8') as st_file:
                for tr in csv.DictReader(st_file, delimiter=',', quotechar='"'):
                    if tr.get('Type') == 'Skill' and tr.get('SkillName'):
                        referenced_by_skilltree.add(tr['SkillName'])
    except Exception:
        pass

    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'skill.ies')
    ies_path = constants.file_dict['skill.ies']['path']
    if(not exists(ies_path)):
       return
    rows = []
    with io.open(ies_path, 'r', encoding = 'utf-8') as ies_file:
        for row in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
            # Include 'Common_' skills only when referenced in skilltree
            if row['ClassName'].find('Common_') == 0 and row['ClassName'] not in referenced_by_skilltree:
                continue
            rows.append(row)
            obj                 = {}
            obj['$ID']          = row['ClassID']
            obj['$ID_NAME']     = row['ClassName']
            obj['Description']  = constants.translate(row['Caption'])
            obj['Icon']         = constants.parse_entity_icon(row['Icon'])
            obj['Name']         = constants.translate(row['Name'])

            obj['Effect']       = constants.translate(row['Caption2'])
            obj['Element']      = TOSElement.value_of(row['Attribute'])
            obj['IsShinobi']    = row['CoolDown'] == 'SCR_GET_SKL_COOLDOWN_BUNSIN' or (row['CoolDown'] and 'Bunshin_Debuff' in LUA_SOURCE[row['CoolDown']])
            obj['OverHeat']     = {
                'Value': int(row['SklUseOverHeat']),
                'Group': row['OverHeatGroup']
            } if not is_rebuild else int(row['SklUseOverHeat'])  # Re:Build overheat is now simpler to calculate
            obj['BasicCoolDown'] = int(row['BasicCoolDown'])
            obj['BasicPoison']  = int(row['BasicPoison'])
            obj['BasicSP']      = int(math.floor(float(row['BasicSP'])))
            obj['LvUpSpendPoison'] = int(row['LvUpSpendPoison'])
            obj['LvUpSpendSp']  = float(row['LvUpSpendSp'])
            obj['SklAtkAdd']    = float(row['SklAtkAdd'])
            obj['SklAtkAddByLevel'] = float(row['SklAtkAddByLevel'])
            obj['SklFactor']    = float(row['SklFactor'])
            obj['SklFactorByLevel'] = float(row['SklFactorByLevel'])
            obj['SklSR']        = float(row['SklSR'])
            obj['SpendItemBaseCount'] = int(row['SpendItemBaseCount'])
            obj['RequiredStance'] = row['ReqStance']
            obj['RequiredStanceCompanion'] = row['EnableCompanion']
            obj['Keyword']      = row['Keyword']
            obj['CoolDown']     = row['CoolDown']
            obj['IsEnchanter']  = False
            obj['IsPardoner']   = False
            obj['IsRunecaster'] = False
            obj['MaxLevel']     = -1
            obj['UnlockClassLevel'] = -1
            obj['SP']           = None
            obj['TypeAttack']   = []
            obj['Link_Attributes'] = []
            obj['Link_Gem']     = None
            obj['Link_Job']     = None
            obj['other']        = []
            obj['TargetBuffs']  = []
            if row['ClassName'] in constants.data['xml_skills']:
                data                    = constants.data['xml_skills'][row['ClassName']]
                obj['TargetBuffs']      = data['TargetBuffs']


            # Parse TypeAttack
            if row['ValueType'] == 'Buff':
                obj['TypeAttack'].append(TOSAttackType.BUFF)
            if row['ClassType'] is not None:
                obj['TypeAttack'].append(TOSAttackType.value_of(row['ClassType']))
            if row['AttackType'] is not None:
                obj['TypeAttack'].append(TOSAttackType.value_of(row['AttackType']))

            obj['TypeAttack'] = list(set(obj['TypeAttack']))
            obj['TypeAttack'] = [attack for attack in obj['TypeAttack'] if attack is not None and attack != TOSAttackType.UNKNOWN]

            # Add missing Description header
            if not re.match(r'{#.+}{ol}(\[.+?\]){\/}{\/}{nl}', obj['Description']):
                header = ['[' + TOSAttackType.to_string(attack) + ']' for attack in obj['TypeAttack']]

                if obj['Element'] != TOSElement.MELEE:
                    header.append('[' + TOSElement.to_string(obj['Element']) + ']')


            # Parse effects
            for effect in re.findall(r'{(.*?)}', obj['Effect']):
                if effect in EFFECT_DEPRECATE:
                    # Hotfix: sometimes IMC changes which effects are used, however they forgot to properly communicate to the translation team.
                    # This code is responsible for fixing that and warning so the in-game translations can be fixed
                    logging.warning('[%32s] Deprecated effect [%s] in Effect', obj['$ID_NAME'], effect)

                    effect_deprecate = effect
                    effect = EFFECT_DEPRECATE[effect]

                    obj['Effect'] = re.sub(r'\b' + re.escape(effect_deprecate) + r'\b', effect, obj['Effect'])

                if effect in row:
                    key = 'Effect_' + effect

                    # HotFix: make sure all skills have the same Effect columns (1/2)
                    if key not in EFFECTS:
                        EFFECTS.append('Effect_' + effect)

                    if row[effect] != 'ZERO':
                        obj[key] = row[effect]

                    else:
                        # Hotfix: similar to the hotfix above
                        logging.warning('[%32s] Deprecated effect [%s] in Effect', obj['$ID_NAME'], effect)
                        obj[key] = None
                else:
                    continue

            # Parse formulas
            if row['CoolDown']:
                obj['CoolDown'] = row['CoolDown']
            if row['SpendSP']:
                obj['SP'] = row['SpendSP']

            constants.data['skills'][obj['$ID']] = obj
            constants.data['skills_by_name'][obj['$ID_NAME']] = obj

    # HotFix: make sure all skills have the same Effect columns (2/2)
    for skill in constants.data['skills'].values():
        for effect in EFFECTS:
            if effect not in skill:
                skill[effect] = None



def parse_skills_overheats( constants):
    logging.debug('Parsing skills overheats...')
    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'cooldown.ies')
    ies_path = constants.file_dict['cooldown.ies']['path']
    if(not exists(ies_path)):
       return
    with io.open(ies_path, 'r', encoding = 'utf-8') as ies_file:
        for row in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
            # We're only interested in overheats
            if row['IsOverHeat'] != 'YES':
                continue
            skill = None
            for obj in constants.data['skills'].values():
                if isinstance(obj['OverHeat'], (dict,)) and row['ClassName'] == obj['OverHeat']['Group']:
                    skill = obj
                    break
            # If skill isn't available, ignore
            if skill is None:
                continue
            skill['OverHeat'] = int(row['MaxOverTime']) / skill['OverHeat']['Value'] if skill['OverHeat']['Value'] > 0 else 0
    # Clear skills with no OverHeat information
    for skill in constants.data['skills'].values():
        if isinstance(skill['OverHeat'], (dict,)):
            skill['OverHeat'] = 0


def parse_skills_simony(constants):
    logging.debug('Parsing skills simony...')

    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'skill_simony.ies')
    if(not exists(ies_path)):
       return
    with io.open(ies_path, 'r', encoding = 'utf-8') as ies_file:
        for row in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
            if row['ClassID'] not in constants.data['skills']:
                logging.error('Unknown skill: {}'.format( row['ClassID']))
                continue

            skill = constants.data['skills'][row['ClassID']]
            skill['IsEnchanter'] = True
            skill['IsPardoner'] = True
            skill['IsRunecaster'] = True


def parse_skills_stances(constants):
    logging.debug('Parsing skills stances...')

    stance_list = []
    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'stance.ies')
    ies_path = constants.file_dict[ 'stance.ies']['path']
    if(not exists(ies_path)):
       return
    # Parse stances
    with io.open(ies_path, 'r', encoding = 'utf-8') as ies_file:
        for row in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
            stance_list.append(row)

    # Add stances to skills
    # from addon.ipf\skilltree\skilltree.lua :: MAKE_STANCE_ICON
    for skill in constants.data['skills'].values():
        stances_main_weapon = []
        stances_sub_weapon = []

        if skill['RequiredStance']:
            for stance in stance_list:
                if skill['RequiredStance'] == 'TwoHandBow' and stance['ClassName'] == 'Bow':
                    continue
                if 'Artefact' in stance['Name']:
                    continue

                if stance['UseSubWeapon'] == 'NO':
                    stances_main_weapon.append({
                        'Icon': constants.parse_entity_icon(stance['Icon']),
                        'Name': stance['ClassName']
                    })
                else:
                    found = False
                    for stance_sub in stances_sub_weapon:
                        if stance_sub['Icon'] == constants.parse_entity_icon(stance['Icon']):
                            found = True
                            break

                    if not found:
                        stances_sub_weapon.append({
                            'Icon': constants.parse_entity_icon(stance['Icon']),
                            'Name': stance['ClassName']
                        })
        else:
            stances_main_weapon.append({
                'Icon': constants.parse_entity_icon('weapon_All'),
                'Name': 'All'
            })

        if skill['RequiredStanceCompanion'] in [TOSRequiredStanceCompanion.BOTH, TOSRequiredStanceCompanion.YES]:
            stances_main_weapon.append({
                'Icon': constants.parse_entity_icon('weapon_companion'),
                'Name': 'Companion'
            })

        skill['RequiredStance'] = [
            stance for stance in (stances_main_weapon + stances_sub_weapon)
            if stance['Icon'] is not None
        ]

def run_lua(skill, key_special, key_dict):
    LUA_RUNTIME = luautil.LUA_RUNTIME
    LUA_SOURCE = luautil.LUA_SOURCE
    var = []
    if (skill[key_special]):
        if (skill['MaxLevel']==-1):
            skill[key_dict] = []
            return
        try:
            # CaptionRatio 값들은 퍼센트로 변환 필요 여부 확인
            is_caption_ratio = key_dict in ['CaptionRatio', 'CaptionRatio2', 'CaptionRatio3']
            
            for lv in range(0,skill['MaxLevel']+10,1):
                skill['Level'] = lv
                row = LUA_RUNTIME[skill[key_special]](skill) 
                if row == -1:
                    row = 0
                elif (math.isnan(row) ):
                    row = 0
                # CaptionRatio 값이 1보다 작으면 퍼센트로 변환 (0.4 -> 40)
                elif is_caption_ratio and 0 < row < 1:
                    row = row * 100
                var.append(row)
            skill[key_dict] = var
        except:
            skill[key_dict] = []


def parse_skills_script(constants):
    """
    parse skills skill factor caption ratio etc which use lua script
    """
    key_dict = [
        'sfr', 'CaptionRatio', 'CaptionRatio2', 'CaptionRatio3',
        'CaptionTime', 'SkillSR', 'SpendItemCount' ,
        'SpendPoison', 'SpendSP' , 'CoolDown'
    ]
    key_special = [
        'Effect_SkillFactor', 'Effect_CaptionRatio','Effect_CaptionRatio2', 'Effect_CaptionRatio3',
        'Effect_CaptionTime', 'Effect_SkillSR', 'Effect_SpendItemCount', 'Effect_SpendPoison',
        'Effect_SpendSP', 'CoolDown'
    ]

    for g in constants.data['skills'].values():
        for i in range(len(key_dict)):
            try:
                run_lua(g,key_special[i], key_dict[i])
            except:
               pass

            
def parse_links(c=None):
    if c is None:
        c = constants()
        c.build(constants.iTOS)
    parse_links_gems(c)
    c = parse_links_jobs(True,c)

def parse_links_gems(constants):
    logging.debug('Parsing gems for skills...')
    
    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'item_gem.ies')
    ies_path = constants.file_dict['item_gem.ies']['path']
    with io.open(ies_path, 'r', encoding='utf-8') as ies_file:
        for row in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
            skill = row['ClassName'][len('Gem_'):]
            
            if skill not in constants.data['skills_by_name']:
                continue
            
            skill = constants.data['skills_by_name'][skill]
            skill['Link_Gem'] = constants.get_gem_link(row['ClassName'])


def parse_links_jobs(constants):
    logging.debug('Parsing jobs for skills...')
    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'skilltree.ies')
    ies_path = constants.file_dict['skilltree.ies']['path']

    z = []
    with io.open(ies_path, 'r', encoding='utf-8') as ies_file:
        for row in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
            z.append(row)
            # Ignore discarded skills
            if row['SkillName'] not in constants.data['skills_by_name']:
                continue

            skill = constants.data['skills_by_name'][row['SkillName']]
            skill['MaxLevel'] = int(row['MaxLevel'])
            skill['LevelPerGrade'] = int(row['LevelPerGrade']) if 'LevelPerGrade' in row else 0
            skill['UnlockClassLevel'] = int(row['UnlockClassLevel']) if 'UnlockClassLevel' in row else 0
            skill['UnlockGrade'] = int(row['UnlockGrade']) if 'UnlockGrade' in row else 0

            job = '_'.join(row['ClassName'].split('_')[:2])       
            skill['Link_Job'] = constants.data['jobs_by_name'][job]['$ID']
            constants.data['skills_by_name'][row['SkillName']] = skill
            constants.data['skills'][skill['$ID']] = skill
    return constants


def parse_clean(constants):
    skills_to_remove = []
    # Find which skills are no longer active
    for skill in constants.data['skills'].values():
        if skill['Link_Job'] is None:
            skills_to_remove.append(skill)

    # Remove all inactive skills
    for skill in skills_to_remove:
        del constants.data['skills'][str(skill['$ID'])]
        del constants.data['skills_by_name'][skill['$ID_NAME']]

        skill_id = skill['$ID']

        for attribute in constants.data['attributes'].values():
            attr = constants.data['attributes_by_name'][attribute['$ID_NAME']]
            attribute['Link_Skills'] = [link for link in attribute['Link_Skills'] if link != skill_id]
            attr['Link_Skills'] = [link for link in attr['Link_Skills'] if link != skill_id]
        for job in constants.data['jobs'].values():
            job2= constants.data['jobs_by_name'][job['$ID_NAME']]
            job['Link_Skills'] = [link for link in job['Link_Skills'] if link != skill_id]
            job2['Link_Skills'] = [link for link in job2['Link_Skills'] if link != skill_id]
    