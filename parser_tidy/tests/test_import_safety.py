"""Importer regression tests; database is an isolated in-memory SQLite alias."""
import atexit
from copy import deepcopy
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'TavernofSoul'))
_HARNESS_WORK_DIR = tempfile.TemporaryDirectory(prefix='import-safety-')
atexit.register(_HARNESS_WORK_DIR.cleanup)


def use_harness():
    os.environ['HARNESS_WORK_DIR'] = _HARNESS_WORK_DIR.name
    os.environ['DJANGO_SETTINGS_MODULE'] = 'TavernofSoul.settings_harness'


use_harness()


@pytest.fixture
def importer(tmp_path):
    use_harness()
    from django.conf import settings
    if settings.configured and getattr(settings, 'SETTINGS_MODULE', None) != 'TavernofSoul.settings_harness':
        raise RuntimeError('Django must use TavernofSoul.settings_harness')
    import django
    django.setup()
    from ipfparser.management.commands import importAll
    cmd = importAll.Command()
    cmd.base_path = str(tmp_path)
    return cmd, importAll


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def read(path):
    return json.loads(path.read_text())


def mock_managers(monkeypatch, *models):
    for model in models:
        monkeypatch.setattr(model, 'objects', Mock())


def fail_at(monkeypatch, module, failure):
    if failure == 'publish':
        real_replace = module.os.replace
        def replace(source, destination):
            if Path(source).name.startswith('.import-prev-') and not str(source).endswith('-backup'):
                raise OSError('publication failed')
            return real_replace(source, destination)
        monkeypatch.setattr(module.os, 'replace', replace)
    if failure == 'commit':
        from django.db import connections, OperationalError
        monkeypatch.setattr(connections['import_safety_test'], 'commit',
                            Mock(side_effect=OperationalError('commit failed')))


def assert_handle_cleared(cmd, tmp_path):
    for name in ('_staged_snapshot', '_snapshot_path', '_previous_path',
                 '_reconcile_map_relations', '_item_ids_by_name', '_available_skill_names'):
        assert not hasattr(cmd, name)
    assert cmd.base_path == str(tmp_path)
    assert not list(tmp_path.glob('.import-prev-*'))


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
    from django.apps import apps
    from django.db import connections, transaction
    cmd, module = importer
    alias = 'import_safety_test'
    connections.databases[alias] = dict(connections.databases['default'],
        ENGINE='django.db.backends.sqlite3', NAME=':memory:', OPTIONS={})
    connection = connections[alias]
    with connection.schema_editor() as editor:
        # Related tables support real deletion collectors and FK checks, too.
        for model in apps.get_models():
            editor.create_model(model)
    real_atomic = transaction.atomic
    monkeypatch.setattr(module.transaction, 'atomic', lambda *args, **kwargs: real_atomic(*args, **dict(kwargs, using=kwargs.get('using', alias))))
    real_manager = module.Version.objects.db_manager(alias)
    monkeypatch.setattr(module.Version, 'objects', real_manager)
    monkeypatch.setattr(module.Item_Type, 'objects', module.Item_Type.objects.db_manager(alias))
    try:
        yield real_manager
    finally:
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
    fail_at(monkeypatch, module, failure)
    audit = Mock(wraps=cmd._audit_item_types)
    monkeypatch.setattr(cmd, '_audit_item_types', audit)
    if failure:
        with pytest.raises(Exception, match='failed'):
            cmd.handle(update=1)
        assert list(isolated_db.all()) == []
        assert read(tmp_path / 'prev/version.json') == {'version': 'old'}
        audit.assert_not_called()
    else:
        cmd.handle(update=1)
        assert set(isolated_db.values_list('version', flat=True)) == {'new', 'intermediate'}
        assert read(tmp_path / 'prev/version.json') == {'version': 'new'}
        audit.assert_called_once_with()
    assert_handle_cleared(cmd, tmp_path)


