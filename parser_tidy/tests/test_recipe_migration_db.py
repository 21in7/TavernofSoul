"""Run migration regressions in subprocesses using SQLite :memory: only."""
import atexit
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest


@pytest.mark.parametrize('case', [
    'both_missing', 'existing_recipe', 'existing_parent', 'retry',
    'dry_run', 'unrelated_collision', 'rollback', 'preserve_links', 'canonical_clash',
    'exact_pairs', 'pair_flags', 'pair_dry_run', 'pair_rollback',
    'pair_equipment_missing', 'pair_generic_missing',
])
def test_recipe_migration_database(case):
    result = subprocess.run([sys.executable, __file__, case],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def run_case(case):
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / 'TavernofSoul'))
    harness_work_dir = tempfile.TemporaryDirectory(prefix='recipe-migration-')
    atexit.register(harness_work_dir.cleanup)
    os.environ['HARNESS_WORK_DIR'] = harness_work_dir.name
    os.environ['DJANGO_SETTINGS_MODULE'] = 'TavernofSoul.settings_harness'
    from django.conf import settings
    if settings.configured and getattr(settings, 'SETTINGS_MODULE', None) != 'TavernofSoul.settings_harness':
        raise RuntimeError('Django must use TavernofSoul.settings_harness')
    import django
    django.setup()
    from django.db import connection
    from Items.models import (Items, Item_Type, Equipments, Equipment_Bonus,
                              Recipes, Item_Recipe_Material, Item_Recipe_Target)
    from ipfparser.management.commands.migrate_recipe_ids import Command
    tables = [Items, Item_Type, Equipments, Equipment_Bonus, Recipes,
              Item_Recipe_Material, Item_Recipe_Target]
    with connection.schema_editor() as editor:
        for model in tables:
            editor.create_model(model)
    if case == 'exact_pairs':
        from unittest.mock import patch
        from django.db import OperationalError
        from django.db.models.query import QuerySet
        from ipfparser.item_types import get_or_create_item_type
        names = ['Sword', 'sword', 'Sword ', '\u00e9', 'e\u0301']
        cache = {}
        ids = {}
        for name in names:
            for flag in (False, True):
                row, created = get_or_create_item_type(name, flag, cache)
                assert created
                ids[name, flag] = row.pk
                assert (row.name, row.is_equipment) == (name, flag)
        for lookup_cache in (cache, {}):
            for pair, pk in ids.items():
                row, created = get_or_create_item_type(*pair, cache=lookup_cache)
                assert row.pk == pk and not created
        duplicate = Item_Type.objects.create(name='Sword', is_equipment=False)
        row, created = get_or_create_item_type('Sword', False, {})
        assert row.pk == ids['Sword', False] < duplicate.pk and not created
        assert Item_Type.objects.count() == len(ids) + 1
        failing_cache = {}
        with patch.object(QuerySet, 'get_or_create',
                          side_effect=OperationalError('lookup failed')):
            with pytest.raises(OperationalError, match='lookup failed'):
                get_or_create_item_type('new', False, failing_cache)
        assert failing_cache == {}
        assert not Item_Type.objects.filter(name='new').exists()
        Command()._upsert_item({'$ID_NAME': 'empty_type', 'Type': ''}, '999')
        assert not Item_Type.objects.filter(name='').exists()
        return
    recipe = {'$ID': 100, '$ID_NAME': 'recipe', 'Type': 'RECIPES',
              'Link_Materials': [{'Item': 'weapon', 'Quantity': 2}],
              'Link_Target': 'weapon'}
    weapon = {'$ID': 100, '$ID_NAME': 'weapon', 'Type': 'Equipment',
              'TypeEquipment': 'Sword', 'TypeAttack': 'Slash',
              'AnvilATK': [], 'AnvilDEF': [], 'AnvilPrice': [],
              'TranscendPrice': [], 'RequiredClass': 'Swordsman',
              'Unidentified': False, 'UnidentifiedRandom': False,
              'Bonus': [['STR', '5']]}
    for field in ['Durability', 'Level', 'Potential', 'SocketsLimit', 'Stars',
                  'Stat_ATTACK_MAGICAL', 'Stat_ATTACK_PHYSICAL_MIN',
                  'Stat_ATTACK_PHYSICAL_MAX', 'Stat_DEFENSE_MAGICAL',
                  'Stat_DEFENSE_PHYSICAL']:
        weapon[field] = 1
    entries = {'recipe': recipe, 'weapon': weapon}
    cmd = Command()
    original_types = []
    if case.startswith('pair_'):
        weapon['Type'] = weapon['TypeEquipment'] = 'Sword'
        for name, flag in [('Sword', False), ('Sword', True),
                           ('sword', True), ('RECIPES', True)]:
            if name == 'Sword' and (
                    (case == 'pair_equipment_missing' and flag) or
                    (case == 'pair_generic_missing' and not flag)):
                continue
            row = Item_Type.objects.create(name=name, is_equipment=flag)
            original_types.append((row.pk, name, flag))
    def assert_types_preserved():
        for pk, name, flag in original_types:
            row = Item_Type.objects.get(pk=pk)
            assert (row.name, row.is_equipment) == (name, flag)
    if case in ('existing_recipe', 'existing_parent'):
        row = cmd._upsert_item(recipe, '100')
        assert cmd._rename_recipe_ids({'recipe'}, False) == 1
        row.refresh_from_db()
        assert row.ids == 'recipe-100'
    if case == 'existing_parent':
        cmd._upsert_item(weapon, '100')
    if case == 'canonical_clash':
        row = cmd._upsert_item(recipe, '100')
        cmd._upsert_item({'$ID_NAME': 'other'}, 'recipe-100')
        assert cmd._rename_recipe_ids({'recipe'}, False) == 0
        row.refresh_from_db()
        assert row.ids == '100'
        result = cmd._backfill(entries, {'recipe'}, False)
        assert result[3] == 2
        assert Items.objects.count() == 2
        assert Recipes.objects.count() == 0
        return
    if case in ('dry_run', 'pair_dry_run'):
        assert cmd._backfill(entries, {'recipe'}, True)[:2] == (1, 1)
        assert Items.objects.count() == 0
        assert Item_Type.objects.count() == len(original_types)
        assert_types_preserved()
        return
    if case == 'unrelated_collision':
        entries.update({'a': {'$ID': 200, '$ID_NAME': 'a'},
                        'b': {'$ID': 200, '$ID_NAME': 'b'}})
    if case in ('rollback', 'pair_rollback'):
        del weapon['AnvilATK']
        with pytest.raises(KeyError):
            cmd._backfill(entries, {'recipe'}, False)
        assert Items.objects.count() == 0
        assert Item_Type.objects.count() == len(original_types)
        assert_types_preserved()
        # The same command must not retain rolled-back category objects.
        weapon['AnvilATK'] = []
        assert cmd._backfill(entries, {'recipe'}, False)[2:] == (0, 0)
        assert Item_Type.objects.filter(name='RECIPES', is_equipment=False).exists()
        assert Item_Recipe_Target.objects.get().target.id_name == 'weapon'
        assert_types_preserved()
        return
    if case == 'retry':
        recipe['Link_Target'] = 'later'
        assert cmd._backfill(entries, {'recipe'}, False)[2] == 1
        assert Item_Recipe_Target.objects.count() == 0
        cmd._upsert_item({'$ID_NAME': 'later'}, '999')
    result = cmd._backfill(entries, {'recipe'}, False)
    assert result[2:] == (0, 0)
    assert Equipments.objects.get(item__id_name='weapon').patk == 1
    assert Equipment_Bonus.objects.get().bonus_stat == 'STR'
    assert Items.objects.get(id_name='recipe').ids == 'recipe-100'
    assert Item_Recipe_Material.objects.get().qty == 2
    assert Item_Recipe_Target.objects.get().target.id_name == recipe['Link_Target']
    assert not Items.objects.filter(id_name__in=['a', 'b']).exists()
    assert_types_preserved()
    if case == 'pair_flags':
        assert Item_Type.objects.get(name='Sword', is_equipment=False).pk == original_types[0][0]
        assert Item_Type.objects.get(name='Sword', is_equipment=True).pk == original_types[1][0]
        assert not Item_Type.objects.filter(name='', is_equipment=False).exists()
    if case.startswith('pair_'):
        assert Item_Type.objects.filter(name='Sword', is_equipment=False).count() == 1
        assert Item_Type.objects.filter(name='Sword', is_equipment=True).count() == 1
    if case == 'preserve_links':
        recipe['Link_Target'] = 'unavailable'
        assert cmd._backfill(entries, {'recipe'}, False)[2] == 1
        assert Item_Recipe_Target.objects.get().target.id_name == 'weapon'
        assert Item_Recipe_Material.objects.get().qty == 2
        return
    counts = [model.objects.count() for model in tables]
    assert cmd._backfill(entries, {'recipe'}, False) == (0, 0, 0, 0)
    assert [model.objects.count() for model in tables] == counts
    assert_types_preserved()


if __name__ == '__main__':
    run_case(sys.argv[1])
