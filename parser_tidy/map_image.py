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
import map_assets

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
    counts = map_assets.counters()
    try:
        assets = map_assets.Assets(c)
        for row in map_assets.rows(c):
            try:
                assets.polygon(row, counts, convert_tok)
            except Exception as e:
                counts['errors'] += 1
                logging.error("Error processing %s: %s", row['ClassName'], str(e))
    except Exception as e:
        counts['errors'] += 1
        logging.warning('Map polygon stage: %s', e)
    finally:
        map_assets.summary('polygon', counts)
        map_assets.summary('PNG', map_assets.counters())


def convert_tok(stream):
    xml = tokutil.tok2xml(stream)
    if xml is None:
        raise ValueError('Invalid TOK XML')
    try:
        vertices = xml.find('mesh3D').find('verts').getchildren()
        result = []
        for polygon in xml.find('mappingTo2D').getchildren():
            points = []
            for edge in polygon.getchildren():
                index = int(edge.attrib['startVert'])
                if index < 0:
                    raise ValueError('negative vertex index')
                vertex = vertices[index]
                points.append((int(vertex.attrib['x']), -int(vertex.attrib['y'])))
            result.append(points)
        return result
    finally:
        xml.clear()


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
