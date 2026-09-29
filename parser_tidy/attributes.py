# -*- coding: utf-8 -*-
"""
Created on Thu Sep 23 08:05:03 2021
@author: CPPG02619
"""

import csv
import logging
import os
import io
from os.path import exists
from DB import ToS_DB as constants
import luautil



def parse(c = None):
    if (c == None):
        c = constants()
        c.build(c.iTOS)
    parse_attributes(c)
    


def parse_attributes( constants):
    logging.debug('Parsing attributes...')
    
    ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies_ability.ipf', 'ability.ies')
    #ies_path = constants.file_dict['ies_ability.ipf']['path']
    if (not exists(ies_path)):
            return 
    with io.open(ies_path, 'r', encoding="utf-8") as ies_file:
        for row in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
            obj = {}
            obj['$ID'] = str(row['ClassID'])
            obj['$ID_NAME'] = row['ClassName']
            obj['Description'] = constants.translate(row['Desc']).strip() + '{nl}'
            obj['Icon'] = constants.parse_entity_icon(row['Icon'])
            obj['Name'] = constants.translate(row['Name'])

            obj['IsToggleable'] = row['AlwaysActive'] == 'NO'

            obj['DescriptionRequired'] = None
            obj['LevelMax'] = -1
            obj['Unlock'] = None
            obj['UnlockArgs'] = {}
            obj['UpgradePrice'] = []
            obj['Link_Jobs'] = []
            obj['Link_Skills'] = []
            
            obj['Link_Skills'] = [skill  for skill in row['SkillCategory'].split(';') if len(skill)]
            if obj['Link_Skills']  == []:
                if row['Job']:
                    obj['Link_Jobs'] = []
                    for j in row['Job'].split(';'):
                        try:
                            if j in constants.data['jobs_by_name']:
                                obj['Link_Jobs'].append(constants.data['jobs_by_name'][j]['$ID'])
                            else:
                                # 해당 직업이 없는 경우 로그 출력
                                logging.warning(f"Job {j} not found in jobs_by_name for attribute {row['ClassName']}.")
                                
                                # 첫 번째 토큰만 사용하여 다시 시도 (예: 'Char1_1' -> 'Char1')
                                base_job = j.split('_')[0]
                                if base_job in constants.data['jobs_by_name']:
                                    obj['Link_Jobs'].append(constants.data['jobs_by_name'][base_job]['$ID'])
                                    logging.info(f"Found alternative job {base_job} for {j}")
                        except:
                            logging.warning(f"Error processing job {j} for attribute {row['ClassName']}.")
                    obj['LevelMax'] = row['Level']
            
            popped = []
            for count in range(len(obj['Link_Skills'])):
                skill = obj['Link_Skills'][count]
                if skill not in constants.data['skills_by_name']:
                    popped.append(count)
            popped.sort()
            popped.reverse()
            for i in popped:
                obj['Link_Skills'].pop(i)
                
            constants.data['attributes'][obj['$ID']] = obj
            constants.data['attributes_by_name'][obj['$ID_NAME']] = obj


def parse_links(c = None):
    if c == None:
        c = constants()
        c.build(constants.iTOS)
        luautil.init()
        
    parse_links_jobs(c)
    #parse_clean(c)
