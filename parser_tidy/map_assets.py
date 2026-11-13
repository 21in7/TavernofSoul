# -*- coding: utf-8 -*-
"""Dormant Python 2.7/3.8 helpers. Consumers must opt in; seeds stay read-only."""
import csv, errno, hashlib, io, json, logging, math, os, re, stat, struct, sys, tempfile, zlib
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POLYGON_VERSION = RENDER_VERSION = 1
COUNTERS = ('generated', 'reused', 'adopted', 'placeholder', 'missing', 'errors')
_SEEDS = [os.path.join(SCRIPT_DIR, 'maps_poly')]
NUMBERS = (int, float) if sys.version_info[0] == 3 else (int, long, float)
STRINGS = (str,) if sys.version_info[0] == 3 else (basestring,)
class _Counts(dict):
    def __init__(self):
        dict.__init__(self, ((key, 0) for key in COUNTERS)); self.pending = {}
def counters(): return _Counts()
def _record(counts, kind, provenance=None, pending=False):
    # A polygon lookup may be promoted into the final image outcome in this request.
    requests = getattr(counts, 'pending', {})
    previous = requests.pop(id(provenance), None)
    if previous is not None: counts[previous[1]] -= 1
    counts[kind] += 1
    if pending and provenance is not None: requests[id(provenance)] = (provenance, kind)
def summary(kind, counts):
    logging.warning('%s: %s', kind, ' '.join('%s=%d' % (k, counts[k]) for k in COUNTERS))
def digest(data): return hashlib.sha256(data).hexdigest()
def encoded(value): return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
def read(path):
    with open(path, 'rb') as stream: return stream.read()
def _absent(exc): return isinstance(exc, (IOError, OSError)) and exc.errno == errno.ENOENT
def _log(exc): logging.warning('map assets: %s', exc)
def _inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)
def _hash(value): return isinstance(value, STRINGS) and re.match(r'^[0-9a-f]{64}\Z', value)
class _Stale(ValueError): pass
def _unchanged(path, expected):
    if digest(read(path)) != expected: raise _Stale('source changed')
def polygons(data):
    value = json.loads(data.decode('utf-8'))
    if not isinstance(value, list) or not value: raise ValueError('invalid polygon list')
    for polygon in value:
        if not isinstance(polygon, list) or len(polygon) < 3: raise ValueError('invalid polygon')
        for point in polygon:
            if (not isinstance(point, list) or len(point) != 2 or
                    any(isinstance(n, bool) or not isinstance(n, NUMBERS) or
                        math.isnan(n) or math.isinf(n) for n in point)):
                raise ValueError('invalid coordinate')
        if not sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(polygon, polygon[1:] + polygon[:1])):
            raise ValueError('degenerate polygon')
    return value
def name(row):
    value = row['ClassName']
    if not re.match(r'^[A-Za-z0-9_-]+\Z', value) or row.get('_asset_collision'):
        raise ValueError('invalid/colliding ClassName')
    return value.lower()
def rows(c):
    stream = (open(c.file_dict['map.ies']['path'], 'rb') if sys.version_info[0] == 2
              else io.open(c.file_dict['map.ies']['path'], encoding='utf-8'))
    with stream: result = list(csv.DictReader(stream))
    names = [row.get('ClassName', '').lower() for row in result]
    for row in result: row['_asset_collision'] = names.count(row.get('ClassName', '').lower()) > 1
    return result
