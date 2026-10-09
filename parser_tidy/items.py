# -*- coding: utf-8 -*-
"""
Created on Mon Sep 20 11:18:38 2021
@author: Temperantia
"""
import os
from os.path import exists
import logging
from DB import ToS_DB as constants
import csv
import io
import re
import luautil
from math import floor, isfinite
import xml.etree.ElementTree as ET
import parse_xac
import package_parser
# from shared.ipf/item_calculate.lua
EQUIPMENT_STAT_COLUMNS = []

equipment_grade_ratios = {}
goddess_atk_list       = {}

log = logging.getLogger("parse.items")
log.setLevel("INFO")


def safe_item_grade(row, default=1):
    """ItemGrade 를 안전하게 정수로 변환.

    PROFILING_REVIEW P0-5: 이전 parse_equips 는 int(row['ItemGrade']) 를
    먼저 수행하고(331라인) 그 결과를 '' 와 비교하는 도달 불가 분기(368-370)를
    가졌다. 빈 값이면 int() 에서 예외가 발생해 기본값 분기에 도달하지 못했다.

    새 구현:
      - 빈/None -> default
      - 유효 범위(0~6) 밖 -> ValueError(데이터 품질 경고)
      - 정상 -> int

    현재 ktos 10,171행에는 빈 값이 0건이므로 예방 조치다.
    """
    raw = row.get('ItemGrade') if isinstance(row, dict) else row
    if raw is None:
        return default
    s = str(raw).strip()
    if s == '':
        return default
    g = int(s)
    if not (0 <= g <= 6):
        raise ValueError('ItemGrade out of expected range [0,6]: %r' % raw)
    return g

def escaper(string):
    string = str(string)
    escaped = string.translate(str.maketrans({"- ":  r"\-",
                                          "]":  r"\]",
                                          "\\": r"\\",
                                          "^":  r"\^",
                                          "$":  r"\$",
                                          "*":  r"\*",
                                          ".":  r"\.",
                                          "'" : r"\'",
                                          '"' : r'\"',
                                          ',' :r''
                                          
                                          }))
    return escaped

def create_fallback_item(constants, class_name, item_type='ITEM'):
    """Create a minimal fallback item when the base entry is missing."""
    try:
        obj = {}
        # Create a shorter ID to avoid database column length issues (max 30 chars)
        # Use hash of class_name to ensure uniqueness while keeping it short
        import hashlib
        hash_obj = hashlib.md5(class_name.encode())
        short_id = str(int(hash_obj.hexdigest()[:6], 16))  # 6자리 hex를 int로 변환 (최대 16777215)
        obj['$ID'] = short_id
        obj['$ID_NAME'] = class_name
        obj['Name'] = class_name.replace('_', ' ').title()  # Humanize the name
        obj['Description'] = 'Auto-generated fallback for ' + class_name
        obj['Icon'] = None  # Will be filled by ensure_skill_icons equivalent
        obj['Grade'] = 1
        obj['Price'] = 0
        obj['TimeCoolDown'] = 0
        obj['TimeLifeTime'] = None
        obj['Weight'] = ''
        obj['Tradability'] = 'FFFF'  # Not tradable by default
        obj['Type'] = item_type
        
        # Type-specific defaults
        if item_type == 'GEM':
            obj['BonusBoots'] = []
            obj['BonusGloves'] = []
            obj['BonusSubWeapon'] = []
            obj['BonusTopAndBottom'] = []
            obj['BonusWeapon'] = []
            obj['TypeGem'] = 'Gem'
        elif item_type == 'COLLECTION':
            obj['Link_Items'] = []
            obj['Bonus'] = []
        elif item_type == 'RECIPE':
            obj['Link_Target'] = None
            obj['Link_Materials'] = []
        elif item_type == 'BOOK':
            obj['Text'] = ''
            
        return obj
    except Exception as e:
        logging.error("Failed to create fallback item for {}: {}".format(class_name, e))
        return None

def resolve_package_contents(constants):
    """PackageContents_Raw(StringArg 원본)를 구성물 목록으로 확정하는 후처리.

    ITEM_IES 는 set 이라 파일 순회 순서가 비결정적이므로, 구성물 이름 해석은
    모든 아이템 파싱이 끝난 뒤 여기서 일괄 수행한다.

    토큰 문법과 Script 라우팅은 package_parser 모듈이 소유한다.
    이전 rpartition('/') 구현은 item/count/prop/value 형식에서 마지막 값을
    count 로, 그 앞 전체를 item 이름으로 잘못 저장해 259개의 잘못된 참조를
    만들었다. 새 구현은 앞에서부터 item, count 를 읽고 뒤쪽을 property/value
    쌍(인스턴스 옵션)으로 보존한다.

    GROWTH 계열 스크립트는 구성물을 생성하지 않고 growth_selection 범주로만
    보고한다(선택 규칙 확정 전). SET_ACCOUNT_PROP 는 StringArg 가 계정
    속성명(account.ies)이지 Item ClassName 이 아니므로 account_prop 범주로만
    보고한다.
    """
    items_by_name = constants.data['items_by_name']
    resolved = 0
    unresolved_total = 0
    growth_report = []
    account_prop_report = []
    warnings_report = []
    for obj in list(constants.data['items'].values()):
        raw = obj.pop('PackageContents_Raw', None)
        if raw is None:
            continue
        script, string_arg, number_arg1 = raw
        parsed = package_parser.parse_package_stringarg(
            script, string_arg, number_arg1,
        )

        # GROWTH 범주: 보고만 하고 구성물 미생성.
        if parsed['kind'] == 'growth_selection':
            growth_report.append(obj['$ID_NAME'])
            for w in parsed['warnings']:
                log.warning('package growth (not interpreted): %s', w)
            continue

        # ACCOUNT_PROP 범주: StringArg 가 계정 속성이므로 구성물 미생성.
        if parsed['kind'] == 'account_prop':
            account_prop_report.append(obj['$ID_NAME'])
            for w in parsed['warnings']:
                log.warning('package account_prop (not an item): %s', w)
            continue

        # 일반/random 구성물 해석.
        # items_by_name 에 존재하는 참조만 정상 항목(items)으로 계산하고,
        # 존재하지 않는 참조(만료 이벤트 Item 등)는 원문(item/count/options)을
        # 보존한 채 unresolved 로 분리한다. 가짜 fallback item 은 만들지 않는다.
        entries = []
        unresolved = []
        for it in parsed['items']:
            class_name = it['item']
            ref = items_by_name.get(class_name)
            if ref is not None:
                entries.append({
                    'item': class_name,
                    'name': ref['Name'],
                    'count': it['count'],
                    'options': it.get('options', []),
                })
            else:
                unresolved.append({
                    'item': class_name,
                    'count': it['count'],
                    'options': it.get('options', []),
                })
                log.warning(
                    'package %s: unresolved item reference %r '
                    '(moved to PackageContents.unresolved)',
                    obj['$ID_NAME'], class_name,
                )

        # alternatives(multiple 계열) 해석: 각 선택지 그룹을 동일 기준으로 분리.
        alternatives = []
        for alt in parsed.get('alternatives', []):
            group = []
            for a in alt:
                ref = items_by_name.get(a['item'])
                if ref is not None:
                    group.append({
                        'item': a['item'],
                        'name': ref['Name'],
                        'count': a['count'],
                        'options': a.get('options', []),
                    })
                else:
                    # multiple 계열의 미해결 선택지도 unresolved 로 보낸다.
                    unresolved.append({
                        'item': a['item'],
                        'count': a['count'],
                        'options': a.get('options', []),
                    })
                    log.warning(
                        'package %s: unresolved alternative item reference %r '
                        '(moved to PackageContents.unresolved)',
                        obj['$ID_NAME'], a['item'],
                    )
            if group:
                alternatives.append(group)

        # entries 또는 alternatives 중 하나라도 있으면 결과 생성.
        # 이전에는 entries 만 검사해 multiple(alternatives만 있는) 계열이
        # PackageContents 없이 누락됐다.
        if entries or alternatives or unresolved:
            obj['PackageContents'] = {
                'random': parsed['random'],
                'kind': parsed['kind'],
                'items': entries,
            }
            if alternatives:
                obj['PackageContents']['alternatives'] = alternatives
            if unresolved:
                # 미해결 참조는 원문을 보존해 별도로 분리한다.
                obj['PackageContents']['unresolved'] = unresolved
                unresolved_total += len(unresolved)
            # items(정상 항목)가 하나라도 있으면 resolved 로 계산.
            if entries or alternatives:
                resolved += 1

        for w in parsed['warnings']:
            warnings_report.append((obj['$ID_NAME'], w))
            log.warning('package %s: %s', obj['$ID_NAME'], w)

    if growth_report:
        log.info('package growth_selection reported: %d items %s',
                 len(growth_report), growth_report)
    if account_prop_report:
        log.info('package account_prop reported: %d items %s',
                 len(account_prop_report), account_prop_report)
    if unresolved_total:
        log.warning('package unresolved item references: %d', unresolved_total)
    if warnings_report:
        log.info('package warnings: %d', len(warnings_report))
    log.info('package contents resolved for %d items', resolved)


