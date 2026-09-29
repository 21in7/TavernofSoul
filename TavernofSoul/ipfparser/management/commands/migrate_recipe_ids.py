# -*- coding: utf-8 -*-
"""P0-8: Item/Recipe ClassID 충돌(49건) 해소를 위한 1회성 데이터 마이그레이션.

배경
----
parser 의 ``items_by_name.json`` 은 ClassName 기준이라 손실이 없지만,
importer(``importAll.py``) 의 ``comparer`` 가 내부에서 숫자 ``$ID`` 로
re-key 하면서 Item/Recipe 가 같은 ClassID 를 공유하는 49건이
last-writer-wins 로 드롭됐다. 신규 importer 코드는 recipe 의 ``$ID`` 를
``'recipe-<n>'`` canonical ID 로 정규화해 이 드롭을 막는다(comparer transform).

이 명령은 **신규 코드 배포 후, importer 실행 전**에 1회 실행해 기존 DB
상태를 canonical 체계로 맞춘다:

1. **rename**: 기존 ``Items`` 행 중 ``type='RECIPES'`` 이면서 아직
   ``ids`` 가 숫자인 행을 ``ids='recipe-<n>'`` 으로 갱신.
2. **backfill**: 과거 드롭으로 DB 에 빠진 recipe 와 그 충돌 짝(equipment)을
   ``items_by_name.json`` 에서 읽어 upsert. 단 **recipe 충돌로 엄격히 한정**:
   ``id_name ∈ item_type['RECIPES']`` 인 엔트리와 그 ``$ID`` 가 겹치는
   비-recipe 짝만. itos 의 COLLECTION/EVENT 충돌(``COLLECT_393``)은
   recipe 가 아니므로 제외한다.

운영 순서(필수)::

    1. 새 importer 코드 배포
    2. python manage_<region>.py migrate_recipe_ids
    3. python manage_<region>.py importAll

순서가 뒤집히면 importer 의 changed/removed 분기가 ``get(ids='recipe-<n>')``
로 기존 숫자 행을 찾지 못해 새 행을 만들고(중복), removed delete 도
조용히 실패한다.
"""
import json
import logging

from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import transaction
from os.path import join, exists

from Items.models import Items, Item_Type, Equipments, Recipes, Item_Recipe_Material, Item_Recipe_Target

log = logging.getLogger('migrate_recipe_ids')
log.setLevel('INFO')

RECIPE_ID_PREFIX = 'recipe-'


