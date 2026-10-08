"""Build item-page data from this release's persisted calculations."""
import json

from Items.models import Equipments, GoddessReinforcement, Items


def calculator_data(item):
    try:
        equipment = item.equipments
    except Equipments.DoesNotExist:
        return None
    if equipment.type_equipment == 'Arcane':
        return None
    attack, defense = equipment.anvil_atk or [], equipment.anvil_def or []
    if not attack and not defense:
        return None
    steps = []
    if item.grade == 6:
        if not equipment.reinforcement_level or not equipment.reinforcement_group:
            return None
        rows = list(GoddessReinforcement.objects.filter(level=equipment.reinforcement_level))
        if not rows or [row.step for row in rows] != list(range(1, len(rows) + 1)):
            return None
        if any(values and len(values) != len(rows) for values in (attack, defense)):
            return None
        material_names = set()
        for row in rows:
            costs = json.loads(row.materials).get(equipment.reinforcement_group)
            if costs is not None:
                material_names.update(costs)
            steps.append({'step': row.step, 'chance': row.chance / 1000,
                          'materials': costs})
        known = {entry.id_name: entry for entry in Items.objects.filter(id_name__in=material_names)}
        for step in steps:
            costs = step['materials']
            if costs is not None:
                step['materials'] = [
                    {'name': known[name].name or name, 'quantity': quantity,
                     'url': known[name].get_absolute_url()} if name in known else
                    {'name': name, 'quantity': quantity, 'url': None}
                    for name, quantity in sorted(costs.items())]
        maximum = len(rows)
    else:
        maximum = min(40, max(len(attack), len(defense)))
    return {
        'goddess': item.grade == 6, 'maximum': maximum,
        'level': equipment.reinforcement_level, 'group': equipment.reinforcement_group,
        'attack': attack, 'defense': defense, 'steps': steps,
        'prices': equipment.anvil_price or [],
        'transcendPrices': equipment.transcend_price or [],
        'transcendRate': 0.03 if item.grade == 6 else 0.1,
        'base': {name: getattr(equipment, name) or 0
                 for name in ('patk', 'patk_max', 'matk', 'pdef', 'mdef')},
    }


def gem_bonus_rows(gem):
    slots = {'Weapon': 'Main weapon', 'SubWeapon': 'Sub weapon',
             'TopAndBottom': 'Top / Bottom', 'Gloves': 'Gloves', 'Boots': 'Boots'}
    result = []
    for slot, bonuses in json.loads(gem.socket_bonuses).items():
        for bonus in bonuses:
            result.append({'slot': slots[slot], 'level': bonus.get('Level'),
                           'stat': bonus['Stat'], 'value': bonus.get('Value')})
    return result
