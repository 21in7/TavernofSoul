# -*- coding: utf-8 -*-
"""
Created on Thu Nov  4 15:29:39 2021
@author: CPPG02619
"""

import translation
import logging
import os
import re
import csv
import io
import xml.etree.ElementTree as ET
from os.path import join, exists

vv_dict={'Reinforced Bowstring' : 'Reinforce Bowstring', 
        'Lewa Advent': ' Lewa Advent ',
         'Cluster Bomb' : 'Cluster Shot', 
         'Triple Steps Single Shot': 'Triple Steps Single Shot',
         'Mass Heal: Freeze' : 'Mass Heal: Cooling', 
         'Doble Attaque' : 'Especial', 
         'クラスターボム' : 'クラスターショット',
         'アドベント・ロア': ' アドベント・ロア', 
         'レバー - アクション': "レバー・アクション", 
         'ドブレ・アタケ' : 'エスペシアル'
         }

vv_dict_job = {'conviction':'4019', 'ema' : '4018'}
vv_common = ['0511050094', '0511050097', '0511050119', '0511050164', '0511050147', '0511050130']
vv_common_name = ['concentrated defence', 'echo', 'coordination', 'bloody fight' ]


def translate(name):
    if name in vv_dict:
        return vv_dict[name]
    return name

def createdict(c):
    all_dic = {}
    exception = []
    for skills in c.data['skills']:
        skills = c.data['skills'][skills]
        job  = skills['Link_Job']
        job  = c.data['jobs'][job]['$ID']
        key= skills['Name'].lower().replace('\xa0', ' ')
        if key in all_dic:
            all_dic.pop(key)
            exception.append(key)
        elif key in exception :
            continue
        else:
            all_dic[key] =job
    """
    ambigous = []
    for i in all_dic.keys():
        for h in all_dic.keys():
            if h!= i and i in h:
                ambigous.append(i)
                break
    for item in ambigous:
        all_dic.pop(item)
    """
    all_dic_k = sorted(all_dic, key=lambda k: len(k))
    all_dic_sorted = {}
    for i in all_dic_k:
        all_dic_sorted[i] = all_dic[i]
    
    all_dic = all_dic_sorted
    global job_names
    job_names = []
    for jobs in c.data['jobs']:
        jobs = c.data['jobs'][jobs]
        all_dic[jobs['Name'].lower()] = jobs['$ID']    
        all_dic_k.append(jobs['Name'].lower())
        job_names.append(jobs['Name'].lower())
        
    global bow, bow_key, class_code
    bow = all_dic 
    bow_key = all_dic_k
    class_code = list(set(bow.values()))
    
    

def parse(c):
    logging.warning("parsing vaivoras")
    items = c.data['items']
    if len(c.data['items']) ==0:
        logging.warning("items are empty ?")
        return
    vvrs = []
    if c.region == 'jtos':
        vv_name = 'バイボラ秘伝'
    else:
        vv_name = "Vaivora Vision"
    c.data['vvrs'] = []
    for i in items:
        vv = {}
        if items[i]['Name']!=None and vv_name.lower()  in items[i]['Name'].lower():
            vv['name']          = items[i]['Name']
            vv['$ID_NAME']      = items[i]['$ID_NAME']
            vv['$ID']           = items[i]['$ID']
            vv['type']          = translate("-".join(items[i]['Name'].split("-")[1:]).strip()).lower().replace("\xa0", " ")
            vvrs.append(vv)
            c.data['vvrs'].append(vv)
            
    tl = c.data['dictionary']
    
    for v in vvrs:
        lookup = "{nl}"+v['type']+"{nl}"
        v['tl_crude'] = []
        for i in tl:
            if lookup in tl[i].lower():
                t = {'code':i, 'tl':tl[i]}
                v['tl_crude'].append(t)
        
    for v in vvrs:
        if len(v['tl_crude'])>0:
            v['tl'] = v['tl_crude'][-1]['tl']
        else:
            v['tl'] = ""
    for v in vvrs:
        if v['tl'] != "" and "Bonus" in c.data['items_by_name'][v['$ID_NAME']]:
            c.data['items_by_name'][v['$ID_NAME']]['Bonus'].append(['-', v['tl']])
            c.data['items'][v['$ID']]   = c.data['items_by_name'][v['$ID_NAME']]
        

