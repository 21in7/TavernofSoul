# -*- coding: utf-8 -*-
"""
Created on Sun Oct  3 21:18:15 2021
@author: Intel
"""

import csv
import logging
import os
import re
from os.path import exists
from PIL import Image, ImageDraw, ImageColor, ImageFilter, ImageOps, ImageChops

from DB import ToS_DB as constants
import luautil

import  imageutil

MAP_SCALE = 0.5

def trim(image):    
    # remove alpha channel
    invert_im = image.convert("RGB") 
    
    # invert image (so that white is 0)
    im  = image
    bg = Image.new(im.mode, im.size, im.getpixel((0,0)))
    invert_im = ImageOps.invert(invert_im)
    diff = ImageChops.difference(im, bg)
    diff = ImageChops.add(diff, diff, 2.0, -100)
    bbox = diff.getbbox()
    cropped=image.crop(bbox)
    return bbox,cropped




def parse(c = None):
    if (c==None):
        c = constants()
        c.build(c.iTOS)
    try:
        os.mkdir(c.PATH_BUILD_ASSETS_IMAGES_MAPS)
    except:
        pass
    parse_maps(c)
    

def parse_maps(constants):
    logging.debug('Parsing Maps...')

    #ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'map.ies')
    ies_path = constants.file_dict['map.ies']['path']
    rows = []
    with open(ies_path, 'r', encoding = 'utf-8') as ies_file:
        for row in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
            rows.append(row)
            obj = {}
            if str(row['ClassID']) in constants.data['maps']:
                #continue
                obj = constants.data['maps'][row['ClassID']]
            obj['$ID'] = str(row['ClassID'])
            obj['$ID_NAME'] = row['ClassName']
            obj['Icon'] = None
            obj['Name'] = constants.translate(row['Name'])

            obj['HasChallengeMode'] = row['ChallengeMode'] == 'YES'
            obj['HasWarp'] = int(row['WarpCost']) > 0
            obj['Level'] = int(row['QuestLevel'])
            obj['Prop_EliteMonsterCapacity'] = int(row['EliteMonsterCapacity'])
            obj['Prop_MaxHateCount'] = int(row['MaxHateCount'])
            obj['Prop_RewardEXPBM'] = float(row['MaxHateCount'])
            obj['Stars'] = int(row['MapRank'])
            obj['Type'] = row['MapType']
            obj['Warp'] = int(row['WarpCost'])
            obj['WorldMap'] = [int(coord) for coord in row['WorldMap'].split('/')] if row['WorldMap'] else None

            obj['Link_Items'] = []
            obj['Link_Items_Exploration'] = []
            obj['Link_Maps'] = []
            obj['Link_Maps_Floors'] = []
            obj['Link_NPCs'] = []
            if ("bbox" not in obj):
                obj['bbox']     = [0,0,0,0]
            constants.data['maps'][obj['$ID']] = obj
            constants.data['maps_by_name'][obj['$ID_NAME']] = obj
            constants.data['maps_by_position']['-'.join(row['WorldMap'].split('/')) if obj['WorldMap'] else ''] = obj


