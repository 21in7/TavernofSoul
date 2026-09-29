"""Run migration regressions in subprocesses using SQLite :memory: only."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('case', [
    'both_missing', 'existing_recipe', 'existing_parent', 'retry',
    'dry_run', 'unrelated_collision', 'rollback', 'preserve_links', 'canonical_clash',
])
def test_recipe_migration_database(case):
    result = subprocess.run([sys.executable, __file__, case],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def run_case(case):
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / 'TavernofSoul'))
    os.environ['DJANGO_SETTINGS_MODULE'] = 'TavernofSoul.settings_test'
    from django.conf import settings
    settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3',
                                    'NAME': ':memory:'}}
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
    if case == 'dry_run':
        assert cmd._backfill(entries, {'recipe'}, True)[:2] == (1, 1)
        assert Items.objects.count() == 0
        assert Item_Type.objects.count() == 0
        return
    if case == 'unrelated_collision':
        entries.update({'a': {'$ID': 200, '$ID_NAME': 'a'},
                        'b': {'$ID': 200, '$ID_NAME': 'b'}})
    if case == 'rollback':
        del weapon['AnvilATK']
        with pytest.raises(KeyError):
            cmd._backfill(entries, {'recipe'}, False)
        assert Items.objects.count() == 0
        assert Item_Type.objects.count() == 0
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
    if case == 'preserve_links':
        recipe['Link_Target'] = 'unavailable'
        assert cmd._backfill(entries, {'recipe'}, False)[2] == 1
        assert Item_Recipe_Target.objects.get().target.id_name == 'weapon'
        assert Item_Recipe_Material.objects.get().qty == 2
        return
    counts = [model.objects.count() for model in tables]
    assert cmd._backfill(entries, {'recipe'}, False) == (0, 0, 0, 0)
    assert [model.objects.count() for model in tables] == counts


if __name__ == '__main__':
    run_case(sys.argv[1])