def getclass_fromstring(c, string):
    
    
    bonus = string.lower().\
            replace('{nl}',' ').\
            replace("'s",' ').\
            replace('\xa0', ' ').\
            replace(',', '').\
            replace(':', '').\
            split(' ')
    rank = {i:0 for i in class_code}
    found = []
    for i in range(len(bonus)):
        if bonus[i] in job_names:
            rank[bow[bonus[i]]] +=5
            found.append(bonus[i])
        if ' '.join(bonus[i:i+2]) in job_names:
             rank[bow[' '.join(bonus[i:i+2])]] +=5
             found.append(bonus[i:1+2])
             

        if bonus[i] in bow_key:
            rank[bow[bonus[i]]] +=1
            found.append(bonus[i])
            
        if ' '.join(bonus[i:i+2]) in bow_key:
            rank[bow[' '.join(bonus[i:i+2])]] +=3
            found.append(bonus[i:i+2])
        if  ' '.join(bonus[i:i+3]) in bow_key:
            rank[bow[' '.join(bonus[i:i+3])]] +=5
            found.append(bonus[i:i+3])
    maks=-1
    maks_code = ''
    for i in rank:
        if maks < rank[i]:
            maks = rank[i]
            maks_code = i 
    if maks == 0:
        return ''
    return maks_code


def getclass_vv(c):
    createdict(c)
    vv4 = []
    for i in c.data['vvrs']:
        if i ['type'] in vv_common_name:
            continue
        if 'lv4' in i['name'].lower():
            vv4.append(i)
            
    vvs = []
    for i in vv4:
        vvs.append(c.data['items'][i['$ID']])
     
    
    for item in vvs:
       
        try:
            string = item['Bonus'][-1][1]
            item['job'] = getclass_fromstring(c, string)
        except:
            continue
        try:
           name = item['Name'].split('-')[1].strip().lower().replace("\xa0", " ")
           item['job'] = vv_dict_job[name]
        except:
           pass
    return vvs
    
def parse_lv4(c):
    vvs = getclass_vv(c)
    tl  = c.data['dictionary']
    key = '{nl}{@st66d}{s15}'
    
    
    meaningfull_phrase = []
    for phrase in tl.values() :
        if key in phrase.lower():
            meaningfull_phrase.append(phrase)
    
    mapped_lv4 = {}
    err = []
    for phrase in meaningfull_phrase:
        string = phrase
        job = getclass_fromstring(c, string)
        if job in mapped_lv4:
            err.append(phrase)
        mapped_lv4[job] = string.replace('{nl} {nl}{@st66d}{s15}', '')
    
    for bonus4 in mapped_lv4:
        for vv in vvs:
            try:
                if bonus4 == vv['job'] and bonus4!='':
                    vv['Bonus'].append(['lv4', mapped_lv4[bonus4]])
            except:
                continue
        
    vv_check = []
    err = []
    for i in vvs:
        if 'job' not in i:
            err.append(i)
            continue
        try:
            job = c.data['jobs'][i['job']]['Name']
        except:
            job = ''
        check = [i['Name'],job]
        vv_check.append(check)


_TOOLTIP_KEY_PAT = re.compile(r"tooltip_([A-Za-z0-9_]+?)_Data_(\d+)$")
_ADDOPT_COLS = ('AdditionalOption_1', 'AdditionalOption_2',
                'AdditionalOption_3', 'AdditionalOption_4')