def parse(c = None, from_scratch = True):
    if c == None:
        c = constants()
        c.build("itos")
        luautil.init(c)
    if (from_scratch):
        c.data['items'] = {}
        c.data['items_by_name'] = {}
        c.cubes_by_stringarg = {}
        c.equipment_sets = {}
        item_ies = c.ITEM_IES
        for i in item_ies:
            parse_items(c, i )
    
    luautil.init(c)
    equipment_ies = c.EQUIPMENT_IES
    global EQUIPMENT_STAT_COLUMNS
    # realpath 기반 장비 파일 중복 방지 집합. EQUIPMENT_IES 대소문자 중복을
    # 제거했더라도 file_dict 의 소문자 키 충돌로 같은 파일이 두 번 처리될 수
    # 있으므로, 실제 경로(realpath) 단위로 한 번만 파싱한다.
    _equip_seen_paths = set()
    a = luautil.LUA_RUNTIME['GET_COMMON_PROP_LIST']()
    EQUIPMENT_STAT_COLUMNS =[a[i] for i in a]
    
    parse_equipment_grade_ratios(c)
    global equipment_grade_ratios        
    equipment_grade_ratios = c.data['equipment_grade_ratios']
    
    
    parse_goddess_reinf(c)
    
    # Registered goddess tables and their supported material groups.
    parse_goddess_EQ(c)
    
    for i in equipment_ies:
        parse_equips(c, i, _seen_paths=_equip_seen_paths)
    
    parse_equipment_sets('setitem.ies', c)
    parse_links_equipment_sets('setitem.ies',c)

    parse_cards(c)
    parse_cards_battle(c)
    
    parse_links_cubes(c)
    
    parse_links_collections(c)
    
    parse_gems(c)
    
    parse_gems_bonus(c)
    
    parse_links_skills(c)

    parse_links_recipes(c)

    # 패키지 구성물 확정 — 장비/카드 등 뒤에 추가된 아이템 이름까지 해석
    # 가능하도록 파싱 마지막에 수행.
    resolve_package_contents(c)

    #parse_books_dialog(c)
    
    

def parse_items(constants, file_name):
    
    
    log.info('Parsing %s...', file_name)
    file_name = file_name.lower()
    try:
        ies_path= constants.file_dict[file_name]['path']
    except:
        return

    #ies_path = os.path.join(constants.PATH_INPUT_DATA, "ies.ipf", file_name)
    if(not exists(ies_path)):
        log.warning("file not found {}".format(file_name))
        return
   
    ies_file = io.open(ies_path, 'r', encoding="utf-8")
    ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')
    rows = []

    for row in ies_reader:
        # 언팩이 파일 끝에서 잘리면 마지막 행이 컬럼 부족(None 값)으로 들어온다
        # (예: itos 2026-07-21 item_EP13.ies 마지막 행). 크래시 대신 건너뛴다.
        if ('ClassName' in row and row['ClassName'] is None) or \
           ('GroupName' in row and row['GroupName'] is None):
            log.warning('malformed ies row skipped (truncated?): file=%s ClassID=%s ClassName=%s',
                        file_name, row.get('ClassID'), row.get('ClassName'))
            continue

        rows.append(row)
        item_type = row['GroupName'].upper() if 'GroupName' in row else None 
        item_type = row['Category'].upper() if 'Category' in row and row['Category'] != '' else item_type

        
        item_type_equipment = row['ClassType'] if 'ClassType' in row else None
        item_type_equipment = row['ClassType2'] if 'ClassType' in row and row['ClassType'] == 'NO' and 'ClassType2' in row else item_type_equipment
    

        obj = {}

        obj['$ID'] = str( row['ClassID'])
        obj['$ID_NAME'] = row['ClassName']
        obj['Description'] = constants.translate(row['Desc']) if 'Desc' in row else None
        obj['Icon'] = constants.parse_entity_icon(row['Icon'])
        obj['Name'] = constants.translate(row['Name']) if 'Name' in row else None
        obj['Grade'] = safe_item_grade(row)
        obj['Price'] = row['SellPrice']
        obj['TimeCoolDown'] = float(int(row['ItemCoolDown']) / 1000) if 'ItemCoolDown' in row else None
        obj['TimeLifeTime'] = float(int(row['LifeTime'])) if 'LifeTime' in row else None
        obj['Tradability'] = '%s%s%s%s' % (
            'T' if row['MarketTrade'] == 'YES' else 'F',    # Market
            'T' if row['UserTrade'] == 'YES' else 'F',      # Players
            'T' if row['ShopTrade'] == 'YES' else 'F',      # Shop
            'T' if row['TeamTrade'] == 'YES' else 'F',      # Team Storage
        )
        obj['Type'] = item_type
        if 'Weight' in row :
            obj['Weight'] = float(row['Weight']) 
        else:
            obj['Weight'] = ''
    
        obj['Link_Collections'] = []
        obj['Link_Cubes'] = []
        obj['Link_Maps'] = []
        obj['Link_Maps_Exploration'] = []
        obj['Link_Monsters'] = []
        obj['Link_RecipeTarget'] = []
        obj['Link_RecipeMaterial'] = []
        if item_type == 'CUBE':
            # 다중 매핑: 같은 StringArg 를 공유하는 큐브가 여러 개일 수 있다.
            # (ktos 기준 65개 그룹을 2개 이상 큐브가 공유)
            # 이전 단일 매핑은 이전 큐브를 덮어써 보상 연결이 누락됐다.
            constants.cubes_by_stringarg.setdefault(row['StringArg'], []).append(obj)
        # 패키지류(사용 시 구성물 지급) 원본 보관. 이름 해석은 모든 item ies
        # 파싱이 끝난 뒤 resolve_package_contents() 후처리에서 수행한다.
        # 수집 조건은 package_parser.is_package_script 로 통일 — 이전
        # 접두사 2개(GIVE_ITEM / RANDOM_GIVE_ITEM) 매칭은
        # SCR_USE_STRING_GIVE_RANDOM_MUTIPLE_* 계열을 누락했다.
        script = (row.get('Script') or '').strip()
        if (
            package_parser.is_package_script(script)
            and (row.get('StringArg') or '').strip()
        ):
            obj['PackageContents_Raw'] = (
                script,
                row['StringArg'].strip(),
                (row.get('NumberArg1') or '').strip(),
            )
        constants.data['items'][obj['$ID']] = obj
        constants.data['items_by_name'] [obj['$ID_NAME']] = obj
    
    
    ies_file.close()
    return constants
   

