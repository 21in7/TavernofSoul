"""Seed a disposable real Django server from parser sources, then drive Chromium."""
import os
from html.parser import HTMLParser
from pathlib import Path
import tempfile

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings
from PIL import Image
from Items.models import (Items, Equipments, Equipment_Bonus, Recipes,
                          Item_Recipe_Material, Item_Recipe_Target, Collections,
                          Item_Collection_Material, Item_Collection_Bonus)

from harness.browser_runner import run_browser
from harness.parser_fixture import parse_workspace, prepare_equipment_workspace
from ipfparser.management.commands.importAll import Command


class FixtureImageRefs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = set()

    def handle_starttag(self, tag, attrs):
        source = dict(attrs).get('src', '')
        if tag == 'img' and source.startswith('/static/icons/'):
            name = source[len('/static/icons/'):]
            if '/' in name or not ('harness' in name or 'regional' in name):
                raise ValueError('Browser fixture references an unexpected game asset: ' + source)
            self.paths.add(name)


class EquipmentBrowserTests(StaticLiveServerTestCase):
    host = '127.0.0.1'

    def seed_detail_layout(self, sword):
        # Browser-only fixed data goes through the real ORM/view/template. Keep
        # existing search keywords, regional fixtures and calculation data intact.
        source = sword.item
        tail = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789' * 3

        def row(ident, kind, name, description):
            return Items.objects.create(
                ids=ident, id_name='harness_detail_' + kind + '_' + tail[:60], name=name,
                descriptions=description, type=source.type, grade=source.grade,
                icon=source.icon, tradability=source.tradability,
            )

        equipment = row('910001', 'equipment', '모바일 장비 日本語 Equipment ' + tail,
                        '긴 설명 日本語 description ' + tail + '{nl}Second description line 12345678901234567890')
        fields = {field.name: getattr(sword, field.name)
                  for field in Equipments._meta.concrete_fields if field.name != 'item'}
        cloned = Equipments.objects.create(item=equipment, **fields)
        Equipment_Bonus.objects.create(equipment=cloned, bonus_stat='ADD_FIRE',
                                       bonus_val='12345678901234567890{nl}' + tail)
        material = row('910002', 'material', '긴 재료 日本語 Material ' + tail,
                       'Core material description 日本語 한글 ' + tail)
        recipe = Recipes.objects.create(item=row('910003', 'recipe',
                    '긴 제작법 日本語 Recipe ' + tail, 'Fixed recipe description'))
        Item_Recipe_Target.objects.create(recipe=recipe, target=equipment)
        Item_Recipe_Material.objects.create(recipe=recipe, material=material, qty=123456789)
        collection = Collections.objects.create(item=row('910004', 'collection',
                    '긴 수집품 日本語 Collection ' + tail, 'Fixed collection description'))
        Item_Collection_Material.objects.create(collection=collection, material=equipment)
        Item_Collection_Material.objects.create(collection=collection, material=material)
        Item_Collection_Bonus.objects.create(collection=collection, bonus_stat='ADD_FIRE',
                                            bonus_val='12345678901234567890')

    def test_browser_scenarios(self):
        with tempfile.TemporaryDirectory(prefix='tavern-browser-fixture-') as temporary:
            workspace = prepare_equipment_workspace(temporary, 'itos')
            db = parse_workspace(workspace, 'browser-v1', region='itos', include_equipment=True)
            command = Command()
            command.base_path = str(db.BASE_PATH_OUTPUT)
            call_command(command, update=1)
            # Browser-only rows provide three full/partial result pages without
            # changing parser fixtures, regional counts, gems or calculator inputs.
            sword = Equipments.objects.get(item__ids='110')
            for number in range(25):
                source = sword.item
                row = Items.objects.create(
                    ids=str(900000 + number), id_name='harness_search_%02d' % number,
                    name='Search & + #? / "한글" <fixture> %02d' % number,
                    type=source.type, grade=source.grade, icon=source.icon,
                    tradability=source.tradability, descriptions='Browser search fixture',
                )
                fields = {field.name: getattr(sword, field.name)
                          for field in Equipments._meta.concrete_fields if field.name != 'item'}
                fields['requiredClass'] = '...T.'
                Equipments.objects.create(item=row, **fields)
            self.seed_detail_layout(sword)
            static = Path(temporary) / 'fixture-static'
            icons = static / 'icons'
            icons.mkdir(parents=True)
            # The hand-authored IDs have no downloaded artwork. Serve local fixture
            # PNGs through Django's real static handler rather than mocking responses.
            with override_settings(REGION='itos', STATICFILES_DIRS=[static] + list(settings.STATICFILES_DIRS)):
                refs = FixtureImageRefs()
                for url in ('/items/?q=&page=1', '/items/?q=&page=2', '/items/?q=&page=3',
                            '/items/?q=&page=4', '/items/100', '/items/110', '/items/111', '/items/112',
                            '/items/113', '/items/230', '/items/240', '/skills/400',
                            '/items/910001', '/items/910002', '/items/910003', '/items/910004'):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200, url)
                    refs.feed(response.content.decode())
                for name in refs.paths:
                    Image.new('RGB', (32, 32), '#437f92').save(icons / name)
                report = run_browser(self.live_server_url, os.environ['HARNESS_BROWSER_REPORT_DIR'])
                self.assertEqual(report['status'], 'passed', 'Browser JSON and trace: ' + report['artifacts'])
