"""Capture a small real game snapshot; parse copies without touching local game state."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'harness/fixtures/live'
REGIONS = ('itos', 'ktos')
IDS = {'11107087', '11107103', '11107104', '11107094', '11100079', '11100080', '643501', '643580'}
MATERIALS = {'SauleCertificate', 'AustejaCertificate', 'misc_BlessedStone_2', 'misc_ore30',
             'misc_ore29', 'misc_boss_EP18_weapon_NoTrade', 'misc_boss_EP18_armor_NoTrade',
             'misc_ep18_acc_NoTrade'}
LUA_FILES = ('item_calculate.lua', 'item_legend_shared.lua', 'shared_item_goddess_reinforce.lua',
             'item_transcend_shared.lua', 'pcbang_shared.lua', 'lib_math.lua')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(source_root, destination):
    from DB import ToS_DB
    source_root, destination = Path(source_root).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError('Capture destination must be new; reviewed snapshots are never overwritten')
    manifest = {'schema': 1, 'regions': {}, 'files': {}}
    destination.mkdir(parents=True)
    for region in REGIONS:
        source = source_root / (region + '_unpack')
        target = destination / region / 'unpack'
        selected, values = set(), set()

        def record(original, output, rows=None):
            key = output.relative_to(destination).as_posix()
            manifest['files'][key] = {'source': original.relative_to(source_root).as_posix(),
                                     'source_sha256': digest(original), 'sha256': digest(output)}
            if rows is not None:
                manifest['files'][key]['class_ids'] = [row['ClassID'] for row in rows]

        for name in ToS_DB.ITEM_IES:
            matches = [p for p in (source / 'ies.ipf').iterdir() if p.name.lower() == name.lower()]
            if not matches:
                continue
            original = matches[0]
            with original.open(encoding='utf-8-sig', newline='') as stream:
                reader = csv.DictReader(stream)
                fields = reader.fieldnames
                rows = [row for row in reader if row['ClassID'] in IDS or row['ClassName'] in MATERIALS]
            if not rows:
                continue
            output = target / 'ies.ipf' / name
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            selected.update(row['ClassID'] for row in rows)
            values.update(value for row in rows for value in row.values())
            record(original, output, rows)
        if not IDS <= selected:
            raise ValueError('Missing real source IDs for {}: {}'.format(region, sorted(IDS - selected)))
        # Model assets are outside this numeric sample; retain the real header.
        original = source / 'ies_client.ipf/xac.ies'
        with original.open(encoding='utf-8-sig', newline='') as stream:
            fields = csv.DictReader(stream).fieldnames
        output = target / 'ies_client.ipf/xac.ies'
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('w', encoding='utf-8', newline='') as stream:
            csv.DictWriter(stream, fieldnames=fields).writeheader()
        record(original, output, [])
        for name in ('item_grade.ies', 'sharedconst.ies', 'sharedconst_system.ies',
                     *ToS_DB.EQUIPMENT_REINFORCE_IES, 'item_goddess_reinforce_580.ies'):
            original, output = source / 'ies.ipf' / name, target / 'ies.ipf' / name
            shutil.copy2(original, output)
            record(original, output)
        for name in LUA_FILES:
            original, output = source / 'shared.ipf/script' / name, target / 'shared.ipf' / name
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, output)
            record(original, output)
        original = source / 'xml.ipf/socket_property.xml'
        socket = ET.parse(original)
        for node in list(socket.getroot()):
            if node.get('Name') not in ('gem_circle_1', 'Gem_Wizard_EnergyBolt'):
                socket.getroot().remove(node)
        output = target / 'xml.ipf/socket_property.xml'
        output.parent.mkdir(parents=True, exist_ok=True)
        socket.write(output, encoding='utf-8', xml_declaration=True)
        record(original, output)
        if region == 'itos':
            original = source / 'language.ipf/wholeDicID.xml'
            dictionary = ET.parse(original)
            identifiers = set()
            for group in list(dictionary.getroot()):
                for node in list(group):
                    if node.get('original') not in values:
                        group.remove(node)
                    else:
                        identifiers.update(re.findall(r'@dicID_\^\*\$(.*?)\$\*\^', node.get('dicid', '')))
                if not len(group):
                    dictionary.getroot().remove(group)
            output = target / 'language.ipf/wholeDicID.xml'
            output.parent.mkdir(parents=True, exist_ok=True)
            dictionary.write(output, encoding='utf-8', xml_declaration=True)
            record(original, output)
            directory = destination / region / 'translation'
            directory.mkdir()
            for original in sorted((source_root / 'Translation/English').glob('*.tsv')):
                rows = [line for line in original.read_text(encoding='utf-8').splitlines()
                        if line.split('\t', 1)[0] in identifiers]
                if rows:
                    output = directory / original.name
                    output.write_text('\n'.join(rows) + '\n', encoding='utf-8')
                    record(original, output)
        revision = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'],
                                  capture_output=True, text=True, check=True).stdout.strip()
        manifest['regions'][region] = {'unpack_commit': revision, 'selected_ids': sorted(selected)}
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


def verify_snapshot(fixture=FIXTURE):
    fixture = Path(fixture)
    manifest = json.loads((fixture / 'manifest.json').read_text())
    if manifest.get('schema') != 1 or set(manifest['regions']) != set(REGIONS):
        raise ValueError('Incomplete real source manifest')
    for name, entry in manifest['files'].items():
        path = (fixture / name).resolve()
        if fixture.resolve() not in path.parents or digest(path) != entry['sha256']:
            raise ValueError('Real source snapshot integrity failed: ' + name)
    return manifest


def prepare_workspace(root, region, fixture=FIXTURE):
    if region not in REGIONS:
        raise ValueError('Unsupported real sample region: ' + region)
    verify_snapshot(fixture)
    root = Path(root)
    shutil.copytree(Path(fixture) / region / 'unpack', root / (region + '_unpack'))
    if region == 'itos':
        shutil.copytree(Path(fixture) / region / 'translation', root / 'Translation/English')
    (root / 'parser_tidy').mkdir()
    (root / 'TavernofSoul' / ('JSON_' + region)).mkdir(parents=True)
    (root / 'TavernofSoul/staticfiles_itos').mkdir()
    return root


def parse_workspace(root, region, version='real-sample-v1'):
    from DB import ToS_DB
    import items
    import parse_xac
    import translation
    from harness.parser_fixture import isolated_parser_state
    db = ToS_DB()
    db.data = {name: [] if isinstance(value, list) else {} for name, value in ToS_DB.data.items()}
    db.file_dict = {}
    db.data['item_type'] = {'RECIPES': []}
    db.build(region, str(Path(root) / 'parser_tidy'))
    with isolated_parser_state():
        parse_xac.parse_xac(db)
        if region == 'itos':
            translation.makeDictionary(db)
        items.parse(db)
        db.export({'version': version})
    return db


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    import sys
    sys.path.insert(0, str(ROOT / 'parser_tidy'))
    capture(args.source_root, args.output_dir)
