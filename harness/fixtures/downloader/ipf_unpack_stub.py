"""Executable stand-in for the native IPF tool; used only in temporary tests."""
import json
from pathlib import Path
import sys

archive, action = sys.argv[1:3]
with Path('tool_calls.log').open('a') as calls:
    calls.write(action + '\n')
if Path('fail-' + action).exists():
    raise SystemExit(7)
if action == 'extract':
    data = json.loads(Path(archive).read_text())
    for name, contents in data['files'].items():
        destination = Path('extract') / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents, encoding='utf-8')
