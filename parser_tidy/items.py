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
import luautil
from math import floor
import xml.etree.ElementTree as ET
import parse_xac
# from shared.ipf/item_calculate.lua
EQUIPMENT_STAT_COLUMNS = []

equipment_grade_ratios = {}
goddess_atk_list       = {}

log = logging.getLogger("parse.items")
log.setLevel("INFO")

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

    StringArg 형식 (Script 변형별):
    - *_NUMBER_SPLIT / RANDOM_*_NUMBER_SPLIT : "ClassName/개수;ClassName/개수;…"
    - SCR_USE_STRING_GIVE_ITEM (정확히)      : "ClassName" 1건, 1개 지급
    - SCR_USE_STRING_GIVE_ITEM_NUMBER (정확히): "ClassName" 1건, NumberArg1 개 지급
    형식 불일치 토큰은 개수를 1 로 지어내지 않고 경고 후 건너뛴다
    (틀린 수량을 사실처럼 노출하지 않기 위함).
    """
    items_by_name = constants.data['items_by_name']
    resolved = 0
    for obj in list(constants.data['items'].values()):
        raw = obj.pop('PackageContents_Raw', None)
        if raw is None:
            continue
        script, string_arg, number_arg1 = raw
        entries = []
        for token in string_arg.split(';'):
            token = token.strip()
            if not token:
                continue
            if '/' in token:
                class_name, _, count_str = token.rpartition('/')
                class_name = class_name.strip()
                try:
                    count = int(count_str)
                except ValueError:
                    count = 0
            elif script == 'SCR_USE_STRING_GIVE_ITEM':
                class_name, count = token, 1
            elif script == 'SCR_USE_STRING_GIVE_ITEM_NUMBER':
                class_name = token
                try:
                    count = int(number_arg1)
                except ValueError:
                    count = 0
            else:
                class_name, count = '', 0
            if not class_name or count <= 0:
                log.warning(
                    'package token skipped: %r (item=%s script=%s)',
                    token, obj['$ID_NAME'], script,
                )
                continue
            ref = items_by_name.get(class_name)
            entries.append({
                'item': class_name,
                'name': ref['Name'] if ref else None,
                'count': count,
            })
        if entries:
            obj['PackageContents'] = {
                'random': script.startswith('SCR_USE_STRING_RANDOM'),
                'items': entries,
            }
            resolved += 1
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
    a = luautil.LUA_RUNTIME['GET_COMMON_PROP_LIST']()
    EQUIPMENT_STAT_COLUMNS =[a[i] for i in a]
    
    parse_equipment_grade_ratios(c)
    global equipment_grade_ratios        
    equipment_grade_ratios = c.data['equipment_grade_ratios']
    
    
    parse_goddess_reinf(c)
    
    # Parse goddess equipment materials for all levels including 530, 540
    parse_goddess_EQ(c)
    
    for i in equipment_ies:    
        parse_equips(c, i)
    
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
        obj['Grade'] = row['ItemGrade']  if 'ItemGrade' in row else 1
        if obj['Grade'] == "":
            obj['Grade'] = 1
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
            constants.cubes_by_stringarg[row['StringArg']] = obj
        # 패키지류(사용 시 구성물 지급) 원본 보관. 이름 해석은 모든 item ies
        # 파싱이 끝난 뒤 resolve_package_contents() 후처리에서 수행한다.
        script = (row.get('Script') or '').strip()
        if (
            script.startswith(('SCR_USE_STRING_GIVE_ITEM', 'SCR_USE_STRING_RANDOM_GIVE_ITEM'))
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
   

def parse_equips(constants, filename):
    log = logging.getLogger("parser.equips")
    log.setLevel("INFO")
    log.info('Parsing equipment %s ...'%(filename))
    try:
        ies_path =  constants.file_dict[filename.lower()]['path']
    except:
        logging.warning("file not found {}".format(filename))
        return
    
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
            
        item_grade = equipment_grade_ratios[int(row['ItemGrade'])]
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
            except :
                pass

        # Add additional fields
        obj['AnvilATK'] = []
        obj['AnvilDEF'] = []
        obj['AnvilPrice'] = []
        obj['Bonus'] = []
        obj['Durability'] = int(row['MaxDur']) / 100
        obj['Durability'] = -1 if obj['Durability'] <= 0 else obj['Durability']
        obj['Grade'] = int(row['ItemGrade'])
        if obj['Grade'] == "":
            obj['Grade'] = 1
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
                    atk = goddess_atk_list[int(row['UseLv'])]['BasicAccAtk']
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
            if any(prop in row['BasicTooltipProp'] for prop in ['ATK', 'DEF', 'MATK', 'MDEF']):
                for lv in range(40):
                    row['Reinforce_2'] = lv
                    if any(prop in row['BasicTooltipProp'] for prop in ['DEF', 'MDEF']):
                        obj['AnvilDEF'].append(LUA_RUNTIME['GET_REINFORCE_ADD_VALUE'](None, row, 0, 1))
                        obj['AnvilPrice'].append(LUA_RUNTIME[reinf](row, {}, None))
                    if any(prop in row['BasicTooltipProp'] for prop in ['ATK', 'MATK']):
                        obj['AnvilATK'].append(LUA_RUNTIME['GET_REINFORCE_ADD_VALUE_ATK'](row, 0, 1, None))
                        obj['AnvilPrice'].append(LUA_RUNTIME[reinf](row, {}, None))
               
    
            obj['AnvilPrice'] = [int(value) for value in obj['AnvilPrice'] if value > 0]
            obj['AnvilATK'] = [int(value) for value in obj['AnvilATK'] if value > 0] if len(obj['AnvilPrice']) > 0 else None
            obj['AnvilDEF'] = [int(value) for value in obj['AnvilDEF'] if value > 0] if len(obj['AnvilPrice']) > 0 else None
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


def parse_goddess_reinf(constants):
    files = constants.EQUIPMENT_REINFORCE_IES
    global goddess_atk_list
    for i in files:
        
        if i not in constants.file_dict:
            continue
        ies_path = constants.file_dict[i]['path']
        ies_file = io.open(ies_path, 'r', encoding = 'utf-8')
        ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')
        rows = []
        for row in ies_reader:
            rows.append(row)
        row = rows[0]
        goddess_atk_list[files[i]] = row
        
        

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
    a = []
    for row in ies_reader:
        if row['Group'] not in constants.data['items_by_name']:
            continue
        
        if row['Group'] not in constants.cubes_by_stringarg:
            continue
        a.append(row)
        cube = constants.cubes_by_stringarg[row['Group']]
        constants.data['item_type']['CUBES'].append(cube['$ID_NAME'])
        cube['Type']         = 'Cube'
        if not 'Link_Items' in cube.keys():
            cube['Link_Items'] = []
        try:
            cube['Link_Items'].append(constants.data['items_by_name'][row['ItemName']]['ID_NAME'])
            constants.data['items'] [cube['$ID']] = cube
            constants.data['items_by_name'] [cube['$ID_NAME']] = cube
        except KeyError:
            # Create a minimal fallback cube item
            fallback_obj = create_fallback_item(constants, row['ItemName'], 'CUBE')
            if fallback_obj:
                constants.data['items'][fallback_obj['$ID']] = fallback_obj
                constants.data['items_by_name'][fallback_obj['$ID_NAME']] = fallback_obj
                cube['Link_Items'].append(fallback_obj['$ID_NAME'])
                log.warning(f"Cube item '{row['ItemName']}' was missing a base entry; created a minimal fallback")
            else:
                log.error(f"Failed to create fallback for cube item '{row['ItemName']}'")
                if constants.region != 'itos':
                    print("key error ... {} for {} cube".format(row['ItemName'], cube['Name']))
            constants.data['items'][cube['$ID']] = cube
            constants.data['items_by_name'][cube['$ID_NAME']] = cube
    
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
    func_list = {'setting_lv_material_acc' : [470, 490, 510, 530],
                 'setting_lv_material_armor' : [480, 500, 520, 540], 
                 'setting_lv_material_weapon' : [480, 500, 520, 540],
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
        ies_file = io.open(ies_path, 'r', encoding="utf-8")
        ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')
        obj  = []
        for row in ies_reader:
            obj.append(row)
        objs[ies_list[ies]] = obj
        c.data['goddess_reinf'][ies_list[ies]] = obj