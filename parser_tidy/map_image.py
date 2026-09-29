# -*- coding: utf-8 -*-
#!/usr/bin/env python2
"""
Created on Tue Oct  5 11:54:34 2021

@author: CPPG02619
"""


import sys
import csv
import logging
import os

from os.path import exists
from DB import ToS_DB as constants
import json

import tokutil

# Python 2.7 전용 강제 가드
if not (sys.version_info[0] == 2 and sys.version_info[1] >= 7):
    logging.error('map_image.py는 Python 2.7에서만 실행해야 합니다. 현재: %s', sys.version)
    sys.exit(1)

# tokutil의 로거 레벨을 ERROR로 설정하여 경고 메시지 숨김
tokutil_logger = logging.getLogger('tokutil')
tokutil_logger.setLevel(logging.ERROR)

MAP_SCALE = 0.2
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def parse_maps_images(c):
    """
    TOK!
    """
    logging.debug('Parsing Maps images...')
    ies_path = c.file_dict['map.ies']['path']
    with open(ies_path, 'rb') as ies_file:
        for row in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
            if exists(os.path.join('maps_poly', row['ClassName'].lower()+'poly.json')):
                continue
                
            image_path = os.path.join(c.PATH_BUILD_ASSETS_IMAGES_MAPS, row['ClassName'].lower() + '.png')
            image_path = os.path.join(c.PATH_BUILD_ASSETS_IMAGES_MAPS, row['ClassName'].lower() + '.jpg')
            tok_path = os.path.join(c.PATH_INPUT_DATA, 'bg.ipf', row['ClassName'].lower() + '.tok')
            
            if not os.path.exists(tok_path):
                continue
                
            # Parse .tok mesh file
            try:
                tok_file = open(tok_path, 'rb')
                tok_xml = tokutil.tok2xml(tok_file)
                
                # tok_xml이 None이거나 자식 요소가 없는 경우 건너뛰기
                if tok_xml is None or not tok_xml.getchildren():
                    logging.warning("Invalid tok_xml for %s", row['ClassName'])
                    tok_file.close()
                    continue
                    
                # mesh3D 요소 찾기
                mesh3D_elems = [elem for elem in tok_xml.getchildren() if elem.tag == 'mesh3D']
                if not mesh3D_elems:
                    logging.warning("No mesh3D element found for %s", row['ClassName'])
                    tok_file.close()
                    continue
                mesh3D = mesh3D_elems[0]
                
                # verts 요소 찾기
                mesh3DVerts_elems = [elem for elem in mesh3D.getchildren() if elem.tag == 'verts']
                if not mesh3DVerts_elems:
                    logging.warning("No verts element found for %s", row['ClassName'])
                    tok_file.close()
                    continue
                mesh3DVerts = mesh3DVerts_elems[0]
                
                # mappingTo2D 요소 찾기
                mappingTo2D_elems = [elem for elem in tok_xml.getchildren() if elem.tag == 'mappingTo2D']
                if not mappingTo2D_elems:
                    logging.warning("No mappingTo2D element found for %s", row['ClassName'])
                    tok_file.close()
                    continue
                mappingTo2D = mappingTo2D_elems[0]
                
                polygons = []
                
                for polygon in mappingTo2D.getchildren():
                    points = []
                    for edge in polygon.getchildren():
                        try:
                            vertex_idx = int(edge.attrib['startVert'])
                            if vertex_idx >= len(mesh3DVerts.getchildren()):
                                continue
                            vertex = mesh3DVerts.getchildren()[vertex_idx]
                            points.append((int(vertex.attrib['x']), -int(vertex.attrib['y'])))
                        except (ValueError, KeyError, IndexError) as e:
                            logging.warning("Error processing polygon: %s", str(e))
                            continue
                    if points:  # 포인트가 하나라도 있는 경우만 추가
                        polygons.append(points)
                
                # 유효한 폴리곤이 있는 경우만 저장
                if polygons:
                    with open(os.path.join('maps_poly', row['ClassName'].lower()+'poly.json'), 'w') as f:
                        json.dump(polygons, f)
                
                # Free some memory before continuing
                tok_file.close()
                tok_xml.clear()
                del mesh3D
                del mesh3DVerts
                del mappingTo2D
                del tok_xml
                
            except Exception as e:
                logging.error("Error processing %s: %s", row['ClassName'], str(e))
                continue


import sys
if __name__ == "__main__":
    # 기본 로그 레벨 설정
    logging.basicConfig(level=logging.INFO)
    # tokutil 로거 레벨 지정
    tokutil_logger = logging.getLogger('tokutil')
    tokutil_logger.setLevel(logging.ERROR)  # 경고 메시지 숨김
    
    try:
        region = sys.argv[1]
    except:
        logging.warning("need 1 positional argument; region")
        quit()
    c= constants()
    c.build(region, SCRIPT_DIR)
    parse_maps_images(c)