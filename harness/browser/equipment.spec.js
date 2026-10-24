'use strict';
const {test: base, expect} = require('@playwright/test');

// Deliberate HTTP failures are exempted only by exact URL/status and only
// for a non-navigation fragment request. All other errors still fail the gate.
async function watchNetworking(page, baseURL, expectedHTTP = new Map()) {
    const errors = [];
    const isExpected = response => !response.request().isNavigationRequest() &&
        response.request().headers()['x-item-search'] === 'results-v1' &&
        new URL(response.url()).pathname === '/items/' &&
        expectedHTTP.get(response.url()) === response.status();
    page.on('pageerror', error => errors.push(`JavaScript: ${error.message}`));
    page.on('console', message => {
        const status = expectedHTTP.get(message.location().url);
        if (message.type() === 'error' && !(status === 503 &&
            /^Failed to load resource: the server responded with a status of 503\b/.test(message.text()))) {
            errors.push(`Console: ${message.text()}`);
        }
    });
    page.on('response', response => {
        if (response.status() >= 400 && !isExpected(response)) {
            errors.push(`HTTP ${response.status()}: ${response.url()}`);
        }
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
    return errors;
}

const test = base.extend({
    expectedHTTP: async ({}, use) => { await use(new Map()); },
    page: async ({page, baseURL, expectedHTTP}, use) => {
        const errors = await watchNetworking(page, baseURL, expectedHTTP);
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
    await expect(page.locator('#item-search-results a[href="/items/110"]')).toHaveCount(2);
    await evidence(page, info, 'search-results');
    await page.getByRole('link', {name: 'Fixture Dawn Sword', exact: true}).click();
    await expect(page.locator('#title')).toHaveText('Fixture Dawn Sword');
    await stat(page, 'patk', '7,000');
    await expect(page.locator('#anvil')).toBeEditable();
});

test('search with no matches stays empty', async ({page}) => {
    await page.goto('/items/');
    await expect(page.locator('#item-search-summary')).toHaveText('Search items');
    await expect(page.locator('.item-search-empty')).toHaveCount(0);
    await page.locator('[name=q]').fill('there-is-no-such-fixture');
    await page.locator('[name=grade]').selectOption('6');
    await page.getByRole('button', {name: 'Filter', exact: true}).click();
    await expect(page).toHaveURL(/q=there-is-no-such-fixture/);
    await expect(page.locator('#item-search-results tbody tr')).toHaveCount(0);
    await expect(page.locator('.item-search-empty')).toContainText('No items found');
    await expect(page.locator('.item-search-empty')).toContainText('change your filters');
    await expect(page.locator('#item-search-summary')).toContainText('0 Results');
    await expect(page.locator('[name=q]')).toHaveValue('there-is-no-such-fixture');
    await expect(page.locator('[name=grade]')).toHaveValue('6');
    const reset = page.locator('#item-search-results [data-search-reset]');
    await expect(reset).toHaveAttribute('href', '/items/');
    await reset.click();
    await expect(page).toHaveURL(/\/items\/$/);
    await expect(page.locator('[name=q]')).toHaveValue('');
    await expect(page.locator('[name=grade]')).toHaveValue('');
    await expect(page.locator('#item-search-summary')).toHaveText('Search items');
});

const searchKeyword = 'Search & + #? / "한글" <fixture>';
const searchRows = page => page.locator('#item-search-results tbody tr');
const searchSubmit = page => page.getByRole('button', {name: 'Filter', exact: true});
const searchSummary = page => page.locator('#item-search-summary');

async function rememberDocument(page) {
    await page.evaluate(() => {
        window.__searchDocument = document;
        window.__searchPersistentNodes = ['item-search-form', 'item-search-status',
            'item-search-error', 'sidebar'].map(id => document.getElementById(id));
    });
}

async function sameDocument(page) {
    expect(await page.evaluate(() => window.__searchDocument === document &&
        window.__searchPersistentNodes.every(node => node === document.getElementById(node.id)))).toBe(true);
}

async function search(page, keyword) {
    await page.locator('[name=q]').fill(keyword);
    await searchSubmit(page).click();
    await expect(page).toHaveURL(url => url.searchParams.get('q') === keyword);
    await expect(page.locator('#item-search-results')).toHaveAttribute('aria-busy', 'false');
}

async function searchPage(page, number, rows) {
    await expect(searchSummary(page)).toHaveText(`25 Results · Page ${number} / 3`);
    await expect(searchRows(page)).toHaveCount(rows);
    await expect(page.locator('[aria-current="page"]')).toHaveText(String(number));
}

async function rowNames(page) {
    return searchRows(page).locator('td:nth-child(3)').allTextContents();
}

test('search labels focus and table fit narrow viewports', async ({page}, info) => {
    await page.goto('/items/');
    await search(page, 'Fixture Dawn Sword');
    const labels = await page.locator('#item-search-form label').evaluateAll(nodes =>
        nodes.map(node => ({name: node.control && node.control.name, text: node.textContent.trim()})));
    expect(labels.map(label => label.name).sort()).toEqual(
        ['q', 'type', 'class', 'grade', 'lvmin', 'lvmax', 'order'].sort());
    expect(labels.every(label => label.text)).toBe(true);
    await expect(page.locator('#item-search-form fieldset legend')).not.toHaveText('');
    await expect(page.locator('#item-search-status')).toHaveAttribute('aria-live', 'polite');
    await expect(page.locator('#item-search-status')).toHaveAttribute('aria-atomic', 'true');
    const sizes = [page.viewportSize(), {width: 390, height: 844}, {width: 320, height: 740}];
    for (const size of sizes) {
        await page.setViewportSize(size);
        const layout = await page.evaluate(() => {
            const table = document.querySelector('.item-search-table');
            const form = document.querySelector('#item-search-form').getBoundingClientRect();
            return {width: innerWidth, document: document.documentElement.scrollWidth,
                body: document.body.scrollWidth, left: form.left, right: form.right,
                table: table.clientWidth, scroll: table.scrollWidth,
                overflow: getComputedStyle(table).overflowX};
        });
        expect(layout.document).toBeLessThanOrEqual(layout.width);
        expect(layout.body).toBeLessThanOrEqual(layout.width);
        expect(layout.left).toBeGreaterThanOrEqual(0);
        expect(layout.right).toBeLessThanOrEqual(layout.width);
        expect(layout.overflow).toMatch(/auto|scroll/);
        if (size.width <= 390) expect(layout.scroll).toBeGreaterThan(layout.table);
        const region = page.getByRole('region', {name: 'Item results', exact: true});
        await region.focus();
        await expect(region).toBeFocused();
        expect(await region.evaluate(node => getComputedStyle(node).outlineStyle)).not.toBe('none');
        await page.keyboard.press('Tab');
        await expect(page.getByRole('link', {name: '110', exact: true})).toBeFocused();
        await page.keyboard.press('Tab');
        const name = page.getByRole('link', {name: 'Fixture Dawn Sword', exact: true});
        await expect(name).toBeFocused();
        expect(await name.evaluate(node => parseFloat(getComputedStyle(node).outlineWidth))).toBeGreaterThan(0);
        await expect(name).toHaveAttribute('href', '/items/110');
        await expect(searchRows(page).locator('td:nth-child(5)')).toContainText('Goddess');
    }
    await evidence(page, info, 'search-320px-focus');
});

test('search partial pages preserve encoded conditions and history', async ({page, context, baseURL}) => {
    await page.goto('/items/');
    await rememberDocument(page);
    const type = await page.locator('[name=type] option').filter({hasText: /^sword$/i}).getAttribute('value');
    const values = {q: searchKeyword, grade: '6', class: '3', type,
        lvmin: '550', lvmax: '560', order: 'name-asc'};
    for (const [key, value] of Object.entries(values)) {
        const input = page.locator(`[name=${key}]`);
        if (['q', 'lvmin', 'lvmax'].includes(key)) await input.fill(value);
        else await input.selectOption(value);
    }
    await searchSubmit(page).click();
    await searchPage(page, 1, 10);
    await expect(searchSubmit(page)).toBeFocused();
    const first = await rowNames(page);
    const firstURL = page.url();
    const historySize = await page.evaluate(() => history.length);
    await page.getByRole('link', {name: 'Next', exact: true}).click();
    await searchPage(page, 2, 10);
    const second = await rowNames(page);
    expect(second.some(name => first.includes(name))).toBe(false);
    await expect(searchSummary(page)).toBeFocused();
    await expect(page.locator('#item-search-status')).toContainText('Page 2 / 3');
    const secondURL = page.url();
    for (const link of await page.locator('[data-search-pagination] a').evaluateAll(nodes => nodes.map(n => n.href))) {
        const url = new URL(link);
        expect(url.pathname).toBe('/items/');
        expect(url.hash).toBe('');
        expect([...url.searchParams.keys()].sort()).toEqual([...Object.keys(values), 'page'].sort());
        for (const [key, value] of Object.entries(values)) expect(url.searchParams.get(key)).toBe(value);
    }
    await page.goBack();
    await searchPage(page, 1, 10);
    await expect(page).toHaveURL(firstURL);
    expect(await rowNames(page)).toEqual(first);
    await page.goForward();
    await searchPage(page, 2, 10);
    await expect(page).toHaveURL(secondURL);
    expect(await rowNames(page)).toEqual(second);
    expect(await page.evaluate(() => history.length)).toBe(historySize + 1);
    for (const [key, value] of Object.entries(values)) await expect(page.locator(`[name=${key}]`)).toHaveValue(value);
    await sameDocument(page);
    await page.getByRole('link', {name: 'Last', exact: true}).click();
    await searchPage(page, 3, 5);
    const third = await rowNames(page);
    expect(new Set([...first, ...second, ...third]).size).toBe(25);
    await page.locator('[name=order]').selectOption('name-dsc');
    await searchSubmit(page).click();
    await searchPage(page, 1, 10);
    expect(new URL(page.url()).searchParams.get('page')).toBe('1');
    expect((await rowNames(page))[0].trim()).toBe(`${searchKeyword} 24`);
    const changedURL = page.url();
    await page.goBack();
    await searchPage(page, 3, 5);
    await expect(page.locator('[name=order]')).toHaveValue('name-asc');
    await page.goForward();
    await searchPage(page, 1, 10);
    await expect(page.locator('[name=order]')).toHaveValue('name-dsc');
    // Restore an actually different keyword as well as pagination and sort.
    await search(page, `${searchKeyword} 24`);
    await expect(searchSummary(page)).toHaveText('1 Results · Page 1 / 1');
    await page.goBack();
    await searchPage(page, 1, 10);
    await expect(page.locator('[name=q]')).toHaveValue(searchKeyword);
    await page.goForward();
    await expect(searchSummary(page)).toHaveText('1 Results · Page 1 / 1');
    await expect(page.locator('[name=q]')).toHaveValue(`${searchKeyword} 24`);
    await page.goBack();
    await searchPage(page, 1, 10);
    await expect(page).toHaveURL(changedURL);
    await sameDocument(page);
    const shared = await context.newPage();
    const sharedErrors = await watchNetworking(shared, baseURL);
    try {
        const response = await shared.goto(changedURL);
        expect(response.headers()['x-item-search']).toBe('document');
        await searchPage(shared, 1, 10);
        await expect(shared.locator('[name=q]')).toHaveValue(searchKeyword);
    } finally {
        await shared.close();
        expect(sharedErrors, 'Shared search browser errors').toEqual([]);
    }
    await page.reload();
    await searchPage(page, 1, 10);
    for (const [key, value] of Object.entries({...values, order: 'name-dsc'})) {
        await expect(page.locator(`[name=${key}]`)).toHaveValue(value);
    }
});

test('search navigation preserves native link and modifier behavior', async ({page, context, baseURL}) => {
    await page.goto('/items/');
    await search(page, searchKeyword);
    await rememberDocument(page);
    const originalURL = page.url();
    const next = page.getByRole('link', {name: 'Next', exact: true});
    const targetURL = await next.getAttribute('href');
    for (const mode of ['control', 'target']) {
        if (mode === 'target') await next.evaluate(link => { link.target = '_blank'; });
        const opened = context.waitForEvent('page').then(async tab => ({
            tab, errors: await watchNetworking(tab, baseURL),
        }));
        await next.click(mode === 'control' ? {modifiers: ['Control']} : {});
        const {tab, errors} = await opened;
        try {
            await tab.waitForLoadState('domcontentloaded');
            await searchPage(tab, 2, 10);
            expect(new URL(tab.url()).pathname + new URL(tab.url()).search).toBe(targetURL);
        } finally {
            await tab.close();
            expect(errors, 'Native link browser errors').toEqual([]);
        }
        await expect(page).toHaveURL(originalURL);
    }
    // Cancel only at document bubbling, after the search handler has had a chance
    // to intercept: assert it leaves these unsupported navigations untouched.
    const intercepted = await page.evaluate(() => {
        const nav = document.querySelector('[data-search-pagination]');
        const results = [];
        const cases = [
            ['/items/?q=x', {metaKey: true}], ['/items/?q=x', {shiftKey: true}],
            ['/items/?q=x', {altKey: true}], ['/items/110', {}],
            ['/skills/400', {}], ['https://example.invalid/items/?q=x', {}],
            ['/items/?q=x#unexpected', {}],
        ];
        for (const [href, modifiers] of cases) {
            const link = document.createElement('a');
            link.href = href;
            nav.append(link);
            document.addEventListener('click', event => {
                results.push(event.defaultPrevented);
                event.preventDefault();
            }, {once: true});
            link.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, ...modifiers}));
            link.remove();
        }
        return results;
    });
    expect(intercepted).toEqual([false, false, false, false, false, false, false]);
    await sameDocument(page);
    await search(page, 'Fixture Dawn Sword');
    await page.getByRole('link', {name: 'Fixture Dawn Sword', exact: true}).click();
    await expect(page.locator('#title')).toHaveText('Fixture Dawn Sword');
    await expect(page).toHaveURL(/\/items\/110$/);
});