def parse_maps_images(constants):

    logging.debug('Parsing Maps images...')
    log = logging.getLogger("parse.items")
    log.setLevel("INFO")

    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'map.ies')
    ies_path = constants.file_dict['map.ies']['path']
    rows = []
    with open(ies_path, 'r', encoding = 'utf-8') as ies_file:
        for row in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
            rows.append(row)
            image_path = os.path.join(constants.PATH_BUILD_ASSETS_IMAGES_MAPS, row['ClassName'].lower() + '.png')
            map = constants.data['maps_by_name'][row['ClassName']]
            if (exists(image_path) and map['bbox'] != [0,0,0,0]):
                continue
            polygons = constants.importJSON(os.path.join('maps_poly',row['ClassName'].lower()+'poly.json'))
            if polygons == {}:
                continue
            # Scale map to save some space
            image_height = int(round(int(row['Height']) * MAP_SCALE))
            image_width = int(round(int(row['Width']) * MAP_SCALE))

            offset_x = image_width / 2.0
            offset_y = image_height / 2.0

            # Render map to image
            image = Image.new("RGBA", (image_width, image_height), (0, 0, 0, 0))
            image_draw = ImageDraw.Draw(image)

            for points in polygons:
                # Make sure coordinates are centered
                points = [(int(offset_x + coords[0] * MAP_SCALE), int(offset_y + coords[1] * MAP_SCALE)) for coords in points]

                image_draw.polygon(points, fill=ImageColor.getrgb('#67768a'))

            # Add a shadow
            image_shadow = imageutil.replace_color(image, ImageColor.getcolor('#F2BC65', 'RGBA'), ImageColor.getcolor('#000000', 'RGBA'))
            image_shadow = image_shadow.filter(ImageFilter.GaussianBlur(2))
            image = Image.composite(image, image_shadow, image_shadow)
            bbox,image= trim(image)
            log.info("map : {} bbox : {}".format(row['ClassName'], bbox))
            # Save image to disk
            try:
                os.mkdir(constants.PATH_BUILD_ASSETS_IMAGES_MAPS)
            except:
                pass
            image.save(image_path, optimize=True)
            image.close()
            image_shadow.close()
            
            map['bbox'] = bbox
            constants.data['maps'][map['$ID']] = map


def parse_links(c = None):
    if (c==None):
        c = constants()
        c.build(c.iTOS)
    c.data['map_item'] = []
    c.data['map_item_spawn'] = []
    # Retain monster diagnostics when rebuilding only map relations.
    c.data['unresolved_drops'] = [row for row in c.data['unresolved_drops']
                                  if row.get('collection') != 'map_item']
    parse_links_items(c)
    parse_links_items_rewards(c)

    parse_links_maps(c)

    c.data['map_npc'] = []
    parse_links_npcs(c)



