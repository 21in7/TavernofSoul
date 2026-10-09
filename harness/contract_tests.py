"""Release contracts run before DB queries; valid imports retain rollback safety."""
import json
import copy
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase
from django.db import connection

from Attributes.models import Attributes
from Buffs.models import Buffs
from Dashboard.models import Version
from Items.models import (Books, Cards, Collections, Equipment_Bonus, Equipments, Recipes,
                          Item_Collection_Bonus, Item_Collection_Material,
                          Item_Recipe_Material, Item_Recipe_Target, Items, Item_Type)
from Jobs.models import Jobs
from Maps.models import Maps, Map_Item, Map_Item_Spawn, Map_NPC
from Monsters.models import Item_Monster, Monsters, Skill_Monster
from Other.models import Achievements
from Skills.models import Skills
from ipfparser.contracts import ContractError
from ipfparser.management.commands import importAll
from harness.contract_fixture import add_contract_edges
from harness.parser_fixture import parse_workspace, prepare_combat_workspace


class ReleaseContractTests(TransactionTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='tavern-contract-pipeline-')
        self.addCleanup(temporary.cleanup)
        workspace = prepare_combat_workspace(temporary.name)
        self.db = add_contract_edges(parse_workspace(workspace, include_combat=True))
        self.db.export(version_payload={'version': 'contract-v1'})
        self.release = Path(self.db.BASE_PATH_OUTPUT)
        self.command = importAll.Command()
        self.command.base_path = str(self.release)

    def import_release(self):
        call_command(self.command, update=1)

    def database_snapshot(self, ignore_updated=False):
        models = (Items, Item_Type, Equipments, Equipment_Bonus, Cards, Collections, Books,
                  Item_Collection_Bonus, Item_Collection_Material,
                  Item_Recipe_Material, Item_Recipe_Target, Jobs, Skills,
                  Monsters, Item_Monster, Skill_Monster, Skill_Monster.monsters.through,
                  Maps, Map_Item, Map_Item_Spawn, Map_NPC, Attributes,
                  Attributes.job.through, Attributes.skill.through, Buffs, Achievements, Version)
        result = [list(model.objects.order_by('pk').values()) for model in models]
        if ignore_updated:
            for records in result:
                for row in records:
                    row.pop('updated', None)
        return result

    def baseline(self):
        directory = self.release / 'prev'
        return {path.name: path.read_bytes() for path in directory.iterdir()} if directory.exists() else {}

    def publish_changed_release(self):
        self.db.data['items_by_name']['harness_ore']['Name'] = 'Changed Ore'
        self.db.data['skills']['400']['BasicSP'] = 22
        self.db.export(version_payload={'version': 'contract-v2'})

    def edit_json(self, name, path, value):
        file = self.release / (name + '.json')
        data = json.loads(file.read_text())
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        file.write_text(json.dumps(data))

    def assert_clean_staging(self):
        self.assertEqual(self.command.base_path, str(self.release))
        self.assertFalse(list(self.release.glob('.import-prev-*')))

    def test_valid_extended_contract_reaches_models_and_reimports(self):
        self.import_release()
        self.assertEqual(Items.objects.get(id_name='harness_card').weight, 0)
        self.assertEqual(Cards.objects.get().type_card, 'ATK')
        self.assertEqual(Books.objects.get().text, 'Contract book text')
        self.assertEqual(Collections.objects.count(), 1)
        self.assertEqual(Item_Collection_Material.objects.get().material.id_name, 'harness_ore')
        self.assertEqual(Buffs.objects.get().applytime, 3000)
        self.assertTrue(Buffs.objects.get().userremove)
        self.assertEqual(Attributes.objects.get().max_lv, 5)
        self.assertEqual(list(Attributes.objects.get().skill.values_list('id_name', flat=True)), ['Harness_Fire'])
        self.assertEqual(Achievements.objects.count(), 1)
        self.assertEqual(Maps.objects.get().level, -1)
        self.assertEqual(Map_Item.objects.get().chance, 100)
        self.assertEqual(Map_NPC.objects.get().positions, ['-1.5', '2'])
        self.assertEqual(Map_NPC.objects.get().time_respawn, 2.5)
        self.assertEqual(Map_Item_Spawn.objects.get().positions, ['3', '-4'])
        # importSkills saves existing rows and advances its audit timestamp.
        before = self.database_snapshot(ignore_updated=True)
        self.import_release()
        self.assertEqual(self.database_snapshot(ignore_updated=True), before)
        self.assert_clean_staging()

    def test_real_nullable_placeholders_and_decimal_skill_factor(self):
        self.import_release()
        self.assertTrue(Recipes.objects.exists())
        self.assertTrue(Item_Recipe_Material.objects.exists())
        self.assertTrue(Item_Recipe_Target.objects.exists())
        self.db.data['items_by_name']['harness_ore']['TimeCoolDown'] = None
        recipe = self.db.data['items_by_name']['harness_recipe']
        recipe['Name'] = None
        recipe.pop('Link_Materials')
        recipe.pop('Link_Target')
        self.db.data['skills']['400']['Element'] = None
        self.db.data['skill_mon']['600']['SFR'] = '908.599976'
        self.db.data['skill_mon']['600']['AAR'] = '-99'
        self.db.export(version_payload={'version': 'contract-v2'})
        self.import_release()
        self.assertIsNone(Items.objects.get(id_name='harness_ore').cooldown)
        self.assertFalse(Recipes.objects.exists())
        self.assertFalse(Item_Recipe_Material.objects.exists())
        self.assertFalse(Item_Recipe_Target.objects.exists())
        self.assertIsNone(Skills.objects.get(ids='400').element)
        self.assertAlmostEqual(Skill_Monster.objects.get(ids='600').sfr, 908.599976)
        self.assertEqual(Skill_Monster.objects.get(ids='600').aar, -99)
        before = self.database_snapshot(ignore_updated=True)
        self.import_release()
        self.assertEqual(self.database_snapshot(ignore_updated=True), before)

    def test_case_distinct_classnames_resolve_recipe_and_collection_by_id(self):
        data = self.db.data
        for name, ids in (('GoldMoru_Box_S', '6900'), ('goldmoru_box_S', '6901')):
            row = copy.deepcopy(data['items_by_name']['harness_ore'])
            row.update({'$ID': ids, '$ID_NAME': name})
            data['items_by_name'][name] = row
        recipe = data['items_by_name']['harness_recipe']
        recipe['Link_Materials'][0]['Item'] = 'goldmoru_box_S'
        recipe['Link_Target'] = 'GoldMoru_Box_S'
        data['items_by_name']['harness_collection']['Link_Items'] = ['GoldMoru_Box_S', 'goldmoru_box_S']
        self.db.export(version_payload={'version': 'case-distinct-v1'})
        self.import_release()
        if connection.vendor == 'mysql':
            self.assertEqual(Items.objects.filter(id_name='GoldMoru_Box_S').count(), 2)
        self.assertEqual(Item_Recipe_Material.objects.filter(material__ids='6901').count(), 1)
        self.assertEqual(Item_Recipe_Material.objects.count(), 2)
        self.assertEqual(Item_Recipe_Target.objects.get().target.ids, '6900')
        self.assertEqual(set(Item_Collection_Material.objects.values_list('material__ids', flat=True)),
                         {'6900', '6901'})
        self.import_release()
        self.assertEqual(Item_Collection_Material.objects.count(), 2)

    def test_first_invalid_release_runs_no_database_queries(self):
        self.edit_json('items_by_name', ('harness_ore', 'Grade'), True)
        with self.assertNumQueries(0), self.assertRaisesMessage(CommandError, 'Grade [number]'):
            self.import_release()
        self.assertEqual(Items.objects.count(), 0)
        self.assertEqual(Version.objects.count(), 0)
        self.assertFalse((self.release / 'prev').exists())
        self.assert_clean_staging()
        self.db.export(version_payload={'version': 'contract-v1'})
        self.import_release()
        self.assertTrue(Items.objects.filter(id_name='harness_ore').exists())

    def test_import_and_export_report_the_same_contract_error(self):
        self.import_release()
        before, baseline = self.database_snapshot(), self.baseline()
        self.publish_changed_release()
        self.db.data['item_monster'][0]['Chance'] = 101
        with self.assertRaises(ContractError) as export_error:
            self.db.export(version_payload={'version': 'contract-v2'})
        self.edit_json('item_monster', (0, 'Chance'), 101)
        with self.assertNumQueries(0), self.assertRaises(CommandError) as import_error:
            self.import_release()
        self.assertIsInstance(import_error.exception.__cause__, ContractError)
        self.assertEqual(str(import_error.exception.__cause__), str(export_error.exception))
        self.assertEqual(self.database_snapshot(), before)
        self.assertEqual(self.baseline(), baseline)
        self.assert_clean_staging()
        self.db.data['item_monster'][0]['Chance'] = 12.5
        self.db.export(version_payload={'version': 'contract-v2'})
        self.import_release()
        self.assertEqual(Items.objects.get(id_name='harness_ore').name, 'Changed Ore')
        self.assertEqual(Skills.objects.get().sp, 22)

    def test_missing_files_duplicate_keys_and_references_preserve_baseline(self):
        self.import_release()
        self.publish_changed_release()
        before, baseline = self.database_snapshot(), self.baseline()
        originals = {path.name: path.read_bytes() for path in self.release.glob('*.json')}
        cases = [
            ('missing-file', 'required', lambda: (self.release / 'buff.json').unlink()),
            ('duplicate-key', 'duplicate_key', lambda: (self.release / 'version.json').write_text(
                '{"version":"v1","version":"v2"}')),
            ('bad-map', 'reference', lambda: self.edit_json('map_npc', (0, 'Map'), 'missing')),
            ('bad-recipe', 'reference', lambda: self.edit_json('items_by_name', ('harness_recipe', 'Link_Target'), 'missing')),
            ('duplicate-id', 'duplicate', lambda: self.edit_json('items_by_name', ('harness_dust', '$ID'), '100')),
            ('nonfinite', 'number', lambda: self.edit_json('item_monster', (0, 'Chance'), float('nan'))),
        ]
        for label, code, corrupt in cases:
            with self.subTest(label=label):
                corrupt()
                with self.assertNumQueries(0), self.assertRaisesMessage(CommandError, '[' + code + ']'):
                    self.import_release()
                self.assertEqual(self.database_snapshot(), before)
                self.assertEqual(self.baseline(), baseline)
                self.assert_clean_staging()
                for name, content in originals.items():
                    (self.release / name).write_bytes(content)
        self.import_release()
        self.assertTrue(Version.objects.filter(version='contract-v2').exists())

    def test_validation_uses_staged_bytes_even_when_source_is_valid(self):
        self.import_release()
        self.publish_changed_release()
        before, baseline = self.database_snapshot(), self.baseline()
        real_copy = importAll.shutil.copy2
        def copy_with_bad_target(source, destination):
            result = real_copy(source, destination)
            if Path(source).name == 'item_monster.json':
                path = Path(destination)
                data = json.loads(path.read_text())
                data[0]['Item'] = 'missing'
                path.write_text(json.dumps(data))
            return result
        with patch.object(importAll.shutil, 'copy2', side_effect=copy_with_bad_target):
            with self.assertNumQueries(0), self.assertRaisesMessage(CommandError, 'reference'):
                self.import_release()
        self.assertEqual(self.database_snapshot(), before)
        self.assertEqual(self.baseline(), baseline)
        self.assert_clean_staging()
        self.import_release()
        self.assertTrue(Version.objects.filter(version='contract-v2').exists())

    def test_valid_contract_still_rolls_back_later_database_failure_and_retries(self):
        self.import_release()
        self.publish_changed_release()
        before, baseline = self.database_snapshot(), self.baseline()
        def fail_after_earlier_writes(*args):
            self.assertEqual(Items.objects.get(id_name='harness_ore').name, 'Changed Ore')
            self.assertEqual(Skills.objects.get().sp, 22)
            raise CommandError('injected later import failure')
        with patch.object(self.command, 'importSkillMon', side_effect=fail_after_earlier_writes):
            with self.assertRaisesMessage(CommandError, 'injected later import failure'):
                self.import_release()
        self.assertEqual(self.database_snapshot(), before)
        self.assertEqual(self.baseline(), baseline)
        self.assert_clean_staging()
        self.import_release()
        self.assertEqual(Skills.objects.get().sp, 22)
        self.assertTrue(Version.objects.filter(version='contract-v2').exists())
