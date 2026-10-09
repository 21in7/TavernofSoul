# -*- coding: utf-8 -*-
"""
Created on Tue Sep 28 14:08:20 2021

@author: Temperantia
"""


from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from django.db import transaction
import tempfile
import logging
import json
from os.path import join, exists
from Monsters.models import Monsters, Item_Monster, Skill_Monster
import os
import shutil
from Items.models import Items, Equipments, Equipment_Bonus, Cards, Recipes, Books, Gems, GoddessReinforcement
from Items.models import Item_Recipe_Material, Item_Recipe_Target, Item_Type
from Items.models import Collections, Item_Collection_Material, Item_Collection_Bonus
from Maps.models import Maps, Map_Item, Map_NPC,Map_Item_Spawn
from Jobs.models import Jobs
from Buffs.models import Buffs
from Skills.models import Skills
from Attributes.models import Attributes
from Dashboard.models import Version
from Other.models import Achievements
from ipfparser.contracts import (ContractError, RECIPE_ID_PREFIX, canonical_item_id,
                                 load_json, load_release, GEM_SLOTS, inactive_recipe, number)
class Command(BaseCommand):
    
    base_path               = settings.JSON_ROOT
    maps_path               = 'maps.json'
    maps_by_name_path       = 'maps_by_name.json'
    maps_by_position_path   = 'maps_by_position.json'
    map_item_path           = 'map_item.json'
    map_npc_path            = 'map_npc.json'
    map_item_spawn_path     = 'map_item_spawn.json'
    jobs_path               = "jobs.json"
    jobs_by_name_path       = "jobs_by_name.json"
    attributes_by_name_path = "attributes_by_name.json"
    attributes_path         = "attributes.json"
    skills_path             = "skills.json"
    skills_by_name_path     = "skills_by_name.json"
    item_path               = 'items_by_name.json'
    monster_path            = 'monsters.json'
    item_monster_path       = 'item_monster.json'
    npc_path                = 'npcs.json'
    item_path               = 'items_by_name.json'
    item_type_path          = 'item_type.json'
    version_path            = 'version.json'
    buff_path               = 'buff.json'
    achieve_path            = 'achievements.json'
    def importJSON(self, file):
        try:
            return load_json(file)
        except ContractError as exc:
            raise CommandError("Cannot load JSON {}: {}".format(file, exc)) from exc

    def _validate_staged_release(self, directory):
        try:
            return load_release(directory)
        except ContractError as exc:
            raise CommandError('Invalid release: {}'.format(exc)) from exc

    def add_arguments(self, parser):
        parser.add_argument('-u', '--update', type=int, help='Indicate wether ignore any \
                            existing data or update them')
        
    
    def escaper(self,string):
        string = str(string)
        escaped = string.translate(str.maketrans({"-":  r"\-",
                                              "]":  r"\]",
                                              "\\": r"\\",
                                              "^":  r"\^",
                                              "$":  r"\$",
                                              "*":  r"\*",
                                              ".":  r"\.",
                                              "'" : r"\'",
                                              '"' : r'\"',
                                              ',' :r''
                                              
                                              }))
        return escaped
    
    def deleteMe(self, all_item, json_item, table, name):
        item_to_delete = []
        for item in all_item:
            if item[0] not in json_item:
                item_to_delete.append(item[0])
        
        for ids in item_to_delete:
            try:
                logging.warn("deleting from {} where ids ={}".format(name, ids))
                item = table.objects.get(ids = ids)
                icon= item.icon
                item.delete()
            except ObjectDoesNotExist:
                logging.warn(" delete error ids {}".format(ids))


    # P0-8: recipe 의 $ID 를 'recipe-<n>' canonical ID 로 정규화한다.
    # Item/Recipe 가 같은 숫자 ClassID 를 공유해 comparer 의 $ID re-key 에서
    # 49건이 드롭되는 것을 막는다. RECIPES 집합(item_type.json)으로 recipe 를
    # 식별하며, transform 으로 comparer 진입 전에 양쪽 JSON 에 일괄 적용한다.
    RECIPE_ID_PREFIX = RECIPE_ID_PREFIX

    def _canonical_item_id(self, entry, recipe_id_names):
        """entry 가 recipe 면 dict 복사 후 $ID 에 'recipe-' 접두를 붙인다.

        원본 entry 를 훼손하지 않는다(items_by_name.json 의 원본 값을 보존).
        """
        if not isinstance(entry, dict):
            return entry
        if entry.get('$ID_NAME') in recipe_id_names:
            e = dict(entry)
            e['$ID'] = canonical_item_id(e, recipe_id_names)
            return e
        return entry

    def _item_by_name(self, name):
        # ClassName is case-sensitive in IES. MySQL's default collation is not:
        # GoldMoru_Box_S and goldmoru_box_S are distinct items in the same release.
        # Resolve validated references through their unambiguous canonical IDs.
        if hasattr(self, '_item_ids_by_name'):
            return Items.objects.get(ids=self._item_ids_by_name[name])
        return Items.objects.get(id_name=name)

    @staticmethod
    def _apply_transform(data, transform):
        """data(dict|list) 의 각 value 에 transform 을 일괄 적용한다.

        comparer 의 모든 분기(early-return 포함) 이전에 호출되어야 한다.
        transform 이 None 이거나 data 가 비어 있으면 그대로 반환한다.
        """
        if transform is None or not data:
            return data
        if isinstance(data, dict):
            return {k: transform(v) for k, v in data.items()}
        return [transform(v) for v in data]

    def comparer(self,path, ids = ['$ID'], transform=None):
        base_path = self.base_path
        json_prev = False
        json_now = False
        file_path = join(base_path, path)
        changes = {'added' : [] ,'removed': [], 'changed': []}

        prev_path = join(getattr(self, '_previous_path', join(base_path, 'prev')), path)
        json_prev = self.importJSON(prev_path) if exists(prev_path) else {}
        json_now = self.importJSON(file_path)

        # P0-8: transform 은 파일 로드 직후, 모든 분기 이전에 양쪽 JSON 에
        # 일괄 적용한다. 분기 후(137행)에만 두면 early-return 경로(prev 없는
        # 첫 임포트)가 transform 을 건너뛰어 recipe 가 숫자 $ID 로 임포트되고
        # DB 충돌이 재발한다.
        json_prev = self._apply_transform(json_prev, transform)
        json_now = self._apply_transform(json_now, transform)

        def keyed(data):
            rows = data.values() if isinstance(data, dict) else data
            result = {}
            for row in rows:
                key = tuple(str(row[field]) for field in ids)
                result[key] = row
            return result

        dict_now = keyed(json_now)
        dict_prev = keyed(json_prev)
        changes['added'] = [row for key, row in dict_now.items() if key not in dict_prev]
        changes['changed'] = [row for key, row in dict_now.items()
                              if key in dict_prev and (row != dict_prev[key] or
                                  (getattr(self, '_reconcile_map_relations', False) and
                                   path in (self.map_item_path, self.map_npc_path, self.map_item_spawn_path))) ]
        changes['removed'] = [row for key, row in dict_prev.items() if key not in dict_now]

        logging.warning("Change at {} : {} added, {} deleted, {} modified row".format(
            path, len(changes['added']), len(changes['removed']), len(changes['changed'])))
        return changes
        


    def handle(self, *args, **kwargs):
        logging.basicConfig(level=logging.WARNING)
        update = kwargs.get('update')
        if update is None:
            update = 1
        # Stage the complete comparison baseline before touching the database.
        # Restore the previous baseline if import, publication, or commit fails.
        staged = tempfile.mkdtemp(prefix='.import-prev-', dir=self.base_path)
        backup = staged + '-backup'
        destination = join(self.base_path, 'prev')
        original_base = self.base_path
        published = False
        moved_old = False
        try:
            for name in os.listdir(self.base_path):
                if name.endswith('.json'):
                    shutil.copy2(join(self.base_path, name), join(staged, name))
            # Validate the exact snapshot used below, before the first DB query.
            ver_json = self._validate_staged_release(staged)
            self.base_path = staged
            self._previous_path = destination
            self._reconcile_map_relations = not exists(join(destination, '.map-relations-v1'))
            # Earlier importers copied these JSONs to prev without importing them.
            # Reconcile their current rows once even when the JSON is unchanged.
            with open(join(staged, '.map-relations-v1'), 'w') as marker:
                marker.write('1\n')
            with transaction.atomic():
                self._import_data(update)
                Version.objects.get_or_create(version=ver_json['version'])
                if exists(destination):
                    os.replace(destination, backup)
                    moved_old = True
                os.replace(staged, destination)
                published = True
        except BaseException:
            if published:
                shutil.rmtree(destination)
            if moved_old:
                os.replace(backup, destination)
            raise
        finally:
            self.base_path = original_base
            self.__dict__.pop('_previous_path', None)
            self.__dict__.pop('_reconcile_map_relations', None)
            self.__dict__.pop('_item_ids_by_name', None)
            if exists(staged):
                shutil.rmtree(staged)
        if moved_old:
            shutil.rmtree(backup)

    def _import_data(self, update):
        item_type       = self.importJSON(join(self.base_path,self.item_type_path))
        #get old dir loc
        #to do compare item from old dir, delete same rows
        # P0-8: recipe 의 $ID 를 'recipe-<n>' canonical ID 로 정규화해
        # Item/Recipe 49건 ClassID 충돌로 인한 드롭을 방지한다. transform 은
        # comparer 내에서 양쪽 JSON(now/prev)에 일괄 적용된다.
        recipe_id_names = set(item_type.get('RECIPES', []))
        self._item_ids_by_name = {
            name: canonical_item_id(row, recipe_id_names)
            for name, row in self.importJSON(join(self.base_path, self.item_path)).items()}
        items           = self.comparer(
            self.item_path,
            transform=lambda e: self._canonical_item_id(e, recipe_id_names),
        )
        self.importItem(items,item_type, update)
        self.importReinforcement()
        
        npc             = self.comparer(self.npc_path)
        monster         = self.comparer(self.monster_path)
        self.importMonster(monster, npc, update)
        
        item_monster    = self.comparer(self.item_monster_path, ['Item','Monster'])
        self.importItemMonster(item_monster,update)
        
        map = self.comparer(self.maps_path)
        self.importMap(map, update)
        
        map = self.comparer(self.map_item_path, ['Map', 'Item'])
        self.importMapItem(map, update)
        
        map = self.comparer(self.map_npc_path, ['Map', 'NPC'])
        self.importMapNPC(map, update)
        
        map = self.comparer(self.map_item_spawn_path, ['Map', 'Item'] )
        self.importMapItemSpawn(map, update)
        
        jobs           = self.comparer(self.jobs_path)
        self.importJobs(jobs, update)
        
        skills         = self.importJSON(join(self.base_path,self.skills_path))
        self.importSkills(skills, update)
        # Gem skill FKs must be created after this release's skills exist.
        self.importGems(item_type)
        
        attrib         = self.comparer(self.attributes_path)
        self.importAttrib(attrib, update)
        
        skillmon = self.comparer('skill_mon.json')
        self.importSkillMon(skillmon, update)
        #to do copy all item to old dir
        #make note about old dir loc
        buff = self.comparer(self.buff_path)
        self.importBuff(buff, update)

        achieve = self.comparer(self.achieve_path)
        self.importAchieve(achieve,update)
        
    def importItem(self,items, item_type, update ):
        for i in items['removed']:
            try:
                Items.objects.get(ids= i['$ID']).delete()
            except ObjectDoesNotExist:
                logging.warning("failed to delete item {} ({})".format(i['Name'], i['$ID']))
        logging.debug("migrating items")
        item_type_db = list(Item_Type.objects.all())  
        dolater = {'RECIPES': [],'COLLECTION': [], 'EQUIPMENT' : [], 'CARD' : []}
        if 'BOOKS' in item_type:
            dolater['BOOKS'] = []
        for i in items['added']:
            upd = False
            try:
                handler = Items.objects.get(ids = i['$ID'])
                upd = True
            except ObjectDoesNotExist:
                handler = Items()
            handler.ids             = i['$ID']
            handler.id_name         = i['$ID_NAME']
            handler.cooldown        = i['TimeCoolDown']
            handler.descriptions    = i['Description']
            handler.name            = i['Name']
            handler.weight          = 0 if i['Weight'] == '' else i['Weight']
            handler.tradability     = i['Tradability']
            handler.type            = i['Type']
            if i['Type'] not in item_type_db:
                try:
                    type_handler = Item_Type.objects.get(name = i['Type'])
                except ObjectDoesNotExist:
                    type_handler = Item_Type()
                type_handler.name = i['Type']
                type_handler.save()
                item_type_db.append(i['Type'])
            handler.grade           = i['Grade']
            handler.icon            = i['Icon']
            handler.package_contents = json.dumps(i['PackageContents'], ensure_ascii=False) if i.get('PackageContents') else None
            handler.save()
            if i['$ID_NAME'] in item_type['EQUIPMENT']:
                dolater['EQUIPMENT'].append([handler,i.copy(), upd])
                #self.makeEQ(handler,i,item_type_db, upd)
            elif i['$ID_NAME'] in item_type['CARD']:
                dolater['CARD'].append([handler,i.copy(), upd])
                #self.makeCard(handler,i,item_type_db, upd)
            elif i['$ID_NAME'] in item_type['RECIPES']:
                dolater['RECIPES'].append([handler,i.copy(), upd])
            elif i['$ID_NAME'] in item_type['COLLECTION']:
                dolater['COLLECTION'].append([handler,i.copy(),  upd])
            elif 'BOOKS' in item_type and i['$ID_NAME'] in item_type['BOOKS']:
                dolater['BOOKS'].append([handler,i.copy(), upd])
                 #self.makeBook(handler,i,item_type_db, upd)
        
        for i in dolater['RECIPES']:
            self.makeRecipe(i[0], i[1], item_type_db, i[2])
        
        for i in dolater['COLLECTION']:
            self.makeCollection(i[0], i[1], item_type_db,i[2])

        for i in dolater['EQUIPMENT']:
            self.makeEQ(i[0], i[1], item_type_db,i[2])

        for i in dolater['CARD']:
            self.makeCard(i[0], i[1], item_type_db,i[2])

        if 'BOOKS' in dolater:
            for i in dolater['BOOKS']:
                self.makeBook(i[0], i[1], item_type_db,i[2])
        
        for i in items['changed']:
            try:
                handler = Items.objects.get(ids = i['$ID'])
            except ObjectDoesNotExist:
                handler = Items()
            handler.ids             = i['$ID']
            handler.id_name         = i['$ID_NAME']
            handler.cooldown        = i['TimeCoolDown']
            handler.descriptions    = i['Description']
            handler.name            = i['Name']
            handler.weight          = 0 if i['Weight'] == '' else i['Weight']
            handler.tradability     = i['Tradability']
            handler.type            = i['Type']
            if i['Type'] not in item_type_db:
                try:
                    type_handler = Item_Type.objects.get(name = i['Type'])
                except ObjectDoesNotExist:
                    type_handler = Item_Type()
                type_handler.name = i['Type']
                type_handler.save()
                item_type_db.append(i['Type'])
            handler.grade           = i['Grade']
            if i['Grade']          == "":
                handler.grade = 1
            handler.icon            = i['Icon']
            handler.package_contents = json.dumps(i['PackageContents'], ensure_ascii=False) if i.get('PackageContents') else None
            handler.save()
            if i['$ID_NAME'] in item_type['EQUIPMENT']:
                self.makeEQ(handler,i,item_type_db, upd = True)
            elif i['$ID_NAME'] in item_type['CARD']:
                self.makeCard(handler,i,item_type_db, upd = True)
            elif i['$ID_NAME'] in item_type['RECIPES']:
                self.makeRecipe(handler,i,item_type_db, upd = True)
            elif i['$ID_NAME'] in item_type['COLLECTION']:
                self.makeCollection(handler,i,item_type_db, upd = True)
            elif 'BOOKS' in item_type and i['$ID_NAME'] in item_type['BOOKS']:
                self.makeBook(handler,i,item_type_db, upd = True)
                
        
           
        
    def importGems(self, item_type):
        names = item_type.get('GEMS', [])
        Gems.objects.exclude(item__id_name__in=names).delete()
        if not names:
            return
        source = self.importJSON(join(self.base_path, self.item_path))
        rows = source.values() if isinstance(source, dict) else source
        by_name = {row['$ID_NAME']: row for row in rows}
        for name in names:
            row = by_name[name]
            skill_id = row.get('Link_Skill')
            skill = Skills.objects.get(ids=str(skill_id)) if skill_id is not None else None
            bonuses = {slot: row.get('Bonus' + slot, []) for slot in GEM_SLOTS}
            Gems.objects.update_or_create(item=self._item_by_name(name), defaults={
                'skill': skill, 'socket_bonuses': json.dumps(bonuses, ensure_ascii=False)})

    def importReinforcement(self):
        table_path = join(self.base_path, 'goddess_reinf.json')
        tables = self.importJSON(table_path) if exists(table_path) else {}
        material_path = join(self.base_path, 'goddess_reinf_mat.json')
        materials = self.importJSON(material_path) if exists(material_path) else {}
        materials = {int(key): groups for key, groups in materials.items()}
        keep = []
        for raw_level, rows in tables.items():
            level = int(raw_level)
            groups = materials.get(level, {})
            if level == 460 and set(groups) == {'armor'}:
                # Legacy JSON wraps the shared level-460 Lua costs in 'armor'.
                groups = {group: groups['armor'] for group in ('acc', 'armor', 'weapon')}
            for row in rows:
                step = int(row['ClassID'])
                costs = {group: values for group, steps in groups.items()
                         for key, values in steps.items() if int(key) == step}
                obj, _ = GoddessReinforcement.objects.update_or_create(level=level, step=step, defaults={
                    'chance': int(row['BasicProp']), 'source': json.dumps(row, ensure_ascii=False),
                    'materials': json.dumps(costs, ensure_ascii=False)})
                keep.append(obj.pk)
        GoddessReinforcement.objects.exclude(pk__in=keep).delete()

    def makeEQ(self, item, i, item_type_db,upd = False):
        try:
            handler = Equipments.objects.get(item = item)
        except ObjectDoesNotExist:
            handler = Equipments()
            handler.item = item
            
        handler.anvil_atk       = i['AnvilATK'] 
        handler.anvil_def       = i['AnvilDEF'] 
        handler.anvil_price     = i['AnvilPrice'] 
       
        
        handler.durability      = i['Durability']
        handler.level           = i['Level']
        handler.reinforcement_level = i.get('GoddessReinforceLevel')
        handler.reinforcement_group = i.get('GoddessReinforceGroup')
        handler.potential       = i['Potential']
        handler.requiredClass   = i['RequiredClass']
        handler.sockets_limit   = i['SocketsLimit']
        handler.stars           = i['Stars']
        handler.matk            = i['Stat_ATTACK_MAGICAL']            
        handler.patk            = i['Stat_ATTACK_PHYSICAL_MIN']
        handler.patk_max        = i['Stat_ATTACK_PHYSICAL_MAX']
        handler.mdef            = i['Stat_DEFENSE_MAGICAL']
        handler.pdef            = i['Stat_DEFENSE_PHYSICAL']
        handler.transcend_price = i['TranscendPrice']
        handler.type_attack     = i['TypeAttack']
        handler.type_equipment  = i['TypeEquipment']
        if i['TypeEquipment'] not in item_type_db:
            try:
                type_handler = Item_Type.objects.get(name = i['Type'])
            except ObjectDoesNotExist:
                type_handler = Item_Type()
            type_handler.name = i['TypeEquipment']
            type_handler.is_equipment = True
            type_handler.save()
            item_type_db.append(i['TypeEquipment'])
        handler.unidentified    = i['Unidentified']
        handler.unidentifiedRandom = i['UnidentifiedRandom']
        Equipment_Bonus.objects.filter(equipment = handler).delete()
        handler.save()
        if (i['Bonus']):
            for b in i['Bonus']:
                bonus = Equipment_Bonus(equipment = handler)
                bonus.bonus_stat = b[0]
                #try:
                #    bonus.bonus_val  = b[1].replace('{img green_up_arrow 16 16}', '▲')\
                #                            .replace('{img green_down_arrow 16 16}', '▼')
                #except ObjectDoesNotExist:
                bonus.bonus_val  = b[1]
                bonus.save()
        handler.save()
    
    def makeCard(self, item, i, item_type_db,upd = False):
        try:
            handler = Cards.objects.get(item = item)
        except ObjectDoesNotExist:
            handler = Cards()
            handler.item = item
        handler.icon = i['IconTooltip']
        
        handler.type_card = i['TypeCard']
        handler.save()
    
    def makeRecipe(self, item, i, item_type_db,upd = False):
        if inactive_recipe(i):
            Recipes.objects.filter(item=item).delete()
            return
        if ('Link_Materials' not in i):
            raise CommandError("invalid recipe {}".format(i['Name']))
        
        try:
            handler = Recipes.objects.get(item = item)
        except ObjectDoesNotExist:
            handler = Recipes()
            handler.item = item
            handler.save()
        Item_Recipe_Material.objects.filter(recipe = handler).delete()
        
        for link in i['Link_Materials']:
            try:
                mat             = Item_Recipe_Material(recipe = handler)
                mat.material    = self._item_by_name(link['Item'])
                mat.qty         = link['Quantity']
                mat.save()
            except ObjectDoesNotExist:
                raise CommandError("[RCP] {} ({}) material not found ({})".format(i['Name'], i['$ID_NAME'], link['Item']))
        
        Item_Recipe_Target.objects.filter(recipe = handler).delete()
        # Some source recipes intentionally have no target (e.g. BlessedStone).
        if i.get('Link_Target') is None:
            return
        try:
            target = Item_Recipe_Target(recipe = handler)
            target.target = self._item_by_name(i['Link_Target'])
            target.save()
        except ObjectDoesNotExist:
            raise CommandError("[RCP] {} ({}) didnt have target".format(i['Name'], i['$ID_NAME']))
    
    def makeCollection(self, item, i, item_type_db,upd = False):
        if ('Link_Items' not in i):
            raise CommandError("invalid collection {}".format(i['Name']))
        try:
            handler = Collections.objects.get(item = item)
        except ObjectDoesNotExist:
            handler = Collections()
            handler.item = item
        handler.save()
        Item_Collection_Material.objects.filter(collection = handler).delete()
        for link in i['Link_Items']:
            try:
                mat             = Item_Collection_Material(collection = handler)
                mat.material    = self._item_by_name(link)
                mat.save()
            except ObjectDoesNotExist:
                raise CommandError("[RCP] {} ({}) material not found ({})".format(i['Name'], i['$ID_NAME'], link))
        
        Item_Collection_Bonus.objects.filter(collection = handler).delete()
        try:
            if (i['Bonus']):
                for b in i['Bonus']:
                    bonus = Item_Collection_Bonus(collection = handler)
                    bonus.bonus_stat = b[0]
                    bonus.bonus_val  = b[1]
                    bonus.save()
        except ObjectDoesNotExist:
            raise CommandError("[RCP] {} ({}) didnt have target".format(i['Name'], i['$ID_NAME']))

    def makeBook (self, item, i, item_type_db,upd = False):
        try:
            handler = Books.objects.get(item = item)
        except ObjectDoesNotExist:
            handler = Books()
            handler.item = item
        if 'Text' in i:
            handler.text = i['Text']
        else:
            handler.text = None
        handler.save()
     
    def importMonster(self,monster, npc, update ):
        for i in monster['removed']:
            try:
                Monsters.objects.get(ids= i['$ID']).delete()
            except ObjectDoesNotExist:
                logging.warning("failed to delete monster {} ({})".format(i['Name'], i['$ID']))
        for i in monster['added'] + monster['changed']:
            try:
                handler                 = Monsters.objects.get(ids= i['$ID'])
            except ObjectDoesNotExist:
                handler = Monsters()
            handler.ids             = i['$ID']
            handler.id_name         = i['$ID_NAME']            
            handler.armor           = i['Armor']
            handler.descriptions    = i['Description']
            handler.element         = i['Element']
            handler.exp             = i['EXP']
            handler.exp_class       = i['EXPClass']
            handler.icon            = i['Icon']
            handler.level           = i['Level']
            handler.name            = i['Name']
            handler.race            = i['Race']
            handler.rank            = i['Rank']
            handler.size            = i['Size']
            handler.accuracy        = i['Stat_Accuracy']
            handler.matk_max        = i['Stat_ATTACK_MAGICAL_MAX']
            handler.matk_min        = i['Stat_ATTACK_MAGICAL_MIN']
            handler.patk_min        = i['Stat_ATTACK_PHYSICAL_MIN']
            handler.patk_max        = i['Stat_ATTACK_PHYSICAL_MAX']
            handler.blockpen        = i['Stat_BlockPenetration']
            handler.block           = i['Stat_BlockRate']
            handler.critdmg         = i['Stat_CriticalDamage']
            handler.critdef         = i['Stat_CriticalDefense']
            handler.critrate        = i['Stat_CriticalRate']
            handler.mdef            = i['Stat_DEFENSE_MAGICAL']
            handler.pdef            = i['Stat_DEFENSE_PHYSICAL']
            handler.eva             = i['Stat_Evasion']
            handler.hp              = i['Stat_HP']
            handler.stat_dex        = i['Stat_DEX']
            handler.stat_int        = i['Stat_INT']
            handler.stat_spr        = i['Stat_SPR']
            handler.stat_str        = i['Stat_STR']
            handler.stat_con        = i['Stat_CON']
            handler.save()
        
       
        
        for i in npc['removed']:
            try:
                Monsters.objects.get(ids= i['$ID']).delete()
            except ObjectDoesNotExist:
                logging.warning("failed to delete monster {} ({})".format(i['Name'], i['$ID']))
        for i in npc['added']:
            try:
                handler                 = Monsters.objects.get(ids= i['$ID'])
            except ObjectDoesNotExist:
                handler = Monsters()
            
            handler.ids             = i['$ID']
            handler.id_name         = i['$ID_NAME']            
            handler.descriptions    = i['Description']
            handler.icon            = i['Icon']
            handler.name            = i['Name']
            handler.save()
        
        for i in npc['changed']:
            handler                 = Monsters.objects.get(ids= i['$ID'])
            handler.ids             = i['$ID']
            handler.id_name         = i['$ID_NAME']            
            handler.descriptions    = i['Description']
            handler.icon            = i['Icon']
            handler.name            = i['Name']
            handler.save()
        
        
           
        
        
    def importItemMonster(self,item_monster, update ):
        for i in item_monster['removed']:
            try:
                Item_Monster.objects.filter(monster__ids=i['Monster'], item__ids=i['Item']).delete()
            except ObjectDoesNotExist:
                logging.warning("failed to delete item_monster {} ({})".format(i['Item'], i['Monster']))
        for i in item_monster['added'] + item_monster['changed']:
            Item_Monster.objects.update_or_create(
                monster=Monsters.objects.get(ids=i['Monster']),
                item=Items.objects.get(ids=i['Item']),
                defaults={'chance': i['Chance'], 'qty_min': i['Quantity_MIN'],
                          'qty_max': i['Quantity_MAX']})
        
        

    
            
    def importMap (self,map, update ):
        for i in map['removed']:
            try:
                Maps.objects.filter(ids=i['$ID']).delete()
            except ObjectDoesNotExist:
                logging.warning("failed to delete map {} ({})".format(i['Name'], i['$ID']))
        for i in map['added'] + map['changed'] :
            try:
                handler = Maps.objects.get(ids= i['$ID'])
            except ObjectDoesNotExist:
                handler = Maps()
            handler.ids            = i['$ID']
            handler.id_name        = i['$ID_NAME']            
            handler.icon           = (i['$ID_NAME'] + ".png").lower()
            handler.name           = i['Name']
            handler.has_cm         = i['HasChallengeMode']
            handler.has_warp       = i['HasWarp']
            handler.level          = i['Level']
            handler.max_elite      = i['Prop_EliteMonsterCapacity']
            handler.max_hate       = i['Prop_MaxHateCount']
            handler.star           = i['Stars']
            handler.type           = i['Type']
            handler.map_link       = i['Link_Maps']
            handler.save()
        
        

    
    def importMapItem (self,map, update ):
        for i in map['removed']:
            try:
                m = Maps.objects.get(ids = i['Map'])
                it = Items.objects.get(ids = i['Item'])
            except ObjectDoesNotExist:
                logging.warning("map {} or item {} not found".format(i['Map'], i['Item']))
                continue
            Map_Item.objects.filter(map=m, item=it).delete()
        for i in map['added'] + map['changed']:
           
            try:
                m = Maps.objects.get(ids = i['Map'])
                it = Items.objects.get(ids = i['Item'])
            except ObjectDoesNotExist:
                raise CommandError("map {} or item {} not found".format(i['Map'], i['Item']))
            try:
                handler = Map_Item.objects.get(map= m, item = it)
            except ObjectDoesNotExist:
                handler = Map_Item()
            handler.chance          = i['Chance']
            handler.item            = it
            handler.map             = m
            handler.qty_max         = i['Quantity_MAX']
            handler.qty_min         = i['Quantity_MIN']
            handler.save()
        
        
            
    
    
    def importMapItemSpawn (self,map, update ):
        for i in map['removed']:
            try:
                m = Maps.objects.get(ids = i['Map'])
                it = Items.objects.get(ids = i['Item'])
                Map_Item_Spawn.objects.filter(map=m, item=it).delete()
            except ObjectDoesNotExist:
                logging.warning("map {} or item {} not found".format(i['Map'], i['Item']))
                continue
        for i in map['added'] +  map['changed']:
          
            try:
                m = Maps.objects.get(ids = i['Map'])
                it = Items.objects.get(ids = i['Item'])
            except ObjectDoesNotExist:
                raise CommandError("map {} or item {} not found".format(i['Map'], i['Item']))
            try:
                handler = Map_Item_Spawn.objects.get(map= m, item = it)
            except ObjectDoesNotExist:
                handler = Map_Item_Spawn()
            handler.population      = i['Population']
            handler.item            = it
            handler.map             = m
            handler.time_respawn    = i['TimeRespawn']
            pos = []
            for posit in i['Positions']:
                for po in posit:
                    pos.append(po)
            handler.positions        = pos
            handler.save()
         
        
        

            
    
    
    def importMapNPC (self,map, update ):
        for i in map['removed']:
            try:
                m = Maps.objects.get(ids = i['Map'])
                it = Monsters.objects.get(ids = i['NPC'])
                Map_NPC.objects.filter(map=m, monster=it).delete()
            except ObjectDoesNotExist:
                logging.warning("map {} or item {} not found".format(i['Map'], i['NPC']))
                continue
        for i in map['added'] + map['changed']:
            
            try:
                m = Maps.objects.get(ids = i['Map'])
                it = Monsters.objects.get(ids = i['NPC'])
            except ObjectDoesNotExist:
                raise CommandError("map {} or NPC {} not found".format(i['Map'], i['NPC']))
            try:
                handler = Map_NPC.objects.get(map= m, monster = it)
            except ObjectDoesNotExist:
                handler = Map_NPC()
            handler.population      = i['Population']
            handler.monster         = it
            handler.map             = m
            pos = []
            for posit in i['Positions']:
                for po in posit:
                    pos.append(po)
            handler.time_respawn    = i['TimeRespawn']
            handler.positions        = pos
            handler.save()
            
        
        

            
            
    
    def importJobs(self,jobs, update ):
        for i in jobs['removed']:
            try:
                Jobs.objects.get(ids= i['$ID']).delete()
            except ObjectDoesNotExist:
                logging.warning("failed to delete jon {} ({})".format(i['Name'], i['$ID']))
        for i in jobs['added'] + jobs['changed']:
            try:
                handler = Jobs.objects.get(ids= i['$ID'])
            except ObjectDoesNotExist:
                handler = Jobs()
            handler.ids             = i['$ID']
            handler.id_name         = i['$ID_NAME']            
            handler.name            = i['Name']
            handler.is_starter      = i['IsStarter']
            handler.job_tree        = i['JobTree']
            handler.icon            = i['Icon']
            handler.descriptions    = i['Description']
            handler.save()
            
        
        
            
            
        
    
    def importSkills(self,skills, update ):
        self._available_skill_names = {row['$ID_NAME'] for row in skills.values()
                                       if row.get('Link_Job') is not None}
        logging.debug("migrating monsters")
        count = 0
        count_all = len(skills)
        table = Skills
        all_item = table.objects.values_list('ids')
        json_item = []
        for i in skills.values() :
            flag_u = False
            try :
                handler = Skills.objects.get(ids= i['$ID'])
                flag_u = True
                if update == 0:
                    logging.info("skipping ({}/{})  {}".format(count,count_all,i['Name']))
                    
                else:
                    logging.info("updating ({}/{})  {}".format(count,count_all,i['Name']))
            except ObjectDoesNotExist:
                handler = Skills()
                logging.info("inserting ({}/{})  {}".format(count,count_all,i['Name']))
            
            if flag_u and update == 0:
                count+=1
                continue
            if i['Link_Job'] == None:
                continue
            json_item.append(str(i['$ID']))
            handler.ids             = i['$ID']
            handler.id_name         = i['$ID_NAME']            
            handler.name            = i['Name']
            handler.icon            = i['Icon']
            handler.descriptions    = i['Description']
            if 'BasicCoolDown' in i:
                handler.cooldown        = i['BasicCoolDown']
            else:
                handler.cooldown        = 0
            handler.sp              = i['BasicSP']
            if (i['RequiredStanceCompanion'].lower() == 'yes'):
                handler.is_riding       = True
            else:
                handler.is_riding       = False
            handler.effect          = i['Effect']
            handler.element         = i['Element']
            handler.max_lv          = i['MaxLevel']
            handler.unlock          = i['UnlockClassLevel']
            handler.overheat        = i['OverHeat']
            handler.job             = Jobs.objects.get(ids = i['Link_Job'])
            if 'sfr' in i:
                handler.sfr             = i['sfr']
            # CaptionRatio 단위 변환은 parser(skills.py)가 단일 소유한다.
            # 이전에는 importer 양쪽에서 0<v<1 을 100배해 이중 확대 위험이 있었다.
            # importer 늀 parser 출력을 int 로만 저장한다.
            if 'CaptionRatio' in i:
                try:
                    i['CaptionRatio'] = [int(h) for h in i['CaptionRatio']]
                except (ValueError, TypeError):
                    i['CaptionRatio'] = None
                handler.captionratio1   = i['CaptionRatio']
            if 'CaptionRatio2' in i:
                try:
                    i['CaptionRatio2'] = [int(h) for h in i['CaptionRatio2']]
                except (ValueError, TypeError):
                    i['CaptionRatio2'] = None
                handler.captionratio2   = i['CaptionRatio2']
            if 'CaptionRatio3' in i:
                try:
                    i['CaptionRatio3'] = [int(h) for h in i['CaptionRatio3']]
                except (ValueError, TypeError):
                    i['CaptionRatio3'] = None
                handler.captionratio3   = i['CaptionRatio3']
            if 'CaptionTime' in i:
                try:
                    for h in i['CaptionTime']:
                        h = int(h)
                except (ValueError, TypeError):
                    i['CaptionTime'] = None
                handler.captiontime     = i['CaptionTime']
            if 'SkillSR' in i:
                try:
                    for h in i['SkillSR']:
                        h = int(h)
                except (ValueError, TypeError):
                    i['SkillSR'] = None
                handler.skillsr     = i['SkillSR'] 
            if 'SpendItemCount' in i:
                try:
                    for h in i['SpendItemCount']:
                        h = int(h)
                except (ValueError, TypeError):
                    i['SpendItemCount'] = None
                handler.spenditemcount  = i['SpendItemCount'] 
            if 'SpendPoison' in i:
                try:
                    for h in i['SpendPoison']:
                        h = int(h)
                except (ValueError, TypeError):
                    i['SpendPoison'] = None
                handler.spendpoison     = i['SpendPoison'] 
            if 'SpendSP' in i:
                try:
                    for h in i['SpendSP']:
                        h = int(h)
                except (ValueError, TypeError):
                    i['SpendSP'] = None
                handler.spendsp     = i['SpendSP'] 
            if 'CoolDown' in i:
                try:
                    for h in i['CoolDown']:
                        h = int(h)
                except (ValueError, TypeError):
                    i['CoolDown'] = None
                handler.cooldown_lv     = i['CoolDown'] 
            handler.job = Jobs.objects.get(ids = i['Link_Job'])
            handler.stance = i['RequiredStance']
            handler.save()
            
            
            count+=1
        self.deleteMe(all_item, json_item, table, 'Skills')
        
    def importAttrib (self,attrib, update ):
        for i in attrib['removed']:
            try:
                Attributes.objects.get(ids= i['$ID']).delete()
            except ObjectDoesNotExist:
                logging.warning("failed to delete attrib {} ({})".format(i['Name'], i['$ID']))

        for i in attrib['added'] + attrib['changed']:
            try:
                handler = Attributes.objects.get(ids= i['$ID'])
                if (i['LevelMax']==-1):
                    attrib['removed'].append(i)
                    continue
                
            except ObjectDoesNotExist:
                handler = Attributes()
                if (i['LevelMax']==-1):
                    continue
            handler.ids             = i['$ID']
            handler.id_name         = i['$ID_NAME']            
            handler.descriptions    = i['Description']
            handler.icon            = i['Icon']
            handler.name            = i['Name']
            handler.descriptions_required = i['DescriptionRequired']
            handler.is_toggleable   = i['IsToggleable']
            handler.max_lv          = i['LevelMax']
            handler.save()
            added_skill = []
            for h in i['Link_Skills']:
                # Exported attributes retain references to retired/non-job skills.
                # Only absence from the source is optional; a missing DB row for
                # an importable skill must still abort the import.
                if hasattr(self, '_available_skill_names') and h not in self._available_skill_names:
                    logging.warning('Skipping non-exported attribute skill %s', h)
                    continue
                try:
                    skill = Skills.objects.get(id_name = h)
                    handler.skill.add(skill)
                    added_skill.append(skill.ids)
                except ObjectDoesNotExist:
                    raise CommandError("skill not found {}".format(h))
            for skill in handler.skill.all():
                if skill.ids not in added_skill:
                    handler.skill.remove(skill)
            added_jobs = []
            for h in i['Link_Jobs']:
                try:
                    job = Jobs.objects.get(ids = h)
                    handler.job.add(job)
                    added_jobs.append(job.ids)
                except ObjectDoesNotExist:
                    raise CommandError("skill not found {}".format(h))
            for job in handler.job.all():
                if job.ids not in added_jobs:
                    handler.job.remove(job)
            handler.save()
            
        
        
            
            
    def importSkillMon(self, skillmon, update):
        for i in skillmon['removed']:
            try:
                Skill_Monster.objects.get(ids= i['$ID']).delete()
            except ObjectDoesNotExist:
                logging.warning("failed to delete skillmon {} ({})".format(i['Name'], i['$ID']))
            
        for i in skillmon['added'] +skillmon['changed'] :
            try:
                handler = Skill_Monster.objects.get(ids= i['$ID'])
            except ObjectDoesNotExist:
                handler = Skill_Monster()
            link_mon = []
            handler.ids             = i['$ID']
            handler.id_name         = i['$ID_NAME']            
            handler.name            = i['Name']
            handler.sfr = 0 if i['SFR'] in (None, '') else number(i['SFR'], 'skill_mon.SFR', raw=True)
            handler.element         = i['Attribute']
            handler.cooldown        = int(i['CD'])
            handler.aar             = i['AAR']
            handler.hit_count       = int(i.get('HitCount') or 1)
            handler.save()
            for monster in i['Monster']:
                try:
                    link_mon.append(Monsters.objects.get(ids = monster))
                except ObjectDoesNotExist:
                    raise CommandError("monster(ids) {} not found (for skill)".format(monster))
            handler.monsters.set(link_mon)
            handler.save()
            
        
            
    def importBuff(self, buff, update):
        for i in buff['removed']:
            try:
                Buffs.objects.get(ids= i['$ID']).delete()
            except ObjectDoesNotExist:
                logging.warning("failed to delete buff {} ({})".format(i['Name'], i['$ID']))
            
        for i in buff['added'] +buff['changed'] :
            try:
                handler = Buffs.objects.get(ids= i['$ID'])
            except ObjectDoesNotExist:
                handler = Buffs()
            link_mon = []
            handler.ids             = i['$ID']
            handler.id_name         = i['$ID_NAME']            
            handler.name            = i['Name']
            handler.icon            = i['Icon']
            handler.descriptions    = i['Description']
            handler.applytime       = i['ApplyTime']
            handler.group1          = i['Group1']
            handler.group2          = i['Group2']
            handler.group3          = i['Group3']
            handler.groupindex      = i['GroupIndex']
            handler.overbuff        = i['OverBuff']
            handler.userremove      = i['UserRemove']
            handler.keyword         = i['Keyword']
            handler.save()
            

            
    def importAchieve(self, achieve, update):
        for i in achieve['removed']:
            try:
                Achievements.objects.get(ids= i['$ID']).delete()
            except ObjectDoesNotExist:
                logging.warning("failed to delete achievements {} ({})".format(i['Name'], i['$ID']))
            
        for i in achieve['added'] +achieve['changed'] :
            try:
                handler = Achievements.objects.get(ids= i['$ID'])
            except ObjectDoesNotExist:
                handler = Achievements()
            link_mon = []
            handler.ids             = i['$ID']
            handler.id_name         = i['$ID_NAME']            
            handler.name            = i['Name']
            handler.icon            = i['Icon']
            if ('Image' in i):
                handler.image           = i['Image']
            handler.hidden          = i['Hidden']
            handler.descriptions    = i['Desc']
            handler.desc_title      = i['DescTitle']
            handler.group           = i['Group']
            handler.save()
