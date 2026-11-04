"""Storage, search and rollback behavior that needs the actual MySQL backend."""
from pathlib import Path
import tempfile

from django.core.management import call_command
from django.db import connection, DataError, IntegrityError, transaction
from django.test import TestCase, TransactionTestCase

from Dashboard.models import Version
from Items.models import Equipments, Items, Item_Recipe_Material, Item_Type
from Maps.models import Map_NPC
from Skills.models import Skills
from harness.mysql_config import TEST_DATABASE_NAME
from harness.parser_fixture import parse_workspace, prepare_world_workspace
from ipfparser.management.commands.importAll import Command
from ipfparser.item_types import get_or_create_item_type


class MySQLSchemaTests(TestCase):
    def test_real_migrations_create_utf8mb4_innodb_tables_in_the_test_schema(self):
        self.assertEqual(connection.vendor, 'mysql')
        with connection.cursor() as cursor:
            cursor.execute('SELECT DATABASE(), @@SESSION.sql_mode')
            database, mode = cursor.fetchone()
            self.assertEqual(database, TEST_DATABASE_NAME)
            self.assertIn('STRICT_TRANS_TABLES', mode.split(','))
            cursor.execute('SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME '
                           'FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = DATABASE()')
            self.assertEqual(cursor.fetchone(), ('utf8mb4', 'utf8mb4_unicode_ci'))
            cursor.execute('SELECT TABLE_NAME, ENGINE, TABLE_COLLATION '
                           'FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()')
            tables = cursor.fetchall()
        self.assertIn('Items_items', {name for name, _, _ in tables})
        self.assertIn('django_migrations', {name for name, _, _ in tables})
        self.assertTrue(all(engine == 'InnoDB' and collation == 'utf8mb4_unicode_ci'
                            for _, engine, collation in tables), tables)

    def test_binary_item_type_lookup_preserves_pairs_under_existing_unicode_ci_collation(self):
        self.assertEqual(connection.vendor, 'mysql')
        with connection.cursor() as cursor:
            cursor.execute('SELECT COLLATION_NAME FROM information_schema.COLUMNS '
                           'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s',
                           [Item_Type._meta.db_table, 'name'])
            self.assertEqual(cursor.fetchone(), ('utf8mb4_unicode_ci',))
        expected, cache = {}, {}
        for name in ('Blade', 'blade', 'Blade ', 'Caf\u00e9', 'Cafe\u0301'):
            for flag in (False, True):
                row, created = get_or_create_item_type(name, flag, cache)
                self.assertTrue(created, (name, flag))
                self.assertEqual((row.name, row.is_equipment), (name, flag))
                expected[(name, flag)] = row.pk
        self.assertEqual(len(set(expected.values())), 10)
        # Establish the backend ambiguity that a name__exact-only lookup misses.
        for name, count in (('Blade', 3), ('Caf\u00e9', 2)):
            self.assertEqual(Item_Type.objects.filter(name__exact=name, is_equipment=False).count(), count)
        before = list(Item_Type.objects.order_by('pk').values_list('pk', 'name', 'is_equipment'))
        for cache_arg in (None, {}, cache):
            for (name, flag), pk in expected.items():
                row, created = get_or_create_item_type(name, flag, cache_arg)
                self.assertFalse(created)
                row.refresh_from_db()
                self.assertEqual((row.pk, row.name, row.is_equipment), (pk, name, flag))
        self.assertEqual(list(Item_Type.objects.order_by('pk').values_list(
            'pk', 'name', 'is_equipment')), before)
        for flag in (False, True):
            Item_Type.objects.create(name='Blade', is_equipment=flag)
        duplicates = list(Item_Type.objects.order_by('pk').values_list('pk', 'name', 'is_equipment'))
        for cache_arg in (None, {}, {}):
            for flag in (False, True):
                row, created = get_or_create_item_type('Blade', flag, cache_arg)
                self.assertFalse(created)
                self.assertEqual(row.pk, expected[('Blade', flag)])
        self.assertEqual(list(Item_Type.objects.order_by('pk').values_list(
            'pk', 'name', 'is_equipment')), duplicates)


