"""Actual skill/monster/drop source → JSON → ORM/HTTP with migrations."""
import json
import copy
from pathlib import Path
import tempfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase
from django.db import connection, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor

from Dashboard.models import Version
from Items.models import Items
from Jobs.models import Jobs
from Monsters.models import Item_Monster, Monsters, Skill_Monster
from Skills.models import Skills
from ipfparser.management.commands.importAll import Command
from harness.parser_fixture import (change_ies_column, parse_workspace,
                                    prepare_combat_workspace)

V1 = 'combat-fixture-v1_001001.ipf'
V2 = 'combat-fixture-v2_001001.ipf'


class CombatPipelineTests(TransactionTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='tavern-combat-pipeline-')
        self.addCleanup(temporary.cleanup)
        self.workspace = prepare_combat_workspace(temporary.name)
        db = self.parse_release(V1)
        self.release = Path(db.BASE_PATH_OUTPUT)
        self.command = Command()
        self.command.base_path = str(self.release)

    def parse_release(self, version):
        return parse_workspace(self.workspace, version, include_combat=True)

    def import_release(self):
        call_command(self.command, update=1)

    def database_snapshot(self):
        models = (Items, Jobs, Skills, Monsters, Item_Monster, Skill_Monster,
                  Skill_Monster.monsters.through, Version)
        return [list(model.objects.order_by('pk').values()) for model in models]

    def test_legacy_duplicate_migration_keeps_latest_then_updates_without_duplicates(self):
        self.import_release()
        old = [('Monsters', '0009_delete_buff_skill_monster')]
        new = [('Monsters', '0010_unique_monster_item_drop')]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor.migrate(old)
        historical = executor.loader.project_state(old).apps.get_model('Monsters', 'Item_Monster')
        drop = Item_Monster.objects.get(monster__ids='500')
        historical.objects.create(monster_id=drop.monster_id, item_id=drop.item_id,
                                   chance=50, qty_min=5, qty_max=10)
        historical.objects.create(monster_id=drop.monster_id, item_id=drop.item_id,
                                   chance=99, qty_min=10, qty_max=20)
        winner = historical.objects.latest('pk').pk
        MigrationExecutor(connection).migrate(new)
        self.assertEqual(Item_Monster.objects.count(), 2)
        survivor = Item_Monster.objects.get(monster_id=drop.monster_id, item_id=drop.item_id)
        self.assertEqual((survivor.pk, survivor.chance), (winner, 99))
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Item_Monster.objects.create(monster_id=drop.monster_id, item_id=drop.item_id)
        row = json.loads((self.release / 'item_monster.json').read_text())[0]
        changes = {'added': [], 'removed': [], 'changed': [row]}
        self.command.importItemMonster(changes, 1)
        self.command.importItemMonster(changes, 1)
        survivor.refresh_from_db()
        self.assertEqual((survivor.pk, survivor.chance, survivor.qty_min, survivor.qty_max),
                         (winner, 12.5, 1, 3))
        self.assertEqual(Item_Monster.objects.count(), 2)

    def test_metadata_only_drop_change_and_repeated_import_keep_one_relation(self):
        self.import_release()
        path = self.release / 'item_monster.json'
        rows = json.loads(path.read_text())
        variant = copy.deepcopy(rows[0])
        variant.update(InputVersion='new-input-version')
        rows[0] = variant
        path.write_text(json.dumps(rows))
        self.import_release()
        self.import_release()
        drop = Item_Monster.objects.get(monster__ids='500')
        self.assertEqual((drop.chance, drop.qty_min, drop.qty_max), (12.5, 1, 3))
        self.assertEqual(Item_Monster.objects.count(), 2)
        # Invalid drop updates must fail before any database query.
        rows[0]['Chance'] = 101
        path.write_text(json.dumps(rows))
        before = self.database_snapshot()
        with self.assertNumQueries(0), self.assertRaisesMessage(CommandError, 'Chance [range]'):
            self.import_release()
        self.assertEqual(self.database_snapshot(), before)

    def test_source_calculations_and_drop_relations_reach_database_and_http(self):
        self.import_release()
        self.assertEqual((Jobs.objects.count(), Skills.objects.count(), Monsters.objects.count()),
                         (1, 1, 2))
        skill = Skills.objects.get(ids='400')
        self.assertEqual((skill.job.ids, skill.cooldown, skill.sp, skill.overheat, skill.is_riding),
                         ('300', 6000, 15, 2, True))
        self.assertEqual(skill.sfr, list(range(100, 221, 10)))
        self.assertEqual(skill.captionratio1, [40] * 13)
        self.assertEqual(skill.cooldown_lv, list(range(6000, 4799, -100)))
        wolf = Monsters.objects.get(ids='500')
        self.assertEqual((wolf.hp, wolf.patk_min, wolf.patk_max, wolf.exp, wolf.exp_class),
                         (500, 30, 35, 1000, 300))
        boar = Monsters.objects.get(ids='501')
        self.assertEqual((boar.hp, boar.patk_min, boar.patk_max, boar.exp, boar.exp_class),
                         (3333, 75, 95, 1234, 432))
        drop = Item_Monster.objects.get(monster=wolf)
        self.assertEqual((drop.item.ids, drop.chance, drop.qty_min, drop.qty_max),
                         ('100', 12.5, 1, 3))
        self.assertEqual(Item_Monster.objects.count(), 2)
        self.assertFalse(Items.objects.filter(id_name='expired_drop').exists())
        self.assertEqual(json.loads((self.release / 'build_provenance.json').read_text())['item_monster'],
                         {'source_region': 'itos', 'input_version': 'drop-fixture-v1',
                          'fallback_reason': None})

        search = self.client.get('/skills/', {'q': 'Fixture', 'job': '300'})
        self.assertEqual(search.context['item_len'], 1)
        self.assertContains(search, 'Fixture Fire')
        detail = self.client.get('/skills/400')
        self.assertContains(detail, 'Fixture Fire')
        self.assertEqual(detail.context['item'].cooldown, 6.0)
        self.assertEqual(detail.context['item'].captionratio1[3], 40)
        self.assertEqual(self.client.get('/skills/999').status_code, 404)
        search = self.client.get('/monsters/', {'q': 'Fixture', 'order': 'ids-asc'})
        self.assertEqual(search.context['item_len'], 2)
        self.assertContains(search, 'Fixture Wolf')
        detail = self.client.get('/monsters/500')
        self.assertContains(detail, 'Fixture Ore')
        self.assertContains(detail, '12.5 %')
        self.assertEqual((detail.context['item'].patk_min, detail.context['item'].patk_max), (30, 35))
        self.assertContains(self.client.get('/items/100'), 'Fixture Wolf')

    def test_monster_skill_hit_count_and_changed_membership_are_updated(self):
        self.import_release()
        attack = Skill_Monster.objects.get(ids='600')
        self.assertEqual((attack.hit_count, attack.cooldown, attack.sfr, attack.aar), (2, 3000, 80, 5))
        self.assertEqual(list(attack.monsters.order_by('ids').values_list('ids', flat=True)),
                         ['500', '501'])
        detail = self.client.get('/monsters/500')
        self.assertContains(detail, 'Fixture Claw')
        self.assertContains(detail, 'x 2')

        change_ies_column(self.workspace / 'itos_unpack/ies.ipf/monster.ies',
                          'SkillType', 'HarnessOther', index=1)
        change_ies_column(self.workspace / 'itos_unpack/ies.ipf/skill_mon.ies', 'SklHitCount', '3')
        self.parse_release(V2)
        self.import_release()
        attack.refresh_from_db()
        self.assertEqual(attack.hit_count, 3)
        self.assertEqual(list(attack.monsters.values_list('ids', flat=True)), ['500'])
        self.assertContains(self.client.get('/monsters/500'), 'x 3')
        self.assertNotContains(self.client.get('/monsters/501'), 'Fixture Claw')
        self.assertEqual(Skill_Monster.objects.count(), 1)

    def test_repeat_import_and_source_updates_keep_ids_and_remove_obsolete_drops(self):
        self.import_release()
        keys = (Skills.objects.get().pk, Monsters.objects.get(ids='500').pk,
                Item_Monster.objects.get(monster__ids='500').pk)
        self.parse_release(V1)
        self.import_release()
        self.assertEqual((Skills.objects.count(), Item_Monster.objects.count(),
                          Skill_Monster.monsters.through.objects.count(), Version.objects.count()),
                         (1, 2, 2, 1))
        unpack = self.workspace / 'itos_unpack'
        change_ies_column(unpack / 'ies.ipf/skill.ies', 'SklFactor', '200')
        change_ies_column(unpack / 'ies.ipf/monster.ies', 'Level', '12')
        change_ies_column(unpack / 'ies_drop.ipf/HARNESS_WOLF.IES', 'DropRatio', '2500')
        (self.workspace / 'downloader/revision.csv').write_text('itos,drop-fixture-v2\n')
        self.parse_release(V2)
        self.import_release()
        self.assertEqual(Skills.objects.get().sfr[3], 230)
        self.assertEqual(Monsters.objects.get(ids='500').hp, 600)
        self.assertEqual(Item_Monster.objects.get(monster__ids='500').chance, 25)
        self.assertEqual((Skills.objects.get().pk, Monsters.objects.get(ids='500').pk,
                          Item_Monster.objects.get(monster__ids='500').pk), keys)
        self.assertEqual(Version.objects.count(), 2)
        self.assertEqual(json.loads((self.release / 'item_monster.json').read_text())[0]['InputVersion'],
                         'drop-fixture-v2')

        change_ies_column(unpack / 'ies_drop.ipf/HARNESS_WOLF.IES', 'ItemClassName', 'removed_item')
        self.parse_release('combat-fixture-v3_001001.ipf')
        self.import_release()
        self.assertEqual(Item_Monster.objects.count(), 1)
        self.assertFalse(Item_Monster.objects.filter(monster__ids='500').exists())
        self.assertNotContains(self.client.get('/monsters/500'), 'Fixture Ore')
        self.assertEqual(len(json.loads((self.release / 'unresolved_drops.json').read_text())), 2)

    def test_bad_monster_skill_reference_preserves_entire_import_then_retries(self):
        self.import_release()
        before = self.database_snapshot()
        baseline = {path.name: path.read_bytes() for path in (self.release / 'prev').iterdir()}
        change_ies_column(self.workspace / 'itos_unpack/ies.ipf/skill.ies', 'SklFactor', '200')
        change_ies_column(self.workspace / 'itos_unpack/ies.ipf/monster.ies', 'Level', '12')
        self.parse_release(V2)
        path = self.release / 'skill_mon.json'
        data = json.loads(path.read_text())
        data['600']['Monster'].append(999)
        path.write_text(json.dumps(data))
        with self.assertRaisesMessage(CommandError, 'target 999 not found in release'):
            self.import_release()
        self.assertEqual(self.database_snapshot(), before)
        self.assertEqual({path.name: path.read_bytes() for path in (self.release / 'prev').iterdir()}, baseline)
        self.assertContains(self.client.get('/monsters/500'), 'Fixture Claw')
        self.assertEqual(self.client.get('/skills/400').context['item'].sfr[3], 130)

        self.parse_release(V2)
        self.import_release()
        self.assertEqual(Skills.objects.get().sfr[3], 230)
        self.assertEqual(Monsters.objects.get(ids='500').hp, 600)
        self.assertEqual(Skill_Monster.monsters.through.objects.count(), 2)
        self.assertEqual(Version.objects.latest('created').version, V2)