def parse_equips(constants, filename, _seen_paths=None):
    log = logging.getLogger("parser.equips")
    log.setLevel("INFO")
    log.info('Parsing equipment %s ...'%(filename))
    try:
        ies_path =  constants.file_dict[filename.lower()]['path']
    except:
        logging.warning("file not found {}".format(filename))
        return

    # realpath 기반 중복 처리 방지. 같은 파일(소문자 키 충돌, 심볼릭 링크 등)이
    # 두 번 파싱되면 약 41%의 불필요한 장비 루프 비용이 발생한다.
    real = os.path.realpath(ies_path)
    if _seen_paths is not None:
        if real in _seen_paths:
            logging.info('equipment file already parsed (skipping duplicate): %s', real)
            return
        _seen_paths.add(real)
    
    #ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', filename)
    #if(not exists(ies_path)):
    #   return
    ies_file = io.open(ies_path, 'r', encoding = 'utf-8')
    ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')
    
    if not 'EQUIPMENT' in constants.data['item_type']:
        constants.data['item_type']['EQUIPMENT'] = []
    LUA_RUNTIME = luautil.LUA_RUNTIME
    LUA_SOURCE = luautil.LUA_SOURCE
    rows = []
    objs = []
    types = []
    for row in ies_reader:
      
        if str(row['ClassName']) not in constants.data['items_by_name'].keys():
            # Create fallback item for equipment that doesn't have base item data
            logging.warning(f"[EQUIPMENT-FALLBACK] Creating fallback for equipment item '{row['ClassName']}'")
            fallback_obj = create_fallback_item(constants, row['ClassName'], 'EQUIPMENT')
            if fallback_obj:
                constants.data['items'][fallback_obj['$ID']] = fallback_obj
                constants.data['items_by_name'][row['ClassName']] = fallback_obj
            
        item_grade = equipment_grade_ratios[safe_item_grade(row)]
        item_type_equipment = row['ClassType']
        types.append(row['ClassType'])
        rows.append(row)
        #continue
        obj = constants.data['items_by_name'][str(row['ClassName'])]
        
        # Update Name and Description from equipment data (overrides fallback values)
        if 'Name' in row and row['Name']:
            obj['Name'] = constants.translate(row['Name'])
        if 'Desc' in row and row['Desc']:
            obj['Description'] = constants.translate(row['Desc'])
        
        if obj['$ID_NAME'] not in constants.data['item_type']['EQUIPMENT']:
            constants.data['item_type']['EQUIPMENT'].append(obj['$ID_NAME'])
        obj['Type'] = 'Equipment'
        # Calculate all properties using in-game formulas
        tooltip_script = row['RefreshScp']
        if ('MarketCategory' in row):
            tooltip_script = 'SCR_REFRESH_ACC' if not tooltip_script and 'Accessory_' in row['MarketCategory'] else tooltip_script
            tooltip_script = 'SCR_REFRESH_ARMOR' if not tooltip_script and 'Armor_' in row['MarketCategory'] else tooltip_script
            tooltip_script = 'SCR_REFRESH_HAIRACC' if not tooltip_script and 'HairAcc_' in row['MarketCategory'] else tooltip_script
            tooltip_script = 'SCR_REFRESH_WEAPON' if not tooltip_script and ('Weapon_' in row['MarketCategory'] or 'ChangeEquip_' in row['MarketCategory']) else tooltip_script

        if tooltip_script:
            try:
                LUA_RUNTIME[tooltip_script](row)
            except Exception as exc:
                raise ValueError('Equipment refresh failed for {} using {}'.format(
                    row['ClassName'], tooltip_script)) from exc

        # Add additional fields
        obj['AnvilATK'] = []
        obj['AnvilDEF'] = []
        obj['AnvilPrice'] = []
        obj['Bonus'] = []
        obj['Durability'] = int(row['MaxDur']) / 100
        obj['Durability'] = -1 if obj['Durability'] <= 0 else obj['Durability']
        # PROFILING_REVIEW P0-5: int(row['ItemGrade']) 결과를 '' 와 비교하는
        # 도달 불가 분기를 제거하고 safe_item_grade 로 빈 값/범위를 방어.
        obj['Grade'] = safe_item_grade(row)
        obj['Level'] = int(row['ItemLv']) if int(row['ItemLv']) > 0 else int(row['UseLv'])
        obj['Material'] = row['Material']
        obj['Potential'] = int(row['MaxPR'])
        obj['RequiredClass'] = '%s%s%s%s%s' % (
            'T' if any(j in row['UseJob'] for j in ['All', 'Char3']) else 'F',  # Archer
            'T' if any(j in row['UseJob'] for j in ['All', 'Char4']) else 'F',  # Cleric
            'T' if any(j in row['UseJob'] for j in ['All', 'Char5']) else 'F',  # Scout
            'T' if any(j in row['UseJob'] for j in ['All', 'Char1']) else 'F',  # Swordsman
            'T' if any(j in row['UseJob'] for j in ['All', 'Char2']) else 'F',  # Wizard
        )
        obj['RequiredLevel'] = int(row['UseLv'])
        obj['Sockets'] = int(row['BaseSocket'])
        obj['SocketsLimit'] = int(row['MaxSocket_COUNT'])
        obj['Stars'] = int(row['ItemStar'])
        try:
            obj['Stat_ATTACK_MAGICAL'] = int(row['MATK']) 
        except:
            obj['Stat_ATTACK_MAGICAL'] = 0
        try:
            obj['Stat_ATTACK_PHYSICAL_MIN'] = int(row['MINATK']) 
        except:
            obj['Stat_ATTACK_PHYSICAL_MIN'] = 0
        try:
            obj['Stat_ATTACK_PHYSICAL_MAX'] = int(row['MAXATK']) if 'MAXATK' in row and row['MAXATK'] !=None else 0
        except:
            obj['Stat_ATTACK_PHYSICAL_MAX'] = 0
        try:
            obj['Stat_DEFENSE_MAGICAL'] = int(row['MDEF']) if 'MDEF' in row and row['MDEF'] !=None else 0
        except:
            obj['Stat_DEFENSE_MAGICAL'] = 0
        try:
            obj['Stat_DEFENSE_PHYSICAL'] = int(row['DEF']) if 'DEF' in row and row['DEF'] !=None else 00
        except:
            obj['Stat_DEFENSE_PHYSICAL'] = 0
        
        
        matk = ['staff', 'rod']
       
        if obj['Grade'] == 6:
            if int(row['UseLv']) in goddess_atk_list:
                
                if tooltip_script == 'SCR_REFRESH_ACC' :
                    atk = int(goddess_atk_list[int(row['UseLv'])]['BasicAccAtk'])
                    obj['Stat_ATTACK_MAGICAL']      = atk
                    obj['Stat_ATTACK_PHYSICAL_MIN'] = atk
                    obj['Stat_ATTACK_PHYSICAL_MAX'] = atk
                        
                        
                #if tooltip_script == 'SCR_REFRESH_ARMOR':
                #    pass
                    
                #if tooltip_script == 'SCR_REFRESH_WEAPON':
                #    

            
        
        
        obj['TypeAttack'] = row['AttackType']
        obj['TypeEquipment'] = item_type_equipment
        # hair acc 
        if ('ReqToolTip' in row):
            if (row['ReqToolTip'] == '헤어 코스튬1'):
                obj['TypeEquipment'] = 'Hair Acc 1'    
            if (row['ReqToolTip'] == '헤어 코스튬2'):
                obj['TypeEquipment'] = 'Hair Acc 2'    
            if (row['ReqToolTip'] == '헤어 코스튬3'):
                obj['TypeEquipment'] = 'Hair Acc 3'    
        obj['Unidentified'] = int(row['NeedAppraisal']) == 1
        obj['UnidentifiedRandom'] = int(row['NeedRandomOption']) == 1

        obj['Link_Set'] = None

        # HotFix: if it's a Rapier, use THRUST as the TypeAttack
        #if obj['TypeEquipment'] == TOSEquipmentType.RAPIER:
        #    obj['TypeAttack'] = TOSAttackType.MELEE_THRUST

        # HotFix: in case it doesn't give physical nor magical defense (e.g. agny necklace)
        if 'ADD_FIRE' in row['BasicTooltipProp'].split(','):
            lv = obj['Level']
            gradeRatio = (int(item_grade['BasicRatio']) / 100.0)

            row['ADD_FIRE'] = floor(lv * gradeRatio)

        # Anvil
        reinf = 'GET_REINFORCE_PRICE'
        if ('GET_REINFORCE_PRICE' not in LUA_RUNTIME) and 'GET_REINFORCE_131014_PRICE' in LUA_RUNTIME:
            reinf = 'GET_REINFORCE_131014_PRICE'
        if (obj['Grade'] != 6) and reinf!= None: #goddess!
            props = row['BasicTooltipProp']
            if (('ATK' in props or 'DEF' in props) if type(props) is str else
                    any(prop in row['BasicTooltipProp'] for prop in ['ATK', 'DEF', 'MATK', 'MDEF'])):
                for lv in range(40):
                    row['Reinforce_2'] = lv
                    props = row['BasicTooltipProp']
                    if ('DEF' in props if type(props) is str else
                            any(prop in row['BasicTooltipProp'] for prop in ['DEF', 'MDEF'])):
                        obj['AnvilDEF'].append(LUA_RUNTIME['GET_REINFORCE_ADD_VALUE'](None, row, 0, 1))
                        obj['AnvilPrice'].append(LUA_RUNTIME[reinf](row, {}, None))
                    props = row['BasicTooltipProp']
                    if ('ATK' in props if type(props) is str else
                            any(prop in row['BasicTooltipProp'] for prop in ['ATK', 'MATK'])):
                        obj['AnvilATK'].append(LUA_RUNTIME['GET_REINFORCE_ADD_VALUE_ATK'](row, 0, 1, None))
                        obj['AnvilPrice'].append(LUA_RUNTIME[reinf](row, {}, None))
               
    
            obj['AnvilPrice'] = [int(value) for value in obj['AnvilPrice'] if value > 0]
            obj['AnvilATK'] = [int(value) for value in obj['AnvilATK'] if value > 0] if len(obj['AnvilPrice']) > 0 else None
            obj['AnvilDEF'] = [int(value) for value in obj['AnvilDEF'] if value > 0] if len(obj['AnvilPrice']) > 0 else None
        elif obj['Grade'] == 6:
            parse_goddess_equipment_calculation(constants, obj, row)
        # try:
        lua = luautil.lua
        obj['TranscendPrice'] = []
        for lv in range(10):
            row['Transcend'] = 0
            obj['TranscendPrice'].append(LUA_RUNTIME['GET_TRANSCEND_MATERIAL_COUNT'](row, lv))
        #somehow it wont contain tc 10 =w=
        if (obj['Grade'] == 6):
            obj['TranscendPrice'].append(lua.execute('return get_TC_goddess')(int(row['UseLv']), row['ClassType'], 0,10))
        
        
        try:
            obj['TranscendPrice'] = [floor(value) for value in obj['TranscendPrice'] if value > 0]
        except:
            #goddess
            a = [dict(table)['Premium_item_transcendence_Stone'] for table in 
                 obj['TranscendPrice'][1:] ]
            obj['TranscendPrice'] = [0] + a + [20]
        
           
        # Bonus
        for stat in EQUIPMENT_STAT_COLUMNS:
            if stat in row:
                if row[stat] == None:
                    row[stat] = 0
                value = floor(float(row[stat]))

                if value != 0:
                    obj['Bonus'].append([
                        stat,    # Stat
                        value                               # Value
                    ])

        # More Bonus
        if 'OptDesc' in row and len(row['OptDesc']) > 0:
            for bonus in constants.translate(row['OptDesc']).split('{nl}'):
                bonus = bonus.strip()
                bonus = bonus[bonus.index('-'):] if '-' in bonus else bonus

                obj['Bonus'].append([
                    'UNKNOWN',           # Stat
                    bonus.replace('- ', '').strip()     # Value
                ])

        # Transcendence
        """
        try:
            obj['FileName'] = row['FileName']
            obj['row'] = row
        except:
            obj['FileName'] = ''
        """
        obj['model'] = parse_xac.eq_model_name(row,constants)
        constants.data['items'][obj['$ID']] = obj
        constants.data['items_by_name'] [obj['$ID_NAME']] = obj
        rows.append(row)
        objs.append(obj)
    return constants