@pytest.mark.parametrize('audit_error', [False, True])
def test_success_audit_is_after_cleanup_and_warning_only(
        importer, isolated_db, tmp_path, monkeypatch, caplog, audit_error):
    from django.db import connections, OperationalError
    cmd, module = importer
    monkeypatch.setattr(module.settings, 'REGION', 'test-region')
    write(tmp_path / 'version.json', {'version': 'new'})
    write(tmp_path / 'prev/version.json', {'version': 'old'})
    manager = module.Item_Type.objects
    for name, flag in [('Sword ', False), ('Sword ', False), ('Sword ', True),
                       ('Sword', False), ('sword ', False)]:
        manager.create(name=name, is_equipment=flag)
    monkeypatch.setattr(cmd, '_import_data', Mock())
    monkeypatch.setattr(cmd, '_validate_staged_release',
                        lambda directory: cmd.importJSON(Path(directory) / 'version.json'))
    original_values = manager.values_list
    audit_observations = []
    def values_list(*fields):
        audit_observations.append((
            connections[isolated_db.db].in_atomic_block,
            list(tmp_path.glob('.import-prev-*')),
            read(tmp_path / 'prev/version.json'),
            isolated_db.filter(version='new').exists()))
        if audit_error:
            raise OperationalError('audit unavailable')
        return original_values(*fields)
    monkeypatch.setattr(manager, 'values_list', Mock(side_effect=values_list))
    with caplog.at_level('WARNING'):
        cmd.handle(update=0)
    manager.values_list.assert_called_once_with('name', 'is_equipment')
    assert audit_observations == [(False, [], {'version': 'new'}, True)]
    assert_handle_cleared(cmd, tmp_path)
    cmd._import_data.assert_called_once_with(0)
    assert isolated_db.filter(version='new').exists()
    assert read(tmp_path / 'prev/version.json') == {'version': 'new'}
    if audit_error:
        assert 'audit failed REGION=test-region' in caplog.text
    else:
        messages = [record.getMessage() for record in caplog.records
                    if 'duplicate pair' in record.getMessage()]
        assert messages == [
            "Item_Type duplicate pair REGION=test-region name='Sword ' is_equipment=False count=2"]
    assert manager.count() == 5


def test_drop_update_and_delete_use_queryset(importer, monkeypatch):
    cmd, module = importer
    manager = Mock()
    monkeypatch.setattr(module.Item_Monster, 'objects', manager)
    mock_managers(monkeypatch, module.Monsters, module.Items)
    row = {'Monster': 4, 'Item': 8, 'Chance': 2, 'Quantity_MIN': 1, 'Quantity_MAX': 1}
    cmd.importItemMonster({'removed': [row], 'added': [], 'changed': [row]}, 1)
    manager.filter.assert_called_once_with(monster__ids=4, item__ids=8)
    manager.filter.return_value.delete.assert_called_once_with()
    manager.update_or_create.assert_called_once_with(
        monster=module.Monsters.objects.get.return_value,
        item=module.Items.objects.get.return_value,
        defaults={'chance': 2, 'qty_min': 1, 'qty_max': 1})
    module.Monsters.objects.get.assert_called_once_with(ids=4)
    module.Items.objects.get.assert_called_once_with(ids=8)


def test_npc_delete_uses_monster_field(importer, monkeypatch):
    cmd, module = importer
    mock_managers(monkeypatch, module.Maps, module.Monsters, module.Map_NPC)
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
    mock_managers(monkeypatch, module.Maps)
    module.Maps.objects.get.side_effect = module.Maps.DoesNotExist
    with pytest.raises(module.CommandError, match='not found'):
        cmd.importMapItem({'removed': [], 'added': [{'Map': 1, 'Item': 2}], 'changed': []}, 1)


