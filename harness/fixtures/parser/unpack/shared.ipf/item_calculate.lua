-- Synthetic formulas: exercise real Lua loading and the Python item bridge.
function GET_COMMON_PROP_LIST()
    return {"STR"}
end

function SCR_HARNESS_REFRESH_WEAPON(item)
    item.MINATK = tonumber(item.UseLv) * HARNESS_ATK_STEP
    item.MAXATK = item.MINATK + HARNESS_ATK_STEP
    item.STR = 2
end

function GET_REINFORCE_ADD_VALUE_ATK(item, value, ratio, owner)
    return (tonumber(item.Reinforce_2) + 1) * HARNESS_ATK_STEP
end

function GET_REINFORCE_PRICE(item, owner, level)
    return (tonumber(item.Reinforce_2) + 1) * HARNESS_REINFORCE_PRICE
end

function GET_TRANSCEND_MATERIAL_COUNT(item, level)
    return (level + 1) * HARNESS_TRANSCEND_STEP
end
