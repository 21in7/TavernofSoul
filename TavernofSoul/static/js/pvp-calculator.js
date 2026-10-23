/* Pure public API is shared by the delivered page and Node tests. No dependencies. */
(function (root, factory) {
    'use strict';
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.PvPCalculator = api;
    if (typeof document !== 'undefined') {
        const start = function () {
            const element = document.getElementById('pvp-calculator');
            if (element) api.mount(element);
        };
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
        else start();
    }
}(typeof window !== 'undefined' ? window : null, function () {
    'use strict';
    const DEFAULTS = Object.freeze({
        myLevel: 500, opponentLevel: 500, accuracy: 20000, evasion: 20000,
        critical: 20000, criticalResistance: 20000, block: 20000, blockPenetration: 20000
    });
    const LIMITS = Object.freeze({level: 10000, stat: 1000000000000, characters: 64});
    const keys = Object.keys(DEFAULTS);

    function validateInputs(raw) {
        const values = {};
        const errors = {};
        keys.forEach(function (key) {
            const input = raw && raw[key];
            const text = typeof input === 'string' ? input.trim() :
                (typeof input === 'number' ? String(input) : '');
            const level = key === 'myLevel' || key === 'opponentLevel';
            // Reject a leading minus BEFORE Number(): -1e-400 would otherwise become -0.
            // Decimal grammar deliberately excludes hex, Infinity and locale separators.
            const syntax = /^\+?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;
            const value = Number(text);
            const mantissa = text.split(/e/i)[0];
            const underflow = value === 0 && /[1-9]/.test(mantissa);
            if (!text || text.length > LIMITS.characters || !syntax.test(text) ||
                Object.is(input, -0) || !Number.isFinite(value) || value < 0 || underflow ||
                value > (level ? LIMITS.level : LIMITS.stat) ||
                (level && !Number.isInteger(value))) {
                errors[key] = 'invalid';
            } else {
                values[key] = value;
            }
        });
        return {valid: Object.keys(errors).length === 0, values: values, errors: errors};
    }

    function calculate(raw) {
        const validation = validateInputs(raw);
        if (!validation.valid) return {valid: false, errors: validation.errors, results: null};
        const v = validation.values;
        // +10 and bounded inputs keep ratios and their squares finite, including zero stats.
        function probability(own, opponent, weight) {
            const ratio = (opponent + 10) / (own + 10);
            return 100 / (1 + weight * ratio * ratio);
        }
        const levelFactor = Math.max(0, 1 - Math.max(0, v.opponentLevel - v.myLevel) / 50);
        const hit = probability(v.accuracy, v.evasion, 1 / 9) * levelFactor;
        return {valid: true, errors: {}, results: {
            hit: hit, evasion: 100 - hit,
            critical: probability(v.critical, v.criticalResistance, 9),
            block: probability(v.block, v.blockPenetration, 7 / 3),
            levelFactor: levelFactor
        }};
    }

    function mount(element) {
        const form = element.querySelector('form');
        const summary = element.querySelector('[data-pvp-error]');
        const fields = {};
        keys.forEach(function (key) {
            fields[key] = form.querySelector('[name="' + key + '"]');
        });
        function update() {
            const raw = {};
            keys.forEach(function (key) { raw[key] = fields[key].value; });
            const calculation = calculate(raw);
            keys.forEach(function (key) {
                const invalid = Boolean(calculation.errors[key]);
                fields[key].setAttribute('aria-invalid', String(invalid));
                element.querySelector('#pvp-' + key + '-error').hidden = !invalid;
            });
            summary.hidden = calculation.valid;
            element.querySelectorAll('[data-pvp-result]').forEach(function (output) {
                const key = output.getAttribute('data-pvp-result');
                output.textContent = calculation.valid ?
                    calculation.results[key].toFixed(2) + (key === 'levelFactor' ? ' ×' : '%') : '—';
            });
        }
        form.addEventListener('input', update);
        form.addEventListener('change', update);
        form.addEventListener('submit', function (event) { event.preventDefault(); update(); });
        form.addEventListener('reset', function (event) {
            event.preventDefault();
            keys.forEach(function (key) { fields[key].value = String(DEFAULTS[key]); });
            update();
        });
        update();
        return {update: update};
    }
    return Object.freeze({DEFAULTS: DEFAULTS, LIMITS: LIMITS,
        validateInputs: validateInputs, calculate: calculate, mount: mount});
}));