@pytest.fixture
def type_rows(importer, monkeypatch):
    """Isolate classification from ORM lookup; exact pairs have separate tests."""
    cmd, module = importer
    rows, selected, saved = [], [], []
    def first(matches, field):
        row = min(matches, key=lambda row: getattr(row, field)) if matches else None
        selected.append(row)
        return row
    def save(row):
        saved.append(row)
        if not any(row is old for old in rows):
            row.pk = max((old.pk for old in rows), default=0) + 1
            rows.append(row)
    def lookup(name, is_equipment, cache=None):
        pair = (name, is_equipment)
        if cache is not None and pair in cache:
            return cache[pair], False
        row = first([row for row in rows
                     if (row.name, row.is_equipment) == pair], 'pk')
        created = row is None
        if created:
            row = module.Item_Type(name=name, is_equipment=is_equipment)
            save(row)
        if cache is not None:
            cache[pair] = row
        return row, created
    monkeypatch.setattr(module, 'get_or_create_item_type', Mock(side_effect=lookup))
    return cmd, module, rows, selected, saved


def item_row():
    return {'$ID': 1, '$ID_NAME': 'Shared', 'Name': 'Shared', 'TimeCoolDown': 0,
            'Description': '', 'Weight': 0, 'Tradability': 'TTTT', 'Type': 'Material',
            'Grade': 1, 'Icon': ''}


def eq_row():
    data = dict.fromkeys(('AnvilATK AnvilDEF AnvilPrice Durability Level Potential '
        'RequiredClass SocketsLimit Stars Stat_ATTACK_MAGICAL Stat_ATTACK_PHYSICAL_MIN '
        'Stat_ATTACK_PHYSICAL_MAX Stat_DEFENSE_MAGICAL Stat_DEFENSE_PHYSICAL '
        'TranscendPrice TypeAttack Unidentified UnidentifiedRandom').split(), 0)
    return dict(data, Type='Material', Bonus=[])


@pytest.mark.parametrize('kind', ['added', 'changed'])
def test_active_import_item_reuses_exact_pairs(importer, isolated_db, monkeypatch, kind):
    cmd, module = importer
    manager = module.Item_Type.objects
    generic = manager.create(name='Shared', is_equipment=False)
    equipment = manager.create(name='Shared', is_equipment=True)
    other = manager.create(name='shared', is_equipment=True)
    original = list(manager.order_by('pk').values_list('pk', 'name', 'is_equipment'))
    mock_managers(monkeypatch, module.Items, module.Equipments, module.Equipment_Bonus)
    row = dict(item_row(), **eq_row(), TypeEquipment='Shared')
    row['Type'] = 'Shared'
    changes = {'added': [], 'changed': [], 'removed': []}
    changes[kind] = [row, row]
    groups = {'EQUIPMENT': ['Shared'], 'CARD': [], 'RECIPES': [], 'COLLECTION': []}
    for _ in range(2):
        cmd.importItem(changes, groups, 1)
    assert list(manager.order_by('pk').values_list('pk', 'name', 'is_equipment')) == original
    assert manager.get(name='Shared', is_equipment=False).pk == generic.pk
    assert manager.get(name='Shared', is_equipment=True).pk == equipment.pk
    assert manager.get(name='shared', is_equipment=True).pk == other.pk


@pytest.mark.parametrize('equipment,existing', [
    ('Weapon', False), ('Weapon', True), ('Material', True),
    ('SEAL', True), ('Seal', True)])
def test_equipment_type_preserves_general_row(type_rows, monkeypatch, equipment, existing):
    cmd, module, rows, selected, saved = type_rows
    general = module.Item_Type(pk=1, name='Material', is_equipment=False)
    rows.append(general)
    if existing and equipment != general.name:
        rows.extend([module.Item_Type(pk=9, name=equipment, is_equipment=False),
                     module.Item_Type(pk=2, name='SEAL' if equipment == 'Seal' else equipment,
                                      is_equipment=False)])
    mock_managers(monkeypatch, module.Equipments, module.Equipment_Bonus)
    data = dict(eq_row(), TypeEquipment=equipment)
    cache = {}
    before = [(row.pk, row.name, row.is_equipment) for row in rows]
    for _ in range(2):
        cmd.makeEQ(Mock(), data, cache)
    assert rows[0] is general
    assert (general.pk, general.name, general.is_equipment) == (1, 'Material', False)
    result = saved[0]
    assert result.is_equipment is True
    assert result is not general
    assert selected == [None]
    assert saved == [result]
    assert len(rows) == len(before) + 1
    for row, state in zip(rows, before):
        assert (row.pk, row.name, row.is_equipment) == (
            state[0], state[1], state[2])
    assert result.name == equipment
    assert cache == {(equipment, True): result}
    module.Equipments.objects.get.return_value.save.assert_called_with()


