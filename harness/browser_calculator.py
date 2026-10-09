"""Execute the shipped JavaScript in Node, including input handlers and DOM writes."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run_calculator(data, inputs, ids=None):
    request = {'data': data, 'inputs': inputs, 'ids': ids}
    result = subprocess.run(['node', str(ROOT / 'harness/browser_calculator.js'),
                             str(ROOT / 'TavernofSoul/static/js/item-enhancement.js')],
                            input=json.dumps(request), text=True, capture_output=True, timeout=15)
    if result.returncode:
        raise AssertionError('Calculator JavaScript failed:\n' + result.stderr)
    return json.loads(result.stdout)
