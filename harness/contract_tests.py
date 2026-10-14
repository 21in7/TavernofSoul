"""Release contracts run before DB queries; valid imports retain rollback safety."""
import json
import copy
from collections import Counter
from contextlib import nullcontext
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase
from django.db import connection, transaction, OperationalError
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

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
from ipfparser import contracts
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
        for name in ('_staged_snapshot', '_snapshot_path', '_previous_path',
                     '_available_skill_names', '_item_ids_by_name', '_reconcile_map_relations'):
            self.assertNotIn(name, self.command.__dict__)

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

    def test_staging_copy_failure_clears_state_and_retry_uses_changed_input(self):
        self.import_release()
        before, baseline = self.database_snapshot(), self.baseline()
        self.publish_changed_release()
        real_copy = importAll.shutil.copy2
        copied = []

        def fail_after_one_copy(source, destination):
            if copied:
                raise OSError('injected staging copy failure')
            copied.append(Path(source).name)
            return real_copy(source, destination)

        with patch.object(importAll.shutil, 'copy2', side_effect=fail_after_one_copy):
            with self.assertNumQueries(0), self.assertRaisesMessage(OSError, 'staging copy failure'):
                self.import_release()
        self.assertEqual(len(copied), 1)
        self.assertEqual(self.database_snapshot(), before)
        self.assertEqual(self.baseline(), baseline)
        self.assert_clean_staging()
        self.edit_json('skills', ('400', 'BasicSP'), 79)
        self.import_release()
        self.assertEqual(Skills.objects.get(ids='400').sp, 79)
        self.assertEqual((self.release / 'prev/skills.json').read_bytes(),
                         (self.release / 'skills.json').read_bytes())
        self.assert_clean_staging()

    def test_validation_version_copy_and_active_snapshot_path_boundaries(self):
        command = self.command
        # Validation on its own never starts a handle-owned cache.
        command._validate_staged_release(self.release)
        self.assertNotIn('_staged_snapshot', command.__dict__)
        command._snapshot_path = str(self.release.absolute())
        version = command._validate_staged_release(self.release)
        version['version'] = 'consumer mutation'
        self.assertEqual(command._staged_snapshot['version'], {'version': 'contract-v1'})
        command._previous_path = str(self.release / 'prev')

        auxiliary = self.release / 'auxiliary.json'
        auxiliary.write_text('{"value": [1]}')
        self.assertEqual(command.importJSON(auxiliary), {'value': [1]})
        auxiliary.write_text('{"value": [2]}')
        self.assertEqual(command.importJSON(auxiliary), {'value': [2]})
        auxiliary.write_text('{"value": Infinity}')
        with self.assertRaisesMessage(CommandError, '[number]'):
            command.importJSON(auxiliary)
        auxiliary.unlink()

        other = self.release.parent / 'direct-input'
        other.mkdir()
        skills_file = other / 'skills.json'
        skills_file.write_text('{"fresh": [1]}')
        self.assertEqual(command.importJSON(skills_file), {'fresh': [1]})
        skills_file.write_text('{"fresh": [2]}')
        self.assertEqual(command.importJSON(skills_file), {'fresh': [2]})
        # Even a consumed filename in the pinned directory must be fresh if
        # the command has moved away from that directory.
        command.base_path = str(other)
        version_file = self.release / 'version.json'
        version_file.write_text('{"version": "fresh-direct-version"}')
        self.assertEqual(command.importJSON(version_file), {'version': 'fresh-direct-version'})
        command.base_path = str(self.release)
        self.import_release()
        self.assertTrue(Version.objects.filter(version='fresh-direct-version').exists())
        self.assert_clean_staging()

    def test_snapshot_api_validates_all_files_once_and_owns_retained_values(self):
        (self.release / 'unresolved_map_links.json').write_text('[]')
        (self.release / 'auxiliary.json').write_text('{"nested": [1, 2]}')
        files = sorted(self.release.glob('*.json'))
        before = {path.name: path.read_bytes() for path in files}
        with patch.object(contracts, 'load_json', wraps=contracts.load_json) as decode:
            first = contracts.load_import_snapshot(self.release)
        self.assertEqual([call.args[0] for call in decode.call_args_list], files)
        expected = set(contracts.REQUIRED_COLLECTIONS) | {'version'}
        expected.update(name for name in contracts.REINFORCEMENT_COLLECTIONS
                        if (self.release / (name + '.json')).exists())
        self.assertEqual(set(first), expected)
        self.assertEqual(contracts.load_release(self.release), first['version'])
        second = contracts.load_import_snapshot(self.release)
        first['items_by_name']['harness_ore']['Name'] = 'mutated in memory'
        first['item_type']['EQUIPMENT'].append('not-an-item')
        with self.assertRaises(ContractError):
            contracts.validate_release(first)
        self.assertEqual(contracts.load_import_snapshot(self.release), second)
        self.assertEqual({path.name: path.read_bytes() for path in files}, before)

    def test_snapshot_api_keeps_strict_diagnostic_order_and_retries_fresh(self):
        earlier, later = (self.release / name for name in ('a-extra.json', 'z-extra.json'))
        earlier.write_text('{"duplicate": 1, "duplicate": 2}')
        later.write_text('{"value": NaN}')
        for loader in (contracts.load_release, contracts.load_import_snapshot):
            with self.subTest(loader=loader.__name__):
                with self.assertRaises(ContractError) as error:
                    loader(self.release)
                self.assertEqual(error.exception.path, str(earlier))
                self.assertEqual(error.exception.code, 'duplicate_key')
        earlier.write_text('{}')
        for loader in (contracts.load_release, contracts.load_import_snapshot):
            with self.assertRaises(ContractError) as error:
                loader(self.release)
            self.assertEqual(error.exception.path, str(later))
            self.assertEqual(error.exception.code, 'number')
        later.write_text('{}')
        diagnostic = self.release / 'unresolved_map_links.json'
        diagnostic.write_text('{}')
        for loader in (contracts.load_release, contracts.load_import_snapshot):
            with self.assertRaises(ContractError) as error:
                loader(self.release)
            self.assertEqual(error.exception.path, 'unresolved_map_links')
        diagnostic.write_text('[]')
        pristine = contracts.load_import_snapshot(self.release)
        version = self.release / 'version.json'
        version.unlink()
        self.assertNotIn('version', contracts.load_import_snapshot(self.release, require_version=False))
        self.assertIsNone(contracts.load_release(self.release, require_version=False))
        for loader in (contracts.load_release, contracts.load_import_snapshot):
            with self.assertRaises(ContractError) as error:
                loader(self.release)
            self.assertEqual((error.exception.path, error.exception.code), ('version.json', 'required'))
        version.write_text(json.dumps(pristine['version']))
        self.assertEqual(contracts.load_import_snapshot(self.release), pristine)

    def test_active_snapshot_copies_mutating_skills_and_reads_direct_and_prev_fresh(self):
        self.import_release()
        skills_file = self.release / 'skills.json'
        skills = json.loads(skills_file.read_text())
        skills['400']['CaptionRatio'] = [1.5, 2.5]
        skills_file.write_text(json.dumps(skills))
        command = importAll.Command()
        command.base_path = str(self.release)
        command._snapshot_path = str(self.release.absolute())
        command._validate_staged_release(self.release)
        command._previous_path = str(self.release / 'prev')
        consumer = command.importJSON(skills_file)
        command.importSkills(consumer, 1)
        self.assertEqual(consumer['400']['CaptionRatio'], [1, 2])
        self.assertEqual(command.importJSON(skills_file), skills)
        self.assertEqual(json.loads(skills_file.read_text()), skills)
        prev = self.release / 'prev/skills.json'
        previous = json.loads(prev.read_text())
        previous['400']['BasicSP'] = 73
        prev.write_text(json.dumps(previous))
        self.assertEqual(command.importJSON(prev), previous)
        prev.write_text('{"duplicate": 1, "duplicate": 2}')
        with self.assertRaisesMessage(CommandError, 'duplicate_key'):
            command.importJSON(prev)
        # A snapshot without an active handle cannot assure a direct call.
        del command._previous_path
        skills['400']['BasicSP'] = 29
        skills_file.write_text(json.dumps(skills))
        self.assertEqual(command.importJSON(skills_file), skills)
        skills_file.write_text('{"bad": NaN}')
        with self.assertRaisesMessage(CommandError, '[number]'):
            command.importJSON(skills_file)
        with self.assertRaises(CommandError):
            command._validate_staged_release(self.release)
        self.assertNotIn('_staged_snapshot', command.__dict__)

    def test_fresh_reads_and_individual_lookups_have_identical_writes_and_prev_bytes(self):
        originals = {path.name: path.read_bytes() for path in self.release.glob('*.json')}

        def individual_ids(model, identifiers):
            result = {}
            for identifier in identifiers:
                try:
                    result[str(identifier)] = model.objects.get(ids=identifier)
                except model.DoesNotExist:
                    pass
            return result

        def trial(fresh):
            directory = self.release.parent / ('fresh-import' if fresh else 'snapshot-import')
            directory.mkdir()
            for name, content in originals.items():
                (directory / name).write_bytes(content)
            command = importAll.Command()
            command.base_path = str(directory)
            observations = []
            # Roll back real ORM effects between the two independent trials.
            with transaction.atomic():
                for phase in ('first', 'repeat', 'changed', 'removed'):
                    if phase == 'changed':
                        for name, key in (('items_by_name', 'harness_ore'), ('skills', '400')):
                            path = directory / (name + '.json')
                            rows = json.loads(path.read_text())
                            clone = copy.deepcopy(rows[key])
                            clone.update({'$ID': '6999', '$ID_NAME': 'Harness_Extra_' + name})
                            rows['Harness_Extra_' + name] = clone
                            rows[key]['Name'] = 'Changed ' + name
                            path.write_text(json.dumps(rows))
                    elif phase == 'removed':
                        for name in ('items_by_name', 'skills'):
                            path = directory / (name + '.json')
                            rows = json.loads(path.read_text())
                            del rows['Harness_Extra_' + name]
                            path.write_text(json.dumps(rows))
                    reads = patch.object(command, 'importJSON', side_effect=contracts.load_json) \
                        if fresh else nullcontext()
                    lookups = patch.object(command, '_prefetch_ids', side_effect=individual_ids) \
                        if fresh else nullcontext()
                    with reads, lookups, CaptureQueriesContext(connection) as queries:
                        call_command(command, update=1)
                    writes = Counter(query['sql'].lstrip().split(None, 1)[0].upper()
                                     for query in queries)
                    writes = {verb: writes[verb] for verb in ('INSERT', 'UPDATE', 'DELETE')}
                    baseline = {path.name: path.read_bytes() for path in (directory / 'prev').iterdir()}
                    self.assertEqual({name: baseline[name] for name in originals},
                                     {name: (directory / name).read_bytes() for name in originals})
                    self.assertEqual(Items.objects.get(id_name='harness_recipe').ids, 'recipe-100')
                    self.assertEqual(Items.objects.filter(ids='6999').exists(), phase == 'changed')
                    self.assertEqual(Skills.objects.filter(ids='6999').exists(), phase == 'changed')
                    self.assertNotIn('_staged_snapshot', command.__dict__)
                    # Compare stable ORM values as well as SQL effects; audit
                    # timestamps and backend allocation of primary keys differ
                    # legitimately between the independent rolled-back trials.
                    state = [
                        list(Items.objects.order_by('ids').values('ids', 'id_name', 'name', 'package_contents')),
                        list(Skills.objects.order_by('ids').values('ids', 'id_name', 'name', 'sp', 'job__ids')),
                        list(Equipments.objects.order_by('item__ids').values('item__ids', 'patk', 'anvil_atk')),
                        list(Item_Recipe_Material.objects.order_by('material__ids').values('material__ids', 'qty')),
                        list(Item_Recipe_Target.objects.order_by('target__ids').values('target__ids')),
                    ]
                    observations.append((writes, baseline, state))
                transaction.set_rollback(True)
            return observations

        optimized, fresh = trial(False), trial(True)
        self.assertEqual(optimized, fresh)
        self.assertEqual(optimized[0][1], optimized[1][1])
        self.assertEqual(optimized[0][2], optimized[1][2])
        self.assertGreater(optimized[0][0]['INSERT'], 0)
        self.assertGreater(optimized[1][0]['UPDATE'], 0)
        self.assertGreater(optimized[2][0]['INSERT'], 0)
        self.assertGreater(optimized[3][0]['DELETE'], 0)


