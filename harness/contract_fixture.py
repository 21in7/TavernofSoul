"""Hand-written JSON edges augment the source fixture; no game data is needed."""
import json
from pathlib import Path

EXTENSIONS = Path(__file__).parent / 'fixtures' / 'contract_extensions.json'


def add_contract_edges(db):
    for collection, value in json.loads(EXTENSIONS.read_text(encoding='utf-8')).items():
        if collection == 'item_type':
            for group, names in value.items():
                db.data[collection].setdefault(group, []).extend(names)
        elif isinstance(value, dict):
            db.data[collection].update(value)
        else:
            db.data[collection].extend(value)
    return db
