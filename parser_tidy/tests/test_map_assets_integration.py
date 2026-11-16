"""Synthetic publisher/consumer generation in a clean, disposable Git checkout."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest

PYTHON27 = shutil.which('python2.7')
CHILD = r'''
import json, os, sys
root, region, phase, expected = sys.argv[1:5]
assert tuple(sys.version_info[:2]) == tuple(map(int, expected.split('.')))
assert sys.dont_write_bytecode and os.environ['PYTHONDONTWRITEBYTECODE'] == '1'
sys.path.insert(0, os.path.join(root, 'parser_tidy'))
import map_assets as a
class Context(object): pass
c = Context(); c.region = region
c.PATH_INPUT_DATA = os.path.join(root, region + '_unpack')
c.PATH_BUILD_ASSETS_IMAGES_MAPS = os.path.join(root, 'TavernofSoul', 'staticfiles_itos', 'maps')
c.file_dict = {'map.ies': {'path': os.path.join(c.PATH_INPUT_DATA, 'map.ies')}}
c.data = {'maps': {}, 'maps_by_name': {}}
for row in a.rows(c):
    obj = {'$ID': row['ClassID'], 'bbox': [0, 0, 0, 0]}
    c.data['maps'][row['ClassID']] = obj; c.data['maps_by_name'][row['ClassName']] = obj
summaries = {}
a.summary = lambda kind, counts: summaries.update({kind: dict(counts)})
if phase == 'tok27':
    import map_image
    map_image.parse_maps_images(c)
elif phase == 'polygon3':
    # CI has no Python 2: exercise the real cache writer with synthetic conversion.
    assets = a.Assets(c); counts = a.counters()
    original = a.read(os.path.join(c.PATH_INPUT_DATA, 'bg.ipf', 'Cache.tok'))
    def convert(stream):
        assert stream.read() == original
        return [[[-8, 8], [8, 8], [0, -8]]]
    for row in a.rows(c): assets.polygon(row, counts, convert)
    a.summary('polygon', counts)
else:
    import maps
    maps.parse_maps_images(c)
assert not any(v['errors'] for v in summaries.values()), summaries
print(json.dumps({'summaries': summaries, 'version': list(sys.version_info[:2]),
                  'bbox': {k: v['bbox'] for k, v in c.data['maps_by_name'].items()}}))
'''


def put(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists(): path.chmod(mode | stat.S_IWUSR)
    path.write_bytes(data)
    path.chmod(mode)


def synthetic_tok():
    # Minimal TOK string/attribute tables and one triangle, never game data.
    def node(index, attrs=b'', children=b''):
        return struct.pack('B', index) + attrs + b'\0' + children + b'\0'
    def attr(index, value): return struct.pack('B', index) + str(value).encode('ascii') + b'\0'
    verts = b''.join(node(4, attr(1, x) + attr(2, y)) for x, y in ((-8, -8), (8, -8), (0, 8)))
    edges = b''.join(node(7, attr(3, i)) for i in range(3))
    return (b'mesh\0mesh3D\0verts\0vert\0mappingTo2D\0polygon\0edge\0\0'
            + b'\1x\0\1y\0\1startVert\0\0'
            + node(1, children=node(2, children=node(3, children=verts))
                   + node(5, children=node(6, children=edges))))


class MapAssetsGitClean(unittest.TestCase):
    def pipeline(self, python27=None):
        self.assertEqual(sys.version_info[:2], (3, 8))
        source = Path(__file__).resolve().parents[2]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        with tempfile.TemporaryDirectory(prefix='map-assets-git-') as temporary:
            checkout = Path(temporary).resolve()
            def git(*args):
                result = subprocess.run(['git'] + list(args), cwd=str(checkout), env=env,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout
            ignores = []
            for directory, dirs, files in os.walk(str(source)):
                dirs[:] = [d for d in dirs if d != '.git' and (Path(directory) / d).resolve() != checkout]
                if '.gitignore' in files:
                    relative = (Path(directory) / '.gitignore').relative_to(source)
                    put(checkout / relative, (source / relative).read_bytes()); ignores.append(relative.as_posix())
            self.assertIn('TavernofSoul/.gitignore', ignores)
            for module in (source / 'parser_tidy').glob('*.py'):
                put(checkout / 'parser_tidy' / module.name, module.read_bytes())
            package = Path('TavernofSoul/ipfparser')
            for filename in ('__init__.py', 'contracts.py'):
                put(checkout / package / filename, (source / package / filename).read_bytes())
            seed = checkout / 'parser_tidy/maps_poly/seedpoly.json'
            polygon = b'[[[-8,8],[8,8],[0,-8]]]'
            put(seed, polygon, 0o444); put(seed, polygon, 0o444)
            rows = b'ClassID,ClassName,BgName,Width,Height\n1,Seed,,64,64\n2,Cache,,64,64\n'
            for region in ('ktos', 'itos'):
                put(checkout / (region + '_unpack/map.ies'), rows)
                put(checkout / (region + '_unpack/bg.ipf/Cache.tok'), synthetic_tok() if region == 'ktos' else b'unused consumer TOK')
            (checkout / 'TavernofSoul/staticfiles_itos/maps').mkdir(parents=True)
            git('init', '-q'); git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@invalid', 'commit', '-qm', 'synthetic baseline')
            git('ls-files', '--error-unmatch', 'parser_tidy/maps_poly/seedpoly.json')
            def clean():
                self.assertEqual(git('status', '--porcelain=v1', '--untracked-files=all'), '')
                self.assertFalse(list(checkout.rglob('*.pyc')) + list(checkout.rglob('*.pyo')))
            def snapshot():
                result = {}
                for directory, dirs, files in os.walk(str(checkout)):
                    dirs[:] = [d for d in dirs if d != '.git']
                    for filename in files:
                        path = Path(directory) / filename; info = path.stat()
                        result[path.relative_to(checkout).as_posix()] = (
                            hashlib.sha256(path.read_bytes()).hexdigest(), info.st_mtime_ns, stat.S_IMODE(info.st_mode))
                return result
            def run(region, phase):
                executable = python27 if phase == 'tok27' else sys.executable
                version = '2.7' if phase == 'tok27' else '3.8'
                result = subprocess.run([executable, '-B', '-c', CHILD, str(checkout), region, phase, version],
                                        cwd=str(checkout), env=env, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, universal_newlines=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                value = json.loads(result.stdout.strip().splitlines()[-1])
                self.assertEqual(value['version'], [int(n) for n in version.split('.')])
                return value
            clean(); before_seed = snapshot()['parser_tidy/maps_poly/seedpoly.json']
            converted = run('ktos', 'tok27' if python27 else 'polygon3')
            self.assertEqual(converted['summaries']['polygon']['generated'], 1)
            self.assertEqual(converted['summaries']['polygon']['reused'], 1)
            published = run('ktos', 'png')
            self.assertEqual(published['summaries']['PNG']['generated'], 2)
            clean(); before = snapshot()
            self.assertEqual(before['parser_tidy/maps_poly/seedpoly.json'], before_seed)
            self.assertEqual(len(list((checkout / 'TavernofSoul/staticfiles_itos/maps').glob('*.png'))), 2)
            self.assertTrue(list((checkout / 'parser_tidy/.map_assets/ktos').glob('*poly.json')))
            self.assertEqual(len(list((checkout / 'parser_tidy/.map_assets/ktos').glob('*.png.meta.json'))), 2)
            if python27:
                skipped = run('itos', 'tok27')
                self.assertTrue(all(not any(v.values()) for v in skipped['summaries'].values()))
            consumed = run('itos', 'png')
            self.assertEqual(consumed['summaries']['PNG']['reused'], 2)
            self.assertEqual(consumed['bbox'], published['bbox'])
            self.assertTrue(all(b != [0, 0, 0, 0] for b in consumed['bbox'].values()))
            self.assertEqual(snapshot(), before)
            self.assertFalse((checkout / 'parser_tidy/.map_assets/itos').exists())
            clean()

    def test_python38_git_clean(self):
        self.pipeline()

    if PYTHON27 is not None:
        def test_installed_python27_git_clean(self):
            self.pipeline(PYTHON27)
