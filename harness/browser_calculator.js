/* A minimal DOM adapter, not a browser engine or layout test. */
'use strict';
const fs = require('fs');
const api = require(process.argv[2]);
const request = JSON.parse(fs.readFileSync(0, 'utf8'));
class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.attributes = {}; this.events = {}; this.value = ''; }
    set value(value) { this.inputValue = String(value); }
    get value() { return this.inputValue; }
    set textContent(value) { this.content = String(value); this.children = []; }
    get textContent() { return (this.content || '') + this.children.map(node => node.textContent).join(''); }
    set innerHTML(value) { throw new Error('Calculator must render source strings as text'); }
    appendChild(child) { this.children.push(child); }
    setAttribute(key, value) { this.attributes[key] = value; }
    addEventListener(event, handler) { this.events[event] = handler; }
}
const ids = request.ids || ['anvil', 'tc', 'patk', 'patk_max', 'matk', 'pdef', 'mdef',
    'anvil_bonus', 'god_chance', 'god_materials', 'anvil_price', 'anvil_total', 'tc_bonus', 'tc_price', 'tc_total'];
const elements = Object.fromEntries(ids.map(id => [id, new Element('div')]));
const document = {
    getElementById: id => elements[id] || null,
    createElement: tag => new Element(tag),
    createTextNode: text => ({textContent: text})
};
api.mount(document, request.data);
function snapshot() {
    return Object.fromEntries(Object.entries(elements).map(([id, element]) => [id, {
        text: element.textContent, value: element.value,
        links: element.children.flatMap(line => (line.children || []).filter(node => node.tag === 'a')
            .map(node => ({text: node.textContent, href: node.attributes.href})))
    }]));
}
const initial = snapshot();
const results = request.inputs.map(input => {
    if (input.anvil !== undefined && elements.anvil) elements.anvil.value = input.anvil;
    if (input.tc !== undefined && elements.tc) elements.tc.value = input.tc;
    const target = elements[input.event || 'anvil'];
    if (target && target.events.input) target.events.input();
    return {display: snapshot(), calculation: api.calculate(request.data,
        elements.anvil ? elements.anvil.value : 0, elements.tc ? elements.tc.value : 0)};
});
process.stdout.write(JSON.stringify({initial: initial, results: results}));