test('search cancels superseded requests and ignores reversed responses', async ({page}) => {
    await page.goto('/items/');
    await rememberDocument(page);
    // Delay delivery of an already-read real response body. Its signal can be
    // aborted but this body still resolves, exercising the sequence guard too.
    await page.evaluate(() => {
        const realFetch = window.fetch.bind(window);
        window.__searchAborted = false;
        window.fetch = async (url, options) => {
            if (new URL(url).searchParams.get('q') !== 'Fixture Dawn Sword') return realFetch(url, options);
            options.signal.addEventListener('abort', () => { window.__searchAborted = true; });
            const response = await realFetch(url, options);
            const markup = await response.text();
            response.text = () => new Promise(resolve => {
                window.__releaseSearch = () => resolve(markup);
            });
            return response;
        };
    });
    await page.locator('[name=q]').fill('Fixture Dawn Sword');
    await searchSubmit(page).click();
    await page.waitForFunction(() => typeof window.__releaseSearch === 'function');
    await expect(page.locator('#item-search-results')).toHaveAttribute('aria-busy', 'true');
    await expect(page.locator('#item-search-status')).toContainText('Loading');
    await search(page, 'Fixture Dawn Armor');
    await expect(searchRows(page).locator('td:nth-child(3)')).toHaveText('Fixture Dawn Armor');
    expect(await page.evaluate(() => window.__searchAborted)).toBe(true);
    const committed = page.url();
    await page.evaluate(async () => {
        window.__releaseSearch();
        await new Promise(resolve => setTimeout(resolve, 0));
    });
    await expect(searchRows(page).locator('td:nth-child(3)')).toHaveText('Fixture Dawn Armor');
    await expect(page).toHaveURL(committed);
    await expect(page.locator('[name=q]')).toHaveValue('Fixture Dawn Armor');
    await expect(page.locator('#item-search-error')).toBeHidden();
    await sameDocument(page);
});

