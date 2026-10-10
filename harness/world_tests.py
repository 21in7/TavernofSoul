"""Map/attribute/buff sources → public JSON → actual importer, ORM and HTTP."""
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase

from Attributes.models import Attributes
from Buffs.models import Buffs
from Dashboard.models import Version
from Items.models import Items
from Jobs.models import Jobs
from Maps.models import Maps, Map_Item, Map_NPC, Map_Item_Spawn
from Monsters.models import Monsters
from Skills.models import Skills
from ipfparser.management.commands.importAll import Command
from harness.parser_fixture import change_ies_column, parse_workspace, prepare_world_workspace

V1, V2 = 'world-fixture-v1', 'world-fixture-v2'


class WorldPipelineTests(TransactionTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='tavern-world-pipeline-')
        self.addCleanup(temporary.cleanup)
        self.workspace = prepare_world_workspace(temporary.name)
        self.db = self.parse_release(V1)
        self.release = Path(self.db.BASE_PATH_OUTPUT)
        self.command = Command()
        self.command.base_path = str(self.release)

    def parse_release(self, version):
        return parse_workspace(self.workspace, version, include_world=True)

    def import_release(self):
        call_command(self.command, update=1)

    def database_snapshot(self, ignore_updated=False):
        models = (Items, Jobs, Skills, Monsters, Maps, Map_Item, Map_NPC, Map_Item_Spawn,
                  Attributes, Attributes.job.through, Attributes.skill.through, Buffs, Version)
        records = [list(model.objects.order_by('pk').values()) for model in models]
        if ignore_updated:
            for rows in records:
                for row in rows:
                    row.pop('updated', None)
        return records

    def snapshot_files(self, directory):
        return {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}

    def test_real_sources_reach_relations_units_search_and_detail_pages(self):
        self.import_release()
        self.assertEqual(Maps.objects.count(), 3)
        field = Maps.objects.get(ids='900')
        self.assertEqual((field.name, field.level, field.has_cm, field.has_warp, field.map_link),
                         ('Fixture Field', 20, True, True, ['901', '902']))
        self.assertEqual(list(Map_Item.objects.order_by('map__ids', 'item__ids')
                              .values_list('map__ids', 'item__ids', 'chance')), [
            ('900', '100', 12.5), ('900', '101', 15), ('900', '110', 5),
            ('901', '101', 1), ('902', '100', 12.5), ('902', '101', 12.5), ('902', '110', 37.5)])
        wolf_spawn = Map_NPC.objects.get(monster__ids='500')
        self.assertEqual((wolf_spawn.population, wolf_spawn.time_respawn, wolf_spawn.positions),
                         (3, 2.5, ['60', '20', '40', '30']))
        self.assertEqual(Map_NPC.objects.get(monster__ids='800').time_respawn, 10)
        self.assertEqual(Map_Item_Spawn.objects.get().positions, ['0', '0'])
        self.assertEqual(Map_Item_Spawn.objects.get().time_respawn, 3)
        self.assertFalse(Map_Item.objects.exclude(qty_min=0, qty_max=0).exists())
        self.assertEqual(Attributes.objects.count(), 4)
        self.assertEqual(list(Attributes.objects.get(ids='921').skill.values_list('id_name', flat=True)), ['Harness_Fire'])
        self.assertEqual(list(Attributes.objects.get(ids='922').job.values_list('ids', flat=True)), ['300'])
        self.assertEqual(Attributes.objects.get(ids='924').skill.count(), 0)
        self.assertEqual(Buffs.objects.count(), 4)
        buff = Buffs.objects.get(ids='910')
        self.assertEqual((buff.applytime, buff.overbuff, buff.userremove, buff.duration()), (3500, 2, True, '3 s'))
        self.assertIsNone(Buffs.objects.get(ids='911').group1)

        response = self.client.get('/maps/', {'q': 'Fixture'})
        self.assertEqual(response.context['item_len'], 3)
        response = self.client.get('/maps/900')
        for name in ('Fixture Field', 'Fixture Ore', 'Fixture Dust', 'Fixture Wolf', 'Fixture Guide'):
            self.assertContains(response, name)
        self.assertContains(response, '12.5 %')
        self.assertEqual(len(response.context['npc']), 2)
        self.assertEqual(len(response.context['itemSpawn']), 1)
        response = self.client.get('/items/100')
        self.assertEqual({row.map.ids for row in response.context['mapDrop']}, {'900', '902'})
        self.assertContains(response, 'Fixture Field')
        response = self.client.get('/attributes/', {'q': 'Fixture', 'job': '300'})
        self.assertEqual(response.context['item_len'], 3)
        self.assertContains(self.client.get('/attributes/921'), 'Fixture Fire')
        self.assertContains(self.client.get('/attributes/922'), 'Fixture Job Boost')
        response = self.client.get('/buffs/', {'q': 'Fixture'})
        self.assertEqual(response.context['item_len'], 4)
        response = self.client.get('/buffs/910')
        for value in ('Fixture Shield Buff', 'A shield', 'Second line', '3 s'):
            self.assertContains(response, value)
        for url in ('/maps/missing', '/attributes/999', '/buffs/999'):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_repeated_source_and_import_preserve_data_and_relation_counts(self):
        self.import_release()
        before = self.database_snapshot(ignore_updated=True)
        files = self.snapshot_files(self.release)
        self.parse_release(V1)
        self.assertEqual(self.snapshot_files(self.release), files)
        self.import_release()
        self.assertEqual(self.database_snapshot(ignore_updated=True), before)
        self.assertEqual((Map_Item.objects.count(), Map_NPC.objects.count(), Map_Item_Spawn.objects.count()), (7, 2, 1))
        self.assertEqual(Attributes.skill.through.objects.count(), 2)
        self.assertEqual(Version.objects.count(), 1)
        self.assertFalse(list(self.release.glob('.import-prev-*')))

    def test_changed_sources_update_units_and_remove_old_relations(self):
        self.import_release()
        unpack = self.workspace / 'itos_unpack'
        change_ies_column(unpack / 'ies_drop.ipf/zonedrop/ZoneDropItemList_harness_field.ies', 'DropRatio', '2500')
        change_ies_column(unpack / 'ies_drop.ipf/dropgroup/HARNESS_GROUP.IES', 'ItemClassName', 'expired_new', index=1)
        change_ies_column(unpack / 'ies_drop.ipf/zonedrop/ZONEDROPITEMLIST_F_HARNESS_CAVE.IES', 'ItemClassName', '')
        gentype = unpack / 'ies_mongen.ipf/GENTYPE_harness_field.IES'
        change_ies_column(gentype, 'ClassType', 'harness_boar', index=0)
        change_ies_column(gentype, 'ClassType', 'harness_boar', index=1)
        change_ies_column(gentype, 'ArgStr2', '', index=3)
        ability = unpack / 'ies_ability.ipf/Ability_HarnessMage.IES'
        change_ies_column(ability, 'MaxLevel', '6', index=0)
        change_ies_column(ability, 'UnlockArgStr', '', index=1)
        change_ies_column(ability, 'MaxLevel', '-1', index=2)
        change_ies_column(unpack / 'ies.ipf/buff_hardskill.ies', 'ApplyTime', '8000')
        change_ies_column(unpack / 'ies.ipf/buff_hardskill.ies', 'UserRemove', 'NO')
        change_ies_column(unpack / 'ies.ipf/buff_contents.ies', 'ClassName', 'Common_RemovedContent')
        self.parse_release(V2)
        self.import_release()
        self.assertEqual(Map_Item.objects.get(map__ids='900', item__ids='100').chance, 25)
        self.assertFalse(Map_Item.objects.filter(map__ids='900', item__ids='110').exists())
        self.assertFalse(Map_Item.objects.filter(map__ids='901').exists())
        self.assertFalse(Map_NPC.objects.filter(monster__ids='500').exists())
        self.assertEqual(Map_NPC.objects.get(monster__ids='501').population, 3)
        self.assertEqual(Map_NPC.objects.get(monster__ids='800').population, 2)
        self.assertEqual(Map_Item_Spawn.objects.count(), 0)
        self.assertEqual(Attributes.objects.get(ids='920').max_lv, 6)
        fallback = Attributes.objects.get(ids='921')
        self.assertEqual(fallback.skill.count(), 0)
        self.assertEqual(list(fallback.job.values_list('ids', flat=True)), ['300'])
        self.assertFalse(Attributes.objects.filter(ids='924').exists())
        buff = Buffs.objects.get(ids='910')
        self.assertEqual((buff.applytime, buff.userremove, buff.duration()), (8000, False, '8 s'))
        self.assertFalse(Buffs.objects.filter(ids='914').exists())
        response = self.client.get('/maps/900')
        self.assertContains(response, 'Fixture Boar')
        self.assertNotContains(response, 'Fixture Wolf')
        self.assertEqual(response.context['itemSpawn'], [])
        self.assertNotContains(self.client.get('/attributes/921'), 'Fixture Fire')
        self.assertContains(self.client.get('/buffs/910'), '8 s')
        self.assertEqual(Version.objects.latest('created').version, V2)

    def test_unresolved_map_links_export_import_and_clear_when_source_restored(self):
        path = self.workspace / 'itos_unpack/ies.ipf/map.ies'
        original_source = path.read_bytes()
        clean = 'harness_cave/id_unknownsanctuary_harness'
        raw = 'harness_cave/missing/900/id_unknownsanctuary_harness/missing/900'
        expected = [
            {'Map': '900', 'MapClassName': 'harness_field', 'Token': token,
             'Raw': raw, 'SourceFile': 'ies.ipf/map.ies',
             'SourceField': 'PhysicalLinkZone', 'SourceRow': 2}
            for token in ('missing', '900')
        ]
        diagnostics = self.release / 'unresolved_map_links.json'
        try:
            # Establish a clean baseline; the shared fixture itself has diagnostics.
            change_ies_column(path, 'PhysicalLinkZone', clean)
            clean_db = self.parse_release(V1)
            self.assertEqual(clean_db.data['unresolved_map_links'], [])
            self.assertEqual(json.loads(diagnostics.read_text(encoding='utf-8')), [])
            self.import_release()
            try:
                change_ies_column(path, 'PhysicalLinkZone', raw)
                changed = self.parse_release(V2)
                self.assertEqual(changed.data['unresolved_map_links'], expected)
                self.assertEqual(json.loads(diagnostics.read_text(encoding='utf-8')), expected)
                self.assertEqual(changed.data['maps']['900']['Link_Maps'], ['901', '902'])
                self.assertEqual(changed.data['maps']['900']['Link_Maps_Floors'], ['901'])
                self.assertEqual(set(changed.data['maps']), {'900', '901', '902'})
                self.import_release()
                self.assertEqual(Maps.objects.get(ids='900').map_link, ['901', '902'])
                self.assertEqual(list(Maps.objects.order_by('ids').values_list('ids', flat=True)),
                                 ['900', '901', '902'])
                self.assertEqual(Maps.objects.get(ids='901').map_link, ['900'])
                self.assertEqual(Maps.objects.get(ids='902').map_link, ['900'])
                self.assertEqual(self.client.get('/maps/', {'q': 'Fixture'}).context['item_len'], 3)
                for map_id, name in (('900', 'Fixture Field'), ('901', 'Fixture Cave'),
                                     ('902', 'Fixture Sanctuary')):
                    self.assertContains(self.client.get('/maps/' + map_id), name)
                self.assertEqual(self.client.get('/maps/missing').status_code, 404)
                self.assertEqual(Version.objects.latest('created').version, V2)
                before = self.database_snapshot(ignore_updated=True)
                files = self.snapshot_files(self.release)
                repeated = self.parse_release(V2)
                self.assertEqual(repeated.data['unresolved_map_links'], expected)
                self.assertEqual(repeated.data['maps']['900']['Link_Maps'], ['901', '902'])
                self.assertEqual(self.snapshot_files(self.release), files)
                self.import_release()
                self.assertEqual(self.database_snapshot(ignore_updated=True), before)
                self.assertEqual((Map_Item.objects.count(), Map_NPC.objects.count(),
                                  Map_Item_Spawn.objects.count()), (7, 2, 1))
                self.assertEqual(Version.objects.count(), 2)
                self.assertFalse(list(self.release.glob('.import-prev-*')))
            finally:
                change_ies_column(path, 'PhysicalLinkZone', clean)
            restored = self.parse_release(V2)
            self.assertEqual(restored.data['unresolved_map_links'], [])
            self.assertEqual(json.loads(diagnostics.read_text(encoding='utf-8')), [])
            self.assertEqual(restored.data['maps']['900']['Link_Maps'], ['901', '902'])
            self.assertEqual(restored.data['maps']['900']['Link_Maps_Floors'], ['901'])
            self.import_release()
            self.assertEqual(self.database_snapshot(ignore_updated=True), before)
            self.assertContains(self.client.get('/maps/900'), 'Fixture Field')
        finally:
            path.write_bytes(original_source)

    def test_source_errors_preserve_publication_database_and_baseline_then_retry(self):
        self.import_release()
        before = self.database_snapshot()
        files, baseline = self.snapshot_files(self.release), self.snapshot_files(self.release / 'prev')
        cases = [
            ('ies_ability.ipf/Ability_HarnessMage.IES', 'MaxLevel', 'bad', 0, ValueError),
            ('ies.ipf/buff_hardskill.ies', 'ApplyTime', 'bad', 0, ValueError),
        ]
        for filename, column, value, index, error in cases:
            with self.subTest(filename=filename):
                path = self.workspace / 'itos_unpack' / filename
                original = change_ies_column(path, column, value, index)
                try:
                    with self.assertRaises(error):
                        self.parse_release(V2)
                    self.assertEqual(self.snapshot_files(self.release), files)
                    self.assertEqual(self.snapshot_files(self.release / 'prev'), baseline)
                    self.assertEqual(self.database_snapshot(), before)
                finally:
                    change_ies_column(path, column, original, index)
        self.parse_release(V2)
        self.import_release()
        self.assertEqual(Version.objects.count(), 2)
        self.assertContains(self.client.get('/maps/900'), 'Fixture Field')

    def test_later_import_failure_rolls_back_world_changes_and_can_retry(self):
        self.import_release()
        before, baseline = self.database_snapshot(), self.snapshot_files(self.release / 'prev')
        unpack = self.workspace / 'itos_unpack'
        change_ies_column(unpack / 'ies_drop.ipf/zonedrop/ZoneDropItemList_harness_field.ies', 'DropRatio', '2500')
        change_ies_column(unpack / 'ies_ability.ipf/Ability_HarnessMage.IES', 'MaxLevel', '6')
        change_ies_column(unpack / 'ies.ipf/buff_hardskill.ies', 'ApplyTime', '8000')
        self.parse_release(V2)
        def fail_after_earlier_writes(*args):
            self.assertEqual(Map_Item.objects.get(map__ids='900', item__ids='100').chance, 25)
            self.assertEqual(Attributes.objects.get(ids='920').max_lv, 6)
            raise CommandError('injected world import failure')
        with patch.object(self.command, 'importBuff', side_effect=fail_after_earlier_writes):
            with self.assertRaisesMessage(CommandError, 'injected world import failure'):
                self.import_release()
        self.assertEqual(self.database_snapshot(), before)
        self.assertEqual(self.snapshot_files(self.release / 'prev'), baseline)
        self.assertFalse(list(self.release.glob('.import-prev-*')))
        self.assertContains(self.client.get('/buffs/910'), '3 s')
        self.import_release()
        self.assertEqual(Buffs.objects.get(ids='910').applytime, 8000)
        self.assertEqual(Map_Item.objects.get(map__ids='900', item__ids='100').chance, 25)
        self.assertTrue(Version.objects.filter(version=V2).exists())
