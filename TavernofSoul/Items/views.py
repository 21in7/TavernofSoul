from django.shortcuts import render
from os.path import join
from django.http import HttpResponse
from Items.models import Items, Equipment_Bonus, Item_Recipe_Material
from Items.models import Item_Recipe_Target,Item_Type
from Items.models import Item_Collection_Material, Item_Collection_Bonus
from Monsters.models import Monsters, Item_Monster
from Maps.models import Maps, Map_Item, Map_NPC, Map_Item_Spawn
from django.http import Http404
# Create your views here.
APP_NAME = "Items"
import math

import os
from django.http import JsonResponse
from django.db.models import Q
from Items.enhancement import calculator_data, gem_bonus_rows
from Items.models import Gems

bonus_stat_translator={
    'ADD_CLOTH'     : 'Attack against Cloth Armored Targets',
    'ADD_LEATHER'   : 'Attack against Leather Armored Targets',
    'ADD_CHAIN'     : 'Attack against Chain Armored Targets',
    'ADD_IRON'      : 'Attack against Plate Armored Targets',
    'ADD_GHOST'     : 'Attack against Ghost Armored Targets',
    'ADD_SMALLSIZE' : 'Attack against Small-sized Targets',
    'ADD_MIDDLESIZE': 'Attack against Medium-sized Targets',
    'ADD_LARGESIZE' : 'Attack against Large-sized Targets',
    'ADD_FORESTER'  : 'Attack against Plant-type Targets',
    'ADD_WIDLING'   : 'Attack against Beast-type Targets',
    'ADD_VELIAS'    : 'Attack against Devil-type Targets',
    'ADD_PARAMUNE'  : 'Attack against Mutant-type Targets',
    'ADD_KLAIDA'    : 'Attack against Insect-type Targets',
    'Aries'         : 'Piercing',
    'AriesDEF'      : 'Piercing Defense',
    'SlashDEF'      : 'Slash Defense',
    'StrikeDEF'     : 'Strike Defense',
    'ADD_FIRE'      : 'Add. Fire Property Damage',
    'ADD_ICE'       : 'Add. Ice Property Damage',
    'ADD_POISON'    : 'Add. Poison Property Damage',
    'ADD_LIGHTNING' : 'Add. Lightning Property Damage',
    'ADD_SOUL'      : 'Add. Soul Property Damage',
    'ADD_EARTH'     : 'Add. Earth Property Damage',
    'ADD_HOLY'      : 'Add. Holy Property Damage',
    'ADD_DARK'      : 'Add. Dark Property Damage',
    'RES_FIRE'      : 'Fire Property Resistance',
    'RES_ICE'       : 'Ice Property Resistance',
    'RES_POISON'    : 'Poison Property Resistance',
    'RES_LIGHTNING' : 'Lightning Property Resistance',
    'RES_SOUL'      : 'Soul Property Resistance',
    'RES_EARTH'     : 'Earth Property Resistance',
    'RES_HOLY'      : 'Holy Property Resistance',
    'RES_DARK'      : 'Dark Property Resistance',
    'LootingChance' : 'Looting Chance',
    'UNKNOWN'       : '-'
}

from ipfparser.utils import *

# Private /items/ HTML contract. Ordinary GETs remain complete documents.
ITEM_SEARCH_HEADER = 'X-Item-Search'
ITEM_SEARCH_FRAGMENT = 'results-v1'
SEARCH_ORDERS = {
    'updated-dsc': '-updated', 'eq-level-asc': 'equipments__level',
    'eq-level-dsc': '-equipments__level', 'ids-asc': 'ids', 'ids-dsc': '-ids',
    'name-asc': 'name', 'name-dsc': '-name',
    'id_name-asc': 'id_name', 'id_name-dsc': '-id_name',
}


