import logging
import sys
import urllib.request, urllib.error, urllib.parse
import os
import json
import struct
if __package__:
    from . import blowfish, unpacker_pak
else:
    import blowfish
    import unpacker_pak
import shutil
from shutil import copyfile, move, rmtree
import subprocess 
from os.path import join
import csv
import tempfile
import stat
IPF_BLACKLIST = []
region = ""
error_ipf = [] #the somehow error patch
EXIT_CHANGED = 0
EXIT_UNCHANGED = 1
EXIT_FAILED = 2


def git_sync(patch_name):
    pass
    # cwd= os.getcwd()
    # os.chdir(join("..", "{}_unpack".format(region)))
    # subprocess.run(['git', 'add', '.'])
    # subprocess.run(['git', 'commit', '-m', patch_name])
    # subprocess.run(['git', 'push'])
    # os.chdir(cwd)

def copyfiles(output):
    if not os.path.exists(output):
        os.makedirs(output, exist_ok=True)
    files = ['shared.ipf', 
             'ies_ability.ipf',
             'ies_client.ipf',
             'ies_drop.ipf',
             'ies_mongen.ipf',
             'ui.ipf',
             'bg.ipf',
             'language.ipf',
             'ies.ipf',
             'xml.ipf',
             'skill_bytool.ipf', 
             'char_hi.ipf',
             'char_texture.ipf',
             'item_hi.ipf',
             'item_texture.ipf',
             'addon.ipf']
    for i in files:
        if os.path.exists (join('extract',i)):
            subprocess.run(['cp', '-r', join('extract',i), output], check=True)
            logging.warning("copying to {}".format(join(output,i)))


def validate_ies_csv(path):
    """Strictly parse one extracted IES CSV in memory without writing to it.

    A field containing a comma, quote or newline must be quoted with inner
    quotes doubled; quoted commas, doubled quotes, multiline fields and
    header-only tables are valid. A first record that is a single unquoted
    empty field (for example a leading blank line) is a missing header. The
    first problem raises RuntimeError naming the file, the 1-based record
    number and the cause. Content is never repaired and no record is ever
    dropped.
    """
    try:
        with open(path, 'r', encoding='utf-8', newline='') as handle:
            text = handle.read()
    except UnicodeDecodeError as error:
        raise RuntimeError('Extracted IES CSV is not UTF-8: {}'.format(path)) from error
    if not text:
        raise RuntimeError('Extracted IES CSV is empty: {}'.format(path))

    def fail(record, cause):
        raise RuntimeError('Extracted IES CSV {} record {}: {}'.format(path, record, cause))

    width = None
    number = 1
    fields = []
    characters = []
    quoted = False
    closed = False
    record_quoted = False
    position = 0
    size = len(text)
    while position < size:
        char = text[position]
        if quoted:
            if char == '"':
                if position + 1 < size and text[position + 1] == '"':
                    characters.append('"')
                    position += 1
                else:
                    quoted = False
                    closed = True
            else:
                characters.append(char)
        elif char == '"':
            if closed:
                fail(number, 'text follows the closing quote')
            if characters:
                fail(number, 'quote inside an unquoted field')
            quoted = True
            record_quoted = True
        elif char == ',':
            fields.append(''.join(characters))
            characters = []
            closed = False
        elif char == '\r' or char == '\n':
            if char == '\r' and position + 1 < size and text[position + 1] == '\n':
                position += 1
            fields.append(''.join(characters))
            characters = []
            closed = False
            if number == 1:
                if fields == [''] and not record_quoted:
                    fail(number, 'the file has no header row')
                width = len(fields)
            elif len(fields) != width:
                fail(number, 'has {} fields, expected {} per the header'.format(len(fields), width))
            fields = []
            record_quoted = False
            number += 1
        elif closed:
            fail(number, 'text follows the closing quote')
        else:
            characters.append(char)
        position += 1
    if quoted:
        fail(number, 'quoted field is not terminated')
    if closed or characters or fields:
        fields.append(''.join(characters))
        if number == 1:
            if fields == [''] and not record_quoted:
                fail(number, 'the file has no header row')
        elif len(fields) != width:
            fail(number, 'has {} fields, expected {} per the header'.format(len(fields), width))


def validate_extracted_ies(root):
    """Validate every *.ies extracted under root in a deterministic order."""
    validated = 0
    for directory, subdirectories, names in os.walk(root):
        subdirectories.sort()
        for name in sorted(names):
            if name.lower().endswith('.ies'):
                validate_ies_csv(join(directory, name))
                validated += 1
    logging.debug('Validated {} IES CSV files under {}'.format(validated, root))


