import logging
import os
import struct
import zlib


PAK_BLACKLIST = [
    b'.aes',
    b'.dll',
    b'.lua',
    b'beforedata/',
    b'bgm/',
    b'BlackCipher/',
    b'loadingimg/',
    b'Client_tos.exe',
    b'hotkey',
    b'xigncode',
]

OFFSET_FILE_NAME_LEN = 0
OFFSET_CHECKSUM = 2 + OFFSET_FILE_NAME_LEN
OFFSET_SIZE_COMPRESSED = 4 + OFFSET_CHECKSUM
OFFSET_SIZE_UNCOMPRESSED = 4 + OFFSET_SIZE_COMPRESSED
OFFSET_FILE_NAME = 4 + OFFSET_SIZE_UNCOMPRESSED

# Neither a whole PAK archive nor a whole member is ever buffered: archive
# reads and raw-deflate output are both limited to these fixed chunk sizes.
# They stay module globals so the harness can shrink them to drive the
# chunked path with small fixed inputs.
_READ_CHUNK_SIZE = 65536
_INFLATE_CHUNK_SIZE = 1 << 20


def _read_exact(source, length, error):
    # A single read() may legally return fewer bytes than asked even before
    # the end of the file, so required reads loop until they have exactly
    # length bytes or the archive ends short.
    data = b''
    while len(data) < length:
        chunk = source.read(length - len(data))
        if not chunk:
            raise ValueError(error)
        data += chunk
    return data


def _iter_member_chunks(source, offset, length):
    # Yield the record's compressed member in bounded chunks; never join
    # them, so no whole member is held in memory.
    source.seek(offset)
    remaining = length
    while remaining:
        chunk = source.read(min(_READ_CHUNK_SIZE, remaining))
        if not chunk:
            raise ValueError('Invalid or truncated PAK record')
        remaining -= len(chunk)
        yield chunk


def _inflate_member(member_chunks, destination_file, size_uncompressed):
    # Raw-deflate the member into destination_file without buffering it
    # whole. Every decompress call passes the same fixed positive
    # max_length, so a single call can never return more than
    # _INFLATE_CHUNK_SIZE bytes; the actual decoded byte count and the
    # completion of the deflate stream are validated below.
    decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
    written = 0
    for chunk in member_chunks:
        while chunk and not decompressor.eof:
            piece = decompressor.decompress(chunk, _INFLATE_CHUNK_SIZE)
            if piece:
                written += len(piece)
                if written > size_uncompressed:
                    raise ValueError('PAK uncompressed size mismatch')
                destination_file.write(piece)
            if decompressor.eof:
                # Trailing bytes after the deflate stream are ignored, just
                # like zlib.decompress ignored them.
                break
            chunk = decompressor.unconsumed_tail
        if decompressor.eof:
            break
    if not decompressor.eof:
        raise zlib.error('incomplete or truncated stream')
    if written != size_uncompressed:
        raise ValueError('PAK uncompressed size mismatch')


def unpack(pak, patch_destination):
    pak = os.path.join(patch_destination, pak)
    logging.warning('Unpacking %s...', pak)
    pak_file = pak
    with open(pak, 'rb') as source:
        pak_size = os.fstat(source.fileno()).st_size
        if not pak_size:
            raise ValueError('Empty PAK archive')
        pak_offset = 0

        while pak_offset < pak_size:
            if pak_size - pak_offset < OFFSET_FILE_NAME:
                raise ValueError('Truncated PAK header')
            source.seek(pak_offset)
            header = _read_exact(source, OFFSET_FILE_NAME, 'Truncated PAK header')
            # Thanks to https://github.com/celophi/Arboretum/blob/master/Arboretum.Lib/PakFile.cs
            file_name_len = struct.unpack_from('@h', header, OFFSET_FILE_NAME_LEN)[0]
            checksum = struct.unpack_from('@i', header, OFFSET_CHECKSUM)[0]
            size_compressed = struct.unpack_from('@i', header, OFFSET_SIZE_COMPRESSED)[0]
            size_uncompressed = struct.unpack_from('@i', header, OFFSET_SIZE_UNCOMPRESSED)[0]
            record_end = pak_offset + OFFSET_FILE_NAME + file_name_len + size_compressed
            if file_name_len <= 0 or size_compressed < 0 or size_uncompressed < 0 or record_end > pak_size:
                raise ValueError('Invalid or truncated PAK record')

            source.seek(pak_offset + OFFSET_FILE_NAME)
            file_name = _read_exact(source, file_name_len, 'Invalid or truncated PAK record')

            if not any(s in file_name for s in PAK_BLACKLIST):
                logging.debug('Unzipping %s...', file_name)
                file_name = file_name.decode(encoding='utf-8')
                # A decoded member name must stay inside patch_destination:
                # absolute paths, '..' components and backslashes are rejected
                # before any directory or .part file is created, so a damaged
                # or hostile archive can never write outside it.
                if (os.path.isabs(file_name) or '..' in file_name.split('/')
                        or '\\' in file_name):
                    raise ValueError('Unsafe PAK member name')
                file_path = os.path.join(patch_destination, file_name)

                # ensure file_path exists
                if not os.path.exists(os.path.dirname(file_path)):
                    os.makedirs(os.path.dirname(file_path))

                # The destination is only replaced after the member decoded
                # fully and cleanly, so failures leave its old contents alone.
                temporary = file_path + '.part'
                try:
                    with open(temporary, 'wb') as destination:
                        member_chunks = _iter_member_chunks(
                            source,
                            pak_offset + OFFSET_FILE_NAME + file_name_len,
                            size_compressed,
                        )
                        _inflate_member(member_chunks, destination, size_uncompressed)
                        destination.flush()
                        os.fsync(destination.fileno())
                    os.replace(temporary, file_path)
                finally:
                    if os.path.exists(temporary):
                        os.remove(temporary)

            pak_offset += OFFSET_FILE_NAME + file_name_len + size_compressed

    # Every record was replaced cleanly; only after the archive is closed
    # is it discarded, so any earlier failure preserves the downloaded file.
    os.remove(pak_file)
