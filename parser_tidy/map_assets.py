"""Region-scoped map assets. Seeds are read-only; this module also runs on 2.7."""
from __future__ import print_function
import hashlib
import json
import logging
import math
import os
import re
import stat
import tempfile

POLYGON_VERSION = 1
RENDER_VERSION = 1
ROOT = os.path.dirname(os.path.abspath(__file__))


def read(path):
    with open(path, 'rb') as stream:
        return stream.read()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf8')


def placeholder(data):
    return len(data) == 32 and re.match(b'^[0-9A-Fa-f]{32}$', data) is not None


def polygon_data(data):
    value = json.loads(data.decode('utf8'))
    if not isinstance(value, list) or not value:
        raise ValueError('empty or invalid polygon list')
    for points in value:
        if not isinstance(points, list) or len(points) < 3:
            raise ValueError('invalid polygon')
        for xy in points:
            if not isinstance(xy, list) or len(xy) != 2:
                raise ValueError('invalid coordinate')
            if any(isinstance(n, bool) or not isinstance(n, (int, float)) or
                   math.isnan(n) or math.isinf(n) for n in xy):
                raise ValueError('invalid coordinate number')
    return value


def summarize(function):
    def run(c):
        assets = Assets(c.PATH_INPUT_DATA)
        try:
            return function(c, assets)
        finally:
            assets.summary()
    return run


def publish(path, meta_path, writer, validate, metadata):
    """Validate both staged files, then replace individually with rollback."""
    staged, backups, replaced = [], {}, []
    try:
        for target in (path, meta_path):
            directory = os.path.dirname(target)
            if not os.path.isdir(directory):
                os.makedirs(directory)
            fd, temp = tempfile.mkstemp(prefix='.map-', dir=directory)
            os.close(fd)
            staged.append(temp)
            if os.path.exists(target):
                fd, backup = tempfile.mkstemp(prefix='.map-', dir=directory)
                os.close(fd)
                backups[target] = backup
                with open(backup, 'wb') as stream:
                    stream.write(read(target))
                os.chmod(backup, stat.S_IMODE(os.stat(target).st_mode))
        writer(staged[0])
        details = validate(staged[0])
        info = dict(metadata, sha256=digest(read(staged[0])), details=details)
        with open(staged[1], 'wb') as stream:
            stream.write(encoded(info))
        if json.loads(read(staged[1]).decode('utf8')) != info:
            raise ValueError('metadata validation failed')
        for target, temp in zip((path, meta_path), staged):
            mode = stat.S_IMODE(os.stat(target).st_mode) if target in backups else 0o644
            os.chmod(temp, mode)
        for target, temp in zip((path, meta_path), staged):
            os.rename(temp, target)
            replaced.append(target)
        return info
    except Exception:
        for target in reversed(replaced):
            if target in backups:
                os.rename(backups[target], target)
            else:
                os.unlink(target)
        raise
    finally:
        for temp in staged + list(backups.values()):
            if os.path.exists(temp):
                os.unlink(temp)