class Assets(object):
    def __init__(self, c, cache=None, seed=None):
        self.input = os.path.realpath(os.path.join(SCRIPT_DIR, c.PATH_INPUT_DATA)); self.region = os.path.basename(self.input)
        if self.region.endswith('_unpack'): self.region = self.region[:-7]
        if not re.match(r'^[A-Za-z0-9_-]+\Z', self.region): raise ValueError('invalid region')
        root = os.path.join(SCRIPT_DIR, '.map_assets', self.region)
        self.cache, self.seed = cache or root, seed or os.path.join(SCRIPT_DIR, 'maps_poly')
        if not _inside(self.cache, root): raise ValueError('cache outside regional root')
        _SEEDS.append(self.seed)
        self.bg, self.index = os.path.join(self.input, 'bg.ipf'), []
        for directory, dirs, files in os.walk(self.bg):
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(directory, d))]
            for filename in files:
                path = os.path.join(directory, filename)
                if filename.lower().endswith('.tok') and not os.path.islink(path):
                    self.index.append(os.path.relpath(path, self.bg).replace(os.sep, '/'))
    def source(self, row):
        result = dict(region=self.region, input=self.input)
        try:
            name(row)
            target = (row.get('BgName') or row['ClassName']).replace('\\', '/')
            if target.lower().startswith('bg.ipf/'): target = target[7:]
            if (not target or target.startswith('/') or ':' in target or '\x00' in target or
                    any(p in ('', '.', '..') for p in target.split('/'))):
                raise ValueError('invalid TOK path')
            if not target.lower().endswith('.tok'): target += '.tok'
            result['requested'] = target; choices = [p for p in self.index if p == target]
            if not choices: choices = [p for p in self.index if p.lower() == target.lower()]
            if not choices and '/' not in target:
                choices = [p for p in self.index if p.rsplit('/', 1)[-1].lower() == target.lower()]
            if len(choices) > 1: raise ValueError('ambiguous TOK: ' + target)
            result['status'] = 'missing'
            if choices:
                result['path'] = os.path.join(self.bg, *choices[0].split('/'))
                if not _inside(result['path'], self.bg) or os.path.islink(result['path']):
                    raise ValueError('unsafe TOK path')
                result['resolved'] = True
                try: data = read(result['path'])
                except (IOError, OSError) as exc:
                    if not _absent(exc): raise
                else:
                    result.update(sha256=digest(data), status='placeholder' if len(data) == 32 and
                                  re.match(br'^[0-9A-Fa-f]{32}\Z', data) else 'ok')
        except Exception as exc: result.update(status='errors', diagnostic=str(exc))
        if result['status'] != 'ok': _log(result)
        return result
    def paths(self, row, suffix):
        path = os.path.join(self.cache, name(row) + suffix)
        if not _inside(path, self.cache): raise ValueError('unsafe cache path')
        return path, path + '.meta.json'
    def polygon(self, row, counts, convert=None):
        source, failure = self.source(row), False
        def finish(kind, value=None, data=None, provenance=None):
            _record(counts, kind, provenance, pending=True)
            return value, data, dict(source, provenance=provenance)
        try:
            path, metadata = self.paths(row, 'poly.json')
            if source['status'] == 'errors' and not source.get('resolved'):
                return finish('errors')
            if source['status'] == 'ok':
                key = dict(source=dict((k, source[k]) for k in ('region', 'input', 'requested', 'sha256')),
                           version=POLYGON_VERSION)
                try:
                    data, meta = read(path), json.loads(read(metadata).decode('utf-8'))
                    value = polygons(data)
                    if (not isinstance(meta, dict) or set(meta) != set(('source', 'version', 'polygon')) or
                            not isinstance(meta['source'], dict) or set(meta['source']) != set(key['source']) or
                            any(not isinstance(v, STRINGS) or not v for v in meta['source'].values()) or
                            not _hash(meta['source']['sha256']) or type(meta['version']) is not int or
                            meta['version'] < 1 or
                            meta['polygon'] != digest(data)):
                        raise ValueError('invalid polygon metadata')
                    if meta == dict(key, polygon=digest(data)):
                        return finish('reused', value, data, dict(origin='cache', verified=True, path=source['path'], sha256=digest(data), key=key))
                except Exception as exc:
                    if not (_absent(exc) and not os.path.lexists(path) and not os.path.lexists(metadata)):
                        failure = True; _log(exc)
                if convert is not None:
                    try:
                        original = read(source['path'])
                        if digest(original) != source['sha256']: raise ValueError('TOK changed')
                        data = encoded(convert(io.BytesIO(original)))
                        replace_pair(path, data, metadata, dict(key, polygon=digest(data)), polygons, lambda: _unchanged(source['path'], source['sha256']))
                        return finish('generated', polygons(data), data, dict(origin='cache', verified=True, path=source['path'], sha256=digest(data), key=key))
                    except Exception as exc: failure = True; _log(exc)
            seed = os.path.join(self.seed, name(row) + 'poly.json')
            if not _inside(seed, self.seed): raise ValueError('unsafe seed path')
            try:
                data = read(seed); value = polygons(data)
                provenance = dict(origin='seed', verified=True, path=os.path.realpath(seed), sha256=digest(data))
                return finish('reused', value, data, provenance)
            except Exception as exc:
                if not _absent(exc): failure = True; _log(exc)
            if source['status'] == 'ok': failure = True; _log('no usable cache/seed or converter result')
            return finish('errors' if failure or source['status'] == 'errors' else source['status'])
        except Exception as exc:
            _log(exc)
            return finish('errors')
