"""Goddess equipment and gem sources reach the real importer, ORM and HTTP."""
import csv
import json
from pathlib import Path
import tempfile
from html.parser import HTMLParser
from unittest.mock import patch
from xml.etree import ElementTree as ET

from django.core.management import call_command, CommandError
from django.db import IntegrityError
from django.contrib.staticfiles import finders
from django.test import TransactionTestCase, override_settings

from Dashboard.models import Version
from Items.models import Items, Equipments, Gems, GoddessReinforcement
from Skills.models import Skills
from harness.fixture_inputs import EQUIPMENT_FIXTURE, REGIONS
from harness.parser_fixture import change_ies_column, parse_workspace, prepare_equipment_workspace
from ipfparser.management.commands.importAll import Command
from harness.browser_calculator import run_calculator

EXPECTED = json.loads((EQUIPMENT_FIXTURE / 'expected_equipment.json').read_text())


class EquipmentPipelineTests(TransactionTestCase):
    def prepare_region(self, region='itos'):
        temporary = tempfile.TemporaryDirectory(prefix='tavern-equipment-pipeline-')
        self.addCleanup(temporary.cleanup)
        override = override_settings(REGION=region)
        override.enable()
        self.addCleanup(override.disable)
        self.region = region
        self.workspace = prepare_equipment_workspace(temporary.name, region)
        self.db = self.parse_release('equipment-v1')
        self.release = Path(self.db.BASE_PATH_OUTPUT)
        self.unpack = self.workspace / (region + '_unpack')
        self.command = Command()
        self.command.base_path = str(self.release)

    def parse_release(self, version):
        return parse_workspace(self.workspace, version, region=self.region, include_equipment=True)

    def import_release(self):
        call_command(self.command, update=1)

    def baseline(self):
        return {path.name: path.read_bytes() for path in (self.release / 'prev').iterdir()}

    def snapshot(self, ignore_updated=False):
        records = [list(model.objects.order_by('pk').values())
                   for model in (Items, Equipments, Gems, GoddessReinforcement, Skills, Version)]
        if ignore_updated:
            for rows in records:
                for row in rows:
                    row.pop('updated', None)
        return records

    def assert_roundtrip(self, region):
        self.prepare_region(region)
        self.import_release()
        self.assertEqual(Items.objects.count(), 14)
        sword = Equipments.objects.get(item__ids='110')
        armor = Equipments.objects.get(item__ids='112')
        acc = Equipments.objects.get(item__ids='113')
        self.assertEqual((sword.level, sword.patk, sword.patk_max),
                         (560, EXPECTED['sword_min'], EXPECTED['sword_max']))
        self.assertEqual((armor.level, armor.pdef, armor.mdef),
                         (560, EXPECTED['armor_def'], EXPECTED['armor_mdef']))
        self.assertEqual((acc.level, acc.matk, acc.patk, acc.patk_max),
                         (550, EXPECTED['accessory_atk'], EXPECTED['accessory_atk'], EXPECTED['accessory_atk']))
        self.assertEqual(sword.transcend_price, EXPECTED['transcend'])
        self.assertEqual(GoddessReinforcement.objects.count(), 90)
        self.assertEqual(sword.anvil_atk, list(range(100, 3001, 100)))
        self.assertEqual(armor.anvil_def, list(range(200, 6001, 200)))
        self.assertEqual(acc.anvil_atk, list(range(80, 2401, 80)))
        self.assertEqual((sword.reinforcement_level, sword.reinforcement_group), (560, 'weapon'))
        self.assertEqual(Gems.objects.count(), 2)
        self.assertIsNone(Gems.objects.get(item__ids='230').skill)
        self.assertEqual(Gems.objects.get(item__ids='240').skill.ids, '400')
        for ident, name in (('110', 'Fixture Dawn Sword'), ('112', 'Fixture Dawn Armor'),
                            ('113', 'Fixture Goddess Necklace'), ('230', 'Fixture Red Gem'),
                            ('240', 'Fixture Fire Skill Gem')):
            self.assertContains(self.client.get('/items/' + ident), name)
            grade = '6' if ident in ('110', '112', '113') else '1'
            self.assertEqual(self.client.get('/items/', {'q': name, 'grade': grade}).context['item_len'], 1)
        self.assertContains(self.client.get('/items/110'), '7000')
        self.assertContains(self.client.get('/items/112'), '9000')
        self.assertContains(self.client.get('/items/113'), '3300')
        self.assertEqual(self.client.get('/items/240').context['item'].gems.skill.ids, '400')
        self.assertContains(self.client.get('/items/240'), 'href="/skills/400"')
        for ident, stat, expected in (('110', 'patk', 7600), ('112', 'pdef', 10200), ('113', 'matk', 3780)):
            response = self.client.get('/items/' + ident)
            payload = response.context['enhancement']
            class ElementIDs(HTMLParser):
                ids = []
                def handle_starttag(self, tag, attributes):
                    self.ids.extend(value for name, value in attributes if name == 'id')
            elements = ElementIDs()
            elements.ids = []
            elements.feed(response.content.decode())
            rendered = run_calculator(payload, [{'anvil': 6}, {'anvil': 30}, {'anvil': 0}], elements.ids)
            self.assertEqual(rendered['results'][0]['calculation']['stats'][stat], expected)
            self.assertEqual(rendered['results'][0]['display']['god_chance']['text'], '98%')
            self.assertEqual(rendered['results'][1]['display']['god_chance']['text'], '50%')
            self.assertEqual(rendered['results'][2]['display']['god_materials']['text'], '—')
            self.assertIn('/items/100', [link['href'] for link in rendered['results'][0]['display']['god_materials']['links']])
        bonuses = json.loads(Gems.objects.get(item__ids='230').socket_bonuses)
        self.assertEqual(bonuses['Weapon'], EXPECTED['gem_weapon'])
        self.assertEqual(self.client.get('/items/230').context['gem_bonuses'][0]['level'], 1)
        self.assertContains(self.client.get('/items/230'), 'gem-socket-bonuses')
        self.assertContains(self.client.get('/items/230'), '<td>-10</td>')
        self.assertTrue(finders.find('js/item-enhancement.js'))
        baseline, snapshot = self.baseline(), self.snapshot(ignore_updated=True)
        self.parse_release('equipment-v1')
        self.import_release()
        self.assertEqual(self.baseline(), baseline)
        self.assertEqual(self.snapshot(ignore_updated=True), snapshot)
        self.assertEqual(Version.objects.count(), 1)

    def test_source_table_changes_recalculate_560_550_and_preserve_material_json(self):
        self.prepare_region('ktos')
        self.import_release()
        change_ies_column(self.unpack / 'ies.ipf/item_goddess_reinforce_560.ies', 'BasicAtk', '8000')
        change_ies_column(self.unpack / 'ies.ipf/item_goddess_reinforce_560.ies', 'BasicDef', '10000')
        change_ies_column(self.unpack / 'ies.ipf/item_goddess_reinforce_550.ies', 'BasicAccAtk', '3600')
        lua = self.unpack / 'shared.ipf/equipment_calculate.lua'
        lua.write_text(lua.read_text().replace('step * multiplier', 'step * (multiplier + 2)'))
        self.parse_release('equipment-v2')
        self.import_release()
        self.assertEqual(Equipments.objects.get(item__ids='110').patk, 8000)
        self.assertEqual(Equipments.objects.get(item__ids='112').pdef, 10000)
        self.assertEqual(Equipments.objects.get(item__ids='113').matk, 3600)
        current = json.loads((self.release / 'goddess_reinf_mat.json').read_text())
        previous = json.loads((self.release / 'prev/goddess_reinf_mat.json').read_text())
        self.assertEqual(current['560']['weapon']['6']['harness_ore'], 48)
        self.assertEqual(current, previous)
        self.assertContains(self.client.get('/items/110'), '8000')
        self.assertEqual(Version.objects.count(), 2)

    def test_skill_gem_retarget_and_source_deletion_update_real_foreign_keys(self):
        self.prepare_region('jtos')
        self.import_release()
        gem = self.unpack / 'ies.ipf/item_gem.ies'
        change_ies_column(gem, 'ClassName', 'Gem_Harness_RegionalFallback', index=1)
        socket = self.unpack / 'xml.ipf/socket_property.xml'
        socket.write_text(socket.read_text().replace('Gem_Harness_Fire', 'Gem_Harness_RegionalFallback'))
        self.parse_release('equipment-v2')
        self.import_release()
        self.assertEqual(Gems.objects.get(item__ids='240').skill.ids, '403')
        with gem.open(newline='') as stream:
            reader = csv.DictReader(stream)
            fields, rows = reader.fieldnames, [row for row in reader if row['ClassID'] != '240']
        with gem.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        xml = ET.parse(socket)
        for element in list(xml.getroot()):
            if element.get('Name') == 'Gem_Harness_RegionalFallback':
                xml.getroot().remove(element)
        xml.write(socket, encoding='utf-8')
        self.parse_release('equipment-v3')
        self.import_release()
        self.assertEqual(Gems.objects.count(), 1)
        self.assertFalse(Items.objects.filter(ids='240').exists())
        self.assertEqual(self.client.get('/items/240').status_code, 404)

    def test_removing_gem_classification_clears_orm_subtype_without_deleting_item(self):
        self.prepare_region()
        self.import_release()
        path = self.release / 'item_type.json'
        types = json.loads(path.read_text())
        types['GEMS'].remove('Gem_Harness_Fire')
        path.write_text(json.dumps(types))
        self.import_release()
        self.assertFalse(Gems.objects.filter(item__ids='240').exists())
        self.assertTrue(Items.objects.filter(ids='240').exists())
        self.assertEqual(self.client.get('/items/240').status_code, 200)

    def test_unlinking_skill_gem_and_unchanged_reimport_restore_current_subtype(self):
        self.prepare_region()
        self.import_release()
        path = self.release / 'items_by_name.json'
        source = json.loads(path.read_text())
        source['Gem_Harness_Fire'].pop('Link_Skill')
        path.write_text(json.dumps(source))
        self.import_release()
        self.assertIsNone(Gems.objects.get(item__ids='240').skill)
        Gems.objects.get(item__ids='240').delete()
        self.import_release()
        self.assertIsNone(Gems.objects.get(item__ids='240').skill)
        self.assertEqual(Gems.objects.count(), 2)
        self.assertEqual(Version.objects.count(), 1)

    def test_bad_gem_skill_reference_is_blocked_before_any_database_query(self):
        self.prepare_region()
        self.import_release()
        snapshot, baseline = self.snapshot(), self.baseline()
        path = self.release / 'items_by_name.json'
        original = path.read_bytes()
        source = json.loads(original)
        source['Gem_Harness_Fire']['Link_Skill'] = 'missing-skill'
        path.write_text(json.dumps(source))
        with self.assertNumQueries(0):
            with self.assertRaisesMessage(CommandError, 'Link_Skill'):
                self.import_release()
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(self.baseline(), baseline)
        path.write_bytes(original)
        self.import_release()
        self.assertEqual(Gems.objects.get(item__ids='240').skill.ids, '400')

    def test_late_gem_import_failure_rolls_back_equipment_gems_version_and_prev_then_retries(self):
        self.prepare_region('twtos')
        self.import_release()
        snapshot, baseline = self.snapshot(), self.baseline()
        change_ies_column(self.unpack / 'ies.ipf/item_goddess_reinforce_560.ies', 'BasicAtk', '8100')
        self.parse_release('equipment-v2')
        original = self.command.importGems

        def fail_after_gems(item_type):
            original(item_type)
            raise RuntimeError('fixture gem import failure')

        with patch.object(self.command, 'importGems', side_effect=fail_after_gems):
            with self.assertRaisesMessage(RuntimeError, 'fixture gem import failure'):
                self.import_release()
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(self.baseline(), baseline)
        self.assertFalse(list(self.release.glob('.import-prev-*')))
        self.import_release()
        self.assertEqual(Equipments.objects.get(item__ids='110').patk, 8100)
        self.assertEqual(Gems.objects.get(item__ids='240').skill.ids, '400')
        self.assertEqual(Version.objects.count(), 2)

    def test_failed_560_material_lua_preserves_public_json_db_and_prev_then_retries(self):
        self.prepare_region('ktest')
        self.import_release()
        snapshot, baseline = self.snapshot(), self.baseline()
        public = {path.name: path.read_bytes() for path in self.release.glob('*.json')}
        source = self.unpack / 'shared.ipf/equipment_calculate.lua'
        original = source.read_bytes()
        source.write_text(original.decode().replace('function setting_lv_material_weapon(', 'function REMOVED_WEAPON('))
        with self.assertRaisesMessage(ValueError, 'Missing goddess 560 material function'):
            self.parse_release('equipment-v2')
        self.assertEqual({path.name: path.read_bytes() for path in self.release.glob('*.json')}, public)
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(self.baseline(), baseline)
        source.write_bytes(original)
        self.parse_release('equipment-v2')
        self.import_release()
        self.assertEqual(Version.objects.count(), 2)

    def rewrite_json(self, name, mutate):
        path = self.release / (name + '.json')
        value = json.loads(path.read_text())
        mutate(value)
        path.write_text(json.dumps(value, ensure_ascii=False))

    def test_auxiliary_only_changes_update_chance_costs_and_keep_item_calculations(self):
        self.prepare_region()
        self.import_release()
        original = list(Equipments.objects.get(item__ids='110').anvil_atk)
        self.rewrite_json('goddess_reinf', lambda data: data['560'][5].update(BasicProp='12345'))
        self.rewrite_json('goddess_reinf_mat', lambda data: data['560']['weapon']['6'].update(
            harness_ore=51, unknown_currency=9))
        self.import_release()
        self.assertEqual(Equipments.objects.get(item__ids='110').anvil_atk, original)
        payload = self.client.get('/items/110').context['enhancement']
        self.assertEqual(payload['steps'][5]['chance'], 12.345)
        self.assertEqual({entry['name']: entry['quantity'] for entry in payload['steps'][5]['materials']},
                         {'Regional Ore': 51, 'Fixture Dust': 12, 'unknown_currency': 9})
        self.assertIsNone(payload['steps'][5]['materials'][-1]['url'])
        self.assertEqual(json.loads((self.release / 'prev/goddess_reinf_mat.json').read_text())['560']['weapon']['6']['harness_ore'], 51)

    def test_source_bonus_changes_and_removed_socket_levels_clear_stale_values(self):
        self.prepare_region()
        self.import_release()
        change_ies_column(self.unpack / 'ies.ipf/item_goddess_reinforce_560.ies', 'AddAtk', '125')
        path = self.unpack / 'xml.ipf/socket_property.xml'
        tree = ET.parse(path)
        gem = tree.getroot().find("Item[@Name='harness_gem']")
        gem.remove(gem.find("Level[@Level='2']"))
        gem.find("Level[@Level='1']").set('PropList_MainOrSubWeapon_Penalty', 'MATK/-7')
        tree.write(str(path), encoding='utf-8')
        self.parse_release('equipment-v2')
        self.import_release()
        self.assertEqual(self.client.get('/items/110').context['enhancement']['attack'][5], 625)
        bonuses = json.loads(Gems.objects.get(item__ids='230').socket_bonuses)
        self.assertEqual(bonuses['Weapon'], [{'Level': 1, 'Stat': 'ADD_ATK', 'Value': 30},
                                             {'Level': 1, 'Stat': 'ADD_MATK', 'Value': -7}])
        self.assertNotContains(self.client.get('/items/230'), '<td>-10</td>')
        self.assertContains(self.client.get('/items/230'), '<td>-7</td>')

    def test_legacy_absent_auxiliary_files_clear_rows_and_omit_unsupported_calculator(self):
        self.prepare_region()
        self.import_release()
        for name in ('goddess_reinf', 'goddess_reinf_mat'):
            (self.release / (name + '.json')).unlink()
        def legacy(data):
            for row in data.values():
                row.pop('GoddessReinforceLevel', None)
                row.pop('GoddessReinforceGroup', None)
                if row['Grade'] == 6:
                    row['AnvilATK'] = row['AnvilDEF'] = []
                for field in ('BonusWeapon', 'BonusSubWeapon', 'BonusBoots', 'BonusGloves', 'BonusTopAndBottom'):
                    for bonus in row.get(field, []):
                        bonus.pop('Level', None)
        self.rewrite_json('items_by_name', legacy)
        self.import_release()
        self.assertFalse(GoddessReinforcement.objects.exists())
        response = self.client.get('/items/110')
        self.assertIsNone(response.context['enhancement'])
        self.assertNotContains(response, 'item-enhancement-data')
        self.assertNotContains(response, 'god_gabija')
        self.assertIsNone(self.client.get('/items/230').context['gem_bonuses'][0]['level'])
        self.assertContains(self.client.get('/items/230'), '—')
        self.parse_release('equipment-v2')
        self.import_release()
        self.assertEqual(GoddessReinforcement.objects.count(), 90)
        self.assertIsNotNone(self.client.get('/items/110').context['enhancement'])

    def test_460_shared_material_wrapper_is_available_to_weapon_and_accessory(self):
        self.prepare_region()
        self.import_release()
        self.rewrite_json('goddess_reinf', lambda data: data.update({'460': data['560']}))
        self.rewrite_json('goddess_reinf_mat', lambda data: data.update({'460': {'armor': data['560']['armor']}}))
        self.rewrite_json('items_by_name', lambda data: [data[name].update(GoddessReinforceLevel=460)
                            for name in ('harness_sword', 'harness_accessory')])
        self.import_release()
        for ident in ('110', '113'):
            payload = self.client.get('/items/' + ident).context['enhancement']
            self.assertEqual({entry['quantity'] for entry in payload['steps'][5]['materials']}, {18, 6})

    def test_real_database_constraint_failure_rolls_back_new_tables_and_gem_bonuses(self):
        self.prepare_region()
        self.import_release()
        snapshot, baseline = self.snapshot(), self.baseline()
        change_ies_column(self.unpack / 'ies.ipf/item_goddess_reinforce_560.ies', 'AddAtk', '120')
        self.parse_release('equipment-v2')
        original = self.command.importGems
        def duplicate_after_writes(item_type):
            original(item_type)
            row = GoddessReinforcement.objects.get(level=560, step=1)
            row.pk = None
            row.save(force_insert=True)
        with patch.object(self.command, 'importGems', side_effect=duplicate_after_writes):
            with self.assertRaises(IntegrityError):
                self.import_release()
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(self.baseline(), baseline)
        self.assertFalse(list(self.release.glob('.import-prev-*')))
        self.import_release()
        self.assertEqual(Equipments.objects.get(item__ids='110').anvil_atk[5], 620)

    def test_invalid_new_data_is_blocked_before_database_queries_and_preserves_state(self):
        self.prepare_region()
        self.import_release()
        snapshot, baseline = self.snapshot(), self.baseline()
        path = self.release / 'goddess_reinf_mat.json'
        original = path.read_bytes()
        self.rewrite_json('goddess_reinf_mat', lambda data: data['560']['weapon']['6'].update(harness_ore=-1))
        with self.assertNumQueries(0):
            with self.assertRaisesMessage(CommandError, 'harness_ore'):
                self.import_release()
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(self.baseline(), baseline)
        path.write_bytes(original)
        self.rewrite_json('items_by_name', lambda data: data['harness_gem']['BonusWeapon'][0].update(Level=0))
        with self.assertNumQueries(0):
            with self.assertRaisesMessage(CommandError, 'BonusWeapon'):
                self.import_release()
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(self.baseline(), baseline)


def regional_roundtrip(region):
    def test(self):
        self.assert_roundtrip(region)
    return test


for region in REGIONS:
    setattr(EquipmentPipelineTests, 'test_source_to_http_' + region, regional_roundtrip(region))