def parse_goddess_equipment_calculation(constants, obj, row):
    level = int(row['UseLv'])
    table = constants.data['goddess_reinf'].get(level)
    # Growth equipment has a separate Lua formula and material system.
    if not table or '/' in row.get('StringArg', ''):
        return
    runtime = luautil.LUA_RUNTIME
    function = 'SCR_GET_GODDESS_REINFORCE'
    for required in (function, 'IS_WEAPON_TYPE'):
        if required not in runtime:
            raise ValueError('Missing goddess reinforcement function: ' + required)
    previous = row.get('Reinforce_2', 0)
    try:
        weapon = runtime['IS_WEAPON_TYPE'](row['ClassType'])
        if type(weapon) is not bool:
            raise ValueError('Invalid goddess equipment type: ' + row['ClassName'])
        group = 'acc' if row['ClassType'] in ('Neck', 'Ring') else 'weapon' if weapon else 'armor'
        obj['GoddessReinforceLevel'] = level
        obj['GoddessReinforceGroup'] = group
        for step in range(1, len(table) + 1):
            row['Reinforce_2'] = step
            value = runtime[function](row)
            if type(value) not in (int, float) or not isfinite(value) or value < 0:
                raise ValueError('Invalid goddess reinforcement result: ' + row['ClassName'])
            attack = floor(value * 0.3) if row['ClassType'] == 'Trinket' else floor(value)
            if obj['Stat_ATTACK_PHYSICAL_MIN'] or obj['Stat_ATTACK_MAGICAL']:
                obj['AnvilATK'].append(attack)
            if obj['Stat_DEFENSE_PHYSICAL'] or obj['Stat_DEFENSE_MAGICAL']:
                obj['AnvilDEF'].append(floor(value))
    except Exception as exc:
        raise ValueError('Goddess reinforcement failed for ' + row['ClassName']) from exc
    finally:
        row['Reinforce_2'] = previous


def parse_goddess_reinf(constants):
    files = constants.EQUIPMENT_REINFORCE_IES
    global goddess_atk_list
    # 모듈 전역 goddess_atk_list는 빌드마다 새로 채운다.
    # 이전 지역/테스트의 잔존 값을 지우지 않으면 같은 프로세스에서
    # 다른 constants로 재실행할 때 stale 레벨이 남는다.
    goddess_atk_list.clear()
    for i in files:
        
        if i not in constants.file_dict:
            continue
        goddess_atk_list[files[i]] = read_goddess_reinforce_rows(constants, i)[0]


def read_goddess_reinforce_rows(constants, filename):
    with io.open(constants.file_dict[filename]['path'], 'r', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    if not rows:
        raise ValueError('Empty goddess reinforcement table: ' + filename)
    # The 560 weapon/armor format differs from the accessory-only 550 format.
    # Keep CSV strings in the public table, but reject malformed new inputs.
    if filename == 'item_goddess_reinforce_560.ies':
        fields = ('ClassID', 'BasicProp', 'AddAtk', 'AddDef', 'BasicAtk', 'BasicDef', 'EvolveAtk')
        seen = set()
        for row in rows:
            try:
                values = {field: int(row[field]) for field in fields}
                if (not row['ClassName'] or values['ClassID'] < 1 or values['ClassID'] in seen
                        or any(value < 0 for value in values.values()) or values['BasicProp'] > 100000):
                    raise ValueError('invalid row')
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError('Invalid goddess reinforcement table: ' + filename) from exc
            seen.add(values['ClassID'])
    return rows
        
        

def parse_equipment_grade_ratios(constants):
    log = logging.getLogger("parser.equips.grade")
    log.setLevel("INFO")
    log.info('Parsing equipment grade...')

    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'item_grade.ies')
    
    ies_file = io.open(ies_path, 'r', encoding = 'utf-8')
    ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')

    for row in ies_reader:
        equipment_grade_ratios[int(row['Grade'])] = row
    constants.data['equipment_grade_ratios'] = equipment_grade_ratios
    ies_file.close()