def _load_dicid_translation(c):
    """For non-Korean regions, load dicid -> translated text from .tsv files
    in c.transaltion_path. Returns empty dict for ktos/ktest."""
    if c.region in ('ktos', 'ktest'):
        return {}
    tr_path = c.transaltion_path
    if not tr_path or not os.path.isdir(tr_path):
        return {}
    out = {}
    for fname in os.listdir(tr_path):
        if not fname.endswith('.tsv'):
            continue
        with io.open(os.path.join(tr_path, fname), 'r', encoding='utf-8') as f:
            for row in csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE):
                if len(row) >= 2:
                    out[row[0]] = row[1]
    return out


def _build_tooltip_index(c):
    """tooltip_<X>_Data_<n> -> text. ktos/ktest: kr from DicIDTable.xml.
    itos/jtos/twtos: dicid -> translated .tsv (fallback to kr if untranslated)."""
    dicid_path = join(c.PATH_INPUT_DATA, 'language.ipf', 'DicIDTable.xml')
    if not exists(dicid_path):
        logging.warning('DicIDTable.xml not found at %s', dicid_path)
        return {}
    raw = {}  # name -> {idx: (dicid, kr)}
    for el in ET.parse(dicid_path).getroot().iter('dic_data'):
        m = _TOOLTIP_KEY_PAT.search(el.get('FilenameWithKey', '') or '')
        if not m:
            continue
        raw.setdefault(m.group(1), {})[int(m.group(2))] = (
            el.get('ID', ''), el.get('kr') or '')

    if c.region in ('ktos', 'ktest'):
        return {name: ''.join(parts[i][1] for i in sorted(parts))
                for name, parts in raw.items()}

    tl = _load_dicid_translation(c)
    return {name: ''.join((tl.get(parts[i][0]) or parts[i][1])
                          for i in sorted(parts))
            for name, parts in raw.items()}


def _scan_item_addopts(c):
    item_files = list(c.ITEM_IES) + list(c.EQUIPMENT_IES)
    out = {}
    for fname in item_files:
        entry = c.file_dict.get(fname.lower())
        if not entry or not exists(entry['path']):
            continue
        with io.open(entry['path'], 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                cn = row.get('ClassName', '')
                if not cn:
                    continue
                opts = [(col, row[col]) for col in _ADDOPT_COLS
                        if row.get(col)]
                if opts:
                    out[cn] = opts
    return out


def parse_additional_options(c):
    """Map AdditionalOption_1..4 columns on item rows to tooltip text from
    DicIDTable.xml (key pattern: tooltip_<value>_Data_<n>). Adds matched text
    to item['Bonus'] as ['lv4', text] for *_Lv4 keys, ['add_opt', text] otherwise.

    Works for all regions:
      ktos/ktest -> kr from DicIDTable.xml directly
      itos/jtos/twtos -> dicid -> translated .tsv (kr fallback if untranslated)
    """
    logging.warning('parsing additional options (lv4 vaivora etc.)')

    tooltip = _build_tooltip_index(c)
    logging.info('  tooltip index: %d entries', len(tooltip))
    if not tooltip:
        return

    item_addopts = _scan_item_addopts(c)
    logging.info('  items with AdditionalOption_N: %d', len(item_addopts))

    items_by_name = c.data.get('items_by_name', {})
    applied, total_entries, unmatched_keys = 0, 0, set()
    for cn, opts in item_addopts.items():
        item = items_by_name.get(cn)
        if not item:
            continue
        bonus = item.setdefault('Bonus', [])
        added = False
        for _col, key in opts:
            text = tooltip.get(key)
            if text is None:
                unmatched_keys.add(key)
                continue
            tag = 'lv4' if 'lv4' in key.lower() else 'add_opt'
            bonus.append([tag, text])
            total_entries += 1
            added = True
        if added:
            applied += 1
    logging.info('  applied to %d items, %d option entries, %d unmatched keys',
                 applied, total_entries, len(unmatched_keys))