-- Human-written formulas for the real Lua runtime, not game balance data.
HARNESS_SKILL_STEP = 10
HARNESS_MON_HP_STEP = 50

function SCR_HARNESS_SKILL_FACTOR(skill)
    return skill.SklFactor + skill.Level * HARNESS_SKILL_STEP
end

function SCR_HARNESS_CAPTION_RATIO(skill)
    return 0.4
end

function SCR_HARNESS_CAPTION_TIME(skill)
    return skill.Level + 2
end

function SCR_HARNESS_SKILL_SR(skill)
    return skill.SklSR + skill.Level
end

function SCR_HARNESS_SPEND_ITEM(skill)
    return 2
end

function SCR_HARNESS_SPEND_POISON(skill)
    return skill.BasicPoison + skill.Level
end

function SCR_HARNESS_SPEND_SP(skill)
    return skill.BasicSP + skill.Level * skill.LvUpSpendSp
end

function SCR_HARNESS_COOLDOWN(skill)
    return skill.BasicCoolDown - skill.Level * 100
end

function SCR_HARNESS_MON_HP(mon)
    return mon.Lv * HARNESS_MON_HP_STEP
end

function SCR_HARNESS_MON_MINPATK(mon)
    return mon.Lv * 3
end

function SCR_HARNESS_MON_MAXPATK(mon)
    return mon.Lv * 3 + 5
end

function SCR_GET_MON_EXP(mon)
    return mon.Lv * 100
end

function SCR_GET_MON_JOBEXP(mon)
    return mon.Lv * 30
end

function SCR_Get_MON_HR(mon)
    return mon.Lv + 20
end

function SCR_Get_MON_DR(mon)
    return mon.Lv + 10
end

function SCR_Get_MON_CRTATK(mon)
    return 15
end

function SCR_Get_MON_CRTDR(mon)
    return 16
end

function SCR_Get_MON_CRTHR(mon)
    return 17
end

function SCR_Get_MON_BLK(mon)
    return 18
end

function SCR_Get_MON_BLK_BREAK(mon)
    return 19
end