class Assets(object):
    def __init__(self, input_path, root=None):
        self.root = os.path.realpath(root or ROOT)
        self.input = os.path.realpath(input_path if os.path.isabs(input_path)
                                      else os.path.join(self.root, input_path))
        self.region = os.path.basename(self.input)
        if self.region.endswith('_unpack'):
            self.region = self.region[:-7]
        if not re.match(r'^[A-Za-z0-9_-]+$', self.region):
            raise ValueError('invalid input region')
        self.cache = os.path.join(self.root, '.map_assets', self.region)
        self.bg = os.path.join(self.input, 'bg.ipf')
        self.index = []
        for directory, _, files in os.walk(self.bg):
            for name in files:
                if name.lower().endswith('.tok'):
                    self.index.append(os.path.relpath(os.path.join(directory, name), self.bg).replace(os.sep, '/'))
        self.counts = {kind: dict.fromkeys(('generated', 'reused', 'placeholder', 'missing', 'errors'), 0)
                       for kind in ('polygon', 'PNG')}

    def issue(self, kind, reason, row, error):
        self.counts[kind][reason] += 1
        logging.warning('%s %s %s: %s', kind, row.get('ClassName'), reason, error)

    def summary(self):
        for kind in ('polygon', 'PNG'):
            print('%s generated=%d reused=%d placeholder=%d missing=%d errors=%d' %
                  ((kind,) + tuple(self.counts[kind][key] for key in
                   ('generated', 'reused', 'placeholder', 'missing', 'errors'))))

    def name(self, row):
        name = row['ClassName'].lower()
        if not re.match(r'^[a-z0-9_-]+$', name):
            raise ValueError('invalid ClassName')
        return name

    def source(self, row):
        name = row.get('BgName') or row['ClassName']
        if not isinstance(name, type(row['ClassName'])):
            raise ValueError('invalid BgName')
        name = name.replace('\\', '/')
        if name.lower().startswith('bg.ipf/'):
            name = name[7:]
        if any(part in ('', '.', '..') for part in name.split('/')) or ':' in name or '\x00' in name:
            raise ValueError('invalid TOK path')
        if not name.lower().endswith('.tok'):
            name += '.tok'
        matches = [item for item in self.index if item == name]
        if not matches:
            matches = [item for item in self.index if item.lower() == name.lower()]
        if not matches and '/' not in name:
            matches = [item for item in self.index if item.rsplit('/', 1)[-1] == name]
            if not matches:
                matches = [item for item in self.index if item.rsplit('/', 1)[-1].lower() == name.lower()]
        if not matches:
            raise IOError('missing TOK: ' + name)
        if len(matches) != 1:
            raise ValueError('ambiguous TOK: ' + name)
        path = os.path.realpath(os.path.join(self.bg, matches[0]))
        if not path.startswith(os.path.realpath(self.bg) + os.sep):
            raise ValueError('TOK outside bg.ipf')
        data = read(path)
        if placeholder(data):
            return None, data
        return path, data

    def polygon(self, row, convert=None):
        try:
            name = self.name(row) + 'poly.json'
        except Exception as error:
            self.issue('polygon', 'errors', row, error)
            return None
        path = os.path.join(self.cache, name)
        try:
            try:
                source, data = self.source(row)
            except (IOError, OSError) as error:
                self.issue('polygon', 'missing', row, error)
                source, data = None, None
            if source is None and data is not None:
                self.issue('polygon', 'placeholder', row, 'MD5 placeholder')
            elif source is not None:
                expected = dict(source=source, region=self.region, tok=digest(data), version=POLYGON_VERSION)
                try:
                    raw = read(path)
                    polygons = polygon_data(raw)
                    meta = json.loads(read(path + '.meta.json').decode('utf8'))
                    if meta.get('sha256') != digest(raw):
                        raise ValueError('polygon cache hash mismatch')
                    if all(meta.get(k) == v for k, v in expected.items()):
                        self.counts['polygon']['reused'] += 1
                        return polygons
                    logging.info('Stale polygon cache for %s', row.get('ClassName'))
                except Exception as error:
                    if os.path.exists(path):
                        self.issue('polygon', 'errors', row, error)
                if convert is not None:
                    raw = encoded(convert(data))
                    polygons = polygon_data(raw)
                    def writer(temp):
                        with open(temp, 'wb') as stream:
                            stream.write(raw)
                    publish(path, path + '.meta.json', writer, lambda p: polygon_data(read(p)), expected)
                    self.counts['polygon']['generated'] += 1
                    return polygons
        except Exception as error:
            self.issue('polygon', 'errors', row, error)
        try:
            polygons = polygon_data(read(os.path.join(self.root, 'maps_poly', name)))
            self.counts['polygon']['reused'] += 1
            return polygons
        except (IOError, OSError):
            return None
        except Exception as error:
            self.issue('polygon', 'errors', row, error)
            return None

    def png(self, row, polygons, path, scale, render):
        from PIL import Image
        from PIL.PngImagePlugin import PngInfo
        width, height = int(row['Width']), int(row['Height'])
        expected = dict(polygon=digest(encoded(polygons)), width=width, height=height,
                        scale=scale, version=RENDER_VERSION, region=self.region,
                        input=self.input, name=self.name(row))
        try:
            source, data = self.source(row)
            expected.update(source=source, tok=digest(data) if source else None)
        except (IOError, OSError, ValueError):
            expected.update(source=None, tok=None)
        meta_path = os.path.join(self.cache, self.name(row) + '.png.meta.json')
        def validate(temp):
            with Image.open(temp) as image:
                if image.format != 'PNG' or min(image.size) <= 0:
                    raise ValueError('invalid PNG')
                image.verify()
            with Image.open(temp) as image:
                image.load()
                if image.mode != 'RGBA' or image.getbbox() is None:
                    raise ValueError('empty PNG')
                return list(image.size)
        def valid_bbox(bbox, size):
            return (isinstance(bbox, list) and len(bbox) == 4 and
                    all(type(n) is int for n in bbox) and 0 <= bbox[0] < bbox[2] <= int(round(width * scale)) and
                    0 <= bbox[1] < bbox[3] <= int(round(height * scale)) and
                    [bbox[2] - bbox[0], bbox[3] - bbox[1]] == size)
        try:
            meta = json.loads(read(meta_path).decode('utf8'))
            size = validate(path)
            with Image.open(path) as image:
                embedded_bbox = json.loads(image.info.get('map_bbox', 'null'))
            if (all(meta.get(k) == v for k, v in expected.items()) and meta.get('sha256') == digest(read(path))
                    and meta.get('details') == size and meta.get('bbox') == embedded_bbox
                    and valid_bbox(meta.get('bbox'), size)):
                self.counts['PNG']['reused'] += 1
                return meta['bbox']
        except Exception:
            pass
        def writer(temp):
            bbox = list(render(temp))
            if not valid_bbox(bbox, validate(temp)):
                raise ValueError('PNG bbox mismatch')
            with Image.open(temp) as image:
                copy = image.copy()
            info = PngInfo()
            info.add_text('map_bbox', json.dumps(bbox))
            try:
                copy.save(temp, format='PNG', pnginfo=info)
            finally:
                copy.close()
            expected['bbox'] = bbox
        meta = publish(path, meta_path, writer, validate, expected)
        self.counts['PNG']['generated'] += 1
        return meta['bbox']