test('search failures preserve results and allow retry', async ({page, expectedHTTP}) => {
    test.setTimeout(60000); // Includes the application's real 12-second timeout.
    await page.goto('/items/');
    await search(page, 'Fixture Dawn Sword');
    await rememberDocument(page);
    let broken = null;
    let releaseTimeout;
    let releaseRetry;
    let attempted = 0;
    await page.route('**/items/?*', async route => {
        if (route.request().headers()['x-item-search'] !== 'results-v1' || !broken) return route.continue();
        attempted++;
        if (broken === 'timeout') {
            await new Promise(resolve => { releaseTimeout = resolve; });
            // The browser has already aborted this request; do not send a late
            // response or let it leak into the retry.
            return route.abort('aborted');
        }
        if (broken === 'http') {
            expectedHTTP.set(route.request().url(), 503);
            return route.fulfill({status: 503, contentType: 'text/html', body: 'Unavailable'});
        }
        const response = await route.fetch();
        let body = await response.text();
        const headers = {...response.headers()};
        delete headers['content-length'];
        delete headers['content-encoding'];
        if (broken === 'header') delete headers['x-item-search'];
        if (broken === 'content-type') headers['content-type'] = 'application/json';
        if (broken === 'document') body = `<!doctype html><html><body>${body}</body></html>`;
        if (broken === 'script') body = body.replace('</section>', '<script>window.__injected = true</script></section>');
        if (broken === 'marker') body = body.replace('results-v1', 'unrecognized');
        if (broken === 'event') body = body.replace('<h2 ', '<h2 onclick="window.__injected=true" ');
        if (broken === 'unsafe-url') body = body.replace('href="/items/112"', 'href="javascript:window.__injected=true"');
        if (broken === 'canonical') body = body.replace(/data-search-url="[^"]*"/, 'data-search-url="https://example.invalid/items/"');
        if (broken === 'retry-delay') await new Promise(resolve => { releaseRetry = resolve; });
        return route.fulfill({response, headers, body});
    });
    for (const fault of ['http', 'header', 'content-type', 'document', 'script', 'marker',
        'event', 'unsafe-url', 'canonical', 'timeout']) {
        const beforeURL = page.url();
        const beforeRows = await rowNames(page);
        broken = fault;
        const beforeAttempts = attempted;
        await page.locator('[name=q]').fill('Fixture Dawn Armor');
        await searchSubmit(page).click();
        await expect.poll(() => attempted).toBe(beforeAttempts + 1);
        await expect(page.locator('#item-search-error')).toBeVisible({timeout: 16000});
        if (releaseTimeout) { releaseTimeout(); releaseTimeout = null; }
        await expect(page.locator('#item-search-results')).toHaveAttribute('aria-busy', 'false');
        expect(await rowNames(page), fault).toEqual(beforeRows);
        await expect(page).toHaveURL(beforeURL);
        await expect(page.locator('#item-search-status')).toContainText('Previous results are still shown');
        const fallback = new URL(await page.locator('#item-search-fallback').getAttribute('href'), page.url());
        expect(fallback.pathname).toBe('/items/');
        expect(fallback.searchParams.get('q')).toBe('Fixture Dawn Armor');
        expect(await page.evaluate(() => window.__injected)).toBeUndefined();
        await sameDocument(page);
        broken = null;
        await page.getByRole('button', {name: 'Retry', exact: true}).click();
        await expect(searchRows(page).locator('td:nth-child(3)')).toHaveText('Fixture Dawn Armor');
        await expect(page.locator('#item-search-error')).toBeHidden();
        await expect(searchSummary(page)).toBeFocused();
        await sameDocument(page);
        await search(page, 'Fixture Dawn Sword');
    }
    // A successful retry must respect focus moved by the user while waiting.
    broken = 'http';
    await page.locator('[name=q]').fill('Fixture Dawn Armor');
    await searchSubmit(page).click();
    await expect(page.locator('#item-search-error')).toBeVisible();
    broken = 'retry-delay';
    try {
        await page.getByRole('button', {name: 'Retry', exact: true}).click();
        await expect.poll(() => typeof releaseRetry).toBe('function');
        await expect(page.locator('#item-search-results')).toHaveAttribute('aria-busy', 'true');
        await page.locator('[name=q]').focus();
    } finally {
        if (releaseRetry) releaseRetry();
    }
    await expect(searchRows(page).locator('td:nth-child(3)')).toHaveText('Fixture Dawn Armor');
    await expect(page.locator('#item-search-error')).toBeHidden();
    await expect(page.locator('#item-search-results')).toHaveAttribute('aria-busy', 'false');
    await expect(page.locator('[name=q]')).toBeFocused();
    await sameDocument(page);
});