@pytest.mark.parametrize('kind', ['added', 'changed'])
@pytest.mark.parametrize('names,query', [
    (['ARCANE', 'ARCANE'], 'arcane'), (['ARCANE', 'Arcane'], 'arcane'),
    (['SEAL', 'Seal'], 'Seal'), ([], 'New')])
def test_general_types_preserve_duplicate_state(type_rows, monkeypatch, kind, names, query):
    cmd, module, rows, selected, saved = type_rows
    rows.extend(module.Item_Type(pk=pk, name=name, is_equipment=pk == 2)
                for pk, name in zip((9, 2), names))
    before = [(row, vars(row).copy()) for row in rows]
    mock_managers(monkeypatch, module.Items)
    changes = {'added': [], 'changed': [], 'removed': []}
    changes[kind] = [dict(item_row(), Type=query)] * 2
    cmd.importItem(changes, dict.fromkeys(('EQUIPMENT', 'CARD', 'RECIPES', 'COLLECTION'), []), 1)
    for row, state in before:
        assert any(row is current for current in rows)
        assert vars(row) == state
    assert len(rows) == len(before) + 1
    assert saved == [rows[-1]]
    assert (rows[-1].name, rows[-1].is_equipment) == (query, False)
    assert selected == [None]


@pytest.mark.parametrize('kind', ['item', 'added', 'changed', 'equipment'])
def test_type_database_errors_propagate(type_rows, monkeypatch, kind):
    from django.db import OperationalError
    cmd, module, rows, _, saved = type_rows
    error = OperationalError('database down')
    module.get_or_create_item_type.side_effect = error
    mock_managers(monkeypatch, module.Items, module.Equipments)
    if kind == 'item':
        module.Items.objects.get.side_effect = error
    with pytest.raises(OperationalError, match='database down'):
        if kind == 'equipment':
            cmd.makeEQ(Mock(), dict(eq_row(), TypeEquipment='Seal'), {})
        else:
            changes = {'added': [], 'changed': [], 'removed': []}
            changes['added' if kind == 'item' else kind] = [item_row()]
            cmd.importItem(changes, {}, 1)
    assert rows == saved == []


@pytest.mark.parametrize('target', [None, 'missing'])
def test_declared_recipe_target_must_exist(importer, monkeypatch, target):
    cmd, module = importer
    mock_managers(monkeypatch, module.Recipes, module.Item_Recipe_Material, module.Item_Recipe_Target, module.Items)
    module.Recipes.objects.get.return_value = module.Recipes(pk=1)
    module.Items.objects.get.side_effect = module.Items.DoesNotExist
    row = {'Name': 'recipe', '$ID_NAME': 'R', 'Link_Materials': [], 'Link_Target': target}
    if target is None:
        cmd.makeRecipe(Mock(), row, [])
        module.Items.objects.get.assert_not_called()
    else:
        with pytest.raises(module.CommandError, match='target'):
            cmd.makeRecipe(Mock(), row, [])


@pytest.mark.parametrize('failure', [False, True])
def test_retired_attribute_skills_optional_but_database_errors_propagate(importer, monkeypatch, failure):
    from django.db import OperationalError
    cmd, module = importer
    mock_managers(monkeypatch, module.Attributes, module.Skills)
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


def empty_release(directory, version='snapshot-v1'):
    from ipfparser import contracts
    data = {name: {} for name in contracts.REQUIRED_COLLECTIONS}
    # Relations serialize as arrays, including when there are no rows. Keep
    # this fixture valid so snapshot lifecycle tests reach their own boundary.
    for name in contracts.RELATIONS:
        data[name] = []
    data['item_type'] = {name: [] for name in ('EQUIPMENT', 'CARD', 'RECIPES', 'COLLECTION')}
    data['version'] = {'version': version, 'metadata': {'labels': ['original']}}
    data['unresolved_map_links'] = []
    data['goddess_reinf'] = {}
    data['goddess_reinf_mat'] = {}
    data['auxiliary'] = {'nested': [1, 2]}
    for name, value in data.items():
        write(directory / (name + '.json'), value)
    return data