def parse_links_items(constants):
    logging.debug('Parsing Maps <> Items...')

    # P0-10: 드롭 소스 결정과 provenance 기록을 데이터셋 단위로 한 번 수행한다.
    # 기존 ../itos_unpack 하드코딩을 제거하고 zonedrop/dropgroup/f_ 변형 모두
    # 동일 소스 drop_ipf 기준으로 통일했다.
    import drop_source
    src = drop_source.get_drop_source(constants)
    constants.data['build_provenance']['map_item'] = {
        'source_region'   : src['source_region'],
        'input_version'   : src['input_version'],
        'fallback_reason' : src['fallback_reason'],
    }

    if src['drop_ipf'] is None:
        logging.warning('Maps <> Items: %s', src['fallback_reason'])
        return

    zonedrop = drop_source.list_drop_subdir(src['drop_ipf'], 'zonedrop')
    dropgroup = drop_source.list_drop_subdir(src['drop_ipf'], 'dropgroup')

    items_by_name = constants.data['items_by_name']
    unresolved = constants.data['unresolved_drops']

    for map in constants.data['maps'].values():
        if map is None:
            continue

        # ZoneDropItemList_<map>.ies (또는 zonedropitemlist_f_<map>.ies 변형)
        zone_path = None
        for pattern in ('ZoneDropItemList_', 'zonedropitemlist_f_'):
            candidate = pattern + map['$ID_NAME'] + '.ies'
            actual = zonedrop['ci'].get(candidate.lower())
            if actual is not None:
                zone_path = os.path.join(zonedrop['dir'], actual)
                break

        if zone_path is None or not os.path.isfile(zone_path):
            continue

        drops = []
        try:
            with open(zone_path, 'r', encoding='utf-8') as zone_fh:
                # Unknownsanctuary 계열은 chance 기준이 다르다. zone_path 기준으로
                # 고정한다(과거엔 dropgroup 이 ies_path 를 덮어써 오염됐었다).
                chance = 10000.0 if 'id_unknownsanctuary' in zone_path.lower() else 100.0
                for zone_drop in csv.DictReader(zone_fh, delimiter=',', quotechar='"'):
                    if not zone_drop['ItemClassName'] and not zone_drop['DropGroup']:
                        continue
                    zone_ratio = int(zone_drop['DropRatio']) / chance
                    if not 0 <= zone_ratio <= 100:
                        raise ValueError('{}: zonedrop chance must be in 0..100'.format(zone_path))
                    if len(zone_drop['ItemClassName']) > 0:
                        drops.append({
                            'ItemClassName': zone_drop['ItemClassName'],
                            'DropRatio': zone_ratio,
                        })

                    if len(zone_drop['DropGroup']) > 0:
                        group_name = zone_drop['DropGroup'] + '.ies'
                        actual_g = dropgroup['ci'].get(group_name.lower())
                        if actual_g is None:
                            logging.debug('dropgroup not found: %s', group_name)
                            continue
                        group_path = os.path.join(dropgroup['dir'], actual_g)

                        group_drop_ratio = 0
                        group_drops = []
                        try:
                            with open(group_path, 'r', encoding='utf-8') as group_fh:
                                for group_drop in csv.DictReader(group_fh, delimiter=',', quotechar='"'):
                                    weight = int(group_drop['DropRatio'])
                                    if weight < 0:
                                        raise ValueError('{}: negative dropgroup weight'.format(group_path))
                                    group_drop_ratio += weight
                                    group_drops.append({
                                        'ItemClassName': group_drop['ItemClassName'],
                                        'DropRatio': weight,
                                    })
                        except (IOError, OSError):
                            logging.debug('dropgroup unreadable: %s', group_path)
                            continue

                        if group_drop_ratio == 0:
                            logging.debug('dropgroup sum 0, skipping: %s', group_name)
                            continue

                        for group_drop in group_drops:
                            group_drop['DropRatio'] = (
                                zone_ratio
                                * group_drop['DropRatio'] / group_drop_ratio
                            )
                            drops.append(group_drop)

        except (IOError, OSError):
            continue

        for drop in drops:
            item_classname = drop['ItemClassName']
            ref = items_by_name.get(item_classname)
            if ref is None:
                unresolved.append({
                    'collection'     : 'map_item',
                    'map'            : map['$ID'],
                    'map_name'       : map['$ID_NAME'],
                    'item_classname' : item_classname,
                    'source_region'  : src['source_region'],
                })
                continue
            # Quantity_* = 0: 직접 zonedrop/dropgroup 모두 수량 정보를 원본에서
            # 신뢰할 수 없다(실버 드롭은 삭제됨). 0은 수량 미제공 호환값이다.
            # importer(Map_Item.qty_max/min 기본값 0)와 importMap.py 필수 키 접근에 안전.
            constants.data['map_item'].append({
                'Chance'        : drop['DropRatio'],
                'Item'          : ref['$ID'],
                'Map'           : map['$ID'],
                'Quantity_MAX'  : 0,
                'Quantity_MIN'  : 0,
                'SourceRegion'  : src['source_region'],
                'InputVersion'  : src['input_version'],
            })