def parse_links_jobs(constants):
    logging.debug("Parsing attributes <> jobs...")
    
    LUA_RUNTIME = luautil.LUA_RUNTIME
    LUA_SOURCE = luautil.LUA_SOURCE

    # Parse level, unlock and formula
    #ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies.ipf', 'job.ies')
    ies_path = constants.file_dict['job.ies']['path']
    if (not exists(ies_path)):
            return 
    with io.open(ies_path, 'r', encoding="utf-8") as ies_file:
        for row in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
            try:
                job = constants.data['jobs_by_name'][row['ClassName']]
            except KeyError:
                # 'Char1_1'와 같은 형식에서 'Char1'과 같은 기본 직업명 추출 시도
                try:
                    base_job_name = row['ClassName'].split('_')[0]
                    if base_job_name in constants.data['jobs_by_name']:
                        job = constants.data['jobs_by_name'][base_job_name]
                        logging.info(f"Using alternative job {base_job_name} for {row['ClassName']}")
                    else:
                        logging.warning(f"Job {row['ClassName']} and base job {base_job_name} not found in jobs_by_name. Skipping.")
                        continue
                except Exception as e:
                    logging.warning(f"Error processing job {row['ClassName']}: {e}. Skipping.")
                    continue
                    
            mongen_dir = os.listdir(os.path.join(constants.PATH_INPUT_DATA, 'ies_ability.ipf'))
            path_insensitive= {}
            for item in mongen_dir:
                path_insensitive[item.lower()] = item
            ies_file = 'ability_' + row['EngName'] + '.ies'
            
            try:
                ies_file = path_insensitive[ies_file.lower()]
            except:
                logging.warning("class not found {}".format(ies_file))
                
            ies_path = os.path.join(constants.PATH_INPUT_DATA, 'ies_ability.ipf', ies_file)

            # If this job is still under development, skip
            if not os.path.isfile(ies_path):
                continue

            with io.open(ies_path, 'r', encoding = 'utf-8') as ies_file:
                for row2 in csv.DictReader(ies_file, delimiter=',', quotechar='"'):
                    
                    if row2['ClassName'] not in constants.data['attributes_by_name']:
                        logging.warn('Missing attribute in ability.ies: %s', row2['ClassName'])
                        continue

                    try:
                        attribute = constants.data['attributes_by_name'][row2['ClassName']]
                        attribute['DescriptionRequired'] = attribute['DescriptionRequired'] if attribute['DescriptionRequired'] else ''
                        attribute['DescriptionRequired'] = attribute['DescriptionRequired'] + '{nl}{b}' + constants.translate(row2['UnlockDesc']) + '{b}'
                        attribute['LevelMax'] = int(row2['MaxLevel'])
                        
                       
                        # Parse attribute skill (in case it is missing in the ability.ies)
                        if not attribute['Link_Skills'] and row2['UnlockArgStr'] in constants.data['skills_by_name']:
                            logging.debug('adding missing skill %s', row2['UnlockArgStr'])
                            try:
                                skill = constants.data['skills_by_name'][row2['UnlockArgStr']]
                                skill['Link_Attributes'].append(attribute['$ID'])
                                attribute['Link_Skills'].append(skill['$ID'])
                                constants.data['skills'][str(skill['$ID'])]['Link_Attributes'] = skill['Link_Attributes']
                                constants.data['attributes'][str(attribute['$ID'])]['Link_Skills'] = attribute['Link_Skills']
                            except KeyError as e:
                                logging.warning(f"Error processing skill {row2['UnlockArgStr']}: {e}")


                        # Parse attribute job
                        if not attribute['Link_Skills'] or 'All' in attribute['Link_Skills']:
                            try:
                                attribute['Link_Jobs'].append(job['$ID'])
                                job['Link_Attributes'].append(attribute['$ID'])
                                constants.data['jobs'][str(job['$ID'])]['Link_Attributes'] = job['Link_Attributes']
                                constants.data['attributes'][str(attribute['$ID'])] = attribute
                            except KeyError as e:
                                logging.warning(f"Error linking job and attribute: {e}")

                        # Parse attribute unlock
                        #attribute['Unlock'] = luautil.lua_function_source_to_javascript(
                        #    luautil.lua_function_source(LUA_SOURCE[row2['UnlockScr']])[1:-1]  # remove 'function' and 'end'
                        #) if not attribute['Unlock'] and row2['UnlockScr'] else attribute['Unlock']

                        try:
                            attribute['UnlockArgs'][job['$ID']] = {
                                'UnlockArgStr': row2['UnlockArgStr'],
                                'UnlockArgNum': row2['UnlockArgNum'],
                            }
                        except KeyError as e:
                            logging.warning(f"Error setting UnlockArgs: {e}")
                    except Exception as e:
                        logging.warning(f"Error processing attribute {row2['ClassName']}: {e}")


def parse_clean(constants):
    attributes_to_remove = []
    # Find which attributes are no longer active
    for attribute in constants.data['attributes_by_name'].values():
        if not attribute['Link_Jobs'] and not attribute['Link_Skills']:
            attributes_to_remove.append(attribute)
        elif attribute['LevelMax'] == -1:
            attributes_to_remove.append(attribute)
        elif attribute['Link_Skills'] == ['All'] and attribute['Link_Jobs'] == []:
            attributes_to_remove.append(attribute)

    # Remove all inactive attributes
    for attribute in attributes_to_remove:
        constants.data['attributes'].pop (str(attribute['$ID']))
        constants.data['attributes_by_name'].pop(str(attribute['$ID_NAME']))

        attribute_id = attribute['$ID']

        for job in constants.data['jobs'].values():
            job['Link_Attributes'] = [link for link in job['Link_Attributes'] if link != attribute_id]
            constants.data['jobs_by_name'][str(job['$ID_NAME'])]['Link_Attributes']  = [link for link in constants.data['jobs_by_name'][str(job['$ID_NAME'])]['Link_Attributes'] if link != attribute_id]
        for skill in constants.data['skills'].values():
            skill['Link_Attributes'] = [link for link in skill['Link_Attributes'] if link != attribute_id]
            constants.data['skills_by_name'] [str(skill['$ID_NAME'])]['Link_Attributes']  =  [link for link in constants.data['skills_by_name'] [str(skill['$ID_NAME'])]['Link_Attributes'] if link != attribute_id]
            