def unpack(f):
    IPF_PATH    = join("..", "{}_patch".format(region))
    OUTPUT_PATH = join("..", "{}_unpack".format(region))
    unpacker    = join("..", 'IPFUnpacker', 'ipf_unpack')
    extension_needed = ['ies', 'xml', 'lua','png', 'jpg', 'tga', 'json' ]
    logging.warning("patching {}".format(f))
    cur_file = join(IPF_PATH, f)
    copyfile(cur_file, f)
    # Never reuse files from a previous failed extraction.
    if os.path.exists('extract'):
        rmtree('extract')
    try:
        subprocess.run([unpacker, f, 'decrypt'], check=True)
        subprocess.run([unpacker, f, 'extract'] + extension_needed, check=True)
        if not os.path.isdir('extract'):
            raise RuntimeError('IPF extraction produced no output directory')
        # An old installed ipf_unpack wrote raw quotes that shifted every
        # column after them; extracted CSVs must parse strictly before any of
        # this patch is published or the downloaded archive is discarded.
        validate_extracted_ies('extract')
        copyfiles(OUTPUT_PATH)
        # Keep the original downloaded archive until every copy has succeeded.
        os.remove(cur_file)
    finally:
        if os.path.exists(f):
            os.remove(f)
        if os.path.exists('extract'):
            rmtree('extract')
    git_sync(f)
    
            



def revision_decrypt(revision):
    # Thanks to https://github.com/celophi/Arboretum/blob/master/Arboretum.Lib/Decryptor.cs
    if len(revision) < 8:
        raise ValueError('Truncated revision header')
    size_unencrypted = struct.unpack_from('@i', revision, 0)[0]
    size_encrypted = struct.unpack_from('@i', revision, 4)[0]
    if size_encrypted < 0 or size_encrypted % 8 or 8 + size_encrypted > len(revision):
        raise ValueError('Invalid encrypted revision length')

    revision = [ord(chr(c)) for c in revision]               # Convert to binary
    blowfish.Decipher(revision, 8, size_encrypted)      # Decrypt with blowfish
    revision = [chr(c) for c in revision]            # Convert back to unicode characters

    # Clean and split into a list
    #revision = ''\
    #    .join(revision[8:])\
    #    .encode('ascii', 'ignore')\
    #    .split('\r\n')
    revision = ''\
        .join(revision[8:])\
        .split('\r\n')
    return revision[:-1]


def getRegion(reg):
    if len(reg) < 2:
        raise ValueError('need 1 positional argument; region')
    selected = reg[1].lower()
    if selected not in ['itos', 'ktos', 'ktest', 'jtos', 'twtos']:
        raise ValueError('region unsupported: {}'.format(selected))
    return selected
    
def write(l,file):
    with open(file, 'w', encoding= 'utf-8') as f:
        json.dump(l,f)
        
def read(file):
    with open(file, 'r', encoding= 'utf-8') as f:
        return json.load(f)

  
def patch_full(patch_path, patch_url, patch_ext, patch_unpack, revision_url,repatch):
    logging.warning('Patching %s...', revision_url)
    with urllib.request.urlopen(revision_url, timeout=60) as response:
        revision_list = response.read()
    revision_list = revision_decrypt(revision_list)

    for revision in revision_list:
        # Download patch
        patch_name = revision + patch_ext
        patch_file = os.path.join(patch_path, patch_name)
        if (not os.path.exists(os.path.join(patch_path, patch_name)) or repatch==1  )and patch_name not in IPF_BLACKLIST :
            logging.warning('Lets Downloading %s...', patch_url + patch_name)
            patch_process(patch_file, patch_name, patch_unpack, patch_url, patch_path)



def patch_process(patch_file, patch_name, patch_unpack, patch_url, patch_destination = ""):
    if patch_name in error_ipf:
        raise RuntimeError('Patch is blocked: {}'.format(patch_name))
    # Ensure patch_file destination exists
    if not os.path.exists(os.path.dirname(patch_file)):
        os.makedirs(os.path.dirname(patch_file))
    def request_as_fox(url):
        headers={"User-Agent":"tos"}
        return urllib.request.Request(url,None,headers)

    filesize = 0
    if os.path.exists(patch_file):
        filesize = os.path.getsize(patch_file)

    if not os.path.isfile(patch_file) or filesize==0:
        # Download patch
        logging.warning('Downloading %s ...', patch_url + patch_name)
        # A failed transfer must not become a nonempty, reusable cache entry.
        partial = patch_file + '.part'
        try:
            with urllib.request.urlopen(request_as_fox(patch_url + patch_name), timeout=60) as response:
                expected = response.headers.get('Content-Length')
                total = 0
                with open(partial, 'wb') as file:
                    while True:
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        file.write(chunk)
                        total += len(chunk)
                    file.flush()
                    os.fsync(file.fileno())
                if not total or (expected is not None and total != int(expected)):
                    raise ValueError('Empty or incomplete patch: {}'.format(patch_name))
            os.replace(partial, patch_file)
        finally:
            if os.path.exists(partial):
                os.remove(partial)
    else:
        logging.debug("Reusing cache %s...",patch_name)

    if os.path.isfile(patch_file):
        filesize = os.path.getsize(patch_file)

    if filesize == 0:
        raise ValueError('Filesize is ZERO: {}'.format(patch_file))
    else:
        pass
    # Extract patch
    if(patch_unpack):
        try:
            unpacker_pak.unpack(patch_name,patch_destination)
        except (ValueError, struct.error, unpacker_pak.zlib.error):
            # Discard malformed archive bytes so a retry downloads a fresh copy.
            if os.path.exists(patch_file):
                os.remove(patch_file)
            raise
    else:
        unpack(patch_name)
    # Delete patch
    # os.remove(patch_file)