def parse_links_items_rewards(constants):
    log = logging.getLogger("parser.links.maps.rewards")
    
    # 파일 핸들러 추가
    # fh = logging.FileHandler('missing_maps.log')
    # fh.setLevel(logging.WARNING)
    # formatter = logging.Formatter('%(asctime)s - %(message)s')
    # fh.setFormatter(formatter)
    # log.addHandler(fh)

    # 이미 처리된 맵 추적
    processed_maps = set()

    try:
        ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'map.ies')
        if not exists(ies_path):
            return

        ies_file = open(ies_path, 'r', encoding='utf-8')
        ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')

        for row in ies_reader:
            class_name = row['ClassName']
            
            # 이미 처리된 맵은 건너뛰기
            if class_name in processed_maps:
                continue
                
            processed_maps.add(class_name)

            # maps_by_name에 없는 경우 새로 생성
            if class_name not in constants.data['maps_by_name']:
                log.warning(f"Missing map in dictionary: {class_name}")
                obj = {
                    '$ID': row.get('ClassID', ''),
                    '$ID_NAME': class_name,
                    'Name': row.get('Name', ''),
                    'Icon': None,
                    'HasChallengeMode': row.get('ChallengeMode', '') == 'YES',
                    'HasWarp': int(row.get('WarpCost', 0)) > 0,
                    'Level': int(row.get('QuestLevel', 0)),
                    'Prop_EliteMonsterCapacity': int(row.get('EliteMonsterCapacity', 0)),
                    'Prop_MaxHateCount': int(row.get('MaxHateCount', 0)),
                    'Prop_RewardEXPBM': float(row.get('MaxHateCount', 0)),
                    'Stars': int(row.get('MapRank', 0)),
                    'Type': row.get('MapType', ''),
                    'Warp': int(row.get('WarpCost', 0)),
                    'WorldMap': [int(coord) for coord in row.get('WorldMap', '').split('/')] if row.get('WorldMap') else None,
                    'Link_Items': [],
                    'Link_Items_Exploration': [],
                    'Link_Maps': [],
                    'Link_Maps_Floors': [],
                    'Link_NPCs': [],
                    'bbox': [0,0,0,0]
                }
                constants.data['maps_by_name'][class_name] = obj

            map = constants.data['maps_by_name'][class_name]
            
            # 여기에 기존의 맵 처리 로직 계속...
            
    finally:
        if 'ies_file' in locals():
            ies_file.close()
        # 파일 핸들러 제거
        # log.removeHandler(fh)
        # fh.close()

    return constants


def parse_links_maps(constants):
    logging.debug('Parsing Maps <> Maps...')

    #ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'map.ies')
    ies_path = constants.file_dict['map.ies']['path']
    for map in constants.data['maps'].values():
        map['Link_Maps'] = []
        map['Link_Maps_Floors'] = []
    with open(ies_path, 'r', encoding='utf8') as ies_file:
        for row in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
            map = constants.data['maps_by_name'][row['ClassName']]
            map['Link_Maps'] = [constants.data['maps_by_name'][name]['$ID']
                               for name in row['PhysicalLinkZone'].split('/') if name]
            # Only upper floors belong to the ground floor's additional list.
            if map['WorldMap'] is not None and map['WorldMap'][2] > 1:
                ground = '-'.join(str(i) for i in map['WorldMap'][0:2] + [1])
                constants.data['maps_by_position'][ground]['Link_Maps_Floors'].append(map['$ID'])