def _stage(path, data, validate, mode=0o644):
    if any(_inside(path, root) for root in _SEEDS) or 'maps_poly' in os.path.realpath(path).split(os.sep):
        raise ValueError('read-only seed destination')
    directory = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(directory): os.makedirs(directory)
    descriptor, temporary = tempfile.mkstemp(prefix='.map-', dir=directory)
    try:
        with os.fdopen(descriptor, 'wb') as stream: stream.write(data)
        saved = read(temporary)
        if saved != data: raise ValueError('staged bytes differ')
        validate(saved); os.chmod(temporary, mode)
        return temporary
    except Exception:
        os.unlink(temporary)
        raise
def replace_pair(path, data, metadata, value, validate, before=None):
    """Publish validated 0644 files; restore old bytes and modes on rename failure."""
    _publish(((path, data, validate), (metadata, encoded(value), lambda b: _json_equal(b, value))), before)
def _json_equal(data, expected):
    if json.loads(data.decode('utf-8')) != expected: raise ValueError('metadata differs')
def _publish(entries, before=None):
    staged, backups, changed = {}, {}, []
    try:
        for target, content, validate in entries:
            if target in staged: raise ValueError('duplicate publication target')
            if os.path.lexists(target):
                if os.path.islink(target): raise ValueError('symlink destination')
                backups[target] = _stage(target, read(target), lambda b: None, stat.S_IMODE(os.stat(target).st_mode))
            staged[target] = _stage(target, content, validate)
        if before is not None: before()
        for target, content, validate in entries:
            os.rename(staged[target], target); changed.append(target)
        changed = []
    finally:
        try:
            for target in reversed(changed):
                if target in backups: os.rename(backups.pop(target), target)
                else: os.unlink(target)
        finally:
            for temporary in list(staged.values()) + list(backups.values()):
                if os.path.exists(temporary): os.unlink(temporary)