def parse_equipment_sets(file_name, constants):
    log = logging.getLogger("parser.equips.set")
    log.setLevel("INFO")
    log.info('Parsing equipment sets...')

    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', file_name)
    if(not exists(ies_path)):
       return
    ies_file = open(ies_path, 'r', encoding = 'utf-8')
    ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')

    for row in ies_reader:
        obj = {}
        obj['$ID'] = str(row['ClassID'])
        obj['$ID_NAME'] = row['ClassName']
        obj['Name'] = constants.translate(row['Name']) if 'Name' in row else None

        obj['Link_Items'] = []

        # Parse bonus
        obj['Bonus2'] = constants.translate(row['EffectDesc_2']) if row['EffectDesc_2'] != '' else None
        obj['Bonus3'] = constants.translate(row['EffectDesc_3']) if row['EffectDesc_3'] != '' else None
        obj['Bonus4'] = constants.translate(row['EffectDesc_4']) if row['EffectDesc_4'] != '' else None
        obj['Bonus5'] = constants.translate(row['EffectDesc_5']) if row['EffectDesc_5'] != '' else None
        obj['Bonus6'] = constants.translate(row['EffectDesc_6']) if row['EffectDesc_6'] != '' else None
        obj['Bonus7'] = constants.translate(row['EffectDesc_7']) if row['EffectDesc_7'] != '' else None

        constants.data['equipment_sets'][obj['$ID']] = obj
        constants.data['equipment_sets_by_name'][obj['$ID_NAME']] = obj
    return constants

def parse_links_equipment_sets(file_name, constants):
    log = logging.getLogger("parser.equips.set.link")
    log.setLevel("INFO")
    log.info('Parsing items for equipment sets: %s...', file_name)

    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', file_name)
    if(not exists(ies_path)):
       return
    ies_file = open(ies_path, 'r', encoding = 'utf-8')
    ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')

    for row in ies_reader:
        equipment_set = constants.data['equipment_sets_by_name'][row['ClassName']]

        # Parse items
        for i in range(1, 8):
            item_name = row['ItemName_' + str(i)]

            if item_name == '':
                continue
            if (item_name in constants.data['items_by_name'].keys()):
                item = constants.data['items_by_name'][item_name]
            else:
                continue

            
            equipment_set['Link_Items'].append(item['$ID_NAME'])

    ies_file.close()
    

def parse_cards(constants):
    log = logging.getLogger("parser.equips.card")
    log.setLevel("INFO")
    log.info('Parsing cards...')

    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'item.ies')
    if(not exists(ies_path)):
       return
    ies_file = open(ies_path, 'r', encoding = 'utf-8')
    ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')
    if 'CARD' not in constants.data['item_type']:
        constants.data['item_type']['CARD'] = []
    for row in ies_reader:
        if row['GroupName'] != 'Card':
            continue
        
        try:
            obj = constants.data['items_by_name'][row['ClassName']]
        except KeyError:
            # Fallback: create a minimal base entry directly from item.ies row
            obj = {}
            obj['$ID'] = str(row['ClassID']) if 'ClassID' in row else row['ClassName']
            obj['$ID_NAME'] = row['ClassName']
            obj['Description'] = constants.translate(row['Desc']) if 'Desc' in row else None
            obj['Icon'] = constants.parse_entity_icon(row['Icon']) if 'Icon' in row else None
            obj['Name'] = constants.translate(row['Name']) if 'Name' in row and row['Name'] != '' else row['ClassName']
            try:
                obj['Grade'] = int(row['ItemGrade']) if 'ItemGrade' in row and row['ItemGrade'] != '' else 1
            except Exception:
                obj['Grade'] = 1
            # Defaults required by downstream importers
            try:
                obj['TimeCoolDown'] = float(int(row['ItemCoolDown']) / 1000) if 'ItemCoolDown' in row and row['ItemCoolDown'] != '' else 0
            except Exception:
                obj['TimeCoolDown'] = 0
            try:
                obj['Weight'] = float(row['Weight']) if 'Weight' in row and row['Weight'] != '' else ''
            except Exception:
                obj['Weight'] = ''
            try:
                obj['Price'] = row['SellPrice'] if 'SellPrice' in row and row['SellPrice'] != '' else 0
            except Exception:
                obj['Price'] = 0
            if all(k in row for k in ['MarketTrade', 'UserTrade', 'ShopTrade', 'TeamTrade']):
                obj['Tradability'] = '%s%s%s%s' % (
                    'T' if row['MarketTrade'] == 'YES' else 'F',
                    'T' if row['UserTrade'] == 'YES' else 'F',
                    'T' if row['ShopTrade'] == 'YES' else 'F',
                    'T' if row['TeamTrade'] == 'YES' else 'F',
                )
            else:
                obj['Tradability'] = 'FFFF'
            obj['Type'] = 'CARD'
            constants.data['items'][obj['$ID']] = obj
            constants.data['items_by_name'][obj['$ID_NAME']] = obj
            log.warning("Card item '{}' was missing a base entry; created a minimal fallback from item.ies".format(row['ClassName']))

        # Ensure CARD type list contains this entry once
        if obj['$ID_NAME'] not in constants.data['item_type']['CARD']:
            constants.data['item_type']['CARD'].append(obj['$ID_NAME'])

        # Populate card-specific fields
        obj['Description'] = obj['Description']
        obj['IconTooltip'] = constants.parse_entity_icon(row['TooltipImage'])
        obj['TypeCard'] = row['CardGroupName']
        obj['Type']         = 'CARD'
        constants.data['items'] [obj['$ID']] = obj
        constants.data['items_by_name'] [obj['$ID_NAME']] = obj

    ies_file.close()
    return constants

def parse_cards_battle(constants):
    log = logging.getLogger("parser.equips.card.battle")
    log.setLevel("INFO")
    log.info('Parsing cards battle...')

    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'cardbattle.ies')
    if(not exists(ies_path)):
       return
    ies_file = open(ies_path, 'r', encoding = 'utf-8')
    ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')

    for row in ies_reader:
        try:
            obj = constants.data['items_by_name'][row['ClassName']]
        except KeyError:
            log.warning(f"Card battle entry '{row['ClassName']}' has no base item; skipping.")
            continue

        obj['Stat_Height'] = int(row['Height'])
        obj['Stat_Legs'] = int(row['LegCount'])
        obj['Stat_Weight'] = int(row['BodyWeight'])
        constants.data['items'] [obj['$ID']] = obj

    ies_file.close()
    return constants