def index(request):
    from django.utils.cache import patch_vary_headers

    types = list(Item_Type.objects.all())
    type_map = {str(t.id) + ('_eq' if t.is_equipment else ''): t for t in types}
    params = request.GET.copy()
    grade = params.get('grade', '')
    grade = grade if grade in ('', '1', '2', '3', '4', '5', '6') else ''
    clas = params.get('class', '')
    clas = clas if clas in ('', '0', '1', '2', '3', '4') else ''
    type_key = params.get('type', '')
    type_key = type_key if type_key in type_map else ''
    order = params.get('order', 'updated-dsc')
    order = order if order in SEARCH_ORDERS else 'updated-dsc'

    def level(key):
        value = params.get(key, '')
        try:
            number = int(value)
            return str(number) if -2147483648 <= number <= 2147483647 else ''
        except (ValueError, TypeError):
            return ''

    min_lv, max_lv = level('lvmin'), level('lvmax')
    searched = 'q' in params
    data = {
        'types': [{'type': t.name.lower(), 'id': key} for key, t in type_map.items()],
        'query': params.get('q', ''), 'grade': grade, 'class': clas, 'type': type_key,
        'minLV': min_lv, 'maxLV': max_lv, 'order': order,
        'searched': searched, 'item': [], 'item_len': 0, 'curpage': 1, 'pageLen': 0,
    }
    for key, value in (('grade', grade), ('class', clas), ('type', type_key),
                       ('lvmin', min_lv), ('lvmax', max_lv), ('order', order)):
        params[key] = value
    if searched:
        params['q'] = data['query']
        query = Q(name__icontains=data['query'])
        if min_lv:
            query &= Q(equipments__level__gte=int(min_lv))
        if max_lv:
            query &= Q(equipments__level__lte=int(max_lv))
        if type_key:
            t = type_map[type_key]
            query &= Q(**{'equipments__type_equipment' if t.is_equipment else 'type': t.name})
        if grade:
            query &= Q(grade=int(grade))
        if clas:
            classes = ['.'] * 5
            classes[int(clas)] = 'T'
            query &= Q(equipments__requiredClass__regex=''.join(classes))
        items = Items.objects.filter(query).order_by(SEARCH_ORDERS[order], 'pk').select_related('equipments')
        count = items.count()
        last = max(1, (count + 9) // 10)
        try:
            page = max(1, min(last, int(params.get('page', '1'))))
        except (ValueError, TypeError):
            page = 1
        data.update(item_len=count, curpage=page, pageLen=last if count else 0,
                    item=items[(page - 1) * 10:page * 10])
        params['page'] = str(page)

        def page_url(number):
            link = params.copy()
            link['page'] = str(number)
            return request.path + '?' + link.urlencode()

        start = max(1, min(page - 5, last - 10))
        data['pages'] = [{'page': n, 'link': page_url(n)}
                         for n in range(start, min(last, start + 10) + 1)] if count else []
        data['previous'] = page_url(page - 1) if page > 1 else None
        data['next'] = page_url(page + 1) if page < last else None
        data['pageStart'], data['pageEnd'] = page_url(1), page_url(last)
    data['search_url'] = request.path + ('?' + params.urlencode() if searched else '')
    fragment = request.META.get('HTTP_X_ITEM_SEARCH') == ITEM_SEARCH_FRAGMENT
    response = render(request, 'Items/search_results.html' if fragment else 'Items/search.html', data)
    patch_vary_headers(response, [ITEM_SEARCH_HEADER])
    response[ITEM_SEARCH_HEADER] = ITEM_SEARCH_FRAGMENT if fragment else 'document'
    return response

def item_detail(request, id):

    try:
        item = Items.objects.get(ids = id)
    except:
        raise Http404
    data = {}
    data['item'] = item
    trade = []
    if item.tradability[0] == 'T':
        trade.append("Market")
    if item.tradability[1] == 'T':
        trade.append("Personal")
    if item.tradability[2] == 'T':
        trade.append("Shop")
    if item.tradability[3] == 'T':
        trade.append("Team")
    item.tradability = ", ".join(trade)
    if len(trade) ==0:
        item.tradability = "None"


    try:
        classes = []
        if (item.equipments.requiredClass[0] == 'T'):
            classes.append('Archer')
        if (item.equipments.requiredClass[1] == 'T'):
            classes.append('Cleric')
        if (item.equipments.requiredClass[2] == 'T'):
            classes.append('Scout')
        if (item.equipments.requiredClass[3] == 'T'):
            classes.append('Swordman')
        if (item.equipments.requiredClass[4] == 'T'):
            classes.append('Wizard')
        if len(classes) >0:
            data['item'].equipments.requiredClass = ", ".join(classes)
        else:
            data['item'].equipments.requiredClass = "None"
    except:
        pass
    try:
        bonus_db = list(Equipment_Bonus.objects.filter(equipment = item.equipments))
        bonus_all = []
        for i in bonus_db:
            bonus = {}
            if i.bonus_stat in bonus_stat_translator:
                bonus['bonus_stat'] = bonus_stat_translator[i.bonus_stat]
            else:
                bonus['bonus_stat'] = i.bonus_stat
            bonus['bonus_val']  = i.bonus_val.replace('{img green_up_arrow 16 16}', '▲')\
                                        .replace('{img green_down_arrow 16 16}', '▼')
            bonus['bonus_val'] = bonus['bonus_val'].split('{nl}')
            bonus_all.append(bonus)
        data['equipment_bonus'] = bonus_all
    except:
        pass

    data['refference'] = 0
    try:
        data['materialRecipe'] = list(Item_Recipe_Material.objects.filter(material = item).prefetch_related('recipe__item'))
        if (len(data['materialRecipe']) != 0):
            data['refference'] = 1
    except:
        pass
    try:
        data['targetRecipe'] = list(Item_Recipe_Target.objects.filter(target = item).prefetch_related('recipe__item'))
        if (len(data['targetRecipe']) != 0):
            data['refference'] = 1
    except:
        pass
    try:
        data['item'].descriptions = data['item'].descriptions.replace("{img star_mark 20 20}", "★")
    except:
        pass

    try:
        data['materialRecipe'] = list(Item_Recipe_Material.objects.filter(recipe = item.recipes).prefetch_related('material'))
    except:
        pass

    try:
        data['target'] = Item_Recipe_Target.objects.filter(recipe = item.recipes).prefetch_related('target')
    except:
        pass

    try:
        data['collectionMaterialFor'] = list(Item_Collection_Material.objects.filter(material = item).prefetch_related('collection__item'))
        if (len(data['collectionMaterialFor']) != 0):
            data['refference'] = 1
    except:
        pass

    try:
        data['mapDrop'] = list(Map_Item.objects.filter(item = item).prefetch_related('map'))
        if (len(data['mapDrop']) != 0):
            data['refference'] = 1
    except:
        pass

    try:
        data['foundAt'] = list(Map_Item_Spawn.objects.filter(item = item).prefetch_related('map'))
        if (len(data['foundAt']) != 0):
            data['refference'] = 1
    except:
        pass


    try:
        data['collectionMaterial'] = list( Item_Collection_Material.objects.filter(collection = item.collections).prefetch_related('material'))
    except:
        pass

    try:
        data['collectionBonus'] = list( Item_Collection_Bonus.objects.filter(collection = item.collections))
    except:
        pass

    try:
        data['pages'] = []
        pages = item.books.text.split("{np}")
        for i in pages:
            i = i.replace('\\-', '')
            i = i.replace('\\', '')
            lines = i.split("{nl}") 

            data['pages'].append(lines)
    except:
        pass
    try:
        desc = data['item'].descriptions
        lines = desc.split('{nl}')
        data['desc'] = lines
    except:
        pass

    try:
        data['dropped'] = list(Item_Monster.objects.filter(item = item).prefetch_related('monster'))
        if (len(data['dropped']) != 0):
            data['refference'] = 1
    except:
        pass

    data['enhancement'] = calculator_data(item)
    try:
        data['gem_bonuses'] = gem_bonus_rows(item.gems)
    except Gems.DoesNotExist:
        pass

    return render(request, join(APP_NAME,"index.html"),data)
