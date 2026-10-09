'use strict';
const {test: base, expect} = require('@playwright/test');
const names = {itos: 'Dawn Sword', ktos: '여명의 소드'};
const test = base.extend({
    page: async ({page, baseURL}, use, info) => {
        const errors = [], observations = [];
        page.on('pageerror', error => errors.push(`JavaScript: ${error.message}`));
        page.on('response', response => {
            if (response.status() >= 400) {
                const entry = `HTTP ${response.status()}: ${response.url()}`;
                (new URL(response.url()).origin === baseURL ? errors : observations).push(entry);
            }
        });
        page.on('requestfailed', request => {
            if (['GET', 'HEAD'].includes(request.method()) &&
                new URL(request.url()).origin === baseURL && request.failure().errorText !== 'net::ERR_ABORTED') {
                errors.push(`Network: ${request.url()} (${request.failure().errorText})`);
            }
        });
        await page.route('**/*', route => {
            const request = route.request();
            if (['GET', 'HEAD'].includes(request.method())) return route.continue();
            observations.push(`Blocked ${request.method()}: ${new URL(request.url()).origin}`);
            return route.abort();
        });
        try {
            await use(page);
        } finally {
            await info.attach('network-observations', {
                body: JSON.stringify({errors, observations}), contentType: 'application/json',
            });
        }
        expect(errors, 'First-party HTTP/network and JavaScript errors').toEqual([]);
    },
});

async function navigate(page, url) {
    const response = await page.goto(url, {waitUntil: 'domcontentloaded'});
    expect(response.status()).toBe(200);
    expect(new URL(page.url()).protocol).toBe('https:');
    expect(response.headers()['strict-transport-security']).toMatch(/max-age=\d+/);
    return response;
}

test('public HTTPS search detail and static assets work', async ({page}, info) => {
    const name = names[process.env.HARNESS_SITE_REGION];
    await navigate(page, `/items/?q=${encodeURIComponent(name)}&grade=6`);
    await expect(page.locator('[name=q]')).toHaveValue(name);
    const link = page.locator('#content a[href="/items/11107087"]');
    await expect(link).toHaveCount(1);
    await link.click();
    await expect(page.locator('#title')).toHaveText(name);
    await expect(page.locator('img[src*="icon_item_lighturiel_sword"]')).toBeVisible();
    expect(await page.locator('img[src*="icon_item_lighturiel_sword"]').evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true);
    expect(await page.evaluate(() => typeof window.jQuery)).toBe('function');
    await page.screenshot({path: info.outputPath('public-search-detail.png'), fullPage: true});
});

test('public 560 equipment has working reinforcement controls', async ({page}) => {
    await navigate(page, '/items/11107087');
    await expect(page.locator('#anvil')).toBeEditable();
    await expect(page.locator('#patk')).toHaveText('322,534');
    await page.locator('#anvil').fill('6');
    await expect(page.locator('#patk')).toHaveText('361,390');
    await page.locator('#anvil').fill('0');
    await expect(page.locator('#patk')).toHaveText('322,534');
});

test('public gems show socket bonuses', async ({page}) => {
    await navigate(page, '/items/643501');
    await expect(page.locator('#gem-socket-bonuses')).toBeVisible();
    await expect(page.locator('#gem-socket-bonuses')).toContainText('-21');
});

test('public skill gem opens the linked skill', async ({page}) => {
    await navigate(page, '/items/643580');
    const skill = page.locator('#content a[href^="/skills/"]');
    await expect(skill).toHaveCount(1);
    await skill.click();
    await expect(page.locator('#title')).not.toBeEmpty();
});
