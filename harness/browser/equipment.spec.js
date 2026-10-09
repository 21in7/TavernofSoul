'use strict';
const {test: base, expect} = require('@playwright/test');

// Exercise real HTML, static files and input events. Unexpected networking is a failure.
const test = base.extend({
    page: async ({page, baseURL}, use) => {
        const errors = [];
        page.on('pageerror', error => errors.push(`JavaScript: ${error.message}`));
        page.on('console', message => {
            if (message.type() === 'error') errors.push(`Console: ${message.text()}`);
        });
        page.on('response', response => {
            if (response.status() >= 400) errors.push(`HTTP ${response.status()}: ${response.url()}`);
        });
        page.on('requestfailed', request => {
            if (request.failure().errorText !== 'net::ERR_ABORTED') {
                errors.push(`Network: ${request.url()} (${request.failure().errorText})`);
            }
        });
        await page.route('**/*', route => {
            const url = new URL(route.request().url());
            if (url.origin === baseURL) return route.continue();
            errors.push(`Unexpected external request: ${url.href}`);
            return route.abort();
        });
        await use(page);
        expect(errors, 'Browser console, HTTP and network errors').toEqual([]);
    },
});

async function item(page, id, name) {
    const response = await page.goto(`/items/${id}`);
    expect(response.status()).toBe(200);
    await expect(page.locator('#title')).toHaveText(name);
}

async function stat(page, id, value) {
    await expect(page.locator(`#${id}`)).toHaveText(value);
}

async function evidence(page, info, name) {
    const screenshot = info.outputPath(`${name}.png`);
    await page.screenshot({path: screenshot, fullPage: true});
    await info.attach(name, {path: screenshot, contentType: 'image/png'});
}

test('search preserves filters and opens the detail page', async ({page}, info) => {
    await page.goto('/items/');
    if (info.project.name === 'mobile') {
        await page.locator('#sidebarCollapse').click();
        await expect(page.locator('#sidebar')).toHaveClass(/active/);
        await page.locator('#sidebarCollapse').click();
        await expect(page.locator('#sidebar')).not.toHaveClass(/active/);
    }
    await page.locator('[name=q]').fill('Fixture Dawn Sword');
    await page.locator('[name=grade]').selectOption('6');
    await page.getByRole('button', {name: 'Filter', exact: true}).click();
    await expect(page).toHaveURL(/q=Fixture\+Dawn\+Sword/);
    await expect(page.locator('[name=q]')).toHaveValue('Fixture Dawn Sword');
    await expect(page.locator('[name=grade]')).toHaveValue('6');
    await expect(page.locator('#content a[href="/items/110"]')).toHaveCount(1);
    await evidence(page, info, 'search-results');
    await page.locator('#content a[href="/items/110"]').click();
    await expect(page.locator('#title')).toHaveText('Fixture Dawn Sword');
    await stat(page, 'patk', '7,000');
    await expect(page.locator('#anvil')).toBeEditable();
});

test('search with no matches stays empty', async ({page}) => {
    await page.goto('/items/');
    await page.locator('[name=q]').fill('there-is-no-such-fixture');
    await page.getByRole('button', {name: 'Filter', exact: true}).click();
    await expect(page).toHaveURL(/q=there-is-no-such-fixture/);
    await expect(page.locator('#content a[href^="/items/"]')).toHaveCount(0);
});

test('560 sword steps reset and material links work', async ({page}, info) => {
    await item(page, '110', 'Fixture Dawn Sword');
    await page.locator('#anvil').fill('5');
    await stat(page, 'patk', '7,500');
    await stat(page, 'god_materials', '0');
    await stat(page, 'god_chance', '100%');
    await page.locator('#anvil').fill('6');
    await stat(page, 'patk', '7,600');
    await stat(page, 'patk_max', '7,700');
    await stat(page, 'god_chance', '98%');
    await expect(page.locator('#god_materials')).toContainText('Regional Ore × 36');
    await expect(page.locator('#god_materials')).toContainText('Fixture Dust × 12');
    await evidence(page, info, 'sword-plus-six');
    await page.locator('#anvil').fill('30');
    await stat(page, 'patk', '10,000');
    await stat(page, 'god_chance', '50%');
    await page.locator('#anvil').fill('0');
    await stat(page, 'patk', '7,000');
    await stat(page, 'god_chance', '—');
    await stat(page, 'god_materials', '—');
    await page.locator('#anvil').fill('6');
    await page.locator('#god_materials a[href="/items/100"]').click();
    await expect(page.locator('#title')).toHaveText('Regional Ore');
});

