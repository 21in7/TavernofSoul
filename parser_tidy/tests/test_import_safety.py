"""Importer regression tests; database is an isolated in-memory SQLite alias."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TavernofSoul'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'TavernofSoul.settings_test')


@pytest.fixture
def importer(tmp_path):
    import django
    django.setup()
    from ipfparser.management.commands import importAll
    cmd = importAll.Command()
    cmd.base_path = str(tmp_path)
    return cmd, importAll


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


@pytest.mark.parametrize('now', [[], {}, [{'Map': 2, 'Item': 3}]])
def test_removed_parent_is_reported(importer, tmp_path, now):
    cmd, _ = importer
    old = {'Map': 1, 'Item': 2}
    write(tmp_path / 'prev/map_item.json', [old])
    write(tmp_path / 'map_item.json', now)
    assert cmd.comparer(cmd.map_item_path, ['Map', 'Item'])['removed'] == [old]


@pytest.mark.parametrize('contents', [None, '{broken', 'null'])
def test_missing_or_invalid_current_fails(importer, tmp_path, contents):
    cmd, module = importer
    if contents is not None:
        (tmp_path / 'map_item.json').write_text(contents)
    with pytest.raises(module.CommandError):
        cmd.comparer(cmd.map_item_path, ['Map', 'Item'])


@pytest.fixture
def isolated_db(importer, monkeypatch):
    from django.db import connections, transaction
    cmd, module = importer
    alias = 'import_safety_test'
    connections.databases[alias] = dict(connections.databases['default'],
        ENGINE='django.db.backends.sqlite3', NAME=':memory:', OPTIONS={})
    connection = connections[alias]
    with connection.schema_editor() as editor:
        editor.create_model(module.Version)
    real_atomic = transaction.atomic
    monkeypatch.setattr(module.transaction, 'atomic', lambda *args, **kwargs: real_atomic(*args, **dict(kwargs, using=kwargs.get('using', alias))))
    real_manager = module.Version.objects.db_manager(alias)
    monkeypatch.setattr(module.Version, 'objects', real_manager)
    yield real_manager
    connection.close()
    del connections[alias]
    del connections.databases[alias]


@pytest.mark.parametrize('failure', ['import', 'publish', 'commit', None])
def test_transaction_and_baseline(importer, isolated_db, tmp_path, monkeypatch, failure):
    cmd, module = importer
    write(tmp_path / 'version.json', {'version': 'new'})
    write(tmp_path / 'prev/version.json', {'version': 'old'})
    write(tmp_path / 'data.json', {'current': True})
    def import_data(update):
        isolated_db.create(version='intermediate')
        if failure == 'import':
            raise RuntimeError('import failed')
    monkeypatch.setattr(cmd, '_import_data', import_data)
    # Arbitrary data.json isolates transaction/publication failure handling.
    monkeypatch.setattr(cmd, '_validate_staged_release',
                        lambda directory: cmd.importJSON(Path(directory) / 'version.json'))
    if failure == 'publish':
        real_replace = module.os.replace
        def replace(source, destination):
            if Path(source).name.startswith('.import-prev-') and not str(source).endswith('-backup'):
                raise OSError('publication failed')
            return real_replace(source, destination)
        monkeypatch.setattr(module.os, 'replace', replace)
    if failure == 'commit':
        from django.db import connections, OperationalError
        monkeypatch.setattr(connections['import_safety_test'], 'commit', Mock(side_effect=OperationalError('commit failed')))
    if failure:
        with pytest.raises(Exception, match='failed'):
            cmd.handle(update=1)
        assert list(isolated_db.all()) == []
        assert json.loads((tmp_path / 'prev/version.json').read_text()) == {'version': 'old'}
    else:
        cmd.handle(update=1)
        assert set(isolated_db.values_list('version', flat=True)) == {'new', 'intermediate'}
        assert json.loads((tmp_path / 'prev/version.json').read_text()) == {'version': 'new'}
    assert cmd.base_path == str(tmp_path)
    assert not list(tmp_path.glob('.import-prev-*'))


def test_drop_update_and_delete_use_queryset(importer, monkeypatch):
    cmd, module = importer
    manager = Mock()
    monkeypatch.setattr(module.Item_Monster, 'objects', manager)
    monkeypatch.setattr(module.Monsters, 'objects', Mock())
    monkeypatch.setattr(module.Items, 'objects', Mock())
    row = {'Monster': 4, 'Item': 8, 'Chance': 2, 'Quantity_MIN': 1, 'Quantity_MAX': 1}
    cmd.importItemMonster({'removed': [row], 'added': [], 'changed': [row]}, 1)
    manager.filter.assert_called_once_with(monster__ids=4, item__ids=8)
    manager.filter.return_value.delete.assert_called_once_with()
    manager.get.assert_called_once_with(monster__ids=4, item__ids=8)
    manager.get.return_value.save.assert_called_once_with()


def test_npc_delete_uses_monster_field(importer, monkeypatch):
    cmd, module = importer
    for model in [module.Maps, module.Monsters, module.Map_NPC]:
        monkeypatch.setattr(model, 'objects', Mock())
    cmd.importMapNPC({'removed': [{'Map': 1, 'NPC': 2}], 'added': [], 'changed': []}, 1)
    module.Map_NPC.objects.filter.assert_called_once_with(
        map=module.Maps.objects.get.return_value, monster=module.Monsters.objects.get.return_value)


def test_old_baseline_reconciles_previously_skipped_map_rows(importer, tmp_path):
    cmd, _ = importer
    row = {'Map': 1, 'Item': 2}
    write(tmp_path / 'prev/map_item.json', [row])
    write(tmp_path / 'map_item.json', [row])
    cmd._reconcile_map_relations = True
    assert cmd.comparer(cmd.map_item_path, ['Map', 'Item'])['changed'] == [row]
    cmd._reconcile_map_relations = False
    assert cmd.comparer(cmd.map_item_path, ['Map', 'Item'])['changed'] == []


def test_missing_map_parent_blocks_success(importer, monkeypatch):
    cmd, module = importer
    monkeypatch.setattr(module.Maps, 'objects', Mock())
    module.Maps.objects.get.side_effect = module.Maps.DoesNotExist
    with pytest.raises(module.CommandError, match='not found'):
        cmd.importMapItem({'removed': [], 'added': [{'Map': 1, 'Item': 2}], 'changed': []}, 1)


def test_database_error_is_not_treated_as_missing_row(importer, monkeypatch):
    from django.db import OperationalError
    cmd, module = importer
    monkeypatch.setattr(module.Items, 'objects', Mock())
    monkeypatch.setattr(module.Item_Type, 'objects', Mock())
    module.Item_Type.objects.all.return_value = []
    module.Items.objects.get.side_effect = OperationalError('database down')
    with pytest.raises(OperationalError, match='database down'):
        cmd.importItem({'removed': [], 'added': [{'$ID': 1}], 'changed': []}, {}, 1)


def test_recipe_without_declared_target_is_optional(importer, monkeypatch):
    cmd, module = importer
    for model in [module.Recipes, module.Item_Recipe_Material, module.Item_Recipe_Target, module.Items]:
        monkeypatch.setattr(model, 'objects', Mock())
    cmd.makeRecipe(Mock(), {'Link_Materials': [], 'Link_Target': None}, [])
    module.Items.objects.get.assert_not_called()


def test_declared_recipe_target_must_exist(importer, monkeypatch):
    cmd, module = importer
    for model in [module.Recipes, module.Item_Recipe_Material, module.Item_Recipe_Target, module.Items]:
        monkeypatch.setattr(model, 'objects', Mock())
    module.Recipes.objects.get.return_value = module.Recipes(pk=1)
    module.Items.objects.get.side_effect = module.Items.DoesNotExist
    with pytest.raises(module.CommandError, match='target'):
        cmd.makeRecipe(Mock(), {'Name': 'recipe', '$ID_NAME': 'R', 'Link_Materials': [], 'Link_Target': 'missing'}, [])


@pytest.mark.parametrize('failure', [False, True])
def test_retired_attribute_skills_optional_but_database_errors_propagate(importer, monkeypatch, failure):
    from django.db import OperationalError
    cmd, module = importer
    for model in [module.Attributes, module.Skills]:
        monkeypatch.setattr(model, 'objects', Mock())
    handler = module.Attributes.objects.get.return_value
    handler.skill.all.return_value = []
    handler.job.all.return_value = []
    cmd._available_skill_names = {'valid'}
    row = {'$ID': 1, '$ID_NAME': 'A', 'Name': 'A', 'Description': '', 'Icon': '',
           'DescriptionRequired': '', 'IsToggleable': False, 'LevelMax': 1,
           'Link_Skills': ['retired', 'valid'], 'Link_Jobs': []}
    changes = {'added': [row], 'changed': [], 'removed': []}
    if failure:
        module.Skills.objects.get.side_effect = OperationalError('database down')
        with pytest.raises(OperationalError, match='database down'):
            cmd.importAttrib(changes, 1)
    else:
        cmd.importAttrib(changes, 1)
        module.Skills.objects.get.assert_called_once_with(id_name='valid')
        handler.skill.add.assert_called_once_with(module.Skills.objects.get.return_value)
