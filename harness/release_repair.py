"""Prepare a validated release in a NEW directory from existing JSON and IES.

This is an explicit data repair, never an automatic import fallback. It does not
modify the input, unpack directories, comparison baseline, database or versions.
Run with the harness Python path (TavernofSoul and parser_tidy).
"""
import argparse
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from ipfparser.contracts import (ContractError, REQUIRED_COLLECTIONS, canonical_item_id,
                                 load_json, number, validate_release)
import drop_source
import maps
import monsters


def prepare_release(source, destination, project, region):
    source, destination, project = map(Path, (source, destination, project))
    if destination.exists():
        raise ValueError('Repair output must be a new directory')
    data = {path.stem: load_json(path) for path in source.glob('*.json')}
    before = copy.deepcopy(data)
    # Check the required files before source parsing; never silently fabricate
    # missing importer collections.
    for name in REQUIRED_COLLECTIONS + ('version',):
        if name not in data:
            raise ContractError(name, 'required', 'missing release collection')
    context = SimpleNamespace(data=data, region=region,
                              PATH_INPUT_DATA=str(project / (region + '_unpack')))
    actual_source = drop_source.get_drop_source(context)
    if actual_source['drop_ipf'] is None:
        raise ValueError('Drop source missing; cannot reconstruct probabilities or recipe identity')
    revisions = drop_source._read_revision(str(project))
    if str(revisions.get(region)) != str(data['version']['version']).split('_')[0]:
        raise ValueError('Region unpack revision does not match the release being repaired')
    for collection in ('item_monster', 'map_item'):
        for row in data[collection]:
            if row.get('SourceRegion') != actual_source['source_region']:
                raise ValueError('Drop provenance mismatch: ' + collection)
    # Older 550 accessories serialized BasicAccAtk as integer strings. The
    # current parser writes integers. Do not coerce arbitrary equipment stats.
    for name in data['item_type']['EQUIPMENT']:
        row = data['items_by_name'][name]
        if row.get('Grade') == 6 and row.get('TypeEquipment') in ('Earring', 'Ring', 'Neck', 'Seal'):
            for field in ('Stat_ATTACK_MAGICAL', 'Stat_ATTACK_PHYSICAL_MIN', 'Stat_ATTACK_PHYSICAL_MAX'):
                value = row[field]
                if isinstance(value, str) and value.isdecimal():
                    row[field] = int(value)
    # The old IntegerField importer silently stored decimal strings as zero.
    # Making these four source factors numeric also triggers their diff update.
    skill_rows = data['skill_mon'].values() if isinstance(data['skill_mon'], dict) else data['skill_mon']
    for row in skill_rows:
        if isinstance(row.get('SFR'), str) and '.' in row['SFR']:
            row['SFR'] = number(row['SFR'], 'skill_mon.SFR', raw=True)
    data.setdefault('unresolved_drops', [])
    data['unresolved_drops'] = [row for row in data['unresolved_drops']
                                if row.get('collection') not in ('item_monster', 'map_item')]
    data.setdefault('build_provenance', {})
    monsters.parse_links(context)
    data['map_item'] = []
    maps.parse_links_items(context)
    # Spawn IDs have no chance/variant bug. Resolve only unambiguous historical
    # aliases; ambiguous IDs require their source ClassName, never a guessed FK.
    candidates = {}
    recipes = set(data['item_type']['RECIPES'])
    for row in data['items_by_name'].values():
        candidates.setdefault(str(row['$ID']), set()).add(canonical_item_id(row, recipes))
    for row in data['map_item_spawn']:
        choices = candidates.get(str(row['Item']), set())
        if len(choices) > 1:
            raise ValueError('Ambiguous spawn item ID: ' + str(row['Item']))
        if len(choices) == 1:
            row['Item'] = next(iter(choices))
    validate_release(data)
    changed = sorted(name for name in data if data[name] != before.get(name))
    destination.mkdir(parents=True)
    for name, value in data.items():
        # Preserve identical bytes including unknown metadata files.
        target = destination / (name + '.json')
        if name not in changed:
            target.write_bytes((source / target.name).read_bytes())
        else:
            target.write_text(json.dumps(value, ensure_ascii=False, indent=4), encoding='utf-8')
    return {'region': region, 'version': data['version'], 'changed': changed,
            'source': actual_source,
            'previous_source_versions': sorted({str(row.get('InputVersion'))
                                                for name in ('item_monster', 'map_item')
                                                for row in before[name]}),
            'relations': {name: {'before': len(before[name]), 'after': len(data[name])}
                          for name in ('item_monster', 'map_item', 'map_item_spawn')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--project', required=True)
    parser.add_argument('--region', required=True, choices=('itos', 'ktos', 'jtos', 'ktest', 'twtos'))
    args = parser.parse_args()
    print(json.dumps(prepare_release(args.source, args.destination, args.project, args.region),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