@pytest.mark.parametrize('collection', ['item_monster', 'map_item', 'map_npc', 'map_item_spawn'])
def test_snapshot_preserves_relation_array_diagnostics(importer, tmp_path, collection):
    from ipfparser import contracts
    data = empty_release(tmp_path)
    data[collection] = {}
    write(tmp_path / (collection + '.json'), data[collection])
    expected = (collection, 'type', 'expected an array of relations')
    for loader in (contracts.load_release, contracts.load_import_snapshot):
        with pytest.raises(contracts.ContractError) as error:
            loader(tmp_path)
        assert (error.value.path, error.value.code, error.value.message) == expected
    with pytest.raises(contracts.ContractError) as error:
        contracts.validate_release(data)
    assert (error.value.path, error.value.code, error.value.message) == expected


def test_snapshot_api_retains_only_consumed_values_and_reads_fresh(importer, tmp_path):
    from ipfparser import contracts
    data = empty_release(tmp_path)
    snapshot = contracts.load_import_snapshot(tmp_path)
    expected = set(contracts.REQUIRED_COLLECTIONS + contracts.REINFORCEMENT_COLLECTIONS + ('version',))
    assert set(snapshot) == expected
    assert snapshot == {name: data[name] for name in expected}
    snapshot['version']['metadata']['labels'].append('consumer')
    assert contracts.load_release(tmp_path) == data['version']
    assert contracts.load_import_snapshot(tmp_path)['version'] == data['version']
    (tmp_path / 'version.json').unlink()
    assert contracts.load_release(tmp_path, require_version=False) is None
    assert 'version' not in contracts.load_import_snapshot(tmp_path, require_version=False)


@pytest.mark.parametrize('file,contents', [
    ('auxiliary.json', '{"duplicate": 1, "duplicate": 2}'),
    ('auxiliary.json', '{"overflow": 1e999}'),
    ('unresolved_map_links.json', '{}'),
    ('goddess_reinf.json', 'null'),
])
def test_snapshot_preserves_release_diagnostics(importer, tmp_path, file, contents):
    from ipfparser import contracts
    empty_release(tmp_path)
    (tmp_path / file).write_text(contents)
    errors = []
    for loader in (contracts.load_release, contracts.load_import_snapshot):
        with pytest.raises(contracts.ContractError) as error:
            loader(tmp_path)
        errors.append(error.value)
    assert (errors[0].path, errors[0].code, errors[0].message) == (
        errors[1].path, errors[1].code, errors[1].message)
    assert str(errors[0]) == str(errors[1])


def test_snapshot_preserves_missing_file_and_sorted_json_error_order(importer, tmp_path):
    from ipfparser import contracts
    empty_release(tmp_path)
    (tmp_path / 'aaa.json').write_text('{broken')
    (tmp_path / 'zzz.json').write_text('{broken')
    (tmp_path / 'skills.json').unlink()
    for loader in (contracts.load_release, contracts.load_import_snapshot):
        with pytest.raises(contracts.ContractError) as error:
            loader(tmp_path)
        assert (error.value.path, error.value.code) == ('skills.json', 'required')
    write(tmp_path / 'skills.json', {})
    for loader in (contracts.load_release, contracts.load_import_snapshot):
        with pytest.raises(contracts.ContractError) as error:
            loader(tmp_path)
        assert (error.value.path, error.value.code) == (str(tmp_path / 'aaa.json'), 'json')


