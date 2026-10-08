"""Required source fixtures shared by preflight and the offline parser runner."""
from pathlib import Path

FIXTURE = Path(__file__).parent / 'fixtures' / 'parser'
COMBAT_FIXTURE = Path(__file__).parent / 'fixtures' / 'combat'
WORLD_FIXTURE = Path(__file__).parent / 'fixtures' / 'world'
REGIONAL_FIXTURE = Path(__file__).parent / 'fixtures' / 'regional'
EQUIPMENT_FIXTURE = Path(__file__).parent / 'fixtures' / 'equipment'
EQUIPMENT_INPUTS = (
    'ies.ipf/item_equip.ies', 'ies.ipf/item_grade.ies', 'ies.ipf/item_gem.ies',
    'ies.ipf/item_goddess_reinforce_540.ies', 'ies.ipf/item_goddess_reinforce_550.ies',
    'ies.ipf/item_goddess_reinforce_560.ies', 'ies.ipf/item_goddess_reinforce_580.ies',
    'shared.ipf/equipment_calculate.lua', 'xml.ipf/socket_property.xml',
)
REGIONS = ('itos', 'ktos', 'ktest', 'jtos', 'twtos')
TRANSLATION_DIRECTORIES = {'itos': 'English', 'jtos': 'Japanese', 'twtos': 'Taiwanese'}
REGIONAL_INPUTS = (
    'ies.ipf/item.ies', 'ies.ipf/item_equip.ies', 'ies.ipf/cardbattle.ies',
    'ies.ipf/collection.ies', 'ies.ipf/skill.ies', 'ies.ipf/skilltree.ies',
    'ies.ipf/job.ies',
    'shared.ipf/item_calculate.lua', 'language.ipf/wholeDicID.xml',
)
REQUIRED_INPUTS = (
    'ies.ipf/item.ies', 'ies.ipf/recipe.ies', 'ies.ipf/item_equip.ies',
    'ies.ipf/item_grade.ies', 'ies.ipf/sharedconst.ies',
    'ies.ipf/sharedconst_system.ies', 'ies.ipf/xac.ies',
    'shared.ipf/item_calculate.lua', 'language.ipf/wholeDicID.xml',
)
MONSTER_FILES = (
    'monster.ies', 'monster2.ies', 'monster_event.ies', 'monster_npc.ies',
    'monster_solo_dungeon.ies', 'monster_pcsummon.ies', 'monster_pet.ies',
    'monster_bountyhunt.ies', 'monster_guild.ies', 'monster_mgame.ies',
)
COMBAT_INPUTS = (
    'ies.ipf/job.ies', 'ies.ipf/statbase_pc.ies', 'ies.ipf/skill.ies',
    'ies.ipf/skilltree.ies', 'ies.ipf/cooldown.ies', 'ies.ipf/skill_mon.ies',
    'ies.ipf/monster_const.ies', 'ies.ipf/statbase_monster.ies',
    'ies.ipf/statbase_monster_type.ies', 'ies.ipf/statbase_monster_race.ies',
    'ies.ipf/field_monster_status_harness_a.ies',
    'ies.ipf/field_monster_status_harness_z.ies',
    'shared.ipf/combat_calculate.lua', 'skill_bytool.ipf/combat.xml',
    'ies_drop.ipf/HARNESS_WOLF.IES', 'ies_drop.ipf/harness_boar.ies',
) + tuple('ies.ipf/' + name for name in MONSTER_FILES)
WORLD_INPUTS = (
    'ies.ipf/map.ies', 'ies.ipf/job.ies', 'ies.ipf/monster_npc.ies',
    'ies.ipf/buff_hardskill.ies', 'ies.ipf/buff.ies',
    'ies.ipf/buff_monster.ies', 'ies.ipf/buff_contents.ies',
    'ies_ability.ipf/ability.ies', 'ies_ability.ipf/Ability_HarnessMage.IES',
    'ies_mongen.ipf/ANCHOR_harness_field.IES', 'ies_mongen.ipf/GENTYPE_harness_field.IES',
    'ies_drop.ipf/zonedrop/ZoneDropItemList_harness_field.ies',
    'ies_drop.ipf/zonedrop/ZONEDROPITEMLIST_F_HARNESS_CAVE.IES',
    'ies_drop.ipf/zonedrop/ZoneDropItemList_id_unknownsanctuary_harness.ies',
    'ies_drop.ipf/dropgroup/HARNESS_GROUP.IES',
    'ies_drop.ipf/dropgroup/SANCTUARY_GROUP.IES',
    'language.ipf/wholeDicID.xml',
)


def required_fixture_files():
    paths = [FIXTURE / 'unpack' / name for name in REQUIRED_INPUTS]
    paths += [FIXTURE / 'translation/items.tsv', FIXTURE / 'expected_items.json']
    paths += [COMBAT_FIXTURE / 'unpack' / name for name in COMBAT_INPUTS]
    paths += [COMBAT_FIXTURE / 'expected_combat.json', COMBAT_FIXTURE / 'revision.csv']
    paths += [FIXTURE.parent / 'contract_extensions.json']
    paths += [WORLD_FIXTURE / 'unpack' / name for name in WORLD_INPUTS]
    paths += [WORLD_FIXTURE / 'translation/world.tsv', WORLD_FIXTURE / 'expected_world.json']
    paths += [REGIONAL_FIXTURE / 'common/unpack' / name for name in REGIONAL_INPUTS]
    paths += [REGIONAL_FIXTURE / 'expected_regions.json']
    paths += [REGIONAL_FIXTURE / 'fallback' / region / filename
              for region in ('ktos', 'ktest')
              for filename in ('skills_by_name.json', 'assets_icons.json')]
    paths += [REGIONAL_FIXTURE / region / 'unpack/ies.ipf/sharedconst.ies' for region in REGIONS]
    paths += [REGIONAL_FIXTURE / region / 'translation/regional.tsv'
              for region in TRANSLATION_DIRECTORIES]
    paths += [EQUIPMENT_FIXTURE / 'unpack' / name for name in EQUIPMENT_INPUTS]
    paths += [EQUIPMENT_FIXTURE / 'expected_equipment.json']
    return paths
