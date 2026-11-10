"""Human mistake guard for make entry points; not an authorization boundary."""
import argparse
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parent.parent


def open_directory(path):
    """Pin every directory component without following symlinks."""
    path = Path(path).absolute()
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_file(path, limit, private=False):
    parent = open_directory(Path(path).parent)
    try:
        fd = os.open(Path(path).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=parent)
    finally:
        os.close(parent)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                (private and (info.st_uid != os.geteuid() or
                              stat.S_IMODE(info.st_mode) != 0o600))):
            raise ValueError('Expected an owned private regular file.' if private
                             else 'Expected a regular file without aliases.')
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(fd, limit + 1 - len(data))
            if not chunk:
                return bytes(data)
            data.extend(chunk)
        raise ValueError('Local file exceeds its size limit.')
    finally:
        os.close(fd)


def host_role(root=ROOT):
    try:
        body = read_file(Path(root) / 'logs/harness/host-role', 32)
    except FileNotFoundError:
        return 'development'
    except (OSError, ValueError):
        raise ValueError('Cannot safely read host-role; refusing entry. '
                         'This marker only prevents human mistakes.') from None
    if body not in (b'development', b'development\n', b'production', b'production\n'):
        raise ValueError('Malformed host-role; use development or production. '
                         'This marker only prevents human mistakes.')
    return body.decode('ascii').rstrip('\n')


def require_development(root=ROOT):
    if host_role(root) == 'production':
        raise ValueError('Production host: workflow/Git publication make target refused. '
                         'This marker only prevents human mistakes, not unauthorized access.')


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        require_development()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
