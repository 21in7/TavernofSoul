"""Regional sources and additional item types reach real ORM and HTTP endpoints."""
import csv
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.test import TransactionTestCase, override_settings

from Attributes.models import Attributes
from Buffs.models import Buffs
from Dashboard.models import Version
from Items.models import (Cards, Collections, Equipment_Bonus, Equipments, Items,
                          Item_Collection_Bonus, Item_Collection_Material)
from Jobs.models import Jobs
from Maps.models import Maps, Map_Item
from Skills.models import Skills
from harness.fixture_inputs import REGIONAL_FIXTURE, REGIONS
from harness.parser_fixture import change_ies_column, parse_workspace, prepare_regional_workspace
from ipfparser.management.commands.importAll import Command

EXPECTED = json.loads((REGIONAL_FIXTURE / 'expected_regions.json').read_text(encoding='utf-8'))


class RegionalPipelineTests(TransactionTestCase):
    def prepare_region(self, region):
        temporary = tempfile.TemporaryDirectory(prefix='tavern-regional-pipeline-')
        self.addCleanup(temporary.cleanup)
        override = override_settings(REGION=region)
        override.enable()
        self.addCleanup(override.disable)
        self.region = region
        self.workspace = prepare_regional_workspace(temporary.name, region)
        self.db = self.parse_release('regional-v1')
        self.release = Path(self.db.BASE_PATH_OUTPUT)
        self.command = Command()
        self.command.base_path = str(self.release)

    def parse_release(self, version):
        return parse_workspace(self.workspace, version, region=self.region, include_regional=True)

    def import_release(self):
        call_command(self.command, update=1)

    def baseline(self):
        return {path.name: path.read_bytes() for path in (self.release / 'prev').iterdir()}

    def snapshot(self, ignore_updated=False):
        models = (Items, Equipments, Equipment_Bonus, Cards, Collections,
                  Item_Collection_Bonus, Item_Collection_Material, Jobs, Skills,
                  Maps, Map_Item, Attributes, Buffs, Version)
        records = [list(model.objects.order_by('pk').values()) for model in models]
        if ignore_updated:
            for rows in records:
                for row in rows:
                    row.pop('updated', None)
        return records

    def assert_regional_roundtrip(self, region):
        self.prepare_region(region)
        self.import_release()
        expected = EXPECTED[region]
        names = expected['names']
        self.assertEqual(Items.objects.count(), 11)
        self.assertEqual(Items.objects.get(ids='100').name, names['ore'])
        self.assertEqual(Items.objects.get(ids='recipe-100').id_name, 'harness_recipe')
        sword = Equipments.objects.get(item__id_name='harness_sword')
        self.assertEqual((sword.patk, sword.patk_max), (expected['sword_min'], expected['sword_max']))
        staff = Equipments.objects.get(item__id_name='harness_staff')
        self.assertEqual((staff.matk, staff.requiredClass), (expected['staff_matk'], 'FFFFT'))
        self.assertEqual(Equipment_Bonus.objects.get(equipment=staff).bonus_val, '4')
        armor = Equipments.objects.get(item__id_name='harness_armor')
        self.assertEqual((armor.pdef, armor.mdef, armor.durability, armor.level, armor.requiredClass),
                         (expected['armor_def'], expected['armor_mdef'], -1, 35, 'FTFTF'))
        self.assertEqual(armor.anvil_def, list(range(expected['def_step'], expected['def_step'] * 40 + 1,
                                                   expected['def_step'])))
        self.assertEqual(Equipment_Bonus.objects.get(equipment=armor).bonus_val, '-3')
        card = Cards.objects.get()
        self.assertEqual((card.item.name, card.type_card, card.icon),
                         (names['card'], 'ATK', 'icon_harness_card_tooltip'))
        self.assertEqual(list(Item_Collection_Material.objects.order_by('material__ids')
                              .values_list('material__id_name', flat=True)), ['harness_ore', 'harness_dust'])
        self.assertEqual(list(Item_Collection_Bonus.objects.order_by('bonus_stat')
                              .values_list('bonus_stat', 'bonus_val')), [('Maximum HP', '25'), ('STR', '3')])
        self.assertEqual(Skills.objects.get(ids='400').descriptions, expected['fire_description'])
        support = Skills.objects.get(ids='403')
        self.assertEqual((support.name, support.descriptions, support.effect, support.icon, support.job.ids),
                         (names['support'], expected['fallback_description'], expected['fallback_effect'],
                          'icon_regional_ktos', '300'))
        self.assertEqual(Maps.objects.get(ids='900').name, names['map'])
        self.assertEqual(Buffs.objects.get(ids='910').name, names['buff'])
        self.assertEqual(Attributes.objects.get(ids='920').name, names['attribute'])
        self.assertEqual(Map_Item.objects.get(map__ids='900', item__ids='100').chance, 12.5)
        package = json.loads(Items.objects.get(id_name='harness_package').package_contents)
        self.assertEqual(package['items'][0]['name'], names['ore'])

        for ident, kind in (('100', 'ore'), ('111', 'staff'), ('112', 'armor'),
                            ('210', 'card'), ('220', 'collection')):
            self.assertContains(self.client.get('/items/' + ident), names[kind])
        collection = self.client.get('/items/220')
        self.assertContains(collection, names['ore'])
        self.assertContains(collection, 'Fixture Dust')
        self.assertContains(self.client.get('/items/100'), names['collection'])
        self.assertContains(self.client.get('/items/210'), '/static/icons/icon_harness_card_tooltip.jpg')
        for path, key in (('/skills/400', 'fire'), ('/skills/403', 'support'),
                          ('/maps/900', 'map'), ('/attributes/920', 'attribute'), ('/buffs/910', 'buff')):
            self.assertContains(self.client.get(path), names[key])
        response = self.client.get('/items/', {'q': names['armor'], 'class': '1'})
        self.assertEqual(response.context['item_len'], 1)
        response = self.client.get('/items/', {'q': names['armor'], 'class': '4'})
        self.assertEqual(response.context['item_len'], 0)
        response = self.client.get('/skills/', {'q': names['fire'], 'job': '300'})
        self.assertEqual(response.context['item_len'], 1)
        self.assertContains(response, names['fire'])

        snapshot = self.snapshot(ignore_updated=True)
        baseline = self.baseline()
        self.parse_release('regional-v1')
        self.import_release()
        self.assertEqual(self.snapshot(ignore_updated=True), snapshot)
        self.assertEqual(self.baseline(), baseline)
        self.assertEqual(Version.objects.count(), 1)

    def test_source_changes_update_magic_defense_card_and_collection_then_remove_card(self):
        self.prepare_region('jtos')
        self.import_release()
        unpack = self.workspace / 'jtos_unpack'
        change_ies_column(unpack / 'ies.ipf/sharedconst.ies', 'Value', '13', index=2)
        change_ies_column(unpack / 'ies.ipf/item_equip.ies', 'UseLv', '28', index=1)
        change_ies_column(unpack / 'ies.ipf/item.ies', 'CardGroupName', 'DEF', index=5)
        change_ies_column(unpack / 'ies.ipf/collection.ies', 'ItemName_2', '')
        change_ies_column(unpack / 'ies.ipf/collection.ies', 'AccPropList', 'MHP_BM/100')
        self.parse_release('regional-v2')
        self.import_release()
        self.assertEqual(Equipments.objects.get(item__id_name='harness_staff').matk, 728)
        armor = Equipments.objects.get(item__id_name='harness_armor')
        self.assertEqual((armor.pdef, armor.mdef, armor.anvil_def[0], armor.anvil_def[-1]), (390, 195, 26, 1040))
        self.assertEqual(Cards.objects.get().type_card, 'DEF')
        self.assertEqual(list(Item_Collection_Material.objects.values_list('material__id_name', flat=True)),
                         ['harness_ore'])
        self.assertEqual(Item_Collection_Bonus.objects.get(bonus_stat='Maximum HP').bonus_val, '100')
        self.assertNotContains(self.client.get('/items/220'), 'Fixture Dust')
        self.assertEqual(Version.objects.count(), 2)
        path = unpack / 'ies.ipf/item.ies'
        with path.open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            fields, rows = reader.fieldnames, [row for row in reader if row['ClassName'] != 'harness_card']
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        self.parse_release('regional-v3')
        self.import_release()
        self.assertFalse(Items.objects.filter(ids='210').exists())
        self.assertEqual(Cards.objects.count(), 0)
        self.assertEqual(self.client.get('/items/210').status_code, 404)

    def test_failed_regional_lua_preserves_published_json_db_and_prev_then_retries(self):
        self.prepare_region('twtos')
        self.import_release()
        snapshot, baseline = self.snapshot(), self.baseline()
        public = {path.name: path.read_bytes() for path in self.release.glob('*.json')}
        source = self.workspace / 'twtos_unpack/shared.ipf/item_calculate.lua'
        original = source.read_text()
        source.write_text(original.replace('function SCR_HARNESS_REFRESH_STAFF(', 'function REMOVED_STAFF('))
        change_ies_column(self.workspace / 'twtos_unpack/ies.ipf/item.ies', 'Name', '更新原石')
        with self.assertRaisesMessage(ValueError, 'Equipment refresh failed for harness_staff'):
            self.parse_release('regional-v2')
        self.assertEqual({path.name: path.read_bytes() for path in self.release.glob('*.json')}, public)
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(self.baseline(), baseline)
        source.write_text(original)
        self.parse_release('regional-v2')
        self.import_release()
        self.assertEqual(Items.objects.get(ids='100').name, '更新原石')
        self.assertEqual(Version.objects.count(), 2)

    def test_late_collection_import_error_rolls_back_prior_regional_writes_and_retries(self):
        self.prepare_region('ktos')
        self.import_release()
        snapshot, baseline = self.snapshot(), self.baseline()
        unpack = self.workspace / 'ktos_unpack'
        change_ies_column(unpack / 'ies.ipf/item.ies', 'Name', '변경 원석')
        change_ies_column(unpack / 'ies.ipf/item.ies', 'CardGroupName', 'DEF', index=5)
        change_ies_column(unpack / 'ies.ipf/collection.ies', 'AccPropList', 'MHP_BM/100')
        self.parse_release('regional-v2')
        with patch.object(self.command, 'makeCollection', side_effect=RuntimeError('fixture collection failure')):
            with self.assertRaisesMessage(RuntimeError, 'fixture collection failure'):
                self.import_release()
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(self.baseline(), baseline)
        self.assertFalse(list(self.release.glob('.import-prev-*')))
        self.import_release()
        self.assertEqual(Items.objects.get(ids='100').name, '변경 원석')
        self.assertEqual(Cards.objects.get().type_card, 'DEF')
        self.assertEqual(Item_Collection_Bonus.objects.get(bonus_stat='Maximum HP').bonus_val, '100')
        self.assertEqual(Version.objects.count(), 2)


def regional_roundtrip(region):
    def test(self):
        self.assert_regional_roundtrip(region)
    return test


# Separate discoverable tests make every selected region visible in failures and counts.
for region in REGIONS:
    setattr(RegionalPipelineTests, 'test_source_to_http_' + region, regional_roundtrip(region))