class SkillImportRegressionTests(TransactionTestCase):
    """Count real ORM reads and writes without replacing the persistence layer."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='tavern-skill-orm-')
        self.addCleanup(temporary.cleanup)
        workspace = prepare_combat_workspace(temporary.name)
        db = parse_workspace(workspace, include_combat=True)
        self.command = importAll.Command()
        jobs = db.data['jobs']
        self.command.importJobs({'added': list(jobs.values()) if isinstance(jobs, dict) else jobs,
                                 'changed': [], 'removed': []}, 1)
        self.template = copy.deepcopy(next(row for row in db.data['skills'].values()
                                           if row['Link_Job'] is not None))
        self.job = Jobs.objects.get(ids=str(self.template['Link_Job']))

    def row(self, ident=9000, job=None):
        row = copy.deepcopy(self.template)
        row.update({'$ID': ident, '$ID_NAME': 'Harness_ORM_' + str(ident),
                    'Link_Job': self.job.ids if job is None else job})
        return row

    @staticmethod
    def count(queries, verb, model=None):
        table = connection.ops.quote_name(model._meta.db_table).lower() if model else None
        return sum(query['sql'].lstrip().upper().startswith(verb) and
                   (table is None or table in query['sql'].lower()) for query in queries)

    def test_growing_skill_and_job_inputs_bound_selects_and_keep_every_row_save(self):
        read_counts = []
        first_read_counts = []
        real_save = Skills.save
        saved = []

        def record_save(instance, *args, **kwargs):
            saved.append(str(instance.ids))
            return real_save(instance, *args, **kwargs)

        for size in (1, 32):
            with self.subTest(size=size):
                Skills.objects.all().delete()
                for index in range(1, size):
                    job_id = str(8000 + index)
                    if not Jobs.objects.filter(ids=job_id).exists():
                        clone = Jobs.objects.get(pk=self.job.pk)
                        clone.pk = None
                        clone.ids = job_id
                        clone.id_name = 'Harness_ORM_Job_' + job_id
                        clone.save()
                rows = {str(9000 + index): self.row(9000 + index,
                        int(self.job.ids) if index == 0 else 8000 + index)
                        for index in range(size)}
                saved.clear()
                with patch.object(Skills, 'save', record_save), CaptureQueriesContext(connection) as first:
                    self.command.importSkills(copy.deepcopy(rows), 1)
                first_counts = (self.count(first, 'SELECT', Skills), self.count(first, 'SELECT', Jobs))
                first_read_counts.append(first_counts)
                self.assertLessEqual(first_counts[0], 2)
                self.assertLessEqual(first_counts[1], 1)
                self.assertEqual(saved, list(rows))
                self.assertEqual(self.count(first, 'INSERT', Skills), size)
                self.assertEqual(self.count(first, 'UPDATE', Skills), 0)
                self.assertEqual(self.count(first, 'DELETE', Skills), 0)
                before = {row.ids: (row.pk, row.created) for row in Skills.objects.all()}
                # A distant persisted timestamp proves auto_now still runs on
                # unchanged rows without sleeps or assumptions about clock precision.
                Skills.objects.update(updated=timezone.now().replace(year=2000))
                saved.clear()
                for row in rows.values():
                    row['$ID'] = str(row['$ID'])
                    row['Link_Job'] = str(row['Link_Job'])
                with patch.object(Skills, 'save', record_save), CaptureQueriesContext(connection) as queries:
                    self.command.importSkills(copy.deepcopy(rows), 1)
                counts = (self.count(queries, 'SELECT', Skills), self.count(queries, 'SELECT', Jobs))
                read_counts.append(counts)
                self.assertLessEqual(counts[0], 2)
                self.assertLessEqual(counts[1], 1)
                self.assertEqual(saved, list(rows))
                self.assertEqual(self.count(queries, 'UPDATE', Skills), size)
                self.assertEqual(self.count(queries, 'INSERT', Skills), 0)
                self.assertEqual(self.count(queries, 'DELETE', Skills), 0)
                for row in Skills.objects.all():
                    self.assertEqual((row.pk, row.created), before[row.ids])
                    self.assertIsNotNone(row.created)
                    self.assertGreater(row.updated.year, 2000)
        self.assertEqual(read_counts[0], read_counts[1])
        self.assertEqual(first_read_counts[0], first_read_counts[1])

    def test_creation_update_and_deletion_preserve_row_identity_and_canonical_ids(self):
        rows = {'9000': self.row(), '9001': self.row('9001')}
        with CaptureQueriesContext(connection) as first:
            self.command.importSkills(copy.deepcopy(rows), 1)
        self.assertEqual(self.count(first, 'INSERT', Skills), 2)
        before = Skills.objects.get(ids='9000')
        changed = self.row('9000')
        changed['BasicSP'] = 71
        with CaptureQueriesContext(connection) as later:
            self.command.importSkills({'9000': changed}, 1)
        saved = Skills.objects.get(ids='9000')
        self.assertEqual((saved.pk, saved.created), (before.pk, before.created))
        self.assertEqual(saved.sp, 71)
        self.assertFalse(Skills.objects.filter(ids='9001').exists())
        self.assertEqual(self.count(later, 'UPDATE', Skills), 1)
        self.assertEqual(self.count(later, 'DELETE', Skills), 1)

    def test_update_zero_skips_existing_saves_but_keeps_original_deletion_behavior(self):
        self.command.importSkills({'9000': self.row()}, 1)
        skipped = self.row('9000', 'missing-job-that-must-not-be-resolved')
        skipped['BasicSP'] = 88
        saved = []
        real_save = Skills.save

        def record_save(instance, *args, **kwargs):
            saved.append(str(instance.ids))
            return real_save(instance, *args, **kwargs)

        with patch.object(Skills, 'save', record_save), CaptureQueriesContext(connection) as queries:
            self.command.importSkills({'9000': skipped, '9001': self.row(9001)}, 0)
        self.assertEqual(saved, ['9001'])
        self.assertEqual(self.count(queries, 'UPDATE', Skills), 0)
        self.assertEqual(self.count(queries, 'INSERT', Skills), 1)
        self.assertEqual(self.count(queries, 'DELETE', Skills), 1)
        self.assertFalse(Skills.objects.filter(ids='9000').exists())
        self.assertTrue(Skills.objects.filter(ids='9001').exists())

    def test_missing_job_raises_without_saving_and_retry_reads_fresh_rows(self):
        row = self.row(job=8999)
        with CaptureQueriesContext(connection) as queries, self.assertRaises(Jobs.DoesNotExist):
            self.command.importSkills({'9000': row}, 1)
        self.assertEqual(self.count(queries, 'INSERT', Skills), 0)
        self.assertFalse(Skills.objects.exists())
        clone = Jobs.objects.get(pk=self.job.pk)
        clone.pk = None
        clone.ids = '8999'
        clone.id_name = 'Harness_Retry_Job'
        clone.save()
        self.command.importSkills({'9000': row}, 1)
        self.assertEqual(Skills.objects.get(ids='9000').job_id, clone.pk)

    def test_unlinked_skills_are_not_created_and_existing_unlinked_rows_are_deleted(self):
        self.command.importSkills({'9000': self.row()}, 1)
        retired, new_unlinked = self.row(), self.row(9001)
        retired['Link_Job'] = new_unlinked['Link_Job'] = None
        with CaptureQueriesContext(connection) as queries:
            self.command.importSkills({'9000': retired, '9001': new_unlinked}, 1)
        self.assertFalse(Skills.objects.exists())
        self.assertEqual(self.count(queries, 'INSERT', Skills), 0)
        self.assertEqual(self.count(queries, 'UPDATE', Skills), 0)
        self.assertEqual(self.count(queries, 'DELETE', Skills), 1)

    def test_prefetch_database_errors_propagate_without_partial_skill_writes(self):
        with patch.object(Skills.objects, 'filter', side_effect=OperationalError('fixture prefetch failure')):
            with self.assertNumQueries(0), self.assertRaisesMessage(OperationalError, 'fixture prefetch failure'):
                self.command.importSkills({'9000': self.row()}, 1)
        self.assertFalse(Skills.objects.exists())

    def test_ambiguous_skill_and_job_ids_raise_at_consumer_before_any_save(self):
        # Each subcase rolls back duplicate legacy rows, including the two
        # update modes, so no case can contaminate the next ORM lookup.
        for target in (Skills, Jobs):
            for update in (0, 1):
                with self.subTest(target=target.__name__, update=update), transaction.atomic():
                    if target is Skills:
                        self.command.importSkills({'9000': self.row()}, 1)
                        original = Skills.objects.get(ids='9000')
                    else:
                        original = Jobs.objects.get(pk=self.job.pk)
                    original.pk = None
                    original.save()
                    with patch.object(target.objects, 'get', wraps=target.objects.get) as get:
                        with CaptureQueriesContext(connection) as queries:
                            with self.assertRaises(target.MultipleObjectsReturned):
                                self.command.importSkills({'9000': self.row()}, update)
                    get.assert_called_once_with(ids=9000 if target is Skills else self.job.ids)
                    self.assertEqual(self.count(queries, 'INSERT', Skills), 0)
                    self.assertEqual(self.count(queries, 'UPDATE', Skills), 0)
                    transaction.set_rollback(True)