test('transcend input order and reset preserve base stats', async ({page}) => {
    await item(page, '110', 'Fixture Dawn Sword');
    await page.locator('#anvil').fill('6');
    await page.locator('#tc').fill('2');
    await stat(page, 'patk', '8,020');
    await stat(page, 'patk_max', '8,126');
    await stat(page, 'tc_bonus', '6%');
    await stat(page, 'tc_price', '6');
    await stat(page, 'tc_total', '9');
    await page.reload();
    await page.locator('#tc').fill('2');
    await page.locator('#anvil').fill('6');
    await stat(page, 'patk', '8,020');
    await stat(page, 'patk_max', '8,126');
    await page.locator('#anvil').fill('-1');
    await expect(page.locator('#anvil')).toHaveValue('0');
    await page.locator('#tc').fill('99');
    await expect(page.locator('#tc')).toHaveValue('10');
    await stat(page, 'patk', '9,100');
    await page.locator('#tc').fill('0');
    await stat(page, 'patk', '7,000');
    await stat(page, 'tc_bonus', '0%');
    await stat(page, 'tc_total', '0');
});

test('560 armor updates both defenses', async ({page}) => {
    await item(page, '112', 'Fixture Dawn Armor');
    await page.locator('#anvil').fill('6');
    await stat(page, 'pdef', '10,200');
    await stat(page, 'mdef', '5,700');
    await expect(page.locator('#god_materials')).toContainText('Regional Ore × 18');
    await expect(page.locator('#god_materials')).toContainText('Fixture Dust × 6');
    await page.locator('#anvil').fill('0');
    await stat(page, 'pdef', '9,000');
    await stat(page, 'mdef', '4,500');
});

test('550 accessory uses its own reinforcement table', async ({page}) => {
    await item(page, '113', 'Fixture Goddess Necklace');
    await page.locator('#anvil').fill('6');
    await stat(page, 'matk', '3,780');
    await stat(page, 'patk', '3,780');
    await expect(page.locator('#god_materials')).toContainText('Regional Ore × 12');
    await expect(page.locator('#god_materials')).toContainText('Fixture Dust × 7');
    await page.locator('#anvil').fill('0');
    await stat(page, 'matk', '3,300');
});

test('ordinary equipment keeps its existing calculator', async ({page}) => {
    await item(page, '111', 'Regional Staff');
    await stat(page, 'matk', '350');
    await page.locator('#anvil').fill('6');
    await stat(page, 'matk', '392');
    await stat(page, 'anvil_price', '600');
    await stat(page, 'anvil_total', '2,100');
    await page.locator('#tc').fill('2');
    await stat(page, 'matk', '462');
    await page.locator('#anvil').fill('0');
    await page.locator('#tc').fill('0');
    await stat(page, 'matk', '350');
});

test('gem levels include bonuses and penalties', async ({page}, info) => {
    await item(page, '230', 'Fixture Red Gem');
    const cells = await page.locator('#gem-socket-bonuses tbody tr').evaluateAll(rows =>
        rows.map(row => Array.from(row.cells, cell => cell.textContent.trim())));
    expect(cells).toHaveLength(16);
    expect(cells).toEqual(expect.arrayContaining([
        ...['Main weapon', 'Sub weapon'].flatMap(slot => [
            ['1', slot, 'ADD_ATK', '30'], ['1', slot, 'ADD_MATK', '-5'],
            ['2', slot, 'ADD_ATK', '60'], ['2', slot, 'ADD_MATK', '-10'],
        ]),
        ['1', 'Top / Bottom', 'ADD_DEF', '10'], ['1', 'Top / Bottom', 'ADD_HP', '-2'],
        ['2', 'Top / Bottom', 'ADD_DEF', '20'], ['2', 'Top / Bottom', 'ADD_HP', '-4'],
        ...['Gloves', 'Boots'].flatMap(slot => [
            ['1', slot, 'ADD_STR', '1'], ['2', slot, 'ADD_STR', '2'],
        ]),
    ]));
    await evidence(page, info, 'gem-levels');
});

test('skill gem opens the related skill', async ({page}) => {
    await item(page, '240', 'Fixture Fire Skill Gem');
    await expect(page.locator('#gem-socket-bonuses')).toContainText('Fixture Fire +1');
    await page.locator('#content a[href="/skills/400"]').click();
    await expect(page.locator('#title')).toHaveText('Regional Fire');
    await expect(page).toHaveURL(/\/skills\/400$/);
});