def print_version(filename, data):
    out = [ [key, data[key]] for key in data]
    descriptor, temporary = tempfile.mkstemp(prefix='.download-version-',
                                           dir=os.path.dirname(os.path.abspath(filename)))
    try:
        with os.fdopen(descriptor, 'w', newline='') as f:
            csv.writer(f).writerows(out)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(filename):
            os.chmod(temporary, stat.S_IMODE(os.stat(filename).st_mode))
        os.replace(temporary, filename)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)

def read_version(filename):
    rev = {}
    with open(filename, 'r') as f:
        w = csv.reader(f)
        for lines in w:
            if len(lines)<2:
                continue
            rev[lines[0]] = lines[1]
    return rev

def patch_partial(patch_path, patch_url, patch_ext, patch_unpack, revision_path, revision_url,repatch):
    logging.debug('Patching %s...', revision_url)
    with urllib.request.urlopen(revision_url, timeout=60) as response:
        revision_list = response.read()
    revision_list = revision_decrypt(revision_list)
    revision_old = read_version(revision_path)
    revision_new = revision_old.copy()
    has_changes = False
    # Apply older patches before newer ones regardless of server list order.
    revisions = sorted(set(line.split(' ')[0] for line in revision_list), key=int)
    for revision in revisions:
     
        if (int(revision) > int(revision_new[region]) or repatch==1) and revision not in ['147674']:
            # Process patch
            patch_name = revision + '_001001' + patch_ext
            patch_file = os.path.join(patch_path, patch_name)
            filesize = 0
            if os.path.isfile(patch_file):
                filesize = os.path.getsize(patch_file)
            
            patch_process(patch_file, patch_name, patch_unpack, patch_url, patch_path)

            if patch_unpack:
                # Translation publication is part of a completed release patch.
                # Keep its cursor behind if copying fails so the next run retries.
                move_language(region)
            # Update revision
            revision_new[region] = revision
            print_version(revision_path, revision_new)
            has_changes = True

    return revision_old, revision_new, has_changes



def do_patch_full(patch_output, url_patch):   
    patch_full(
        os.path.join("..", "{}_patch".format(region)),  url_patch + 'full/data/', '.ipf', False,
        url_patch + 'full/data.file.list.txt',True
    )
    

def move_language(region):
    if region not in ['itos', 'jtos', 'twtos']:
        return 

    input_path  = {'itos' : os.path.join('..', 'itos_patch', 'languageData', 'English'),
                   'jtos' : os.path.join('..', 'jtos_patch', 'languageData', 'Japanese'),
                   'twtos' : os.path.join('..', 'twtos_patch', 'languageData', 'Taiwanese'),}

    output_path = os.path.join('..', 'Translation')
    input_path  = input_path[region]
    if os.path.exists(input_path):
        #try:
        #    #shutil.move(input_path, output_path)
        os.makedirs(output_path, exist_ok=True)
        subprocess.run(['cp', '-r', input_path, output_path], check=True)
        #except:
        #    pass



def main(argv=None):
    global region
    argv = sys.argv[1:] if argv is None else argv
    try:
        return _run(argv)
    except Exception:
        logging.exception('Download failed; parsing and DB import must stop')
        return EXIT_FAILED


def _run(argv):
    global region
    logging.warning('Patching...')
    region = getRegion(['downloader.py'] + argv)
    #region = "itos"
    url_patch = {'itos' : 'http://drygkhncipyq8.cloudfront.net/toslive/patch/',
                 'jtos' : 'http://d3bbj7hlpo9jjy.cloudfront.net/live/patch/',
                 'ktos' : 'http://d31k064uwo645x.cloudfront.net/patchkor/',
                 'ktest' : 'http://tosg.dn.nexoncdn.co.kr/patch/test/',
                 'twtos' : 'http://tospatch.x2game.com.tw/live/patch/'}
    
    
    
    url_patch = url_patch[region]
    output = os.path.join("..", "{}_patch".format(region))
    
    if ('full' in argv ):
        do_patch_full(output, url_patch)
        return EXIT_CHANGED
    else:
        version_data, version_data_new, has_data_chages = patch_partial(
            output , url_patch + 'partial/data/', '.ipf', False,
            'revision.csv', url_patch + 'partial/data.revision.txt' ,0
        )
        version_release, version_release_new, has_release_chages = patch_partial(
            output, url_patch + 'partial/release/', '.pak', True,
            'release.csv', url_patch + 'partial/release.revision.txt',0
        )

        move_language(region)

        # 변경 사항이 있으면 0, 없으면 1을 반환
        if has_data_chages or has_release_chages:
            return EXIT_CHANGED
        else:
            return EXIT_UNCHANGED


if __name__ == "__main__":
    sys.exit(main())