def png(data, bbox, size):
    """Validate PNG chunks, CRCs, deflate stream and scanlines without Pillow."""
    if data[:8] != b'\x89PNG\r\n\x1a\n': raise ValueError('PNG signature')
    offset, chunks, compressed, palette, transparency = 8, [], [], None, False
    while offset < len(data):
        if offset + 12 > len(data): raise ValueError('truncated PNG chunk')
        length, kind = struct.unpack('>I4s', data[offset:offset + 8]); end = offset + length + 12
        if length > 0x7fffffff or end > len(data) or not re.match(br'^[A-Za-z]{4}\Z', kind) or kind[2:3].islower():
            raise ValueError('invalid PNG chunk')
        body = data[offset + 8:end - 4]
        if (zlib.crc32(kind + body) & 0xffffffff) != struct.unpack('>I', data[end - 4:end])[0]:
            raise ValueError('PNG CRC')
        if not chunks and kind != b'IHDR': raise ValueError('missing IHDR')
        if kind == b'IHDR':
            if chunks or length != 13: raise ValueError('bad IHDR')
            width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', body)
            allowed = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
            if (not 0 < width <= 0x7fffffff or not 0 < height <= 0x7fffffff or depth not in allowed.get(color, ()) or
                    compression or filtering or interlace not in (0, 1)): raise ValueError('invalid IHDR')
        elif kind == b'PLTE':
            if palette is not None or compressed or transparency or color in (0, 4) or not length or length % 3 or length > 768:
                raise ValueError('invalid palette')
            palette = length // 3
            if color == 3 and palette > 2 ** depth: raise ValueError('oversized palette')
        elif kind == b'tRNS':
            if (transparency or compressed or color not in (0, 2, 3) or
                    (color == 3 and (palette is None or not 0 < length <= palette)) or
                    (color != 3 and length != {0: 2, 2: 6}[color])): raise ValueError('invalid transparency')
            if color != 3 and any(n >= 2 ** depth for n in struct.unpack('>' + 'H' * (length // 2), body)):
                raise ValueError('invalid transparent sample')
            transparency = True
        elif kind == b'IDAT':
            if compressed and chunks[-1] != b'IDAT' or color == 3 and palette is None: raise ValueError('invalid IDAT order')
            compressed.append(body)
        elif kind == b'IEND':
            if length or not compressed or end != len(data): raise ValueError('invalid IEND')
        elif kind[:1].isupper(): raise ValueError('unknown critical PNG chunk')
        chunks.append(kind); offset = end
    if not chunks or chunks[-1] != b'IEND': raise ValueError('missing IEND')
    if (len(bbox) != 4 or any(type(n) is not int for n in bbox) or
            not (0 <= bbox[0] < bbox[2] <= size[0] and 0 <= bbox[1] < bbox[3] <= size[1]) or
            (width, height) != (bbox[2] - bbox[0], bbox[3] - bbox[1])): raise ValueError('PNG dimensions/bbox')
    bits = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color] * depth
    passes = ((0, 0, 1, 1),) if not interlace else ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
    scans = [((width - x + dx - 1) // dx, (height - y + dy - 1) // dy) for x, y, dx, dy in passes if width > x and height > y]
    expected = sum(((w * bits + 7) // 8 + 1) * h for w, h in scans)
    packed = b''.join(compressed); decoder = zlib.decompressobj()
    # Python 2.7 has no decoder.eof: an unused sentinel proves stream completion.
    raw = decoder.decompress(packed + b'\0', expected + 1)
    if len(raw) != expected or decoder.unconsumed_tail or decoder.unused_data != b'\0':
        raise ValueError('invalid PNG image data')
    pos, stride = 0, max(1, (bits + 7) // 8)
    for w, h in scans:
        length = (w * bits + 7) // 8
        prior = [0] * length if color == 3 else None
        for unused in range(h):
            filter_type = ord(raw[pos:pos + 1])
            if filter_type > 4: raise ValueError('invalid PNG filter')
            if color != 3:
                pos += length + 1
                continue
            line = bytearray(raw[pos + 1:pos + length + 1]); pos += length + 1
            for i in range(length):
                a, b, c = (line[i - stride] if i >= stride else 0), prior[i], (prior[i - stride] if i >= stride else 0)
                p = a + b - c; distances = (abs(p - a), abs(p - b), abs(p - c))
                predictor = (a, b, c)[distances.index(min(distances))]
                line[i] = (line[i] + (0, a, b, (a + b) // 2, predictor)[filter_type]) & 255
            if color == 3 and any((line[(i * depth) // 8] >> (8 - depth - (i * depth) % 8)) & (2 ** depth - 1) >= palette for i in range(w)):
                raise ValueError('invalid palette index')
            prior = line
def image_key(row, data, source, scale):
    polygons(data); width, height, scale = float(row['Width']), float(row['Height']), float(scale)
    if any(not 0 < n < float('inf') for n in (width, height, scale)): raise ValueError('invalid render dimensions')
    return dict(source=source, polygon=digest(data), width=width, height=height, scale=scale, version=RENDER_VERSION)
def _seed(key):
    provenance = key['source'].get('provenance', key['source'])
    if (provenance.get('origin') != 'seed' or provenance.get('verified') is not True or
            not any(_inside(provenance['path'], root) for root in _SEEDS) or os.path.islink(provenance['path']) or
            provenance.get('sha256') != key['polygon']): raise ValueError('unverified seed provenance')
    data = read(provenance['path']); polygons(data)
    if digest(data) != provenance['sha256']: raise _Stale('seed changed')
    return provenance
def _verify_key(key):
    if key['version'] != RENDER_VERSION: raise _Stale('obsolete render key')
    provenance = key['source'].get('provenance', key['source'])
    if provenance.get('origin') == 'seed': return _seed(key)
    if (provenance.get('origin') != 'cache' or provenance.get('verified') is not True or
            provenance.get('sha256') != key['polygon']): raise ValueError('unverified cache provenance')
    if provenance['key']['version'] != POLYGON_VERSION: raise _Stale('obsolete polygon key')
    _unchanged(provenance['path'], provenance['key']['source']['sha256'])
    return provenance
def _size(key): return (int(round(key['width'] * key['scale'])), int(round(key['height'] * key['scale'])))
def _image_meta(key, bbox, data, adopted=False):
    value = dict(key=key, bbox=list(bbox), png=digest(data), binding=digest(encoded([key, list(bbox), digest(data)])))
    if adopted: value.update(adopted=True, seed=_seed(key)['sha256'])
    return value
def image_cached(path, metadata, key, size, counts=None):
    try:
        value = json.loads(read(metadata).decode('utf-8')); data = read(path)
        fields = set(('key', 'bbox', 'png', 'binding'))
        if value.get('adopted') is True: fields.update(('adopted', 'seed'))
        if (set(value) != fields or not _hash(value['png']) or value['png'] != digest(data) or
                value['binding'] != digest(encoded([value['key'], value['bbox'], value['png']]))):
            raise ValueError('invalid image metadata')
        if value['key'] != key: return None
        _verify_key(key)
        if tuple(size) != _size(key): raise ValueError('render size differs')
        if value != _image_meta(key, value['bbox'], data, value.get('adopted') is True):
            raise ValueError('invalid image metadata binding')
        png(data, value['bbox'], size)
        if counts is not None: _record(counts, 'reused', key['source'].get('provenance', key['source']))
        return value['bbox']
    except Exception as exc:
        if not _absent(exc) and not isinstance(exc, _Stale): _log(exc)
        return None
def adopt_image(row, data, provenance, scale, path, metadata, counts, bbox):
    """Return supplied bbox or None. Adoption certifies current checks, not history."""
    try:
        key = image_key(row, data, provenance, scale); seed = _seed(key)
        if os.path.realpath(metadata) in (os.path.realpath(path), os.path.realpath(seed['path'])):
            raise ValueError('adoption destination aliases an input')
        size = _size(key)
        if not isinstance(bbox, (list, tuple)): raise ValueError('invalid adoption bbox')
        bbox = list(bbox); original = read(path); png(original, bbox, size)
        if image_cached(path, metadata, key, size) is not None: return None
        value = _image_meta(key, bbox, original, True)
        def unchanged():
            _seed(key)
            if read(path) != original: raise ValueError('PNG changed before adoption')
        _publish(((metadata, encoded(value), lambda b: _json_equal(b, value)),), unchanged)
        _record(counts, 'adopted', seed)
        return bbox
    except Exception as exc:
        _log(exc)
        return None
def save_image(image, bbox, path, metadata, key, size, counts=None):
    try:
        _verify_key(key)
        if tuple(size) != _size(key): raise ValueError('render size differs')
        buffer = io.BytesIO(); image.save(buffer, format='PNG', optimize=True); data = buffer.getvalue()
        replace_pair(path, data, metadata, _image_meta(key, bbox, data), lambda b: png(b, bbox, size), lambda: _verify_key(key))
    except Exception:
        if counts is not None: _record(counts, 'errors', key['source'].get('provenance', key['source']))
        raise
    if counts is not None: _record(counts, 'generated', key['source'].get('provenance', key['source']))
