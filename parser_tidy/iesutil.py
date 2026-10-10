# -*- coding: utf-8 -*-
"""
Created on Thu Sep 23 08:07:28 2021
@author: Temperantia
"""

import csv
import logging
import os
import io
from DB import ToS_DB as constants


def load(ies_name,c):
    ies_data = []
    #ies_path = os.path.join(constants.PATH_INPUT_DATA, "ies.ipf", ies_name)
    

    if ies_name.lower() not in c.file_dict:
        logging.warn('Missing ies file: %s', ies_name.lower())
        return []
    ies_path = c.file_dict[ies_name.lower()]['path']
    # Reuse only short scalar tokens within this read. Once full, keep the
    # existing entries and convert new tokens normally; never exceed the bound.
    scalar_cache = {}
    cache_miss = object()
    with io.open(ies_path, 'r', encoding = "utf-8") as ies_file:
        ies_reader = csv.DictReader(ies_file, delimiter=',', quotechar='"')

        for row in ies_reader:
            # auto cast to int/float if possible
            for key, value in row.items():
                cacheable = False
                if isinstance(value, str):
                    converted = scalar_cache.get(value, cache_miss)
                    if converted is not cache_miss:
                        row[key] = converted
                        continue
                    cacheable = len(value) <= 128
                try:
                    row[key] = int(value)
                except :
                    try:
                        row[key] = float(value)
                    except :
                        row[key] = value
                if cacheable and len(scalar_cache) < 4096:
                    converted = row[key]
                    # Shared NaN identity can change container equality. None
                    # and DictReader's mutable overflow lists bypass the cache.
                    if not (isinstance(converted, float) and converted != converted):
                        scalar_cache[value] = converted

            ies_data.append(row)

    return ies_data
