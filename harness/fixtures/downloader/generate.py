"""Regenerate tiny encrypted revision / PAK fixtures without game-server access."""
from pathlib import Path
import struct
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from downloader import blowfish


def main():
    root = Path(__file__).resolve().parent
    plain = b'1\r\n2\r\n'
    padded = plain + b'\0' * (-len(plain) % 8)
    data = list(struct.pack('<ii', len(plain), len(padded)) + padded)
    blowfish.Encipher(data, 8, len(padded))
    (root / 'revisions.bin').write_bytes(bytes(value & 255 for value in data))
    records = []
    for name, contents in [
        (b'languageData/English/items.tsv', b'harness_ore\tHarness Ore\n'),
        (b'Client_tos.exe', b'ignored executable fixture'),
    ]:
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        compressed = compressor.compress(contents) + compressor.flush()
        records.append(struct.pack('<hiii', len(name), 0, len(compressed), len(contents))
                       + name + compressed)
    (root / 'release.pak').write_bytes(b''.join(records))


if __name__ == '__main__':
    main()
