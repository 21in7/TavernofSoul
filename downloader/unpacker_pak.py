

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


def unpack(pak,patch_destination):
    pak = os.path.join(patch_destination, pak)
    logging.warning('Unpacking %s...', pak)
    pak_file = pak
    with open(pak, 'rb') as source:
        pak = source.read()
    if not pak:
        raise ValueError('Empty PAK archive')
    pak_offset = 0

    while pak_offset < len(pak):
        if len(pak) - pak_offset < OFFSET_FILE_NAME:
            raise ValueError('Truncated PAK header')
        # Thanks to https://github.com/celophi/Arboretum/blob/master/Arboretum.Lib/PakFile.cs
        file_name_len = struct.unpack_from('@h', pak, OFFSET_FILE_NAME_LEN + pak_offset)[0]
        checksum = struct.unpack_from('@i', pak, OFFSET_CHECKSUM + pak_offset)[0]
        size_compressed = struct.unpack_from('@i', pak, OFFSET_SIZE_COMPRESSED + pak_offset)[0]
        size_uncompressed = struct.unpack_from('@i', pak, OFFSET_SIZE_UNCOMPRESSED + pak_offset)[0]
        record_end = pak_offset + OFFSET_FILE_NAME + file_name_len + size_compressed
        if file_name_len <= 0 or size_compressed < 0 or size_uncompressed < 0 or record_end > len(pak):
            raise ValueError('Invalid or truncated PAK record')

        file_name = pak[
            OFFSET_FILE_NAME + pak_offset:
            OFFSET_FILE_NAME + file_name_len + pak_offset
        ]
        
        if not any(s in file_name for s in PAK_BLACKLIST):
            logging.debug('Unzipping %s...', file_name)
            data = pak[
                OFFSET_FILE_NAME + file_name_len + pak_offset:
                OFFSET_FILE_NAME + file_name_len + size_compressed + pak_offset
            ]
            file_name=file_name.decode(encoding="utf-8")        
            file_path = os.path.join(patch_destination, file_name )

            # ensure file_path exists
            if not os.path.exists(os.path.dirname(file_path)):
                os.makedirs(os.path.dirname(file_path))

            # Validate before opening the destination; bad bytes preserve its old contents.
            data = zlib.decompress(data, -zlib.MAX_WBITS)
            if len(data) != size_uncompressed:
                raise ValueError('PAK uncompressed size mismatch')
            temporary = file_path + '.part'
            try:
                with open(temporary, 'wb') as file:
                    file.write(data)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, file_path)
            finally:
                if os.path.exists(temporary):
                    os.remove(temporary)
    
        pak_offset += OFFSET_FILE_NAME + file_name_len + size_compressed
    os.remove(pak_file)
