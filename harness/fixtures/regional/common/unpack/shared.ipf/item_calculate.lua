-- Independent synthetic formulas for physical, magical and defensive equipment.
function GET_COMMON_PROP_LIST()
    return {"STR", "INT"}
end

function SCR_HARNESS_REFRESH_WEAPON(item)
    item.MINATK = tonumber(item.UseLv) * HARNESS_ATK_STEP
    item.MAXATK = item.MINATK + HARNESS_ATK_STEP
    item.STR = 2
end

function SCR_HARNESS_REFRESH_STAFF(item)
    item.MATK = tonumber(item.UseLv) * HARNESS_ATK_STEP * 2
    item.INT = 4.9
end

function SCR_HARNESS_REFRESH_ARMOR(item)
    item.DEF = tonumber(item.UseLv) * HARNESS_DEF_STEP
    item.MDEF = item.DEF / 2
    item.STR = -3
end

function GET_REINFORCE_ADD_VALUE_ATK(item, value, ratio, owner)
    return (tonumber(item.Reinforce_2) + 1) * HARNESS_ATK_STEP
end

function GET_REINFORCE_ADD_VALUE(owner, item, value, ratio)
    return (tonumber(item.Reinforce_2) + 1) * HARNESS_DEF_STEP * 2
end

function GET_REINFORCE_PRICE(item, owner, level)
    return (tonumber(item.Reinforce_2) + 1) * HARNESS_REINFORCE_PRICE
end

function GET_TRANSCEND_MATERIAL_COUNT(item, level)
    return (level + 1) * HARNESS_TRANSCEND_STEP
end
