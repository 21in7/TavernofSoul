"""Synthetic shared-helper regressions; each interpreter runs the complete body."""
import glob, json, os, shutil, subprocess, sys, tempfile, unittest
CHILD = r'''
import errno, glob, json, os, shutil, stat, struct, sys, tempfile, unittest, zlib
from contextlib import contextmanager
print(json.dumps(dict(executable=sys.executable, version=list(sys.version_info[:2]))))
if tuple(sys.version_info[:2]) != tuple(map(int, sys.argv[3].split('.'))): raise AssertionError((sys.executable, sys.version))
if not sys.dont_write_bytecode or os.environ.get('PYTHONDONTWRITEBYTECODE') != '1': raise AssertionError('child bytecode safeguards missing')
sys.path.insert(0, sys.argv[1])
import map_assets as a
POLY = [[[0, 0], [4, 0], [0, 2]]]; DATA = a.encoded(POLY)
BAD_BBOX = (None,[0,0,0,0],[-1,1,1,2],[3,1,5,2],[1,-1,3,0],[1,2,3,3],[3,1,1,2],[1,2,3,1],[1,1,1,2],[1,1,3,1],[True,1,3,2],[1.0,1,3,2],[1,None,3,2],[],[1,1,3],[1,1,3,2,4],'1132',{'left':1},7)
@contextmanager
def patch(obj, key, value):
    old = getattr(obj, key); setattr(obj, key, value)
    try: yield old
    finally: setattr(obj, key, old)
def fail(*args, **kw): raise IOError(errno.EIO, 'injected failure')
def put(path, data, mode=0o640):
    if not os.path.isdir(os.path.dirname(path)): os.makedirs(os.path.dirname(path))
    if os.path.exists(path): os.chmod(path, mode | stat.S_IWUSR)
    with open(path, 'wb') as stream: stream.write(data)
    os.chmod(path, mode)
def state(path): return (a.read(path), stat.S_IMODE(os.stat(path).st_mode), os.stat(path).st_mtime)
def chunk(kind, body): return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
def png(w=4, h=2, depth=8, scan=None, packed=None):
    raw = (b'\0' + b'\xff\0\0\xff' * w) * h if scan is None else scan
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, depth, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw) if packed is None else packed) + chunk(b'IEND', b'')
def scan_png(w, h, scan, color=6, depth=8, interlace=0):
    header = chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, depth, color, 0, 0, interlace))
    return b'\x89PNG\r\n\x1a\n' + header + (chunk(b'PLTE', b'\0'*6) if color == 3 else b'') + chunk(b'IDAT', zlib.compress(scan)) + chunk(b'IEND', b'')
class BadWriter(object):
    def __init__(self, stream): self.stream = stream
    def __enter__(self): return self
    def __exit__(self, *args): self.stream.close()
    def write(self, data): fail()
class Shared(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(dir=sys.argv[2]); a.SCRIPT_DIR = self.root; a._SEEDS = []
        self.row = dict(ClassName='Map', BgName='', Width='7.2', Height='3.2'); self.seed = os.path.join(self.root, 'maps_poly', 'mappoly.json'); self.tok = os.path.join(self.root, 'kr_unpack', 'bg.ipf', 'Map.tok')
        self.image = os.path.join(self.root, '.map_assets', 'kr', 'map.png'); self.meta = self.image + '.meta.json'; self.assets = self.new()
    def tearDown(self):
        for directory, dirs, files in os.walk(self.root):
            self.assertFalse([f for f in files if f.endswith(('.pyc', '.pyo'))]); self.assertFalse([f for f in files if f.startswith('.map-')]); os.chmod(directory, 0o755)
        shutil.rmtree(self.root)
    def new(self, region='kr'): return a.Assets(type('Config', (), {'PATH_INPUT_DATA': os.path.join(self.root, region + '_unpack')})())
    def outcome(self, expected, convert=None, assets=None):
        counts = a.counters(); result = (assets or self.assets).polygon(self.row, counts, convert); self.assertEqual(counts, dict((k, int(k == expected)) for k in a.COUNTERS)); return result
    def seed_key(self, counts=None):
        put(self.seed, DATA, 0o444); counts = a.counters() if counts is None else counts
        value, data, source = self.assets.polygon(self.row, counts); self.assertEqual(value, POLY); self.assertEqual(source['provenance'],dict(origin='seed',verified=True,path=self.seed,sha256=a.digest(DATA))); return a.image_key(self.row, data, source, 0.5)
    def clean_temps(self): self.assertEqual(glob.glob(os.path.dirname(self.image) + '/.map-*'), [])
    def test_png_rgba_filters_lengths_and_crc(self):
        self.assertIsNone(a.png(png(), [0,0,4,2], (4,2)))
        row = b'\0' + b'\xff'*8
        for kind in range(5):
            self.assertIsNone(a.png(png(2,2,scan=row + struct.pack('B',kind) + b'\xff'*8), [0,0,2,2], (2,2)))
        for kind in (5, 255):
            for scan in (struct.pack('B',kind) + row[1:] + row, row + struct.pack('B',kind) + row[1:]):
                with self.assertRaises(ValueError): a.png(png(2,2,scan=scan), [0,0,2,2], (2,2))
        for scan in ((row*2)[:-1], row*2 + b'\0'):
            with self.assertRaises(ValueError): a.png(png(2,2,scan=scan), [0,0,2,2], (2,2))
        data = png(); corrupt = data[:-13] + struct.pack('B',ord(data[-13:-12]) ^ 1) + data[-12:]
        with self.assertRaises(ValueError): a.png(corrupt, [0,0,4,2], (4,2))
    def test_png_stream_completion(self):
        packed = zlib.compress((b'\0' + b'\xff\0\0\xff'*4)*2)
        for bad in tuple(packed[:-n] for n in range(1,5)) + (packed+b'\0', packed+b'garbage', packed+zlib.compress(b''), packed+packed):
            with self.assertRaises((ValueError,zlib.error)): a.png(png(packed=bad), [0,0,4,2], (4,2))
    def test_png_palette_reconstruction(self):
        # Each second row reconstructs to indices [1, 1], including Sub/Up.
        for kind, encoded in enumerate((b'\1\1', b'\1\0', b'\0\0', b'\1\0', b'\0\0')):
            scan = b'\0\1\1' + struct.pack('B',kind) + encoded
            self.assertIsNone(a.png(scan_png(2,2,scan,color=3), [0,0,2,2], (2,2)))
        for scan in (b'\0\0\2\0\0\0', b'\0\1\1\1\1\1', b'\0\1\1\2\1\0'):
            with self.assertRaises(ValueError): a.png(scan_png(2,2,scan,color=3), [0,0,2,2], (2,2))
        self.assertIsNone(a.png(scan_png(2,1,b'\0\x10',color=3,depth=2), [0,0,2,1], (2,1)))
        with self.assertRaises(ValueError): a.png(scan_png(2,1,b'\0\x20',color=3,depth=2), [0,0,2,1], (2,1))
    def test_png_adam7_scan_traversal(self):
        # All seven passes of a 5x5 image, with different row lengths.
        scans = ((1,1),(1,1),(2,1),(1,2),(3,1),(2,3),(5,2))
        for color, depth, channels in ((0,1,1),(2,16,3),(4,8,2),(6,8,4)):
            rows, offsets, length = [], [], 0
            for w, h in scans:
                for unused in range(h):
                    row = struct.pack('B',len(rows)%5) + b'\xff'*((w*channels*depth+7)//8)
                    offsets.append(length); rows.append(row); length += len(row)
            raw = b''.join(rows)
            self.assertIsNone(a.png(scan_png(5,5,raw,color,depth,1), [0,0,5,5], (5,5)))
            for offset in offsets:
                bad = raw[:offset] + b'\5' + raw[offset+1:]
                with self.assertRaises(ValueError): a.png(scan_png(5,5,bad,color,depth,1), [0,0,5,5], (5,5))
    def test_source_resolution(self):
        for data, expected in ((b'a'*31,'ok'),(b'a'*32,'placeholder'),(b'A'*32,'placeholder'),(b'a'*33,'ok'),(b'a'*31+b'\n','ok'),(b' '*32,'ok'),(b'g'*32,'ok'),(b'a'*32+b'\n','ok'),(b' '+b'a'*32,'ok'),(b'\xff'*32,'ok'),(b'abc','ok'),(b'0123456789abcdefABCDEF0123456789','placeholder')):
            put(self.tok, data); self.assets = self.new(); self.assertEqual(self.assets.source(self.row)['status'], expected)
        put(self.tok, b'class'); other = os.path.join(os.path.dirname(self.tok), 'nested', 'Other.TOK'); put(other, b'background'); self.assets = self.new(); self.row['BgName'] = 'BG.IPF\\nested\\Other.TOK'; self.assertEqual(self.assets.source(self.row)['sha256'], a.digest(b'background'))
        self.row['BgName'] = 'nested/other.tok'; self.assertEqual(self.assets.source(self.row)['status'], 'ok'); self.row['BgName'] = 'absent'; self.assertEqual(self.assets.source(self.row)['status'], 'missing')
        put(os.path.join(os.path.dirname(self.tok), 'MAP.TOK'), b'upper'); self.assets = self.new(); self.row['BgName'] = ''; self.assertEqual(self.assets.source(self.row)['sha256'], a.digest(b'class')); self.row['BgName'] = 'map.tok'; self.assertEqual(self.assets.source(self.row)['status'], 'errors')
        put(os.path.join(os.path.dirname(self.tok), 'second', 'OTHER.tok'), b'other'); self.assets = self.new(); self.row['BgName'] = 'other'; self.assertEqual(self.assets.source(self.row)['status'], 'errors')
        for target in ('../Map', '/Map', 'a//Map', 'a/./Map', 'C:/Map', 'a/../Map', 'a\x00Map'):
            self.row['BgName'] = target; self.outcome('errors')
        self.row.update(BgName='', _asset_collision=True); self.outcome('errors'); self.row.update(ClassName='../Map', _asset_collision=False); self.outcome('errors')
        csv_path = os.path.join(self.root, 'synthetic.csv'); put(csv_path, b'ClassName,BgName\nMap,\nMAP,\n'); config = type('Config', (), {'file_dict': {'map.ies': {'path': csv_path}}})(); self.assertTrue(all(r['_asset_collision'] for r in a.rows(config)))
    def test_absence_and_recovery(self):
        self.outcome('missing'); put(self.seed, DATA); self.outcome('reused'); os.unlink(self.seed); put(self.tok, b'f'*32); self.assets = self.new(); self.outcome('placeholder'); put(self.seed, DATA); self.outcome('reused')
        put(self.tok, b'tok'); self.assets = self.new(); os.unlink(self.tok); self.assertEqual(self.assets.source(self.row)['status'], 'missing'); self.outcome('reused'); os.unlink(self.seed); self.outcome('missing')
        for error_type in (IOError, OSError):
            for number, expected in ((errno.ENOENT, 'missing'), (errno.EACCES, 'errors'), (errno.EIO, 'errors')):
                original = a.read
                def denied(path):
                    if path == self.tok: raise error_type(number, 'injected open')
                    return original(path)
                with patch(a, 'read', denied):
                    self.assertEqual(self.assets.source(self.row)['status'], expected); self.outcome(expected); put(self.seed, DATA); self.outcome('reused'); os.unlink(self.seed)
    def test_cache_freshness_corruption_and_regions(self):
        put(self.tok, b'tok'); self.assets = self.new()
        def convert(stream): self.assertIn(stream.read(), (b'tok', b'changed')); return POLY
        self.outcome('generated', convert); self.outcome('reused', fail); path, meta = self.assets.paths(self.row, 'poly.json'); put(self.seed, a.encoded([[[0,0],[8,0],[0,8]]])); self.assertEqual(self.outcome('reused')[1], DATA)
        put(self.tok, b'changed'); self.outcome('generated', convert)
        with patch(a, 'POLYGON_VERSION', a.POLYGON_VERSION + 1): self.outcome('generated', convert); self.outcome('reused', fail)
        self.outcome('generated', convert); os.unlink(self.seed); os.unlink(self.tok); self.outcome('missing'); put(self.tok, b'a'*32); self.outcome('placeholder'); put(self.tok, b'changed')
        good = (a.read(path), a.read(meta))
        for bad_data, bad_meta in ((b'{', good[1]), (b'[]', good[1]), (b'[[[0,0],[1,1],[2,2]]]', good[1]), (DATA, b'{'), (DATA, b'{}'), (DATA, b'[]'), (DATA, good[1].replace(a.digest(DATA).encode('ascii'), b'0'*64))):
            put(path, bad_data); put(meta, bad_meta); self.outcome('errors'); put(self.seed, DATA); self.outcome('reused', fail); os.unlink(self.seed); self.outcome('generated', convert)
        put(path, good[0]); put(meta, good[1]); before = (state(path), state(meta))
        put(self.tok, b'tok'); self.outcome('errors', fail); self.assertEqual((state(path), state(meta)), before); self.outcome('generated', convert)
        other = self.new('jp'); self.assertNotEqual(other.cache, self.assets.cache); self.outcome('missing', assets=other)
        put(self.seed, DATA, 0o444); os.chmod(os.path.dirname(self.seed), 0o555); before = state(self.seed); put(self.tok, b'changed'); self.outcome('generated', convert); self.assertEqual(state(self.seed), before); self.assertEqual(os.listdir(os.path.dirname(self.seed)), ['mappoly.json'])
        with self.assertRaises(ValueError): a.Assets(type('C', (), {'PATH_INPUT_DATA': os.path.dirname(os.path.dirname(self.tok))})(), cache=os.path.dirname(self.seed))
        with self.assertRaises(ValueError): a.replace_pair(self.seed, DATA, self.seed+'.meta', {}, a.polygons)
        os.chmod(os.path.dirname(self.seed),0o755); os.unlink(self.tok)
        for bad in (b'{',b'[]',b'[[[true,0],[4,0],[0,2]]]',b'[[[NaN,0],[4,0],[0,2]]]'): put(self.seed,bad); self.outcome('errors')
    def test_publication(self):
        path, meta = self.image, self.meta; put(path, b'old', 0o640); put(meta, b'old metadata', 0o600); before = (state(path)[:2], state(meta)[:2]); descriptor = a.os.fdopen; rename = a.os.rename; chmod = a.os.chmod; read = a.read
        for operation in ('write', 'validate', 'saved', 'chmod', 'rename'):
            calls = [0]
            def failing(*args, **kw):
                calls[0] += 1
                if operation == 'write': return BadWriter(descriptor(*args, **kw))
                if operation == 'saved': return b'bad saved bytes' if os.path.basename(args[0]).startswith('.map-') else read(*args, **kw)
                if calls[0] == 2: fail()
                return (rename if operation == 'rename' else chmod)(*args, **kw)
            obj, attr = (a, 'read') if operation == 'saved' else (a.os, {'write':'fdopen', 'chmod':'chmod', 'rename':'rename'}.get(operation, 'chmod'))
            with patch(obj, attr, failing if operation != 'validate' else chmod):
                with self.assertRaises((IOError, OSError, ValueError)): a.replace_pair(path, DATA, meta, {'ok':True}, fail if operation == 'validate' else a.polygons)
            self.assertEqual((state(path)[:2], state(meta)[:2]), before); self.clean_temps()
        temporary = a._stage(path,DATA,a.polygons); self.assertEqual(os.path.dirname(temporary),os.path.dirname(path)); os.unlink(temporary); previous = os.umask(0o077)
        try: a.replace_pair(path, DATA, meta, {'ok':True}, a.polygons); self.assertEqual((state(path)[1], state(meta)[1]), (0o644, 0o644)); os.unlink(path); os.unlink(meta); a.replace_pair(path, DATA, meta, {'ok':True}, a.polygons)
        finally: os.umask(previous)
        self.assertEqual((state(path)[1], state(meta)[1]), (0o644, 0o644)); self.clean_temps()
    def test_adoption_and_image_reuse(self):
        for supplied in ([1,1,3,2],(1,1,3,2),[0,0,4,2]):
            expected = list(supplied); data = png(expected[2]-expected[0],expected[3]-expected[1]); counts = a.counters(); key = self.seed_key(counts)
            put(self.image,data,0o600); os.utime(self.image,(123456789,123456789)); before = state(self.image); seed_before = state(self.seed); previous = os.umask(0o077)
            try: bbox = a.adopt_image(self.row,DATA,key['source'],0.5,self.image,self.meta,counts,supplied)
            finally: os.umask(previous)
            self.assertIsInstance(bbox,list); self.assertEqual(bbox,expected); self.assertEqual(list(supplied),expected); self.assertIsNot(bbox,supplied)
            self.assertEqual(counts,dict((k,int(k=='adopted')) for k in a.COUNTERS)); self.assertEqual((state(self.image),state(self.seed)),(before,seed_before)); self.assertEqual(state(self.meta)[1],0o644)
            meta = json.loads(a.read(self.meta).decode('utf8')); self.assertTrue(meta['adopted']); self.assertEqual((meta['seed'],meta['png'],meta['key'],meta['bbox']),(a.digest(DATA),a.digest(data),key,expected)); self.assertEqual(meta['binding'],a.digest(a.encoded([key,expected,a.digest(data)])))
            saved = state(self.meta); bbox[0] = -1
            if isinstance(supplied,list): supplied[0] = -2
            fresh = a.counters(); self.assertEqual(a.image_cached(self.image,self.meta,key,(4,2),fresh),expected); self.assertEqual(fresh,dict((k,int(k=='reused')) for k in a.COUNTERS))
            self.assertIsNone(a.adopt_image(self.row,DATA,key['source'],0.5,self.image,self.meta,fresh,expected)); self.assertEqual((state(self.image),state(self.meta)),(before,saved)); self.assertEqual(fresh,dict((k,int(k=='reused')) for k in a.COUNTERS))
            for bad in (b'{}',b'{',a.encoded(dict(meta,seed='0'*64)),a.encoded(dict(meta,binding='0'*64)),a.encoded(dict(meta,bbox=[0,0,2,1]))):
                put(self.meta,bad); rejected = a.counters(); self.assertIsNone(a.image_cached(self.image,self.meta,key,(4,2),rejected)); self.assertEqual(sum(rejected.values()),0)
            for invalid in BAD_BBOX + ([0,0,1,2],):
                tampered = dict(meta,bbox=invalid); tampered['binding'] = a.digest(a.encoded([key,invalid,meta['png']]))
                put(self.meta,a.encoded(tampered)); rejected = a.counters(); self.assertIsNone(a.image_cached(self.image,self.meta,key,(4,2),rejected)); self.assertEqual(sum(rejected.values()),0)
            changed_key = dict(key,version=key['version']+1); tampered = dict(meta,key=changed_key,binding=a.digest(a.encoded([changed_key,expected,meta['png']])))
            put(self.meta,a.encoded(tampered)); self.assertIsNone(a.image_cached(self.image,self.meta,key,(4,2)))
            put(self.meta,a.encoded(meta))
            with patch(a,'RENDER_VERSION',a.RENDER_VERSION+1): self.assertIsNone(a.image_cached(self.image,self.meta,key,(4,2)))
            for bad_png in (data[:-1],png(1,2)):
                tampered = dict(meta,png=a.digest(bad_png),binding=a.digest(a.encoded([key,expected,a.digest(bad_png)])))
                put(self.image,bad_png); put(self.meta,a.encoded(tampered)); rejected = a.counters(); self.assertIsNone(a.image_cached(self.image,self.meta,key,(4,2),rejected)); self.assertEqual(sum(rejected.values()),0)
            put(self.image,data); put(self.meta,a.encoded(meta))
            put(self.seed,a.encoded([[[0,0],[8,0],[0,8]]])); self.assertIsNone(a.image_cached(self.image,self.meta,key,(4,2))); os.unlink(self.meta)
    def test_adoption_rejections_and_failed_metadata(self):
        key = self.seed_key(); put(self.meta,b'previous metadata',0o640)
        for data in (png(2,1),png(3,2),png(4,1),b'bad signature',png()[:-1],png()+b'x',png()[:29]+b'BAD!'+png()[33:],png(depth=3),png(packed=b'bad deflate'),png(packed=zlib.compress((b'\0'+b'\xff'*16)*2)[:-1]),png(scan=(b'\5'+b'\0'*16)*2),png()[:-12],png()[:-12]+chunk(b'ABCD',b'')+png()[-12:],png()[:8]+chunk(b'IHDR',b'\0'*12)+png()[33:],png()[:33]+png()):
            put(self.image,data,0o600); before = (state(self.image),state(self.meta)); counts = a.counters(); self.assertIsNone(a.adopt_image(self.row,DATA,key['source'],0.5,self.image,self.meta,counts,[0,0,4,2])); self.assertEqual((state(self.image),state(self.meta)),before); self.assertEqual(sum(counts.values()),0)
        put(self.image,png(2,1),0o600); before = (state(self.image),state(self.meta))
        for invalid in BAD_BBOX + ([0,0,4,2],[1,0,3,2],[1,1,4,2]):
            counts = a.counters(); self.assertIsNone(a.adopt_image(self.row,DATA,key['source'],0.5,self.image,self.meta,counts,invalid)); self.assertEqual((state(self.image),state(self.meta)),before); self.assertEqual(sum(counts.values()),0)
        put(self.image,png(),0o600); before = (state(self.image),state(self.meta)); provenance = key['source']['provenance']
        for bad in (dict(provenance,origin='cache'),dict(provenance,origin='unknown'),dict(provenance,verified=False),dict(provenance,sha256='0'*64)):
            counts = a.counters(); self.assertIsNone(a.adopt_image(self.row,DATA,bad,0.5,self.image,self.meta,counts,[0,0,4,2])); self.assertEqual((state(self.image),state(self.meta)),before); self.assertEqual(sum(counts.values()),0)
        stage = a._stage
        def changed(*args, **kw):
            result = stage(*args, **kw); put(self.seed,a.encoded([[[0,0],[8,0],[0,8]]])); return result
        for injected in (fail, changed):
            put(self.seed,DATA); counts = a.counters()
            with patch(a,'_stage',injected): self.assertIsNone(a.adopt_image(self.row,DATA,key['source'],0.5,self.image,self.meta,counts,[0,0,4,2]))
            self.assertEqual((state(self.image),state(self.meta)),before); self.assertEqual(sum(counts.values()),0); self.clean_temps()
        counts = a.counters(); self.assertIsNone(a.adopt_image(self.row,DATA,key['source'],0.5,self.image,self.meta,counts,[0,0,4,2])); self.assertEqual((state(self.image),state(self.meta)),before); self.assertEqual(sum(counts.values()),0)
        put(self.seed,DATA); descriptor = a.os.fdopen
        for attr, injected in (('fdopen',lambda *args,**kw:BadWriter(descriptor(*args,**kw))),('chmod',fail),('rename',fail)):
            counts = a.counters()
            with patch(a.os,attr,injected): self.assertIsNone(a.adopt_image(self.row,DATA,key['source'],0.5,self.image,self.meta,counts,[0,0,4,2]))
            self.assertEqual((state(self.image),state(self.meta)),before); self.assertEqual(sum(counts.values()),0); self.clean_temps()
        os.unlink(self.meta); counts = a.counters()
        with patch(a.os,'rename',fail): self.assertIsNone(a.adopt_image(self.row,DATA,key['source'],0.5,self.image,self.meta,counts,[0,0,4,2]))
        self.assertFalse(os.path.exists(self.meta)); self.assertEqual(state(self.image),before[0]); self.assertEqual(sum(counts.values()),0); self.clean_temps()
    def test_saved_image_outcome_and_summary(self):
        counts = a.counters(); key = self.seed_key(counts)
        image = type('Image',(),{'save':lambda self,stream,**kw:stream.write(png())})(); a.save_image(image,[0,0,4,2],self.image,self.meta,key,(4,2),counts); self.assertEqual(counts,dict((k,int(k=='generated')) for k in a.COUNTERS)); self.assertEqual((state(self.image)[1],state(self.meta)[1]),(0o644,0o644)); self.assertEqual(a.image_cached(self.image,self.meta,key,(4,2)),[0,0,4,2]); messages = []
        with patch(a.logging,'warning',lambda *args: messages.append(args)): a.summary('unit',counts)
        self.assertIn('adopted=0',messages[0][2])
        put(self.tok,b'tok'); self.assets = self.new(); value,data,source = self.outcome('generated',lambda stream:POLY); key = a.image_key(self.row,data,source,0.5); self.assertEqual(source['provenance']['origin'],'cache'); self.assertIsNone(a.adopt_image(self.row,data,source,0.5,self.image,self.meta,a.counters(),[0,0,4,2])); a.save_image(image,[0,0,4,2],self.image,self.meta,key,(4,2)); os.unlink(self.tok); self.assertIsNone(a.image_cached(self.image,self.meta,key,(4,2)))
result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Shared)); print(json.dumps(dict(executable=sys.executable,version=list(sys.version_info[:2]),tests=result.testsRun))); sys.exit(0 if result.wasSuccessful() else 1)
'''
class MapAssetsInterpreters(unittest.TestCase):
    def run_child(self, executable, version):
        source = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        def bytecode(): return set(glob.glob(os.path.join(source, 'map_assets.py[co]')) + glob.glob(os.path.join(source, '__pycache__', 'map_assets*.py[co]')))
        before = bytecode(); environment = os.environ.copy(); environment['PYTHONDONTWRITEBYTECODE'] = '1'
        with tempfile.TemporaryDirectory() as fixture:
            child = subprocess.run([executable,'-B','-c',CHILD,source,fixture,'%d.%d' % version],env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
            self.assertEqual(bytecode(),before)
            for root, dirs, files in os.walk(fixture): self.assertFalse([f for f in files if f.endswith(('.pyc','.pyo'))])
        print(child.stdout); self.assertEqual(child.returncode,0,child.stdout+child.stderr); record = json.loads(child.stdout.strip().splitlines()[-1]); self.assertEqual(tuple(record['version']),version); self.assertTrue(record['executable']); self.assertGreater(record['tests'],0)
    def test_python38_required(self): self.run_child(sys.executable,(3,8))
    PYTHON27 = shutil.which('python2.7')
    if PYTHON27 is not None:
        def test_python27_separate(self):
            self.run_child(self.PYTHON27,(2,7))