def parse_links_npcs(constants):
    logging.debug('Parsing Maps <> NPCs...')

    #ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'map.ies')
    ies_path = constants.file_dict['map.ies']['path']
    with open(ies_path, 'r', encoding = 'utf8') as ies_file:
        for row in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
            map = constants.data['maps_by_name'][row['ClassName']]
            map = constants.data['maps'][str(map['$ID'])]
            map_offset_x = int(round(int(row['Width']) / 2.0))
            map_offset_y = int(round(int(row['Height']) / 2.0))

            anchors = {}

            # Spawn Positions (aka Anchors)
            mongen_dir = os.listdir(os.path.join(constants.PATH_INPUT_DATA, 'ies_mongen.ipf'))
            path_insensitive= {}
            for item in mongen_dir:
                path_insensitive[item.lower()] = item
                
            ies_file = 'anchor_' + map['$ID_NAME'] + '.ies'
            try:
                ies_file = path_insensitive[ies_file.lower()]
            except:
                logging.debug("maps not found {}".format(ies_file))
                pass
            
            ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies_mongen.ipf', ies_file)
            
            try:
                with open(ies_path, 'r', encoding='utf8') as ies_file:
                    for row in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
                        obj = anchors[row['GenType']] if row['GenType'] in anchors else { 'Anchors': [], 'GenType': {} }
                        obj['Anchors'].append([
                            int((map_offset_x + float(row['PosX'])) * MAP_SCALE),
                            int((map_offset_y - float(row['PosZ'])) * MAP_SCALE),
                        ])

                        anchors[row['GenType']] = obj
            except IOError:
                logging.debug("file not found {}".format(ies_path))
                continue

            # Spawn NPCs
            
            ies_file = 'gentype_' + map['$ID_NAME'] + '.ies'
            try:
                ies_file = path_insensitive[ies_file.lower()]
            except:
                logging.debug("gentype not found {}".format(ies_file))
                pass
            ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies_mongen.ipf', ies_file)

            try:
                with open(ies_path, 'r', encoding='utf8') as ies_file:
                    for row in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
                        if constants.getNPCbyName(row['ClassType']) is None:
                            continue
                        if row['GenType'] not in anchors:
                            continue

                        obj = anchors[row['GenType']]
                        obj['GenType'] = row
            except IOError:
                continue

            # Group by Item/NPC and join anchors
            anchors_by_npc = {}

            for anchor in anchors.values():
                if len(anchor['GenType'].keys()) == 0:
                    continue

                item_name = re.search('\w+:(\w+):\w+', anchor['GenType']['ArgStr2'])
                npc_name = item_name.group(1) if item_name else anchor['GenType']['ClassType']

                if npc_name in anchors_by_npc:
                    anchors_by_npc[npc_name]['Anchors'] += anchor['Anchors']
                    anchors_by_npc[npc_name]['GenType']['MaxPop'] = int(anchors_by_npc[npc_name]['GenType']['MaxPop']) + int(anchor['GenType']['MaxPop'])
                else:
                    anchors_by_npc[npc_name] = anchor
                
            # Link everyone
            for anchor_name in anchors_by_npc.keys():
                anchor = anchors_by_npc[anchor_name]

                if anchor_name in constants.data['items_by_name']:
                    item = constants.data['items_by_name'][anchor_name]
                    item_link = item['$ID']
                    position = []
                    new_pos = []
                    for i in anchor['Anchors']:
                        pos = [i[0]-map['bbox'][0],i[1]-map['bbox'][1]]
                        new_pos.append(pos)
                        
                    item_link = {
                        'Item': item_link,
                        'Map' : map['$ID'],
                        'Population': int(anchor['GenType']['MaxPop']),
                        'Positions': new_pos,
                        'TimeRespawn': int(anchor['GenType']['RespawnTime']) / 1000.0,
                    }
                    constants.data['map_item_spawn'].append(item_link)
                    

                elif anchor_name in constants.data['npcs_by_name'] or anchor_name in constants.data['monsters_by_name']:
                    npc, types = constants.getNPCbyName(anchor_name)
                    npc_link = npc['$ID']
                    position = []
                    new_pos = []
                    for i in anchor['Anchors']:
                        pos = [i[0]-map['bbox'][0],i[1]-map['bbox'][1]]
                        new_pos.append(pos)
                    npc_link = {
                        'NPC': npc_link,
                        'Map': map['$ID'],
                        'Type' : types,
                        'Population': int(anchor['GenType']['MaxPop']),
                        'Positions': new_pos,
                        'TimeRespawn': int(anchor['GenType']['RespawnTime']) / 1000.0,
                    }
                    constants.data['map_npc'].append(npc_link)

import pandas as pd
def parseWorldMap(c):
    filename = 'map_area.ies'
    try:
        ies_path = c.file_dict[filename]['path']
    except:
        logging.warning('ies not found : %s'%(filename))
    with open(ies_path, 'r', encoding='utf-8') as f:
        ies_reader = csv.DictReader(f,  delimiter=',', quotechar='"')    
        
        rows = []
        for row in ies_reader:
            for col in row:
                try:
                    row[col] = int(row[col])
                except:
                    pass
            rows.append(row)
    mapdata = pd.DataFrame(rows)
    mapdata['Pos1_X'].apply(pd.to_numeric)