def test_staged_snapshot_copies_consumers_but_direct_and_previous_reads_are_fresh(importer, tmp_path):
    cmd, module = importer
    staged = tmp_path / 'staged'
    data = empty_release(staged)
    cmd._snapshot_path = str(staged)
    version = cmd._validate_staged_release(staged)
    version['metadata']['labels'].append('version-consumer')
    # A validation call alone never activates reuse.
    write(staged / 'version.json', {'version': 'direct'})
    assert cmd.importJSON(staged / 'version.json') == {'version': 'direct'}
    cmd.base_path = str(staged)
    assert cmd.importJSON(staged / 'version.json') == {'version': 'direct'}
    cmd._previous_path = str(tmp_path / 'prev')
    first = cmd.importJSON(staged / 'version.json')
    first['metadata']['labels'].append('mutable-consumer')
    assert cmd.importJSON(staged / 'version.json') == data['version']
    previous = tmp_path / 'prev/version.json'
    write(previous, {'version': 'old'})
    assert cmd.importJSON(previous) == {'version': 'old'}
    write(previous, {'version': 'changed-old'})
    assert cmd.importJSON(previous) == {'version': 'changed-old'}
    previous.write_text('{broken')
    with pytest.raises(module.CommandError):
        cmd.importJSON(previous)
    # Unconsumed staging collections remain fresh, too.
    write(staged / 'auxiliary.json', {'changed': True})
    assert cmd.importJSON(staged / 'auxiliary.json') == {'changed': True}
    other = tmp_path / 'other/version.json'
    write(other, {'version': 'other'})
    assert cmd.importJSON(other) == {'version': 'other'}
    cmd.base_path = str(tmp_path)
    write(tmp_path / 'version.json', {'version': 'outside'})
    assert cmd.importJSON(tmp_path / 'version.json') == {'version': 'outside'}


def test_failed_revalidation_discards_previous_snapshot(importer, tmp_path):
    cmd, module = importer
    empty_release(tmp_path)
    cmd._snapshot_path = str(tmp_path)
    cmd._validate_staged_release(tmp_path)
    cmd._previous_path = str(tmp_path / 'prev')
    assert cmd._staged_snapshot
    (tmp_path / 'auxiliary.json').write_text('{broken')
    with pytest.raises(module.CommandError, match='Invalid release'):
        cmd._validate_staged_release(tmp_path)
    assert not hasattr(cmd, '_staged_snapshot')
    write(tmp_path / 'version.json', {'version': 'fresh-direct'})
    assert cmd.importJSON(tmp_path / 'version.json') == {'version': 'fresh-direct'}


@pytest.mark.parametrize('failure', ['validation', 'import', 'publish', 'commit', None])
def test_real_snapshot_handle_clears_state_and_retry_reads_new_input(importer, isolated_db, tmp_path, monkeypatch, failure):
    cmd, module = importer
    empty_release(tmp_path)
    empty_release(tmp_path / 'prev', 'previous')
    original_prev = {p.name: p.read_bytes() for p in (tmp_path / 'prev').iterdir()}
    imported = []
    def import_data(update):
        imported.append(cmd.importJSON(Path(cmd.base_path) / 'version.json')['version'])
        cmd._available_skill_names = {'temporary'}
        cmd._item_ids_by_name = {'temporary': '1'}
        if failure == 'import':
            raise RuntimeError('import failed')
    monkeypatch.setattr(cmd, '_import_data', import_data)
    if failure == 'validation':
        (tmp_path / 'auxiliary.json').write_text('{broken')
    with monkeypatch.context() as faults:
        fail_at(faults, module, failure)
        if failure:
            with pytest.raises(Exception):
                cmd.handle(update=1)
            assert list(isolated_db.all()) == []
            assert {p.name: p.read_bytes() for p in (tmp_path / 'prev').iterdir()} == original_prev
        else:
            cmd.handle(update=1)
    assert_handle_cleared(cmd, tmp_path)
    failure = None
    empty_release(tmp_path, 'retry-v2')
    cmd.handle(update=1)
    assert imported[-1] == 'retry-v2'
    assert read(tmp_path / 'prev/version.json')['version'] == 'retry-v2'
    assert_handle_cleared(cmd, tmp_path)


