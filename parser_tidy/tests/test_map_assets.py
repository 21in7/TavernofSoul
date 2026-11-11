"""Synthetic regressions only. The workflow owns execution of these tests."""
import contextlib
import glob
import json
import os
import shutil
import stat
import subprocess
import sys
import types

SOURCE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(SOURCE)
POLY = [[[0, 0], [12, 0], [0, 12]]]
SEED = [[[1, 1], [9, 1], [1, 9]]]
ROW = dict(ClassName='Zone', BgName='bg.ipf\\Sub\\Actual.TOK', Width='100', Height='100')


def put(path, data):
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    with open(path, 'wb') as stream:
        stream.write(data)


def load(name, root):
    module = types.ModuleType(name)
    module.__file__ = os.path.join(root, name + '.py')
    sys.modules[name] = module
    with open(os.path.join(SOURCE, name + '.py'), 'rb') as stream:
        exec(compile(stream.read(), module.__file__, 'exec'), module.__dict__)
    return module


@contextlib.contextmanager
def patch(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


def fail(*args, **kwargs):
    raise IOError('injected failure')


def snapshot(m, paths):
    return [(m.read(path), stat.S_IMODE(os.stat(path).st_mode)) for path in paths]


def atomic_cases(m, base):
    path, meta = os.path.join(base, 'asset'), os.path.join(base, 'meta')
    def writer(temp):
        put(temp, b'new')
    old_umask = os.umask(0o077)
    try:
        m.publish(path, meta, writer, lambda p: len(m.read(p)), {})
    finally:
        os.umask(old_umask)
    assert [mode for _, mode in snapshot(m, (path, meta))] == [0o644, 0o644]
    os.chmod(path, 0o640)
    os.chmod(meta, 0o664)
    m.publish(path, meta, writer, lambda p: len(m.read(p)), {})
    before = snapshot(m, (path, meta))
    def failure_at(original, position):
        count = [0]
        def call(*args):
            count[0] += 1
            if count[0] == position:
                raise IOError('injected operation failure')
            return original(*args)
        return call
    original_open = open
    def metadata_failure(path, mode='r', *args, **kwargs):
        if active[0] is not None and mode == 'wb' and os.path.basename(path).startswith('.map-') and path != active[0]:
            raise IOError('metadata save failure')
        return original_open(path, mode, *args, **kwargs)
    active = [None]
    def tracked_writer(temp):
        active[0] = temp
        writer(temp)
    injections = [(m, 'encoded', fail), (m.os, 'chmod', failure_at(m.os.chmod, 3)),
                  (m.os, 'rename', failure_at(m.os.rename, 1)), (m.os, 'rename', failure_at(m.os.rename, 2))]
    for obj, key, replacement in injections:
        with patch(obj, key, replacement):
            try:
                m.publish(path, meta, writer, lambda p: len(m.read(p)), {})
                assert False, key
            except IOError:
                pass
        assert snapshot(m, (path, meta)) == before
    for write, validate in ((fail, m.read), (writer, fail)):
        try:
            m.publish(path, meta, write, validate, {})
            assert False
        except IOError:
            pass
        assert snapshot(m, (path, meta)) == before
    # Fail opening staged metadata, after artifact validation and before replacement.
    m.open = original_open
    try:
        with patch(m, 'open', metadata_failure):
            try:
                m.publish(path, meta, tracked_writer, lambda p: len(m.read(p)), {})
                assert False
            except IOError:
                pass
    finally:
        del m.open
    assert snapshot(m, (path, meta)) == before
    assert sorted(os.listdir(base)) == ['asset', 'meta']


def polygon_cases(m, work):
    root, input_path = os.path.join(work, 'parser'), os.path.join(work, 'itos_unpack')
    tok = os.path.join(input_path, 'bg.ipf', 'Sub', 'Actual.TOK')
    seed = os.path.join(root, 'maps_poly', 'zonepoly.json')
    put(tok, b'valid TOK'); put(seed, m.encoded(SEED))
    for data in (b'a' * 31, b'a' * 33, b'a' * 31 + b'\n', b' ' + b'a' * 31, b'z' * 32):
        assert not m.placeholder(data)
    assert m.placeholder(b'aB09' * 8)
    a = m.Assets(input_path, root)
    assert a.source(ROW)[0] == tok
    assert a.source(dict(ROW, BgName='sub/actual'))[0] == tok
    for bg in ('', None):
        assert a.source(dict(ROW, ClassName='Actual', BgName=bg))[0] == tok
    assert a.source({'ClassName': 'Actual'})[0] == tok
    for bg in ('../Actual', '/Actual', 'C:/Actual', 'missing'):
        try:
            a.source(dict(ROW, BgName=bg)); assert False
        except (IOError, ValueError):
            pass
    other = os.path.join(input_path, 'bg.ipf', 'Other', 'Actual.TOK')
    put(other, b'other')
    a = m.Assets(input_path, root)
    assert a.source(ROW)[0] == tok  # Exact relative path wins over basename collision.
    try:
        a.source(dict(ROW, BgName='actual')); assert False
    except ValueError:
        pass
    os.unlink(other)
    put(os.path.join(input_path, 'bg.ipf', 'Sub', 'actual.tok'), b'case collision')
    a = m.Assets(input_path, root)
    assert a.source(ROW)[0] == tok
    try:
        a.source(dict(ROW, BgName='SUB/ACTUAL')); assert False
    except ValueError:
        pass
    os.unlink(os.path.join(input_path, 'bg.ipf', 'Sub', 'actual.tok'))
    a = m.Assets(input_path, root)
    calls = []
    def convert(data):
        calls.append(data)
        return POLY
    old_umask = os.umask(0o077)
    try:
        assert a.polygon(ROW, convert) == POLY
    finally:
        os.umask(old_umask)
    cache = os.path.join(a.cache, 'zonepoly.json')
    assert [mode for _, mode in snapshot(m, (cache, cache + '.meta.json'))] == [0o644, 0o644]
    os.chmod(cache, 0o640); os.chmod(cache + '.meta.json', 0o664)
    assert a.polygon(ROW, convert) == POLY and len(calls) == 1
    put(tok, b'changed TOK'); a.polygon(ROW, convert)
    assert [mode for _, mode in snapshot(m, (cache, cache + '.meta.json'))] == [0o640, 0o664]
    with patch(m, 'POLYGON_VERSION', 2):
        a.polygon(ROW, convert)
    assert a.counts['polygon'] == dict(generated=3, reused=1, placeholder=0, missing=0, errors=0)
    assert a.polygon(ROW) == SEED and a.counts['polygon']['errors'] == 0
    put(cache, b'corrupt'); a.polygon(ROW, convert)
    put(cache + '.meta.json', b'broken'); a.polygon(ROW, convert)
    os.unlink(cache + '.meta.json'); a.polygon(ROW, convert)
    put(cache, m.encoded(SEED)); a.polygon(ROW, convert)  # Valid JSON with a mismatched hash is corrupt.
    assert len(calls) == 7
    assert a.counts['polygon']['errors'] == 4
    assert [mode for _, mode in snapshot(m, (cache, cache + '.meta.json'))] == [0o640, 0o644]
    saved = snapshot(m, (cache, cache + '.meta.json'))
    put(tok, b'aB09' * 8)
    assert a.polygon(ROW, fail) == SEED and a.counts['polygon']['placeholder'] == 1
    assert snapshot(m, (cache, cache + '.meta.json')) == saved
    os.unlink(tok)
    assert a.polygon(ROW, fail) == SEED and a.counts['polygon']['missing'] == 1
    put(tok, b'bad TOK')
    assert a.polygon(ROW, fail) == SEED and a.counts['polygon']['errors'] == 5
    assert snapshot(m, (cache, cache + '.meta.json')) == saved
    os.unlink(cache + '.meta.json')
    assert a.polygon(ROW) == SEED  # Metadata-free cache is never a cache hit.
    assert m.Assets(os.path.join(work, 'ktos_unpack'), root).cache != a.cache
    assert m.read(seed) == m.encoded(SEED) and os.listdir(os.path.dirname(seed)) == ['zonepoly.json']


def png_cases(m, work):
    from PIL import Image
    a = m.Assets(os.path.join(work, 'itos_unpack'), os.path.join(work, 'png-parser'))
    path = os.path.join(work, 'images', 'zone.png')
    calls = []
    def render(temp):
        calls.append(temp)
        image = Image.new('RGBA', (10, 10), (len(calls), 40, 50, 255))
        image.save(temp, format='PNG'); image.close()
        return [1, 2, 11, 12]
    def generate(row=ROW, poly=POLY, scale=0.5):
        return a.png(row, poly, path, scale, render)
    old_umask = os.umask(0o077)
    try:
        assert generate() == [1, 2, 11, 12]
    finally:
        os.umask(old_umask)
    meta = os.path.join(a.cache, 'zone.png.meta.json')
    assert [mode for _, mode in snapshot(m, (path, meta))] == [0o644, 0o644]
    generate(); assert len(calls) == 1
    put(os.path.join(work, 'itos_unpack', 'bg.ipf', 'Sub', 'Actual.TOK'), b'another TOK')
    generate(); assert len(calls) == 2
    for row, poly, scale in ((dict(ROW, Width='101'), POLY, .5), (dict(ROW, Height='101'), POLY, .5),
                             (ROW, [[[0, 0], [14, 0], [0, 14]]], .5), (ROW, POLY, .6)):
        generate()
        n = len(calls); generate(row, poly, scale); assert len(calls) == n + 1
    generate()
    with patch(m, 'RENDER_VERSION', 2):
        n = len(calls); generate(); assert len(calls) == n + 1
    for target in (path, meta):
        for action in ('corrupt', 'missing'):
            if action == 'corrupt':
                put(target, b'broken')
            else:
                os.unlink(target)
            n = len(calls); generate(); assert len(calls) == n + 1
    info = json.loads(m.read(meta).decode('utf8')); info['bbox'] = [2, 2, 12, 12]
    put(meta, m.encoded(info)); n = len(calls); generate(); assert len(calls) == n + 1
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o644
    other = m.Assets(os.path.join(work, 'ktos_unpack'), os.path.join(work, 'png-parser'))
    n = len(calls); other.png(ROW, POLY, path, .5, render); assert len(calls) == n + 1
    n = len(calls); generate(); assert len(calls) == n + 1
    saved = snapshot(m, (path, meta))
    try:
        a.png(dict(ROW, Width='102'), POLY, path, .5, fail); assert False
    except IOError:
        pass
    assert snapshot(m, (path, meta)) == saved


def full_generation(m, checkout, input_path, phase):
    # Dependencies are synthetic, while both production entry functions are real.
    db = types.ModuleType('DB'); db.ToS_DB = object; sys.modules['DB'] = db
    c = types.ModuleType('fixture_constants')
    c.PATH_INPUT_DATA = input_path
    c.PATH_BUILD_ASSETS_IMAGES_MAPS = os.path.join(checkout, 'TavernofSoul', 'staticfiles_itos', 'maps')
    c.file_dict = {'map.ies': {'path': os.path.join(input_path, 'map.ies')}}
    if phase == 'polygon':
        import xml.etree.ElementTree as ET
        tok = types.ModuleType('tokutil')
        tok.tok2xml = lambda stream: ET.fromstring(stream.read())
        sys.modules['tokutil'] = tok
        load('map_image', os.path.join(checkout, 'parser_tidy')).parse_maps_images(c)
        cached = os.path.join(checkout, 'parser_tidy', '.map_assets', 'itos', 'zonepoly.json')
        assert json.loads(m.read(cached).decode('utf8')) == [[[0, 0], [12, 0], [0, -12]]]
    else:
        package = types.ModuleType('ipfparser'); package.__path__ = []
        sys.modules['ipfparser'] = package
        contracts = types.ModuleType('ipfparser.contracts'); contracts.canonical_item_id = lambda x, *args: x
        sys.modules['ipfparser.contracts'] = contracts
        sys.modules['luautil'] = types.ModuleType('luautil')
        imageutil = types.ModuleType('imageutil'); imageutil.replace_color = lambda image, *args: image.copy()
        sys.modules['imageutil'] = imageutil
        c.data = {'maps_by_name': {'Zone': {'$ID': '1', 'bbox': [0, 0, 0, 0]}}, 'maps': {}}
        maps = load('maps', os.path.join(checkout, 'parser_tidy'))
        maps.parse_maps_images(c)
        maps.parse_maps_images(c)
        assert c.data['maps']['1']['bbox'] != [0, 0, 0, 0]


def bytecode(root):
    return sorted(os.path.join(directory, name) for directory, _, files in os.walk(root)
                  for name in files if name.endswith(('.pyc', '.pyo')))


def launch(executable, expected, *args):
    env = os.environ.copy(); env['PYTHONDONTWRITEBYTECODE'] = '1'
    output = subprocess.check_output([executable, '-B', os.path.abspath(__file__), json.dumps(expected)] + list(args), env=env)
    print(output.decode('utf8'))
    return output


if __name__ == '__main__':
    expected = tuple(json.loads(sys.argv[1]))
    assert sys.version_info[:2] == expected, sys.version
    assert sys.dont_write_bytecode and os.environ.get('PYTHONDONTWRITEBYTECODE') == '1'
    print('map_assets interpreter=%r executable=%s phase=%s' % (sys.version_info[:2], sys.executable, sys.argv[2]))
    phase, work = sys.argv[2:4]
    sys.path.insert(0, SOURCE)
    import map_assets as m
    assert m.ROOT == SOURCE
    m.ROOT = os.path.join(work, 'parser_tidy')
    if phase == 'logic':
        atomic_cases(m, os.path.join(work, 'atomic'))
        polygon_cases(m, work)
        if expected == (3, 8):
            png_cases(m, work)
    else:
        full_generation(m, work, sys.argv[4], phase)
else:
    import pytest
    INTERPRETERS = [(sys.executable, (3, 8))]
    PY2 = shutil.which('python2.7')
    if PY2:
        INTERPRETERS.append((PY2, (2, 7)))

    @pytest.mark.parametrize('executable,expected', INTERPRETERS)
    def test_shared_logic(tmp_path, record_property, executable, expected):
        record_property('collected_interpreters', repr(INTERPRETERS))
        before = bytecode(SOURCE)
        launch(executable, expected, 'logic', str(tmp_path))
        assert bytecode(SOURCE) == before
        assert bytecode(str(tmp_path)) == []

    def test_full_generation_git_clean(tmp_path, record_property):
        assert PY2, 'full polygon generation requires Python 2.7'
        record_property('collected_interpreters', repr(INTERPRETERS))
        checkout = str(tmp_path / 'checkout'); os.makedirs(checkout)
        ignores = []
        for directory, dirs, files in os.walk(REPO):
            dirs[:] = [name for name in dirs if name != '.git' and
                       os.path.realpath(os.path.join(directory, name)) != os.path.realpath(checkout)]
            if '.gitignore' in files:
                relative = os.path.relpath(os.path.join(directory, '.gitignore'), REPO)
                ignores.append(relative)
                with open(os.path.join(directory, '.gitignore'), 'rb') as stream:
                    put(os.path.join(checkout, relative), stream.read())
        assert 'TavernofSoul/.gitignore' in ignores
        seed = os.path.join(checkout, 'parser_tidy', 'maps_poly', 'zonepoly.json')
        put(seed, json.dumps(POLY).encode('utf8'))
        def git(*args):
            return subprocess.check_output(['git', '-C', checkout] + list(args))
        git('init', '-q'); git('add', '--', *(ignores + ['parser_tidy/maps_poly/zonepoly.json']))
        git('-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
        with open(seed, 'rb') as stream:
            seed_before = stream.read()
        listing = sorted(os.listdir(os.path.dirname(seed)))
        input_path = str(tmp_path / 'itos_unpack')
        put(os.path.join(input_path, 'map.ies'), b'ClassName,BgName,Width,Height\nZone,Sub/Actual.TOK,100,100\n')
        put(os.path.join(input_path, 'bg.ipf', 'Sub', 'Actual.TOK'),
            b'<root><mesh3D><verts><v x="0" y="0"/><v x="12" y="0"/><v x="0" y="12"/>'
            b'<v x="bad" y="0"/></verts></mesh3D><mappingTo2D><p><e startVert="0"/>'
            b'<e startVert="-1"/><e startVert="9"/><e startVert="bad"/><e/><e startVert="3"/>'
            b'<e startVert="1"/><e startVert="2"/></p></mappingTo2D></root>')
        before = bytecode(SOURCE)
        for executable, version, phase in ((PY2, (2, 7), 'polygon'), (sys.executable, (3, 8), 'PNG')):
            output = launch(executable, version, phase, checkout, input_path)
            for kind in (b'polygon', b'PNG'):
                assert kind + b' generated=' in output
                assert all(key in output for key in (b' reused=', b' placeholder=', b' missing=', b' errors='))
        assert os.path.isfile(os.path.join(checkout, 'parser_tidy', '.map_assets', 'itos', 'zonepoly.json'))
        png = os.path.join(checkout, 'TavernofSoul', 'staticfiles_itos', 'maps', 'zone.png')
        assert os.path.isfile(png) and stat.S_IMODE(os.stat(png).st_mode) == 0o644
        assert git('status', '--porcelain=v1', '--untracked-files=all') == b''
        with open(seed, 'rb') as stream:
            assert stream.read() == seed_before
        assert sorted(os.listdir(os.path.dirname(seed))) == listing
        assert bytecode(checkout) == [] and bytecode(SOURCE) == before
