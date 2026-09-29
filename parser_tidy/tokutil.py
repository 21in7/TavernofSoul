# -*- coding: utf-8 -*-

import struct
import xml.etree.ElementTree as XML
import logging

# 경고 로그 설정
logger = logging.getLogger('tokutil')
logger.setLevel(logging.ERROR)  # ERROR 레벨로 설정하여 WARNING 메시지 숨김


class TokAttrType:
    C_STR   = 1
    SINT_32 = 2
    SINT_16 = 3
    SINT_8  = 4
    UINT_32 = 5
    UINT_16 = 6
    UINT_8  = 7
    def __init__(self):
        pass


def _read_string(buf, pos):
    l = buf.find('\x00', pos)
    if l == pos or l < 0:  # 널 문자가 없거나 현재 위치에 있는 경우
        return None
    length = l - pos
    if length <= 0:
        return None
    data = buf[pos:l]
    if not data:  # 데이터가 비어있는지 확인
        return None
    format_string = "%ds" % length  # 포맷 문자열 안전하게 생성
    return struct.unpack(format_string, data)[0]


def tok2xml(f):
    """
    :param f: PathEngine *.tok file
    :return: xml.etree.ElementTree
    @type f: file
    @rtype xml.etree.ElementTree
    """
    s = []
    attr = []
    buf = f.read()
    pos = 0
    # read strings
    while True:
        _s = _read_string(buf, pos)
        if _s is None:
            pos += 1
            break
        pos += len(_s) + 1
        s.append(_s)
        # print _s
    # read attributes
    while True:
        _type = struct.unpack("b", buf[pos:pos+1])[0]
        pos += 1
        if _type == 0:
            break
        _s = _read_string(buf, pos)
        if _s is None:
            # None인 경우 다음 널 바이트로 이동
            next_null = buf.find('\x00', pos)
            if next_null == -1: # 널 바이트가 없으면 중단
                break
            pos = next_null + 1
            continue
        pos += len(_s) + 1
        attr.append((_type, _s))
        # print (_type, _s)
    root_node = None
    while True:
        # 버퍼 경계 확인 추가
        if pos >= len(buf):
            logger.debug("Buffer position (%d) exceeds buffer length (%d)", pos, len(buf))
            break
        # read node name
        try:
            _name_idx = struct.unpack("b", buf[pos:pos+1])[0] - 1
            pos += 1
        except struct.error:
            logger.debug("Failed to unpack node name index at position %d", pos)
            break
        if _name_idx == -1:  # end of element
            node = node.parent
            if node is None:
                break
            continue

        # 인덱스 범위 검사 추가
        if _name_idx < 0 or _name_idx >= len(s):
            # 인덱스가 범위를 벗어난 경우 기본값 사용
            node_name = "unknown_node_%d" % _name_idx
            logger.debug("Node name index %d out of range (0-%d)", _name_idx, len(s)-1)
        else:
            node_name = s[_name_idx]

        if root_node is None:
            root_node = XML.Element(node_name)
            root_node.parent = None
            node = root_node
        else:
            parent = node
            node = XML.SubElement(node, node_name)
            node.parent = parent
        # print s[_name_idx]
        # read attributes
        while True:
            _attr_idx = struct.unpack("b", buf[pos:pos+1])[0] - 1
            if buf[pos] == '\x00':
                pos += 1
                break
            pos += 1

            # 속성 인덱스 범위 검사 추가
            if _attr_idx < 0 or _attr_idx >= len(attr):
                logger.debug("Attribute index %d out of range (0-%d)", _attr_idx, len(attr)-1)
                # 현재 노드의 속성 읽기를 건너뛰고 다음 노드로 이동
                break

            _attr_type, _attr_name = attr[_attr_idx]
            if _attr_type == TokAttrType.C_STR:
                _val = _read_string(buf, pos)
                if _val is None:
                    # None인 경우 다음 널 바이트로 이동
                    next_null = buf.find('\x00', pos)
                    if next_null == -1:
                        break
                    pos = next_null + 1
                    _val = "" # 기본값 설정
                else:
                    pos += len(_val) + 1
            elif _attr_type == TokAttrType.SINT_8:
                _val = struct.unpack("b", buf[pos:pos+1])[0]
                pos += 1
            elif _attr_type == TokAttrType.SINT_16:
                _val = struct.unpack("h", buf[pos:pos+2])[0]
                pos += 2
            elif _attr_type == TokAttrType.SINT_32:
                _val = struct.unpack("i", buf[pos:pos+4])[0]
                pos += 4
            elif _attr_type == TokAttrType.UINT_8:
                _val = struct.unpack("B", buf[pos:pos+1])[0]
                pos += 1
            elif _attr_type == TokAttrType.UINT_16:
                _val = struct.unpack("H", buf[pos:pos+2])[0]
                pos += 2
            elif _attr_type == TokAttrType.UINT_32:
                _val = struct.unpack("I", buf[pos:pos+4])[0]
                pos += 4
            node.set(_attr_name, _val)
            # print _attr_name, _val
    return root_node 