def skill_row(identifier=10, job=1):
    return {'$ID': identifier, '$ID_NAME': 'Skill' + str(identifier), 'Name': 'Skill',
            'Link_Job': job, 'Icon': '', 'Description': '', 'BasicSP': 0,
            'RequiredStanceCompanion': 'No', 'Effect': '', 'Element': 'Fire',
            'MaxLevel': 5, 'UnlockClassLevel': 1, 'OverHeat': 1,
            'RequiredStance': '', 'CaptionRatio': [1, 2]}


@pytest.fixture
def skill_db(importer, isolated_db, monkeypatch):
    from django.db import connections
    _, module = importer
    alias = isolated_db.db
    for model in (module.Skills, module.Jobs):
        monkeypatch.setattr(model, 'objects', model.objects.db_manager(alias))
    original_save = module.Skills.save
    def save(instance, *args, **kwargs):
        kwargs['using'] = alias
        return original_save(instance, *args, **kwargs)
    monkeypatch.setattr(module.Skills, 'save', save)
    module.Jobs.objects.create(ids='1', id_name='Job1', name='Job', is_starter=True,
                               job_tree='Warrior', icon='', descriptions='')
    yield connections[alias]


def test_skill_prefetch_real_orm_saves_timestamps_and_deletion(importer, skill_db):
    from django.test.utils import CaptureQueriesContext
    cmd, module = importer
    rows = {str(i): skill_row(i) for i in range(10, 30)}
    with CaptureQueriesContext(skill_db) as first:
        cmd.importSkills(deepcopy(rows), 1)
    assert sum(q['sql'].lstrip().upper().startswith('INSERT') for q in first) == 20
    before = {s.ids: (s.pk, s.created, s.updated) for s in module.Skills.objects.all()}
    with CaptureQueriesContext(skill_db) as repeated:
        cmd.importSkills(deepcopy(rows), 1)
    assert sum(q['sql'].lstrip().upper().startswith('UPDATE') for q in repeated) == 20
    assert sum(q['sql'].lstrip().upper().startswith('SELECT') for q in repeated) == 3
    for saved in module.Skills.objects.all():
        pk, created, updated = before[saved.ids]
        assert (saved.pk, saved.created) == (pk, created)
        assert saved.updated >= updated
        assert saved.job_id == module.Jobs.objects.get(ids='1').pk
    cmd.importSkills({'10': skill_row('10', '1')}, 1)
    assert list(module.Skills.objects.values_list('ids', flat=True)) == ['10']
    with CaptureQueriesContext(skill_db) as single:
        cmd.importSkills({'10': skill_row(10, 1)}, 1)
    assert sum(q['sql'].lstrip().upper().startswith('SELECT') for q in single) == 3
    assert sum(q['sql'].lstrip().upper().startswith('UPDATE') for q in single) == 1


def test_active_snapshot_survives_mutating_skill_consumer(importer, skill_db, tmp_path):
    cmd, _ = importer
    data = empty_release(tmp_path)
    data['jobs'] = [{'$ID': 1, '$ID_NAME': 'Job1', 'Name': 'Job',
                     'IsStarter': True, 'JobTree': 'Warrior', 'Icon': '', 'Description': ''}]
    data['skills'] = {'10': skill_row()}
    data['skills']['10']['CaptionRatio'] = [1.5, 2.5]
    write(tmp_path / 'jobs.json', data['jobs'])
    write(tmp_path / 'skills.json', data['skills'])
    cmd._snapshot_path = str(tmp_path)
    cmd._validate_staged_release(tmp_path)
    cmd._previous_path = str(tmp_path / 'prev')
    consumer = cmd.importJSON(tmp_path / 'skills.json')
    cmd.importSkills(consumer, 1)
    assert consumer['10']['CaptionRatio'] == [1, 2]
    assert cmd.importJSON(tmp_path / 'skills.json') == data['skills']
    assert read(tmp_path / 'skills.json') == data['skills']