def parse_links_cubes(constants):
    log = logging.getLogger("parser.cubes")
    log.setLevel("INFO")
    log.info('Parsing items for cubes...')

    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'reward_indun.ies')
    if(not exists(ies_path)):
       return
    ies_file = open(ies_path, 'r', encoding = 'utf-8')
    ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')
    if 'CUBES' not in constants.data['item_type']:
        constants.data['item_type']['CUBES'] = []

    # reward_indun 의 Group 은 큐브의 StringArg 와 매칭된다(116개 그룹).
    # 이전 코드는 row['Group'] 을 items_by_name 에서 찾는 잘못된 선행 조건과
    # '$ID_NAME' 대신 'ID_NAME' 오타, 그리고 단일 큐브 매핑을 써서
    # 1044개 큐브 모두 Link_Items 가 비어 있었다.
    linked_cubes = set()
    for row in ies_reader:
        group = row['Group']
        cubes = constants.cubes_by_stringarg.get(group)
        if not cubes:
            continue
        item_name = row['ItemName']
        for cube in cubes:
            if not 'Link_Items' in cube.keys():
                cube['Link_Items'] = []
            # Type 은 원본 CUBE 를 유지(DB 검색/분류 호환).
            cube['Type'] = 'CUBE'
            if cube['$ID_NAME'] not in constants.data['item_type']['CUBES']:
                constants.data['item_type']['CUBES'].append(cube['$ID_NAME'])
            try:
                cube['Link_Items'].append(constants.data['items_by_name'][item_name]['$ID_NAME'])
            except KeyError:
                # 보상 아이템이 기본 엔트리에 없으면 fallback.
                fallback_obj = create_fallback_item(constants, item_name, 'CUBE')
                if fallback_obj:
                    constants.data['items'][fallback_obj['$ID']] = fallback_obj
                    constants.data['items_by_name'][fallback_obj['$ID_NAME']] = fallback_obj
                    cube['Link_Items'].append(fallback_obj['$ID_NAME'])
                    log.warning(f"Cube item '{item_name}' was missing a base entry; created a minimal fallback")
                else:
                    log.error(f"Failed to create fallback for cube item '{item_name}'")
                    if constants.region != 'itos':
                        print("key error ... {} for {} cube".format(item_name, cube['Name']))
            constants.data['items'][cube['$ID']] = cube
            constants.data['items_by_name'][cube['$ID_NAME']] = cube
            linked_cubes.add(cube['$ID_NAME'])

    # Link_Items 중복 제거(stable dedupe).
    for cube_name in linked_cubes:
        cube = constants.data['items_by_name'].get(cube_name)
        if cube and cube.get('Link_Items'):
            seen = set()
            deduped = []
            for it in cube['Link_Items']:
                if it not in seen:
                    seen.add(it)
                    deduped.append(it)
            cube['Link_Items'] = deduped

    log.info('cubes linked to reward_indun: %d', len(linked_cubes))
    ies_file.close()
    return constants


def parse_links_collections(constants):
    log = logging.getLogger("parser.collections")
    log.setLevel("INFO")
    log.info('Parsing items for collections...')
    if 'COLLECTION' not in constants.data['item_type']:
        constants.data['item_type']['COLLECTION'] = []
    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'collection.ies')
    if(not exists(ies_path)):
       return
    ies_file = open(ies_path, 'r', encoding = 'utf-8')
    ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')

    for row in ies_reader:
        try:
            collection = constants.data['items_by_name'][row['ClassName']]
        except KeyError:
            # Create a minimal fallback collection item
            collection = create_fallback_item(constants, row['ClassName'], 'COLLECTION')
            if collection:
                constants.data['items'][collection['$ID']] = collection
                constants.data['items_by_name'][collection['$ID_NAME']] = collection
                log.warning(f"Collection '{row['ClassName']}' was missing a base entry; created a minimal fallback")
            else:
                log.error(f"Failed to create fallback for collection '{row['ClassName']}'")
                continue
        constants.data['item_type']['COLLECTION'].append(collection['$ID_NAME'])
        collection['Type']         = 'COLLECTION'
        if not 'Link_Items' in collection.keys():
            collection['Link_Items'] = []
            collection['Bonus'] = []
        # Parse items
        for i in range(1, 10):
            item_name = row['ItemName_' + str(i)]

            if item_name == '':
                continue

            try:
                collection['Link_Items'].append(constants.data['items_by_name'][item_name]['$ID_NAME'])
            except KeyError:
                # Create a minimal fallback collection item
                fallback_obj = create_fallback_item(constants, item_name, 'COLLECTION_ITEM')
                if fallback_obj:
                    constants.data['items'][fallback_obj['$ID']] = fallback_obj
                    constants.data['items_by_name'][fallback_obj['$ID_NAME']] = fallback_obj
                    collection['Link_Items'].append(fallback_obj['$ID_NAME'])
                    log.warning(f"Collection item '{item_name}' was missing a base entry; created a minimal fallback")
                else:
                    log.error(f"Failed to create fallback for collection item '{item_name}'")
                    if constants.region != 'itos':
                        raise

        # Parse bonus
        bonus = row['PropList'].split('/') + row['AccPropList'].split('/')

        for i in bonus:
            if i == '':
                bonus.remove(i)
        if (len(bonus) != 1):
            for i in range(0, len(bonus), 2):
                try:
                    collection['Bonus'].append([
                        parse_links_items_bonus_stat(bonus[i]),   # Property
                        int(bonus[i + 1])                         # Value
                    ])
                except KeyError as e:
                    log.error(f"Unknown bonus stat '{bonus[i]}' in collection '{row['ClassName']}' (ID: {row.get('ClassID', 'N/A')}). PropList: {row['PropList']}, AccPropList: {row['AccPropList']}")
                    raise
        constants.data['items'][collection['$ID']] = collection
        constants.data['items_by_name'][collection['$ID_NAME']] = collection
    ies_file.close()
    return constants

def parse_links_items_bonus_stat(stat):
    stat_map = {
        'CON_BM': 'CON',
        'DEX_BM': 'DEX',
        'INT_BM': 'INT',
        'MNA_BM': 'SPR',
        'STR_BM': 'STR',
        'ALLSTAT_BM': 'ALLSTAT',

        'CRTATK_BM': 'Critical Attack',
        'CRTMATK_BM': 'Critical Magic Attack',
        'CRTHR_BM': 'Critical Rate',
        'CRTDR_BM': 'Critical Defense',

        'MHP_BM': 'Maximum HP',
        'MSP_BM': 'Maximum SP',
        'RHP_BM': 'HP Recovery',
        'RSP_BM': 'SP Recovery',

        'DEF_BM': 'Defense',
        'MDEF_BM': 'Magic Defense',
        'MATK_BM': 'Magic Attack',
        'PATK_BM': 'Physical Attack',

        'DR_BM': 'Evasion',
        'DR_CONST': 'Evasion',
        'HR_BM': 'Accuracy',
        'MHR_BM': 'Magic Amplification',  # ???

        'ResDark_BM': 'Dark Property Resistance',
        'ResEarth_BM': 'Earth Property Resistance',
        'ResHoly_BM': 'Holy Property Resistance',

        'MaxSta_BM': 'Stamina',
        'MaxAccountWarehouseCount': 'Team Storage Slots',
        'MaxWeight_Bonus': 'Weight Limit',
        'MaxWeight_BM': 'Weight Limit',
        'BLK_BREAK_BM': 'Block Break',
        'BLK_BM': 'Block',
    }
    
    if stat not in stat_map:
        raise KeyError(f"Unknown bonus stat: '{stat}'. Available stats: {list(stat_map.keys())}")
    
    return stat_map[stat]

def parse_gems(constants):
    log = logging.getLogger("parser.gems")
    log.setLevel("INFO")
    log.info('Parsing gems...')

    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'item_gem.ies')
    if(not exists(ies_path)):
       return
    ies_file = open(ies_path, 'r', encoding = 'utf-8')
    ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')
    if 'GEMS' not in constants.data['item_type']:
        constants.data['item_type']['GEMS'] = []
    for row in ies_reader:
        try:
            obj = constants.data['items_by_name'][row['ClassName']]
            constants.data['item_type']['GEMS'].append(obj['$ID_NAME'])
            obj['BonusBoots'] = []
            obj['BonusGloves'] = []
            obj['BonusSubWeapon'] = []
            obj['BonusTopAndBottom'] = []
            obj['BonusWeapon'] = []
            obj['TypeGem'] = row['EquipXpGroup']
            constants.data['items_by_name'][row['ClassName']] = obj
            constants.data['items'][obj['$ID']] = obj
        except KeyError:
            # Create a minimal fallback gem item
            obj = create_fallback_item(constants, row['ClassName'], 'GEM')
            if obj:
                constants.data['items'][obj['$ID']] = obj
                constants.data['items_by_name'][obj['$ID_NAME']] = obj
                log.warning(f"Gem item '{row['ClassName']}' was missing a base entry; created a minimal fallback")
            else:
                log.error(f"Failed to create fallback for gem item '{row['ClassName']}'")
                if constants.region != 'itos':
                    raise
                continue
    ies_file.close()
    return constants

