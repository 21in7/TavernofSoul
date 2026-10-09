"""Exercise actual parser/exporter, importer, ORM, URLs, views, and templates."""
import json
from pathlib import Path
import tempfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase

from DB import ToS_DB
from items import resolve_package_contents
from Dashboard.models import Version
from Items.models import (Equipment_Bonus, Equipments, Items,
                          Item_Recipe_Material, Item_Recipe_Target)
from ipfparser.management.commands.importAll import Command
from harness.parser_fixture import parse_workspace, prepare_workspace

FIXTURE = Path(__file__).parent / 'fixtures' / 'minimal_release.json'
VERSION = {'version': 'harness-v1_001001.ipf'}


class PipelineTests(TransactionTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='tavern-pipeline-')
        self.addCleanup(temporary.cleanup)
        self.release = Path(temporary.name) / 'json'
        self.release.mkdir()
        data = json.loads(FIXTURE.read_text(encoding='utf-8'))
        # The parser shares item objects between its two indexes.
        data['items'] = {name: row for name, row in data['items_by_name'].items()}
        self.db = ToS_DB.__new__(ToS_DB)
        self.db.data = data
        self.db.BASE_PATH_OUTPUT = str(self.release)
        resolve_package_contents(self.db)
        self.db.export(version_payload=VERSION)
        self.command = Command()
        self.command.base_path = str(self.release)

    def import_release(self):
        # Command instance pins base_path to the temporary exported release.
        call_command(self.command, update=1)

    def test_parse_export_import_and_http_queries(self):
        self.import_release()
        self.assertEqual(Items.objects.count(), 3)
        self.assertEqual(Items.objects.get(id_name='harness_ore').ids, '100')
        self.assertEqual(Items.objects.get(id_name='harness_recipe').ids, 'recipe-100')
        self.assertEqual(Version.objects.get().version, VERSION['version'])
        material = Item_Recipe_Material.objects.get()
        self.assertEqual((material.material.id_name, material.qty), ('harness_ore', 2))
        self.assertEqual(Item_Recipe_Target.objects.get().target.id_name, 'harness_ore')
        package = Items.objects.get(id_name='harness_package')
        self.assertEqual(json.loads(package.package_contents)['items'], [
            {'item': 'harness_ore', 'name': 'Harness Ore', 'count': 5, 'options': []},
        ])
        response = self.client.get('/items/', {'q': 'Harness', 'order': 'ids-asc'})
        self.assertEqual(response.context['item_len'], 3)
        self.assertContains(response, 'Harness Package')
        self.assertContains(response, 'Harness Recipe')
        response = self.client.get('/items/recipe-100')
        self.assertContains(response, 'Harness Recipe')
        self.assertContains(response, 'Harness Ore')
        self.assertContains(self.client.get('/items/101'), 'Harness Package')
        self.assertEqual(self.client.get('/items/does-not-exist').status_code, 404)

    def test_reimport_is_idempotent(self):
        self.import_release()
        before = list(Items.objects.order_by('pk').values())
        self.import_release()
        self.assertEqual(list(Items.objects.order_by('pk').values()), before)
        self.assertEqual(Item_Recipe_Material.objects.count(), 1)
        self.assertEqual(Item_Recipe_Target.objects.count(), 1)
        self.assertEqual(Version.objects.count(), 1)
        self.assertEqual(json.loads((self.release / 'prev' / 'version.json').read_text()), VERSION)
        self.assertFalse(list(self.release.glob('.import-prev-*')))

    def test_bad_reference_preserves_database_and_baseline_then_retries(self):
        self.import_release()
        baseline = {path.name: path.read_bytes() for path in (self.release / 'prev').iterdir()}
        data = self.db.data
        data['items_by_name']['harness_ore']['Name'] = 'Changed Ore'
        self.db.export(version_payload={'version': 'harness-v2_001001.ipf'})
        path = self.release / 'items_by_name.json'
        invalid = json.loads(path.read_text())
        invalid['harness_recipe']['Link_Target'] = 'missing_target'
        path.write_text(json.dumps(invalid))
        with self.assertRaises(CommandError):
            self.import_release()
        self.assertEqual(Items.objects.get(id_name='harness_ore').name, 'Harness Ore')
        self.assertEqual(Version.objects.get().version, VERSION['version'])
        self.assertEqual(Item_Recipe_Target.objects.get().target.id_name, 'harness_ore')
        self.assertEqual({path.name: path.read_bytes() for path in (self.release / 'prev').iterdir()}, baseline)
        self.assertFalse(list(self.release.glob('.import-prev-*')))
        data['items_by_name']['harness_recipe']['Link_Target'] = 'harness_ore'
        self.db.export(version_payload={'version': 'harness-v2_001001.ipf'})
        self.import_release()
        self.assertEqual(Items.objects.get(id_name='harness_ore').name, 'Changed Ore')
        self.assertTrue(Version.objects.filter(version='harness-v2_001001.ipf').exists())