test('search failed popstate restores URL form and retry target', async ({page, expectedHTTP}) => {
    await page.goto('/items/');
    await search(page, 'Fixture Dawn Sword');
    const swordURL = page.url();
    await page.locator('[name=grade]').selectOption('6');
    await search(page, 'Fixture Dawn Armor');
    const armorURL = page.url();
    await rememberDocument(page);
    let fail = true;
    await page.route('**/items/?*', route => {
        if (!fail || route.request().headers()['x-item-search'] !== 'results-v1') return route.continue();
        expectedHTTP.set(route.request().url(), 503);
        return route.fulfill({status: 503, contentType: 'text/html', body: 'Unavailable'});
    });
    await page.goBack();
    await expect(page.locator('#item-search-error')).toBeVisible();
    await expect(page).toHaveURL(armorURL);
    await expect(page.locator('[name=q]')).toHaveValue('Fixture Dawn Armor');
    await expect(page.locator('[name=grade]')).toHaveValue('6');
    await expect(searchRows(page).locator('td:nth-child(3)')).toHaveText('Fixture Dawn Armor');
    await expect(page.getByRole('button', {name: 'Retry', exact: true})).toBeFocused();
    expect(await page.locator('#item-search-fallback').getAttribute('href')).toBe(swordURL);
    await sameDocument(page);
    fail = false;
    await page.getByRole('button', {name: 'Retry', exact: true}).click();
    await expect(page).toHaveURL(swordURL);
    await expect(page.locator('[name=q]')).toHaveValue('Fixture Dawn Sword');
    await expect(page.locator('[name=grade]')).toHaveValue('');
    await expect(searchRows(page).locator('td:nth-child(3)')).toHaveText('Fixture Dawn Sword');
    await expect(page.locator('#item-search-error')).toBeHidden();
    await expect(searchSummary(page)).toBeFocused();
    await sameDocument(page);
});