class Command(BaseCommand):
    help = ('P0-8: rename 기존 recipe 행의 ids 를 recipe-<n> 으로 변경하고, '
            '과거 ClassID 충돌로 드롭된 recipe/장비 짝을 backfill 한다. '
            '신규 importer 배포 후, importAll 실행 전에 1회 실행한다.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='변경 없이 수행할 작업만 로그로 출력한다.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        base_path = settings.JSON_ROOT

        item_type = self._load_json(join(base_path, 'item_type.json'))
        recipe_id_names = set(item_type.get('RECIPES', []))
        if not recipe_id_names:
            log.warning('item_type.json 에 RECIPES 가 없다. 중단.')
            return

        items_by_name = self._load_json(join(base_path, 'items_by_name.json'))
        if not items_by_name:
            log.warning('items_by_name.json 이 비었거나 없다. 중단.')
            return

        # 1) rename: 기존 recipe 행 ids -> recipe-<n>
        renamed = self._rename_recipe_ids(recipe_id_names, dry_run)

        # 2) backfill: 과거 드롭된 recipe + 충돌 짝(equipment)
        recipe_filled, equip_filled, mat_failures, skipped = self._backfill(
            items_by_name, recipe_id_names, dry_run)

        self.stdout.write(self.style.SUCCESS(
            'migrate_recipe_ids 완료: renamed={} recipe_filled={} '
            'equip_filled={} material_failures={} skipped={}'.format(
                renamed, recipe_filled, equip_filled, mat_failures, skipped)))

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_json(path):
        if not exists(path):
            return {}
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except (IOError, OSError, ValueError) as e:
            log.error('JSON 로드 실패 %s: %s', path, e)
            return {}

    @staticmethod
    def _canonical_id(raw_id):
        return RECIPE_ID_PREFIX + str(raw_id)

    def _rename_recipe_ids(self, recipe_id_names, dry_run):
        """기존 recipe 행(type='RECIPES') 중 ids 가 아직 숫자인 것을 rename."""
        qs = Items.objects.filter(type='RECIPES').exclude(
            ids__startswith=RECIPE_ID_PREFIX)
        renamed = 0
        for row in qs:
            # id_name 이 RECIPES 집합에 있는지 재확인(방어).
            if row.id_name not in recipe_id_names:
                continue
            new_ids = self._canonical_id(row.ids)
            if Items.objects.filter(ids=new_ids).exclude(pk=row.pk).exists():
                log.warning('skip rename %s: canonical ids %s already exists',
                            row.id_name, new_ids)
                continue
            if dry_run:
                log.info('[dry-run] rename %s: %s -> %s',
                         row.id_name, row.ids, new_ids)
            else:
                row.ids = new_ids
                row.save(update_fields=['ids'])
            renamed += 1
        log.info('rename 완료: %d건', renamed)
        return renamed

    @transaction.atomic
    def _backfill(self, items_by_name, recipe_id_names, dry_run):
        """Create all missing parents before repairing children and recipe links.

        Existing recipes must participate: an earlier run may have created only
        their parent row, or their colliding equipment may still be missing.
        Non-recipe collisions unrelated to recipes are deliberately excluded.
        """
        from .importAll import Command as ImportCommand

        recipe_filled = equip_filled = mat_failures = skipped = 0
        by_numeric_id = {}
        for entry in items_by_name.values():
            if entry.get('$ID') is not None:
                by_numeric_id.setdefault(str(entry['$ID']), []).append(entry)

        candidates = {}
        for entry in items_by_name.values():
            if entry.get('$ID_NAME') not in recipe_id_names:
                continue
            candidates[entry['$ID_NAME']] = entry
            for partner in by_numeric_id.get(str(entry.get('$ID')), []):
                if partner.get('$ID_NAME') not in recipe_id_names:
                    candidates[partner['$ID_NAME']] = partner

        recipes = []
        equipment = []
        for name, entry in candidates.items():
            is_recipe = name in recipe_id_names
            canonical = (self._canonical_id(entry['$ID']) if is_recipe
                         else str(entry['$ID']))
            matches = Items.objects.filter(id_name=name)
            if matches.count() > 1:
                skipped += 1
                log.warning('skip backfill %s: multiple existing parent rows', name)
                continue
            existing = matches.first()
            clash = Items.objects.filter(ids=canonical).exclude(id_name=name).first()
            if clash is not None:
                skipped += 1
                log.warning('skip backfill %s: ids %s already belongs to %s',
                            name, canonical, clash.id_name)
                continue
            if existing is None:
                if dry_run:
                    log.info('[dry-run] backfill %s (ids=%s)', name, canonical)
                else:
                    existing = self._upsert_item(entry, canonical)
                if is_recipe:
                    recipe_filled += 1
                else:
                    equip_filled += 1
            if is_recipe:
                recipes.append(entry)
            elif 'TypeEquipment' in entry:
                equipment.append((existing, entry))

        if not dry_run:
            importer = ImportCommand()
            for item, entry in equipment:
                if not Equipments.objects.filter(item=item).exists():
                    # Pre-create the equipment category: makeEQ's fallback may
                    # otherwise rename the generic item category in place.
                    Item_Type.objects.update_or_create(
                        name=entry['TypeEquipment'], defaults={'is_equipment': True})
                    importer.makeEQ(item, entry, [entry['TypeEquipment']])
            for entry in recipes:
                mat_failures += self._relink_recipe(entry)

        log.info('backfill 완료: recipe=%d equipment=%d material_failures=%d '
                 'skipped=%d', recipe_filled, equip_filled, mat_failures, skipped)
        return recipe_filled, equip_filled, mat_failures, skipped

    def _upsert_item(self, entry, canonical_ids):
        """entry 로 Items 행을 생성한다(canonical_ids 사용). importItem 의
        added 분기와 동일한 필드 매핑."""
        handler = Items()
        handler.ids = canonical_ids
        handler.id_name = entry.get('$ID_NAME', '')
        handler.cooldown = entry.get('TimeCoolDown', 0)
        handler.descriptions = entry.get('Description', '')
        handler.name = entry.get('Name', '')
        weight = entry.get('Weight', '')
        handler.weight = 0 if weight == '' else weight
        handler.tradability = entry.get('Tradability', '')
        handler.type = entry.get('Type', '')
        # Item_Type 이 없으면 생성(importItem 과 동일).
        if handler.type:
            Item_Type.objects.get_or_create(name=handler.type)
        handler.grade = entry.get('Grade', '') or 1
        handler.icon = entry.get('Icon', '')
        pc = entry.get('PackageContents')
        handler.package_contents = (
            json.dumps(pc, ensure_ascii=False) if pc else None)
        handler.save()
        return handler

    def _relink_recipe(self, entry):
        """Retry links even for existing recipes; retain old links if unresolved."""
        if 'Link_Materials' not in entry:
            return 0
        item = Items.objects.get(id_name=entry['$ID_NAME'])
        handler, _ = Recipes.objects.get_or_create(item=item)
        failures = 0
        materials = []
        for link in entry['Link_Materials']:
            try:
                material = Items.objects.get(id_name=link['Item'])
            except (Items.DoesNotExist, Items.MultipleObjectsReturned):
                failures += 1
                log.warning('[RCP] %s material missing or ambiguous: %s',
                            entry['$ID_NAME'], link['Item'])
            else:
                materials.append((material, link.get('Quantity', 0)))
        target = None
        if entry.get('Link_Target'):
            try:
                target = Items.objects.get(id_name=entry['Link_Target'])
            except (Items.DoesNotExist, Items.MultipleObjectsReturned):
                failures += 1
                log.warning('[RCP] %s target missing or ambiguous: %s',
                            entry['$ID_NAME'], entry['Link_Target'])
        if failures:
            return failures
        Item_Recipe_Material.objects.filter(recipe=handler).delete()
        Item_Recipe_Target.objects.filter(recipe=handler).delete()
        for material, qty in materials:
            Item_Recipe_Material.objects.create(
                recipe=handler, material=material, qty=qty)
        if target is not None:
            Item_Recipe_Target.objects.create(recipe=handler, target=target)
        return 0