def parse_gems_bonus(constants):
    log = logging.getLogger("parser.gems.bonus")
    log.setLevel("INFO")
    log.info('Parsing gems bonus...')

    xml_path = os.path.join(constants.PATH_INPUT_DATA, 'xml.ipf', 'socket_property.xml')
    if(not exists(xml_path)):
       return
    xml = ET.parse(xml_path).getroot()

    SLOTS = ['TopLeg', 'HandOrFoot', 'MainOrSubWeapon']

    # example: <Item Name="gem_circle_1">
    for item in xml:
        try:
            gem = constants.data['items_by_name'][item.get('Name')]
        except KeyError:
            # Create a minimal fallback gem for bonus processing
            fallback_obj = create_fallback_item(constants, item.get('Name'), 'GEM')
            if fallback_obj:
                constants.data['items'][fallback_obj['$ID']] = fallback_obj
                constants.data['items_by_name'][fallback_obj['$ID_NAME']] = fallback_obj
                gem = fallback_obj
                log.warning(f"Gem bonus item '{item.get('Name')}' was missing a base entry; created a minimal fallback")
            else:
                log.error(f"Failed to create fallback for gem bonus item '{item.get('Name')}'")
                logging.warning('gem not found {}'.format(item.get('Name')))
                continue

        for level in item:
            if level.get('Level') == '0':
                continue

            for slot in SLOTS:
                bonus = level.get('PropList_' + slot)
                penalty = level.get('PropList_' + slot + '_Penalty')

                for slot in (slot.split('Or') if 'Or' in slot else [slot]): # support for Re:Build 2-in-1 slots
                    for prop in [bonus, penalty]:
                        if prop is not None and prop != 'None':
                            if gem['TypeGem'] == 'Gem_Skill':
                                gem['Bonus' + parse_gems_slot(slot)].append({
                                    'Level': int(level.get('Level')),
                                    'Stat': constants.translate(prop).replace('OptDesc/', '')
                                })
                            elif gem['TypeGem'] == "Gem":
                                prop_slot = prop.split('/')

                                stat ='ADD_' + prop_slot[0]
                                stat = prop_slot[0] if stat is None else stat

                                try:
                                    value = int(prop_slot[1])
                                except ValueError:
                                    # 한글 텍스트나 다른 형식의 값은 그대로 저장
                                    value = prop_slot[1]
                                gem['Bonus' + parse_gems_slot(slot)].append({
                                    'Level': int(level.get('Level')),
                                    'Stat': stat,
                                    'Value': value
                                })
            constants.data['items'][gem['$ID']] = gem


def parse_gems_slot(key):
    return {
        'Foot': 'Boots',
        'Hand': 'Gloves',
        'Main': 'Weapon',
        'SubWeapon': 'SubWeapon',
        'TopLeg': 'TopAndBottom',
        'Weapon': 'Weapon',
    }[key]

def parse_links_skills(constants):
    log = logging.getLogger("parser.gem.link")
    log.setLevel("INFO")
    log.info('Parsing skills for gems...')

    for gem in constants.data['items'].values():
        if gem['Type'] != 'GEM':
            continue
        skill = gem['$ID_NAME'][len('Gem_'):]
        if (skill not in constants.data['skills_by_name']):
            logging.debug('skills missing : %s', skill)
            continue
        skill = constants.data['skills_by_name'][skill]['$ID']
        gem['Link_Skill'] = skill
        constants.data['items'][gem['$ID']] = gem
        


def parse_links_recipes(constants):
    log = logging.getLogger("parser.recipe.link")
    log.setLevel("INFO")
    log.info('Parsing items for recipes...')

    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'recipe.ies')
    if(not exists(ies_path)):
       return
    ies_file = open(ies_path, 'r', encoding = "utf-8")
    ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')
    if 'RECIPES' not in constants.data['item_type']:
         constants.data['item_type']['RECIPES'] = []
    for row in ies_reader:
        try:
            recipe = constants.data['items_by_name'][row['ClassName']]
        except KeyError:
            # Create a minimal fallback recipe item
            recipe = create_fallback_item(constants, row['ClassName'], 'RECIPE')
            if recipe:
                constants.data['items'][recipe['$ID']] = recipe
                constants.data['items_by_name'][recipe['$ID_NAME']] = recipe
                log.warning(f"Recipe item '{row['ClassName']}' was missing a base entry; created a minimal fallback")
            else:
                log.error(f"Failed to create fallback for recipe item '{row['ClassName']}'")
                if constants.region != 'itos':
                    raise
                continue
        constants.data['item_type']['RECIPES'].append(recipe['$ID_NAME'])
        if row['TargetItem'] in constants.data['items_by_name'] :
            recipe['Link_Target'] = constants.data['items_by_name'][row['TargetItem']]['$ID_NAME']
        else:
            log.warning('recipe target not found {}'.format( row['TargetItem']))
            continue
        recipe['Name'] = 'Recipe - Unknown'
        recipe['Type'] = "RECIPES"
        if recipe['Link_Target'] is not None:
            recipe['Name'] = 'Recipe - ' + constants.data['items_by_name'][row['TargetItem']]['Name']

        # Parse ingredients
        for i in range(1, 6):
            if row['Item_' + str(i) + '_1'] == '':
                continue

            obj = {}
            try:
                obj['Item'] = constants.data['items_by_name'][row['Item_' + str(i) + '_1']]['$ID_NAME']
            except KeyError:
                # Create a minimal fallback recipe ingredient
                ingredient_name = row['Item_' + str(i) + '_1']
                fallback_obj = create_fallback_item(constants, ingredient_name, 'RECIPE_INGREDIENT')
                if fallback_obj:
                    constants.data['items'][fallback_obj['$ID']] = fallback_obj
                    constants.data['items_by_name'][fallback_obj['$ID_NAME']] = fallback_obj
                    obj['Item'] = fallback_obj['$ID_NAME']
                    log.warning(f"Recipe ingredient '{ingredient_name}' was missing a base entry; created a minimal fallback")
                else:
                    log.error(f"Failed to create fallback for recipe ingredient '{ingredient_name}'")
                    if constants.region != 'itos':
                        logging.warn("missing item {} for recipe {}".format(ingredient_name, recipe['Name']))
                    continue
            obj['Quantity'] = int(row['Item_' + str(i) + '_1_Cnt'])
            
            if 'Link_Materials' not in recipe.keys():
                recipe['Link_Materials'] = []
                
            recipe['Link_Materials'].append(obj)
            
        constants.data['items'][recipe['$ID']] = recipe
    ies_file.close()

def parse_gem_bernice(constants):
    file = 'item_gem_relic.ies'
    logging.debug('Parsing bernice gems (ep13)...')
    
    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf',file)
    ies_file = open(ies_path, 'r', encoding = 'utf-8')
    ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')
    rows = []
    for row in ies_reader:
        rows.append(row)
    ies_file.close()
    return constants


# def parse_books_dialog(constants):
#     logging.debug('Parsing books dialog...')

