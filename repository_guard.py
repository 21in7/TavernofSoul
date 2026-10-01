#!/usr/bin/env python3
"""Verify repository ownership before automatic Git operations."""

import argparse
from pathlib import Path
import re
import subprocess


def git(path, *args):
    return subprocess.check_output(
        ["git", "-C", str(path), *args], stderr=subprocess.PIPE
    ).decode("utf-8", "surrogateescape").strip()


def validate_repository(path, repository_name, unpack=False):
    path = Path(path).resolve()
    root = Path(git(path, "rev-parse", "--show-toplevel")).resolve()
    if root != path:
        raise ValueError(f"Expected independent repository at {path}; found {root}")
    expected = re.compile(
        r"(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)"
        + re.escape("21in7/" + repository_name)
        + r"(?:\.git)?/?$"
    )
    for args in [("remote", "get-url", "--all", "origin"),
                 ("remote", "get-url", "--push", "--all", "origin")]:
        urls = git(path, *args).splitlines()
        if not urls or any(not expected.fullmatch(url) for url in urls):
            raise ValueError(f"Wrong origin for {path}: {urls}; expected 21in7/{repository_name}")
    if unpack:
        paths = git(path, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
        validate_unpack_paths(paths.split("\0"))
    return root


def validate_unpack_paths(paths):
    metadata = {".gitignore", ".gitattributes", "README.md", "readme.md"}
    invalid = [path for path in paths if path and path not in metadata
               and not path.split("/", 1)[0].endswith(".ipf")]
    if invalid:
        raise ValueError("Only unpacked .ipf content and repository metadata are allowed: "
                         + ", ".join(invalid[:10]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("repository_name")
    parser.add_argument("--unpack", action="store_true")
    args = parser.parse_args()
    try:
        validate_repository(args.path, args.repository_name, args.unpack)
    except (ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Repository guard: {error}\n")


if __name__ == "__main__":
    main()
