# -*- coding: utf-8 -*-
"""parser_tidy 테스트 공통 설정.

테스트는 venv 파이썬(TavernofSoul/itos/3.8/bin/python)으로 실행한다:

    cd parser_tidy
    /home/ubuntu/TavernofSoul/TavernofSoul/itos/3.8/bin/python -m pytest tests/ -v
"""
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(THIS_DIR)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)