test('search without JavaScript keeps GET pages and reset usable', async ({browser, page, baseURL}) => {
    const context = await browser.newContext({baseURL, javaScriptEnabled: false, viewport: page.viewportSize()});
    const native = await context.newPage();
    const errors = await watchNetworking(native, baseURL);
    const navigationHeaders = [];
    native.on('request', request => {
        if (request.isNavigationRequest()) navigationHeaders.push(request.headers()['x-item-search']);
    });
    try {
        await native.goto('/items/');
        await native.locator('[name=q]').fill(searchKeyword);
        await Promise.all([native.waitForNavigation(), searchSubmit(native).click()]);
        await searchPage(native, 1, 10);
        await Promise.all([native.waitForNavigation(), native.getByRole('link', {name: 'Next', exact: true}).click()]);
        await searchPage(native, 2, 10);
        expect(new URL(native.url()).searchParams.get('q')).toBe(searchKeyword);
        await native.locator('[name=q]').fill('missing & + #? "한글"');
        await native.locator('[name=grade]').selectOption('6');
        await Promise.all([native.waitForNavigation(), searchSubmit(native).click()]);
        expect(new URL(native.url()).searchParams.has('page')).toBe(false);
        await expect(native.locator('.item-search-empty')).toContainText('No items found');
        await expect(native.locator('[name=q]')).toHaveValue('missing & + #? "한글"');
        await expect(native.locator('[name=grade]')).toHaveValue('6');
        await Promise.all([native.waitForNavigation(), native.locator('#item-search-results [data-search-reset]').click()]);
        await expect(native).toHaveURL(/\/items\/$/);
        await expect(searchSummary(native)).toHaveText('Search items');
        await expect(native.locator('[name=q]')).toHaveValue('');
        await native.locator('[name=q]').fill('Fixture Dawn Sword');
        await Promise.all([native.waitForNavigation(), searchSubmit(native).click()]);
        await Promise.all([native.waitForNavigation(),
            native.getByRole('link', {name: 'Fixture Dawn Sword', exact: true}).click()]);
        await expect(native.locator('#title')).toHaveText('Fixture Dawn Sword');
        expect(navigationHeaders.length).toBe(7);
        expect(navigationHeaders.every(header => header === undefined)).toBe(true);
    } finally {
        await context.close();
        expect(errors, 'Native GET browser errors').toEqual([]);
    }
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

async function pvpResults(page, expected) {
    for (const [key, value] of Object.entries(expected)) {
        await expect(page.locator(`[data-pvp-result="${key}"]`)).toHaveText(value);
    }
}

async function pvpFitsViewport(page, info) {
    if (info.project.name === 'mobile') expect(page.viewportSize().width).toBe(390);
    const layout = await page.evaluate(() => {
        const calculator = document.querySelector('#pvp-calculator').getBoundingClientRect();
        return {
            width: window.innerWidth, document: document.documentElement.scrollWidth,
            body: document.body.scrollWidth, left: calculator.left, right: calculator.right,
        };
    });
    expect(layout.document).toBeLessThanOrEqual(layout.width);
    expect(layout.body).toBeLessThanOrEqual(layout.width);
    expect(layout.left).toBeGreaterThanOrEqual(0);
    expect(layout.right).toBeLessThanOrEqual(layout.width);
}

test('pvp calculator updates probabilities and level boundaries', async ({page}, info) => {
    if (info.project.name === 'mobile') await page.setViewportSize({width: 390, height: 844});
    await page.goto('/items/');
    const menu = await page.locator('#sidebar a').evaluateAll(links =>
        links.map(link => ({href: link.getAttribute('href'), text: link.textContent.trim()})));
    const planner = menu.findIndex(link => link.href === '/planner/');
    expect(planner).toBeGreaterThanOrEqual(0);
    expect(menu.slice(planner, planner + 3).map(link => link.href)).toEqual([
        '/planner/', '/planner/pvp/', 'https://www.buymeacoffee.com/gihyeonofsoul',
    ]);
    expect(menu[planner + 1].text).toBe('PvP Calculator');
    if (info.project.name === 'mobile') {
        await page.locator('#sidebarCollapse').click();
        await expect(page.locator('#sidebar')).toHaveClass(/active/);
    }
    await page.locator('#sidebar a[href="/planner/pvp/"]').click();
    await expect(page).toHaveURL(/\/planner\/pvp\/$/);
    await expect(page.locator('#pvp-calculator')).toBeVisible();
    await pvpResults(page, {hit: '90.00%', evasion: '10.00%', critical: '10.00%',
                            block: '30.00%', levelFactor: '1.00 ×'});
    await pvpFitsViewport(page, info);
    for (const key of ['accuracy', 'critical', 'block']) {
        await page.locator(`[name="${key}"]`).fill('10');
    }
    for (const key of ['evasion', 'criticalResistance', 'blockPenetration']) {
        await page.locator(`[name="${key}"]`).fill('0');
    }
    await pvpResults(page, {hit: '97.30%', evasion: '2.70%', critical: '30.77%', block: '63.16%'});
    await page.locator('[name="opponentLevel"]').fill('525');
    await pvpResults(page, {hit: '48.65%', evasion: '51.35%', levelFactor: '0.50 ×'});
    await page.locator('[name="opponentLevel"]').fill('549');
    await pvpResults(page, {hit: '1.95%', evasion: '98.05%', levelFactor: '0.02 ×'});
    for (const level of ['550', '551']) {
        await page.locator('[name="opponentLevel"]').fill(level);
        await pvpResults(page, {hit: '0.00%', evasion: '100.00%', levelFactor: '0.00 ×',
                                critical: '30.77%', block: '63.16%'});
    }
    await page.locator('[name="myLevel"]').fill('600');
    await pvpResults(page, {hit: '97.30%', evasion: '2.70%', levelFactor: '1.00 ×',
                            critical: '30.77%', block: '63.16%'});
    await pvpFitsViewport(page, info);
    await evidence(page, info, 'pvp-probabilities');
});

test('pvp calculator rejects invalid inputs and resets accessibly', async ({page}, info) => {
    if (info.project.name === 'mobile') await page.setViewportSize({width: 390, height: 844});
    const response = await page.goto('/planner/pvp/');
    expect(response.status()).toBe(200);
    const calculator = page.locator('#pvp-calculator');
    const labels = await calculator.locator('label').evaluateAll(nodes => nodes.map(label => ({
        text: label.textContent.trim(), input: label.control && label.control.name,
    })));
    expect(labels.map(label => label.input)).toEqual([
        'myLevel', 'opponentLevel', 'accuracy', 'evasion', 'critical',
        'criticalResistance', 'block', 'blockPenetration',
    ]);
    expect(labels.every(label => label.text.length > 0)).toBe(true);
    await expect(calculator.locator('.pvp-results')).toHaveAttribute('aria-live', 'polite');
    await expect(calculator.locator('.pvp-results')).toHaveAttribute('aria-atomic', 'true');
    await page.locator('[name="critical"]').fill('25000');
    await pvpResults(page, {critical: '14.79%'});
    for (const [key, value] of [
        ['accuracy', ''], ['accuracy', '-1'], ['accuracy', '-1e-400'],
        ['accuracy', 'abc'], ['accuracy', 'Infinity'], ['accuracy', '1e309'],
        ['accuracy', '1000000000001'], ['myLevel', '500.5'], ['opponentLevel', '10001'],
    ]) {
        const input = page.locator(`[name="${key}"]`);
        await input.fill(value);
        await expect(input).toHaveValue(value);
        await expect(input).toHaveAttribute('aria-invalid', 'true');
        await expect(page.locator(`#pvp-${key}-error`)).toBeVisible();
        await expect(calculator.locator('[data-pvp-error]')).toBeVisible();
        await expect(calculator.locator('[data-pvp-result]')).toHaveText(['—', '—', '—', '—', '—']);
        if (value === '-1e-400') {
            await pvpFitsViewport(page, info);
            await evidence(page, info, 'pvp-input-error');
        }
        await input.fill(key.endsWith('Level') ? '500' : '20000');
        await expect(input).toHaveAttribute('aria-invalid', 'false');
        await expect(calculator.locator('[data-pvp-error]')).toBeHidden();
        await pvpResults(page, {hit: '90.00%', critical: '14.79%'});
    }
    // Change every default and leave an error active so reset must restore both
    // the complete form and the cleared results, using the real keyboard path.
    for (const {input: key} of labels) {
        await page.locator(`[name="${key}"]`).fill(key.endsWith('Level') ? '600' : '0');
    }
    await page.locator('[name="opponentLevel"]').fill('650');
    await page.locator('[name="blockPenetration"]').fill('-1e-400');
    await expect(calculator.locator('[data-pvp-error]')).toBeVisible();
    await expect(calculator.locator('[data-pvp-result]')).toHaveText(['—', '—', '—', '—', '—']);
    // Native keyboard traversal follows the eight labelled fields, then reset.
    await page.locator('[name="myLevel"]').focus();
    await expect(page.locator('[name="myLevel"]')).toBeFocused();
    for (const key of labels.slice(1).map(label => label.input)) {
        await page.keyboard.press('Tab');
        await expect(page.locator(`[name="${key}"]`)).toBeFocused();
    }
    await page.keyboard.press('Tab');
    const reset = calculator.locator('button[type="reset"]');
    await expect(reset).toBeFocused();
    await page.keyboard.press('Enter');
    for (const {input: key} of labels) {
        await expect(page.locator(`[name="${key}"]`)).toHaveValue(key.endsWith('Level') ? '500' : '20000');
    }
    await pvpResults(page, {hit: '90.00%', evasion: '10.00%', critical: '10.00%',
                            block: '30.00%', levelFactor: '1.00 ×'});
    await expect(calculator.locator('[aria-invalid="true"]')).toHaveCount(0);
    await expect(calculator.locator('[data-pvp-error]')).toBeHidden();
    await pvpFitsViewport(page, info);
    await evidence(page, info, 'pvp-reset');
});