@pytest.mark.parametrize('target', ['skill', 'job'])
@pytest.mark.parametrize('update', [0, 1])
def test_ambiguous_ids_raise_at_original_consumer(importer, monkeypatch, target, update):
    cmd, module = importer
    skill_manager, job_manager = Mock(), Mock()
    monkeypatch.setattr(module.Skills, 'objects', skill_manager)
    monkeypatch.setattr(module.Jobs, 'objects', job_manager)
    skill_manager.values_list.return_value = []
    duplicates = [Mock(ids='10'), Mock(ids=10)]
    skill_manager.filter.return_value = duplicates if target == 'skill' else []
    job_manager.filter.return_value = [Mock(ids='1'), Mock(ids=1)]
    manager = skill_manager if target == 'skill' else job_manager
    model = module.Skills if target == 'skill' else module.Jobs
    manager.get.side_effect = model.MultipleObjectsReturned
    save = Mock()
    monkeypatch.setattr(module.Skills, 'save', save)
    with pytest.raises(model.MultipleObjectsReturned):
        cmd.importSkills({'10': skill_row()}, update)
    manager.get.assert_called_once_with(ids=10 if target == 'skill' else 1)
    save.assert_not_called()


def test_missing_job_and_prefetch_database_errors_propagate(importer, monkeypatch):
    from django.db import OperationalError
    cmd, module = importer
    mock_managers(monkeypatch, module.Skills, module.Jobs)
    module.Skills.objects.filter.return_value = []
    module.Jobs.objects.filter.return_value = []
    module.Jobs.objects.get.side_effect = module.Jobs.DoesNotExist
    with pytest.raises(module.Jobs.DoesNotExist):
        cmd.importSkills({'10': skill_row()}, 1)
    module.Jobs.objects.get.assert_called_once_with(ids=1)
    module.Skills.objects.filter.side_effect = OperationalError('prefetch failed')
    with pytest.raises(OperationalError, match='prefetch failed'):
        cmd.importSkills({'10': skill_row()}, 1)


def test_update_zero_retains_original_skip_and_deletion_behavior(importer, monkeypatch):
    cmd, module = importer
    existing = Mock(ids='10')
    mock_managers(monkeypatch, module.Skills, module.Jobs)
    module.Skills.objects.filter.return_value = [existing]
    module.Jobs.objects.filter.return_value = []
    all_rows = [('10',)]
    module.Skills.objects.values_list.return_value = all_rows
    deletion = Mock()
    monkeypatch.setattr(cmd, 'deleteMe', deletion)
    cmd.importSkills({'10': skill_row()}, 0)
    existing.save.assert_not_called()
    module.Skills.objects.get.assert_not_called()
    module.Jobs.objects.get.assert_not_called()
    module.Jobs.objects.filter.assert_called_once_with(ids__in=set())
    # Existing update=0 rows were always omitted from the deletion keep list.
    deletion.assert_called_once_with(all_rows, [], module.Skills, 'Skills')


@pytest.mark.parametrize('kind', ['added', 'changed'])
def test_classification_indexes_preserve_lists_priority_and_missing_group_errors(importer, monkeypatch, kind):
    cmd, module = importer
    mock_managers(monkeypatch, module.Items, module.Item_Type)
    module.Item_Type.objects.all.return_value = [module.Item_Type(name='Material')]
    monkeypatch.setattr(module, 'get_or_create_item_type',
                        Mock(return_value=(module.Item_Type(name='Material'), False)))
    groups = {'EQUIPMENT': ['Shared'], 'CARD': ['Shared'], 'RECIPES': [], 'COLLECTION': []}
    before = deepcopy(groups)
    lists = list(groups.values())
    row = item_row()
    changes = {'added': [], 'changed': [], 'removed': []}
    changes[kind] = [row]
    for method in ('makeEQ', 'makeCard', 'makeRecipe', 'makeCollection'):
        monkeypatch.setattr(cmd, method, Mock())
    cmd.importItem(changes, groups, 1)
    assert groups == before
    assert all(current is original for current, original in zip(groups.values(), lists))
    cmd.makeEQ.assert_called_once()
    cmd.makeCard.assert_not_called()
    cmd.makeRecipe.assert_not_called()
    cmd.makeCollection.assert_not_called()
    with pytest.raises(KeyError, match='EQUIPMENT'):
        cmd.importItem(changes, {'CARD': ['Shared']}, 1)
