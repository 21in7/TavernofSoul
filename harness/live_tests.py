"""Separate real-source regression gate: snapshot -> parser -> SQLite -> HTTP/JS."""
import json
import os
from pathlib import Path
import tempfile

from django.core.management import call_command
from django.test import TransactionTestCase, override_settings

from Items.models import Items, Equipments, Gems, GoddessReinforcement
from Dashboard.models import Version
from ipfparser.management.commands.importAll import Command
from harness.browser_calculator import run_calculator
from harness.parser_fixture import change_ies_column
from harness.live_fixture import FIXTURE, prepare_workspace, parse_workspace

EXPECTED = json.loads((FIXTURE / 'expected.json').read_text())


class RealSourceTests(TransactionTestCase):
    region = 'itos'

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='tavern-real-sample-')
        self.addCleanup(self.temporary.cleanup)
        override = override_settings(REGION=self.region)
        override.enable()
        self.addCleanup(override.disable)
        fixture = Path(os.environ.get('HARNESS_LIVE_FIXTURE', str(FIXTURE)))
        self.workspace = prepare_workspace(self.temporary.name, self.region, fixture)
        self.db = parse_workspace(self.workspace, self.region)
        self.release = Path(self.db.BASE_PATH_OUTPUT)
        self.command = Command()
        self.command.base_path = str(self.release)
        call_command(self.command, update=1)

    def test_equipment_and_gems_roundtrip_to_orm_and_real_views(self):
        self.assertEqual(Equipments.objects.count(), 6)
        self.assertEqual(Gems.objects.count(), 2)
        for ident, expected in EXPECTED['equipment'].items():
            equipment = Equipments.objects.get(item__ids=ident)
            for key in ('patk', 'patk_max', 'matk', 'pdef', 'mdef', 'level'):
                self.assertEqual(getattr(equipment, key), expected[key], (ident, key))
            bonus = getattr(equipment, 'anvil_' + expected['bonus'])
            self.assertEqual((len(bonus), bonus[5], bonus[29]), (30, expected['step6'], expected['step30']))
            response = self.client.get('/items/' + ident)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, equipment.item.name)
        sword = Items.objects.get(ids='11107087')
        self.assertEqual(sword.name, EXPECTED['sword_names'][self.region])
        self.assertEqual(self.client.get('/items/', {'q': sword.name, 'grade': 6}).context['item_len'], 1)
        bonuses = json.loads(Gems.objects.get(item__ids='643501').socket_bonuses)['Weapon']
        self.assertEqual([x['Value'] for x in bonuses if x['Stat'] == 'ADD_PATK'], EXPECTED['gem_attack'])
        self.assertEqual([x['Value'] for x in bonuses if x['Stat'] == 'ADD_CRTHR'], EXPECTED['gem_penalty'])
        self.assertContains(self.client.get('/items/643501'), '<td>-21</td>')
        self.assertContains(self.client.get('/items/643580'), 'gem-socket-bonuses')
        self.assertEqual(self.db.data['goddess_reinf_mat'][560]['weapon'][6], EXPECTED['weapon_material_6'])
        self.assertEqual(self.db.data['goddess_reinf_unregistered'], {'item_goddess_reinforce_580.ies': 580})
        self.assertFalse(GoddessReinforcement.objects.filter(level=580).exists())

    def test_actual_inputs_reach_calculator_steps_and_reset(self):
        for ident, expected in EXPECTED['equipment'].items():
            payload = self.client.get('/items/' + ident).context['enhancement']
            result = run_calculator(payload, [{'anvil': 6}, {'anvil': 30}, {'anvil': 0}])['results']
            for index, step in enumerate(('step6', 'step30')):
                for stat in ('patk', 'patk_max', 'matk', 'pdef', 'mdef'):
                    if expected[stat]:
                        self.assertEqual(result[index]['calculation']['stats'][stat],
                                         expected[stat] + expected[step], (ident, stat, step))
            for stat in ('patk', 'patk_max', 'matk', 'pdef', 'mdef'):
                self.assertEqual(result[2]['calculation']['stats'][stat], expected[stat])

    def test_repeat_and_table_mutation_recalculate_without_stale_values(self):
        before = {p.name: p.read_bytes() for p in self.release.glob('*.json')}
        parse_workspace(self.workspace, self.region)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.release.glob('*.json')})
        call_command(self.command, update=1)
        self.assertEqual(Version.objects.count(), 1)
        change_ies_column(self.workspace / (self.region + '_unpack/ies.ipf/item_goddess_reinforce_560.ies'),
                          'BasicAtk', '400000')
        parse_workspace(self.workspace, self.region, 'real-sample-v2')
        call_command(self.command, update=1)
        sword = Equipments.objects.get(item__ids='11107087')
        self.assertEqual((sword.patk, sword.patk_max), (388000, 412000))
        self.assertEqual(Version.objects.count(), 2)

    def test_bad_real_lua_preserves_published_json_and_recovers(self):
        before = {p.name: p.read_bytes() for p in self.release.glob('*.json')}
        lua = self.workspace / (self.region + '_unpack/shared.ipf/shared_item_goddess_reinforce.lua')
        original = lua.read_bytes()
        lua.write_bytes(original + b'\nmissing_engine.initialize()\n')
        with self.assertRaisesRegex(ValueError, 'goddess Lua module'):
            parse_workspace(self.workspace, self.region, 'real-sample-v2')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.release.glob('*.json')})
        self.assertEqual(Version.objects.count(), 1)
        lua.write_bytes(original)
        parse_workspace(self.workspace, self.region, 'real-sample-v2')
        call_command(self.command, update=1)
        self.assertEqual(Version.objects.count(), 2)


class KtosRealSourceTests(RealSourceTests):
    region = 'ktos'