class SourcePipelineTests(TransactionTestCase):
    """Keep source interpretation and the published Django data in one check."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='tavern-source-pipeline-')
        self.addCleanup(temporary.cleanup)
        self.workspace = prepare_workspace(temporary.name)
        self.db = parse_workspace(self.workspace)
        self.release = Path(self.db.BASE_PATH_OUTPUT)
        self.command = Command()
        self.command.base_path = str(self.release)

    def import_release(self):
        call_command(self.command, update=1)

    def database_snapshot(self):
        models = (Items, Equipments, Equipment_Bonus,
                  Item_Recipe_Material, Item_Recipe_Target)
        return [list(model.objects.order_by('pk').values()) for model in models]

    def test_ies_translation_lua_recipes_packages_reach_database_and_http(self):
        self.import_release()
        self.assertEqual(Items.objects.count(), 7)
        ore = Items.objects.get(id_name='harness_ore')
        self.assertEqual((ore.ids, ore.name, ore.descriptions),
                         ('100', 'Fixture Ore', 'Translated ore description'))
        self.assertEqual((ore.weight, ore.cooldown, ore.grade, ore.tradability),
                         (0.25, 2, 1, 'TFFT'))
        self.assertEqual(Items.objects.get(id_name='harness_recipe').ids, 'recipe-100')
        self.assertEqual(list(Item_Recipe_Material.objects.order_by('material__id_name')
                              .values_list('material__id_name', 'qty')),
                         [('harness_dust', 3), ('harness_ore', 2)])
        self.assertEqual(Item_Recipe_Target.objects.get().target.id_name, 'harness_sword')
        sword = Equipments.objects.get(item__id_name='harness_sword')
        self.assertEqual((sword.patk, sword.patk_max, sword.level, sword.durability),
                         (140, 147, 20, 25))
        self.assertEqual(sword.anvil_atk, list(range(7, 281, 7)))
        self.assertEqual(sword.transcend_price, list(range(3, 31, 3)))
        bonus = Equipment_Bonus.objects.get(equipment=sword)
        self.assertEqual((bonus.bonus_stat, bonus.bonus_val), ('STR', '2'))
        package = json.loads(Items.objects.get(id_name='harness_package').package_contents)
        self.assertEqual(package['items'], [
            {'item': 'harness_ore', 'name': 'Fixture Ore', 'count': 5,
             'options': [['ItemExp', '60']]},
        ])
        mixed = json.loads(Items.objects.get(id_name='harness_mixed').package_contents)
        self.assertEqual(mixed['unresolved'], [
            {'item': 'expired_material', 'count': 2, 'options': [['ItemExp', '7']]},
        ])
        random = json.loads(Items.objects.get(id_name='harness_random').package_contents)
        self.assertTrue(random['random'])
        self.assertEqual([item['item'] for item in random['alternatives'][0]],
                         ['harness_ore', 'harness_dust'])
        self.assertFalse(Items.objects.filter(id_name='expired_material').exists())
        self.assertEqual(Version.objects.get().version, 'parser-fixture-v1_001001.ipf')

        search = self.client.get('/items/', {'q': 'Fixture', 'order': 'ids-asc'})
        self.assertEqual(search.context['item_len'], 7)
        self.assertContains(search, 'Recipe - Fixture Sword')
        self.assertContains(search, 'Fixture Package')
        recipe = self.client.get('/items/recipe-100')
        for name in ('Recipe - Fixture Sword', 'Fixture Sword', 'Fixture Ore', 'Fixture Dust'):
            self.assertContains(recipe, name)
        self.assertContains(self.client.get('/items/100'), 'Translated ore description')
        sword_page = self.client.get('/items/110')
        self.assertContains(sword_page, '<span id = "patk">140</span>')
        self.assertContains(sword_page, '<span id = "patk_max">147</span>')
        self.assertContains(self.client.get('/items/201'), 'Fixture Mixed Package')

    def test_reparse_is_idempotent_and_changed_lua_constant_updates_existing_equipment(self):
        self.import_release()
        before = self.database_snapshot()
        parse_workspace(self.workspace)
        self.import_release()
        self.assertEqual(self.database_snapshot(), before)
        self.assertEqual(Version.objects.count(), 1)

        constants = self.workspace / 'itos_unpack/ies.ipf/sharedconst.ies'
        constants.write_text(constants.read_text().replace('HARNESS_ATK_STEP,7,YES',
                                                         'HARNESS_ATK_STEP,9,YES'))
        parse_workspace(self.workspace, 'parser-fixture-v2_001001.ipf')
        self.import_release()
        self.assertEqual(Items.objects.count(), 7)
        self.assertEqual(Equipments.objects.count(), 1)
        sword = Equipments.objects.get(item__id_name='harness_sword')
        self.assertEqual((sword.patk, sword.patk_max, sword.anvil_atk[-1]), (180, 189, 360))
        self.assertEqual(Item_Recipe_Material.objects.count(), 2)
        self.assertEqual(Equipment_Bonus.objects.count(), 1)
        self.assertEqual(Version.objects.count(), 2)
        self.assertEqual(Version.objects.latest('created').version, 'parser-fixture-v2_001001.ipf')
        self.assertEqual(json.loads((self.release / 'prev/version.json').read_text()),
                         {'version': 'parser-fixture-v2_001001.ipf'})
        self.assertContains(self.client.get('/items/110'),
                            '<span id = "patk">180</span>')

    def test_source_failure_keeps_release_and_served_data_then_retries(self):
        self.import_release()
        before = self.database_snapshot()
        published = {path.name: path.read_bytes() for path in self.release.glob('*.json')}
        baseline = {path.name: path.read_bytes() for path in (self.release / 'prev').iterdir()}
        lua_file = self.workspace / 'itos_unpack/shared.ipf/item_calculate.lua'
        original = lua_file.read_text()
        lua_file.write_text('function GET_COMMON_PROP_LIST()\nthis is not lua\nend\n')
        with self.assertRaises(KeyError):
            parse_workspace(self.workspace, 'parser-fixture-v2_001001.ipf')
        self.assertEqual({path.name: path.read_bytes() for path in self.release.glob('*.json')},
                         published)
        self.assertEqual({path.name: path.read_bytes() for path in (self.release / 'prev').iterdir()},
                         baseline)
        self.assertEqual(self.database_snapshot(), before)
        self.assertEqual(Version.objects.get().version, 'parser-fixture-v1_001001.ipf')
        self.assertContains(self.client.get('/items/110'),
                            '<span id = "patk">140</span>')

        lua_file.write_text(original)
        parse_workspace(self.workspace, 'parser-fixture-v2_001001.ipf')
        self.import_release()
        self.assertEqual(Version.objects.count(), 2)
        self.assertEqual(Version.objects.latest('created').version, 'parser-fixture-v2_001001.ipf')
        self.assertEqual(Items.objects.count(), 7)
        self.assertEqual(Equipments.objects.count(), 1)
        self.assertEqual(Item_Recipe_Target.objects.count(), 1)
