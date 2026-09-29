# -*- coding: utf-8 -*-
"""
Created on Wed Sep 22 13:47:21 2021
@author: CPPG02619
"""

from PIL import Image, ImageFile
import logging

# 손상되었거나 잘린 이미지도 로드할 수 있도록 설정
ImageFile.LOAD_TRUNCATED_IMAGES = True


def optimize(path, mode, rect, size):
    format = 'JPEG' if mode == 'RGB' else 'PNG'
    quality = 80 if mode == 'RGB' else 1

    try:
        image = Image.open(path)
        image.load()
    except Exception as e:
        logging.warning("Failed to open image %s: %s", path, e)
        return

    # 모드 변환
    if image.mode != mode:
        try:
            image = image.convert(mode)
        except Exception as e:
            logging.warning("Failed to convert image mode for %s: %s", path, e)
            return

    # 크롭
    try:
        if rect is not None and (rect[2], rect[3]) != image.size:
            image = image.crop((rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]))
    except Exception as e:
        logging.warning("Failed to crop image %s: %s", path, e)

    # 리사이즈 (원본보다 큰 사이즈로 키우진 않음)
    try:
        if size and (size[0], size[1]) < image.size:
            image = image.resize((size[0], size[1]), Image.LANCZOS)
    except Exception as e:
        logging.warning("Failed to resize image %s: %s", path, e)

    # 저장
    try:
        save_kwargs = { 'optimize': True }
        if format == 'JPEG':
            save_kwargs['quality'] = quality
        image.save(path, format, **save_kwargs)
    except Exception as e:
        logging.warning("Failed to save image %s: %s", path, e)


# https://stackoverflow.com/a/6483549
def replace_color(image, color_from, color_to):
    image = image.copy()
    image_width, image_height = image.size
    image_data = image.load()

    for x in range(0, image_width):
        for y in range(0, image_height):
            if image_data[x,y] == color_from:
                image_data[x,y] = color_to

    return image
