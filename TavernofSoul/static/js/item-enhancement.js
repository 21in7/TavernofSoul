/* The parser supplies cumulative bonuses. Display never reimplements game Lua. */
(function (root) {
    'use strict';
    function clamp(value, maximum) {
        const number = Number(value);
        return Number.isFinite(number) ? Math.max(0, Math.min(maximum, Math.trunc(number))) : 0;
    }
    function calculate(data, enhancement, transcend) {
        const step = clamp(enhancement, data.maximum);
        const tc = clamp(transcend, Math.min(10, data.transcendPrices.length));
        const attack = step ? (data.attack[step - 1] || 0) : 0;
        const defense = step ? (data.defense[step - 1] || 0) : 0;
        const rate = tc * data.transcendRate;
        const stats = {};
        Object.keys(data.base).forEach(function (stat) {
            const base = data.base[stat];
            const bonus = stat === 'pdef' || stat === 'mdef' ? defense : attack;
            stats[stat] = base + bonus + Math.floor(base * rate);
        });
        const detail = data.goddess && step ? data.steps[step - 1] : null;
        return {step: step, transcend: tc, attack: attack, defense: defense, stats: stats,
            chance: detail ? detail.chance : null,
            materials: detail ? detail.materials : null,
            price: step ? (data.prices[step - 1] || 0) : 0,
            total: data.prices.slice(0, step).reduce((a, b) => a + b, 0),
            transcendPercent: Math.round(rate * 100),
            transcendPrice: tc ? data.transcendPrices[tc - 1] : 0,
            transcendTotal: data.transcendPrices.slice(0, tc).reduce((a, b) => a + b, 0)};
    }
    function mount(document, data) {
        const anvil = document.getElementById('anvil');
        const tc = document.getElementById('tc');
        if (!anvil || !tc) return;
        function text(id, value) {
            const element = document.getElementById(id);
            if (element) element.textContent = value;
        }
        function update() {
            const result = calculate(data, anvil.value, tc.value);
            anvil.value = result.step;
            tc.value = result.transcend;
            Object.keys(result.stats).forEach(stat => text(stat, result.stats[stat].toLocaleString('en')));
            text('anvil_bonus', [result.attack ? 'ATK +' + result.attack : '',
                result.defense ? 'DEF +' + result.defense : ''].filter(Boolean).join(' / ') || '0');
            text('god_chance', result.chance === null ? '—' : result.chance + '%');
            text('anvil_price', result.price.toLocaleString('en'));
            text('anvil_total', result.total.toLocaleString('en'));
            text('tc_bonus', result.transcendPercent + '%');
            text('tc_price', result.transcendPrice.toLocaleString('en'));
            text('tc_total', result.transcendTotal.toLocaleString('en'));
            const materials = document.getElementById('god_materials');
            if (materials) {
                materials.textContent = '';
                if (result.materials === null) materials.textContent = '—';
                else if (!result.materials.length) materials.textContent = '0';
                else result.materials.forEach(function (material) {
                    const line = document.createElement('div');
                    const name = document.createElement(material.url ? 'a' : 'span');
                    if (material.url) name.setAttribute('href', material.url);
                    name.textContent = material.name;
                    line.appendChild(name);
                    line.appendChild(document.createTextNode(' × ' + material.quantity.toLocaleString('en')));
                    materials.appendChild(line);
                });
            }
        }
        anvil.addEventListener('input', update);
        tc.addEventListener('input', update);
        update();
    }
    const api = {calculate: calculate, mount: mount};
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.ItemEnhancement = api;
}(typeof window !== 'undefined' ? window : globalThis));