class MySQLPipelineTests(TransactionTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='tavern-mysql-pipeline-')
        self.addCleanup(temporary.cleanup)
        self.workspace = prepare_world_workspace(temporary.name)
        self.db = parse_workspace(self.workspace, 'mysql-v1', include_world=True)
        self.release = Path(self.db.BASE_PATH_OUTPUT)
        self.command = Command()
        self.command.base_path = str(self.release)

    def import_release(self):
        call_command(self.command, update=1)

    def baseline(self):
        return {path.name: path.read_bytes() for path in (self.release / 'prev').iterdir()}

    def snapshot(self):
        return [list(model.objects.order_by('pk').values())
                for model in (Items, Equipments, Skills, Map_NPC, Version)]

    def test_successful_import_keeps_byte_distinct_type_pairs_and_reuses_them(self):
        expected = {}
        names = ('Blade', 'blade', 'Blade ', 'Caf\u00e9', 'Cafe\u0301')
        for name in names:
            self.db.data['items_by_name']['harness_sword'].update(Type=name, TypeEquipment=name)
            self.db.export(version_payload={'version': 'mysql-type-pairs'})
            self.import_release()
            self.assertEqual(Items.objects.get(id_name='harness_sword').type, name)
            self.assertEqual(Equipments.objects.get(item__id_name='harness_sword').type_equipment, name)
            for flag in (False, True):
                matches = [(pk, stored_name, stored_flag) for pk, stored_name, stored_flag in
                           Item_Type.objects.values_list('pk', 'name', 'is_equipment')
                           if (stored_name, stored_flag) == (name, flag)]
                self.assertEqual(len(matches), 1)
                expected[(name, flag)] = matches[0][0]
            for (stored_name, flag), pk in expected.items():
                row, created = get_or_create_item_type(stored_name, flag, {})
                self.assertFalse(created)
                self.assertEqual(row.pk, pk)
        before = list(Item_Type.objects.order_by('pk').values())
        # Force another changed-item import instead of relying on an empty diff.
        self.db.data['items_by_name']['harness_sword']['Name'] = 'Repeated MySQL pair'
        self.db.export(version_payload={'version': 'mysql-type-pairs'})
        self.import_release()
        self.assertEqual(list(Item_Type.objects.order_by('pk').values()), before)
        self.assertEqual(Version.objects.count(), 1)
        self.assertEqual((self.release / 'prev/items_by_name.json').read_bytes(),
                         (self.release / 'items_by_name.json').read_bytes())
        self.assertFalse(list(self.release.glob('.import-prev-*')))

    def test_korean_emoji_and_case_insensitive_search_round_trip(self):
        self.db.data['items_by_name']['harness_ore']['Name'] = '하네스 Café 🧙'
        self.db.export(version_payload={'version': 'mysql-unicode'})
        self.import_release()
        self.assertEqual(Items.objects.get(ids='100').name, '하네스 Café 🧙')
        for query in ('하네스', '🧙', 'CAFÉ', 'cafe'):
            response = self.client.get('/items/', {'q': query})
            self.assertEqual(response.context['item_len'], 1)
            self.assertContains(response, '하네스 Café 🧙')
        self.assertContains(self.client.get('/items/100'), '하네스 Café 🧙')

    def test_class_filter_executes_mysql_regex_in_the_actual_search_view(self):
        self.import_release()
        equipment = Equipments.objects.get(item__id_name='harness_sword')
        equipment.requiredClass = 'TFTFF'
        equipment.save(update_fields=['requiredClass'])
        for selected, count in (('0', 1), ('1', 0), ('2', 1), ('3', 0), ('4', 0)):
            response = self.client.get('/items/', {'q': 'Fixture', 'class': selected})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['item_len'], count)
            if count:
                self.assertContains(response, 'Fixture Sword')

    def test_listcharfield_storage_membership_null_and_empty_values(self):
        self.import_release()
        skill = Skills.objects.get(ids='400')
        self.assertEqual(skill.sfr, list(range(100, 221, 10)))
        self.assertEqual(list(Skills.objects.filter(sfr__contains=110).values_list('ids', flat=True)), ['400'])
        self.assertFalse(Skills.objects.filter(sfr__contains=10).exists())
        equipment = Equipments.objects.get(item__id_name='harness_sword')
        self.assertEqual(equipment.anvil_atk, list(range(7, 281, 7)))
        self.assertEqual(equipment.transcend_price, list(range(3, 31, 3)))
        self.assertEqual(Map_NPC.objects.get(monster__ids='500').positions, ['60', '20', '40', '30'])
        skill.captionratio2, skill.captionratio3 = [], None
        skill.save(update_fields=['captionratio2', 'captionratio3'])
        skill.refresh_from_db()
        self.assertEqual(skill.captionratio2, [])
        self.assertIsNone(skill.captionratio3)
        with connection.cursor() as cursor:
            cursor.execute('SELECT sfr, captionratio2, captionratio3 FROM Skills_skills WHERE id = %s',
                           [skill.pk])
            stored = cursor.fetchone()
        self.assertEqual(stored, (','.join(str(value) for value in range(100, 221, 10)), '', None))

    def test_equipment_price_array_exceeding_legacy_410_chars_round_trips(self):
        prices = [2147483647] * 41
        self.assertGreater(len(','.join(map(str, prices))), 410)
        self.db.data['items_by_name']['harness_sword']['AnvilPrice'] = prices
        self.db.export(version_payload={'version': 'mysql-long-price-array'})
        self.import_release()
        self.assertEqual(Equipments.objects.get(item__id_name='harness_sword').anvil_price, prices)

    def test_foreign_key_error_rolls_back_prior_writes(self):
        self.import_release()
        ore = Items.objects.get(ids='100')
        relation = Item_Recipe_Material.objects.get(material=ore)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Items.objects.filter(pk=ore.pk).update(name='Should roll back')
            relation.material_id = 99999999
            relation.save(update_fields=['material'])
        ore.refresh_from_db()
        relation.refresh_from_db()
        self.assertEqual(ore.name, 'Fixture Ore')
        self.assertEqual(relation.material_id, ore.pk)

    def test_strict_list_storage_error_preserves_db_version_and_prev_then_retries(self):
        self.import_release()
        snapshot, baseline = self.snapshot(), self.baseline()
        self.db.data['items_by_name']['harness_ore']['Name'] = 'Changed Ore'
        # Valid numeric JSON, but its comma-separated storage exceeds VARCHAR(220).
        self.db.data['skills']['400']['sfr'] = [1234567890] * 30
        self.db.export(version_payload={'version': 'mysql-v2'})
        with self.assertRaises(DataError) as failure:
            self.import_release()
        self.assertEqual(failure.exception.args[0], 1406)
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(self.baseline(), baseline)
        self.assertFalse(Version.objects.filter(version='mysql-v2').exists())
        self.assertFalse(list(self.release.glob('.import-prev-*')))
        self.db.data['skills']['400']['sfr'] = list(range(100, 221, 10))
        self.db.export(version_payload={'version': 'mysql-v2'})
        self.import_release()
        self.assertEqual(Items.objects.get(ids='100').name, 'Changed Ore')
        self.assertEqual(Skills.objects.get(ids='400').sfr, list(range(100, 221, 10)))
        self.assertEqual(Version.objects.count(), 2)
        self.assertNotEqual(self.baseline(), baseline)