#     ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies_client.ipf', 'dialogtext.ies')
#     if(not exists(ies_path)):
#        return
#     ies_file = io.open(ies_path, 'r', encoding = 'utf-8')
#     ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')
#     b = []
#     if 'BOOKS' not in constants.data['item_type']:
#         constants.data['item_type']['BOOKS'] = []
#     for row in ies_reader:
#         # Skip dialog texts that are not actual items (NPC dialogs, quest dialogs, events, etc.)
#         class_name = row['ClassName']
#         skip_keywords = [
#             '_DLG', '_SNPC_', '_MQ_', '_DIALOG', 'CORAL_RAID', 'CASTLE_RAID',
#             'EVENT_', 'Demonicar_', 'VI_SANTA_', 'W_MOON_', 'Object_Interaction',
#             'REGULAR_BURNING', 'UNKNOWN_SANTUARY', 'TOSHERO_', 'REPUTATION_',
#             '_START_', '_GUIDE', '_NEWYEAR', '_MUSCLE_', '_FRIEND_', '_LITTLE',
#             '_GHOST_', '_SUPPLY_', '_FISHING_', '_WHITEDAY_', '_CANDY',
#             'EQUIPMENT_PROCESSING', 'SELECT_', 'CHECK_', 'GIMMICK_', 'AreaStart',
#             '_Use', '_Active', '_BASIC', '_POSSIBLEQUEST', 'TRADE_SELLING'
#         ]
#         if any(keyword in class_name for keyword in skip_keywords):
#             log.debug("Skipping dialog/event text '{}' as it's not an actual item".format(class_name))
#             continue
            
#         try:
#             book = constants.data['items_by_name'][row['ClassName']]
#         except KeyError:
#             # Create a minimal fallback book item
#             book = create_fallback_item(constants, row['ClassName'], 'BOOK')
#             if book:
#                 constants.data['items'][book['$ID']] = book
#                 constants.data['items_by_name'][book['$ID_NAME']] = book
#                 log.warning(f"Book item '{row['ClassName']}' was missing a base entry; created a minimal fallback")
#             else:
#                 log.error(f"Failed to create fallback for book item '{row['ClassName']}'")
#                 continue
#         constants.data['item_type']['BOOKS'].append(book['$ID_NAME'])
#         if 'Text' not in book:
#             book['Text'] = None
        
#         book['Text'] = constants.translate(row['Text'])
#         b.append(book)
#         constants.data['items'][book['$ID']] = book
#         constants.data['items_by_name'][book['$ID_NAME']] = book
    
#     ies_file.close()

def parse_goddess_EQ(c):
    LUA_RUNTIME = luautil.LUA_RUNTIME
    LUA_SOURCE = luautil.LUA_SOURCE
    # c.data는 클래스 가변 상태(DB.py)라 같은 프로세스에서 다른 constants로
    # 재실행하면 이전 빌드의 goddess_reinf 레벨이 잔존한다. 매번 새 dict로 교체한다.
    c.data['goddess_reinf'] = {}
    # 550은 accessory 전용(5열 IES)이며 Lua acc 분기만 존재한다.
    # 현재 지역에 550 IES가 없으면(twtos/ktest) material 생성과 acc 550 호출을
    # 건너뛴다. 정적 EQUIPMENT_REINFORCE_IES 등록 여부와 현재 지역 파일 존재를 분리.
    has_550 = ('item_goddess_reinforce_550.ies' in c.EQUIPMENT_REINFORCE_IES
               and 'item_goddess_reinforce_550.ies' in c.file_dict)
    has_560 = ('item_goddess_reinforce_560.ies' in c.EQUIPMENT_REINFORCE_IES
               and 'item_goddess_reinforce_560.ies' in c.file_dict)
    weapon_armor_levels = [480, 500, 520, 540] + ([560] if has_560 else [])
    acc_levels = [470, 490, 510, 530] + ([550] if has_550 else [])
    func_list = {'setting_lv_material_acc' : acc_levels,
                 'setting_lv_material_armor' : weapon_armor_levels,
                 'setting_lv_material_weapon' : weapon_armor_levels,
                 'setting_lv460_material' : 460,
                 }
    #mat_list_by_lv[460][1][seasonCoin]
    #mat_list_by_lv[lv]['armor'][1][seasonCoin] = 263
    mat  = {
            460: { i : {} for i in range(1, 31) },
            470: {
                'acc' : {i : {} for i in range(1, 31) },
                'armor': {i : {} for i in range(1, 31) },
                'weapon': {i : {} for i in range(1, 31) }
                },
            480: {
                'acc' : {i : {} for i in range(1, 31) },
                'armor': {i : {} for i in range(1, 31) },
                'weapon': {i : {} for i in range(1, 31) }
                },
            490: {
                'acc' : {i : {} for i in range(1, 31) },
                'armor': {i : {} for i in range(1, 31) },
                'weapon': {i : {} for i in range(1, 31) }
                },
            500: {
                'acc' : {i : {} for i in range(1, 31) },
                'armor': {i : {} for i in range(1, 31) },
                'weapon': {i : {} for i in range(1, 31) }
                },
            510: {
                'acc' : {i : {} for i in range(1, 31) },
                'armor': {i : {} for i in range(1, 31) },
                'weapon': {i : {} for i in range(1, 31) }
                },
            520: {
                'acc' : {i : {} for i in range(1, 31) },
                'armor': {i : {} for i in range(1, 31) },
                'weapon': {i : {} for i in range(1, 31) }
                },
            530: {
                'acc' : {i : {} for i in range(1, 31) },
                'armor': {i : {} for i in range(1, 31) },
                'weapon': {i : {} for i in range(1, 31) }
                },
            540: {
                'acc' : {i : {} for i in range(1, 31) },
                'armor': {i : {} for i in range(1, 31) },
                'weapon': {i : {} for i in range(1, 31) }
                }
        }
    # 550은 accessory 전용: acc만 30단계 슬롯을 만든다.
    # armor/weapon은 키 자체를 두지 않는다(None이 아님). Lua acc 함수가
    # mat[550]['acc'][i]에만 쓰므로 안전하며, JSON 소비자는 부재를 키 유무로 판별한다.
    if has_550:
        mat[550] = {'acc' : {i : {} for i in range(1, 31) }}
    if has_560:
        mat[560] = {group: {i: {} for i in range(1, 31)} for group in ('armor', 'weapon')}
        for group in ('armor', 'weapon'):
            function = 'setting_lv_material_' + group
            if function not in LUA_RUNTIME:
                raise ValueError('Missing goddess 560 material function: ' + function)
    for func in func_list:
        levels = func_list[func]
        if func not in LUA_RUNTIME:
            continue
        
        # setting_lv460_material은 단일 레벨 처리
        if func == 'setting_lv460_material':
            LUA_RUNTIME[func](mat)
        else:
            # 나머지 함수들은 여러 레벨 처리
            if isinstance(levels, list):
                for lv in levels:
                    LUA_RUNTIME[func](mat, lv)
            else:
                LUA_RUNTIME[func](mat, levels)
    if has_560:
        for group in ('armor', 'weapon'):
            steps = mat[560][group]
            if not any(steps.values()):
                raise ValueError('Empty goddess 560 material calculation: ' + group)
            for materials in steps.values():
                for quantity in materials.values():
                    if (type(quantity) not in (int, float) or not isfinite(quantity)
                            or quantity < 0 or quantity != int(quantity)):
                        raise ValueError('Invalid goddess 560 material quantity: ' + group)
    a = mat[460] 
    mat[460]  = {'armor' : a}
    c.data['goddess_reinf_mat'] = mat
    
    ies_list = c.EQUIPMENT_REINFORCE_IES
    objs = {}
    for ies in ies_list:
        file_name = ies.lower()
        try:
            ies_path= c.file_dict[file_name]['path']
        except:
            continue
        obj = read_goddess_reinforce_rows(c, file_name)
        objs[ies_list[ies]] = obj
        c.data['goddess_reinf'][ies_list[ies]] = obj
    # File discovery is broader than the allowlist. Surface future tables without
    # interpreting preloaded data as a released level or a supported Lua branch.
    unregistered = {}
    for filename in sorted(c.file_dict):
        match = re.fullmatch(r'item_goddess_reinforce_(\d+)\.ies', filename)
        if match and filename not in ies_list:
            unregistered[filename] = int(match.group(1))
            log.warning('Unregistered goddess reinforcement table: %s (level %s)',
                        filename, match.group(1))
    c.data['goddess_reinf_unregistered'] = unregistered
