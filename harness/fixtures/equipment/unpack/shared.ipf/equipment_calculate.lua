-- Hand-authored formulas; not the game's balance or full reinforcement script.
function SCR_HARNESS_REFRESH_DAWN_SWORD(item)
    local base = GetClassByType('item_goddess_reinforce_560', 1)
    item.MINATK = base.BasicAtk
    item.MAXATK = base.BasicAtk + base.AddAtk
end

function SCR_HARNESS_REFRESH_DAWN_ARMOR(item)
    local base = GetClassByType('item_goddess_reinforce_560', 1)
    item.DEF = base.BasicDef
    item.MDEF = base.BasicDef / 2
end

function SCR_REFRESH_ACC(item)
    item.MINATK = 111
    item.MAXATK = 111
    item.MATK = 111
end

function get_TC_goddess(level, class_type, current, goal)
    return (goal + 1) * 3
end

function IS_WEAPON_TYPE(class_type)
    return class_type == 'Sword' or class_type == 'Staff' or class_type == 'Trinket' or class_type == 'Shield'
end

function SCR_GET_GODDESS_REINFORCE(item)
    local column = 'AddDef'
    if IS_WEAPON_TYPE(item.ClassType) then column = 'AddAtk' end
    if item.ClassType == 'Neck' or item.ClassType == 'Ring' then column = 'AddAccAtk' end
    local result = 0
    for step = 1, item.Reinforce_2 do
        local row = GetClassByType('item_goddess_reinforce_' .. item.UseLv, step)
        result = result + row[column]
    end
    return result
end

function setting_lv_material_weapon(materials, level)
    if level ~= 540 and level ~= 560 then return end
    local multiplier = (level - 500) / 10
    for step = 6, 30 do
        materials[level]['weapon'][step]['harness_ore'] = step * multiplier
        materials[level]['weapon'][step]['harness_dust'] = step * 2
    end
end

function setting_lv_material_armor(materials, level)
    if level ~= 540 and level ~= 560 then return end
    for step = 6, 30 do
        materials[level]['armor'][step]['harness_ore'] = step * 3
        materials[level]['armor'][step]['harness_dust'] = step
    end
end

function setting_lv_material_acc(materials, level)
    if level ~= 550 then return end
    for step = 6, 30 do
        materials[level]['acc'][step]['harness_ore'] = step * 2
        materials[level]['acc'][step]['harness_dust'] = step + 1
    end
end
