'use strict';
const {test: base, expect} = require('@playwright/test');

// Deliberate HTTP failures are exempted only by exact URL/status and only
// for a non-navigation fragment request. All other errors still fail the gate.
async function watchNetworking(context, baseURL, expectedHTTP = new Map()) {
    const errors = [];
    const isExpected = response => !response.request().isNavigationRequest() &&
        response.request().headers()['x-item-search'] === 'results-v1' &&
        new URL(response.url()).pathname === '/items/' &&
        expectedHTTP.get(response.url()) === response.status();
    // Install before creating pages/clicking links. A popup's first request and
    // script errors can precede its page event; never enable page routing there.
    context.on('weberror', error => errors.push(`JavaScript: ${error.error().message}`));
    context.on('console', message => {
        const status = expectedHTTP.get(message.location().url);
        if (message.type() === 'error' && !(status === 503 &&
            /^Failed to load resource: the server responded with a status of 503\b/.test(message.text()))) {
            errors.push(`Console: ${message.text()}`);
        }
    });
    context.on('response', response => {
        if (response.status() >= 400 && !isExpected(response)) {
            errors.push(`HTTP ${response.status()}: ${response.url()}`);
        }
    });
    context.on('requestfailed', request => {
        if (request.failure().errorText !== 'net::ERR_ABORTED') {
            errors.push(`Network: ${request.url()} (${request.failure().errorText})`);
        }
    });
    context.on('request', request => {
        if (new URL(request.url()).origin !== baseURL) {
            errors.push(`Unexpected external request: ${request.url()}`);
        }
    });
    await context.route('**/*', route => {
        const url = new URL(route.request().url());
        if (url.origin === baseURL) return route.continue();
        return route.abort();
    });
    return errors;
}

const test = base.extend({
    expectedHTTP: async ({}, use) => { await use(new Map()); },
    context: async ({context, baseURL, expectedHTTP}, use) => {
        const errors = await watchNetworking(context, baseURL, expectedHTTP);
        try {
            await use(context);
        } finally {
            expect(errors, 'Browser console, HTTP and network errors in every tab').toEqual([]);
        }
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

// The unfiltered keyword is a substring: it also matches the newer recipe.
const swordNames = ['Recipe - Fixture Dawn Sword', 'Fixture Dawn Sword'];

async function singlePageResults(page, names) {
    await expect(searchRows(page)).toHaveCount(names.length);
    await expect(searchRows(page).locator('td:nth-child(3)')).toHaveText(names);
    await expect(searchSummary(page)).toHaveText(`${names.length} Results · Page 1 / 1`);
    await expect(page.locator('[aria-current="page"]')).toHaveText('1');
}

test('search labels focus and table fit narrow viewports', async ({page}, info) => {
    await page.goto('/items/');
    await search(page, 'Fixture Dawn Sword');
    await singlePageResults(page, swordNames);
    await expect(page.locator('[name=order]')).toHaveValue('updated-dsc');
    const recipeName = page.getByRole('link', {name: swordNames[0], exact: true});
    const recipeID = searchRows(page).filter({has: recipeName}).locator('td:nth-child(2) a');
    const recipeHref = await recipeName.getAttribute('href');
    await expect(recipeID).toHaveAttribute('href', recipeHref);
    await expect(recipeID).toHaveText(recipeHref.slice('/items/'.length));
    const swordID = page.getByRole('link', {name: '110', exact: true});
    const name = page.getByRole('link', {name: 'Fixture Dawn Sword', exact: true});
    await expect(swordID).toHaveAttribute('href', '/items/110');
    await expect(name).toHaveAttribute('href', '/items/110');
    const labels = await page.locator('#item-search-form label').evaluateAll(nodes =>
        nodes.map(node => ({name: node.control && node.control.name, text: node.textContent.trim()})));
    expect(labels.map(label => label.name).sort()).toEqual(
        ['q', 'type', 'class', 'grade', 'lvmin', 'lvmax', 'order'].sort());
    expect(labels.every(label => label.text)).toBe(true);
    await expect(page.locator('#item-search-form fieldset legend')).not.toHaveText('');
    await expect(page.locator('#item-search-status')).toHaveAttribute('aria-live', 'polite');
    await expect(page.locator('#item-search-status')).toHaveAttribute('aria-atomic', 'true');
    const region = page.getByRole('region', {name: 'Item results', exact: true});
    await expect(searchSubmit(page)).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(page.locator('#item-search-form [data-search-reset]')).toBeFocused();
    await page.keyboard.press('Tab');
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
        await expect(region).toBeFocused();
        expect(await region.evaluate(node => getComputedStyle(node).outlineStyle)).not.toBe('none');
        expect(await region.evaluate(node => parseFloat(getComputedStyle(node).outlineWidth))).toBeGreaterThan(0);
        // Default updated order places Recipe before Sword; visit both links in
        // both rows, rather than focusing the desired item programmatically.
        for (const link of [recipeID, recipeName, swordID, name]) {
            await page.keyboard.press('Tab');
            await expect(link).toBeFocused();
            await expect(link).toBeInViewport();
            expect(await link.evaluate(node => getComputedStyle(node).outlineStyle)).not.toBe('none');
            expect(await link.evaluate(node => parseFloat(getComputedStyle(node).outlineWidth))).toBeGreaterThan(0);
        }
        await expect(searchRows(page).filter({has: name}).locator('td:nth-child(5)')).toContainText('Goddess');
        for (const target of [swordID, recipeName, recipeID, region]) {
            await page.keyboard.press('Shift+Tab');
            await expect(target).toBeFocused();
        }
    }
    await evidence(page, info, 'search-320px-focus');
});

test('search partial pages preserve encoded conditions and history', async ({page, context}) => {
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
    try {
        const response = await shared.goto(changedURL);
        expect(response.headers()['x-item-search']).toBe('document');
        await searchPage(shared, 1, 10);
        await expect(shared.locator('[name=q]')).toHaveValue(searchKeyword);
    } finally {
        await shared.close();
    }
    await page.reload();
    await searchPage(page, 1, 10);
    for (const [key, value] of Object.entries({...values, order: 'name-dsc'})) {
        await expect(page.locator(`[name=${key}]`)).toHaveValue(value);
    }
});

function settledValues(observations, message) {
    const failures = observations.filter(result => result.status === 'rejected').map(result => result.reason);
    if (failures.length === 1) throw failures[0];
    if (failures.length > 1) throw new AggregateError(failures, message);
    return observations.map(result => result.value);
}

async function nativeSearchDocument(tab, targetURL) {
    // Read current state: a popup can already have loaded before Playwright
    // observes its lifecycle events. An about:blank document must never pass.
    await expect.poll(() => tab.url(), {message: 'Native tab has the exact target URL'}).toBe(targetURL);
    await expect.poll(() => tab.evaluate(() => ({
        url: document.URL,
        readyState: document.readyState,
        doctype: document.doctype && document.doctype.name,
    })), {message: 'Native target document is complete HTML'}).toEqual({
        url: targetURL, readyState: 'complete', doctype: 'html',
    });
    await expect(tab.locator('#item-search-form')).toHaveCount(1);
    await expect(tab.locator('#item-search-form')).toBeVisible();
    await expect(tab.locator('#item-search-form')).toHaveAttribute('action', '/items/');
    await expect(tab.locator('#item-search-form')).toHaveAttribute('method', 'get');
    const stylesheet = tab.locator('head link[rel="stylesheet"][href="/static/css/item-search.css"]');
    await expect(stylesheet).toHaveCount(1);
    await expect.poll(() => stylesheet.evaluate(link => Boolean(link.sheet &&
        !link.sheet.disabled && link.sheet.cssRules.length))).toBe(true);
    await expect(tab.locator('.item-search-fields')).toHaveCSS('display', 'grid');
    await expect(tab.locator('head script[src="/static/js/item-search.js"]')).toHaveAttribute('defer', '');
    // Complete documents have finished deferred scripts. Require the script's
    // completed resource too; the context monitor propagates script/HTTP errors.
    await expect.poll(() => tab.evaluate(() => performance.getEntriesByName(
        new URL('/static/js/item-search.js', document.URL).href).some(entry =>
        entry.initiatorType === 'script' && entry.responseEnd > 0))).toBe(true);
    await expect(tab.locator('[name=q]')).toHaveValue(searchKeyword);
    await expect(tab.locator('#item-search-results')).toHaveCount(1);
    await expect(tab.locator('#item-search-results')).toBeVisible();
    await expect(tab.locator('#item-search-results')).toHaveAttribute('aria-busy', 'false');
    await searchPage(tab, 2, 10);
}

async function nativeSearchNavigation(browser, options, mode) {
    // Each path gets its own first navigation and context. A partially observed
    // background tab from Control-click cannot affect the _blank document check.
    const context = await browser.newContext(options);
    const failures = [];
    let errors = [];
    try {
        errors = await watchNetworking(context, options.baseURL);
        const page = await context.newPage();
        await page.goto('/items/');
        await search(page, searchKeyword);
        await searchPage(page, 1, 10);
        await rememberDocument(page);
        const originalURL = page.url();
        const originalRows = await rowNames(page);
        const next = page.getByRole('link', {name: 'Next', exact: true});
        const targetURL = new URL(await next.getAttribute('href'), options.baseURL).href;
        await page.bringToFront();
        if (mode === 'target') await next.evaluate(link => { link.target = '_blank'; });
        await next.evaluate(link => {
            window.__nativeSearchClicks = [];
            window.__nativeSearchResults = document.getElementById('item-search-results');
            // The app listens on .item-search during bubbling. Document bubbling
            // runs afterwards; this passive observer never cancels the default.
            document.addEventListener('click', event => {
                const clicked = event.target.closest('a');
                window.__nativeSearchClicks.push({
                    isTrusted: event.isTrusted, ctrlKey: event.ctrlKey,
                    button: event.button, correctLink: clicked === link,
                    href: clicked && clicked.href, defaultPrevented: event.defaultPrevented,
                });
            }, {once: true, passive: true});
        });
        const existingPages = context.pages();
        const documents = [];
        const documentResponses = [];
        const fragments = [];
        const openedPages = [];
        const recordDocument = request => {
            if (request.isNavigationRequest() && request.resourceType() === 'document') documents.push(request);
            if (request.headers()['x-item-search'] === 'results-v1') fragments.push(request);
        };
        const recordResponse = response => {
            if (documents.includes(response.request())) documentResponses.push(response);
        };
        const recordPage = tab => openedPages.push(tab);
        context.on('request', recordDocument);
        context.on('response', recordResponse);
        context.on('page', recordPage);
        // Observe the initial request/response before clicking, without consulting
        // frame/opener or retrieving the navigation response body.
        const observations = [context.waitForEvent('response', response => response.url() === targetURL &&
                response.request().url() === targetURL && response.request().method() === 'GET' &&
                response.request().isNavigationRequest() && response.request().resourceType() === 'document' &&
                documents.includes(response.request()))];
        // Control-click only collects page events; their delivery is not an app
        // contract. Only the separate _blank path requires a new Page and its DOM.
        if (mode === 'target') observations.push(context.waitForEvent('page'));
        observations.push(next.click({noWaitAfter: true,
            ...(mode === 'control' ? {modifiers: ['Control']} : {})}));
        const [response, tab] = settledValues(await Promise.allSettled(observations),
            'Native search navigation failed');
        expect(await page.evaluate(() => window.__nativeSearchClicks)).toEqual([{
            isTrusted: true, ctrlKey: mode === 'control', button: 0,
            correctLink: true, href: targetURL, defaultPrevented: false,
        }]);
        expect(documents).toHaveLength(1);
        expect(documentResponses).toEqual([response]);
        expect(documents[0]).toBe(response.request());
        expect(documents[0].url()).toBe(targetURL);
        expect(documents[0].method()).toBe('GET');
        expect(documents[0].isNavigationRequest()).toBe(true);
        expect(documents[0].resourceType()).toBe('document');
        expect(documents[0].headers()['x-item-search']).toBeUndefined();
        expect(documents[0].redirectedFrom()).toBeNull();
        expect(response.url()).toBe(targetURL);
        expect(response.status()).toBe(200);
        expect(response.headers()['x-item-search']).toBe('document');
        expect(response.headers()['content-type']).toMatch(/^text\/html(?:\s*;|$)/i);
        expect(response.headers()['vary'].split(',').map(token => token.trim().toLowerCase()))
            .toContain('x-item-search');
        if (mode === 'target') {
            expect(existingPages).not.toContain(tab);
            expect(openedPages).toEqual([tab]);
            expect(context.pages().filter(candidate => !existingPages.includes(candidate))).toEqual([tab]);
            await nativeSearchDocument(tab, targetURL);
        }
        await expect(page).toHaveURL(originalURL);
        await searchPage(page, 1, 10);
        expect(await rowNames(page)).toEqual(originalRows);
        await sameDocument(page);
        expect(await page.evaluate(() => window.__nativeSearchResults ===
            document.getElementById('item-search-results'))).toBe(true);
        expect(fragments).toEqual([]);
        expect(documents).toHaveLength(1);
        expect(documentResponses).toEqual([response]);
        if (mode === 'target') {
            expect(openedPages).toEqual([tab]);
            expect(context.pages().filter(candidate => !existingPages.includes(candidate))).toEqual([tab]);
        }
    } catch (error) {
        failures.push(error);
    } finally {
        // Closing the entire context also handles partially initialized tabs
        // without requiring a Page event or masking the primary failure.
        const cleanup = await Promise.allSettled([context.close()]);
        failures.push(...cleanup.filter(result => result.status === 'rejected').map(result => result.reason));
        try {
            expect(errors, 'Native path console, HTTP and network errors from the first request').toEqual([]);
        } catch (error) {
            failures.push(error);
        }
    }
    if (failures.length === 1) throw failures[0];
    if (failures.length > 1) throw new AggregateError(failures, 'Native navigation/cleanup failed');
}

test('search navigation preserves native link and modifier behavior', async ({
    page, browser, baseURL, contextOptions, isMobile, hasTouch, deviceScaleFactor, userAgent,
}) => {
    const options = {...contextOptions, baseURL, viewport: page.viewportSize(),
        isMobile, hasTouch, deviceScaleFactor, userAgent};
    await nativeSearchNavigation(browser, options, 'control');
    await nativeSearchNavigation(browser, options, 'target');
    await page.goto('/items/');
    await search(page, searchKeyword);
    await rememberDocument(page);
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
    await singlePageResults(page, swordNames);
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
    async function retryArmor(moveFocus = false) {
        const beforeURL = page.url();
        const target = await page.locator('#item-search-fallback').getAttribute('href');
        const canonical = new URL(target);
        expect(canonical.origin).toBe(new URL(beforeURL).origin);
        expect(canonical.pathname).toBe('/items/');
        expect(canonical.searchParams.get('q')).toBe('Fixture Dawn Armor');
        expect(canonical.searchParams.get('grade')).toBe('');
        canonical.searchParams.set('page', '1');
        let responseReceived;
        releaseRetry = null;
        broken = 'retry-delay';
        try {
            await page.getByRole('button', {name: 'Retry', exact: true}).click();
            await expect.poll(() => typeof releaseRetry).toBe('function');
            await expect(page.locator('#item-search-results')).toHaveAttribute('aria-busy', 'true');
            await expect(page.locator('#item-search-status')).toHaveText('Loading search results…');
            await expect(page.locator('#item-search-error')).toBeHidden();
            await singlePageResults(page, swordNames);
            await expect(page).toHaveURL(beforeURL);
            if (moveFocus) {
                await page.locator('[name=q]').click();
                await expect(page.locator('[name=q]')).toBeFocused();
            }
            // The route is still held, so install the listener immediately
            // before release without leaving a pending waiter if an assertion fails.
            responseReceived = page.waitForResponse(response => response.url() === target &&
                response.request().headers()['x-item-search'] === 'results-v1');
        } finally {
            if (releaseRetry) releaseRetry();
        }
        const response = await responseReceived;
        expect(response.status()).toBe(200);
        expect(response.headers()['x-item-search']).toBe('results-v1');
        // Receiving headers alone does not mean the client has replaced the DOM.
        await expect(page).toHaveURL(canonical.href);
        await expect(page.locator('#item-search-results')).toHaveAttribute('aria-busy', 'false');
        await expect(page.locator('#item-search-results')).toHaveAttribute('data-search-url',
            canonical.pathname + canonical.search);
        await singlePageResults(page, ['Fixture Dawn Armor']);
        await expect(searchRows(page).locator('td:nth-child(2)')).toHaveText(['112']);
        await expect(page.locator('[name=q]')).toHaveValue('Fixture Dawn Armor');
        await expect(page.locator('[name=grade]')).toHaveValue('');
        await expect(page.locator('#item-search-status')).toHaveText('1 Results · Page 1 / 1');
        await expect(page.locator('#item-search-error')).toBeHidden();
        await expect(moveFocus ? page.locator('[name=q]') : searchSummary(page)).toBeFocused();
        await sameDocument(page);
        broken = null;
    }
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
        await singlePageResults(page, swordNames);
        await expect(page).toHaveURL(beforeURL);
        await expect(page.locator('[name=q]')).toHaveValue('Fixture Dawn Armor');
        await expect(searchSubmit(page)).toBeFocused();
        await expect(page.locator('#item-search-status')).toContainText('Previous results are still shown');
        const fallback = new URL(await page.locator('#item-search-fallback').getAttribute('href'), page.url());
        expect(fallback.pathname).toBe('/items/');
        expect(fallback.searchParams.get('q')).toBe('Fixture Dawn Armor');
        expect(await page.evaluate(() => window.__injected)).toBeUndefined();
        await sameDocument(page);
        await page.keyboard.press('Tab');
        await expect(page.locator('#item-search-form [data-search-reset]')).toBeFocused();
        await page.keyboard.press('Tab');
        await expect(page.getByRole('button', {name: 'Retry', exact: true})).toBeFocused();
        await retryArmor();
        await search(page, 'Fixture Dawn Sword');
        await singlePageResults(page, swordNames);
    }
    // A successful retry must respect focus moved by the user while waiting.
    broken = 'http';
    await page.locator('[name=q]').fill('Fixture Dawn Armor');
    await searchSubmit(page).click();
    await expect(page.locator('#item-search-error')).toBeVisible();
    await expect(page.locator('#item-search-results')).toHaveAttribute('aria-busy', 'false');
    await singlePageResults(page, swordNames);
    await retryArmor(true);
});

test('search failed popstate restores URL form and retry target', async ({page, expectedHTTP}) => {
    await page.goto('/items/');
    await search(page, 'Fixture Dawn Sword');
    await singlePageResults(page, swordNames);
    const swordURL = page.url();
    await page.locator('[name=grade]').selectOption('6');
    await search(page, 'Fixture Dawn Armor');
    await singlePageResults(page, ['Fixture Dawn Armor']);
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
    await singlePageResults(page, ['Fixture Dawn Armor']);
    await expect(searchRows(page).locator('td:nth-child(2)')).toHaveText(['112']);
    await expect(page.locator('#item-search-results')).toHaveAttribute('aria-busy', 'false');
    await expect(page.locator('#item-search-status')).toContainText('Previous results are still shown');
    await expect(page.getByRole('button', {name: 'Retry', exact: true})).toBeFocused();
    expect(await page.locator('#item-search-fallback').getAttribute('href')).toBe(swordURL);
    await sameDocument(page);
    fail = false;
    const [response] = await Promise.all([
        page.waitForResponse(response => response.url() === swordURL &&
            response.request().headers()['x-item-search'] === 'results-v1'),
        page.getByRole('button', {name: 'Retry', exact: true}).click(),
    ]);
    expect(response.status()).toBe(200);
    expect(response.headers()['x-item-search']).toBe('results-v1');
    await expect(page).toHaveURL(swordURL);
    await expect(page.locator('#item-search-results')).toHaveAttribute('aria-busy', 'false');
    await expect(page.locator('[name=q]')).toHaveValue('Fixture Dawn Sword');
    await expect(page.locator('[name=grade]')).toHaveValue('');
    await singlePageResults(page, swordNames);
    const canonical = new URL(swordURL);
    await expect(page.locator('#item-search-results')).toHaveAttribute('data-search-url',
        canonical.pathname + canonical.search);
    await expect(page.locator('#item-search-status')).toHaveText('2 Results · Page 1 / 1');
    await expect(page.locator('#item-search-error')).toBeHidden();
    await expect(searchSummary(page)).toBeFocused();
    await sameDocument(page);
});

test('search without JavaScript keeps GET pages and reset usable', async ({browser, page, baseURL}) => {
    const context = await browser.newContext({baseURL, javaScriptEnabled: false, viewport: page.viewportSize()});
    let errors = [];
    try {
        errors = await watchNetworking(context, baseURL);
        const navigationHeaders = [];
        context.on('request', request => {
            if (request.isNavigationRequest()) navigationHeaders.push(request.headers()['x-item-search']);
        });
        const native = await context.newPage();
        await native.goto('/items/');
        await native.locator('[name=q]').fill(searchKeyword);
        await Promise.all([native.waitForNavigation(), searchSubmit(native).click()]);
        await searchPage(native, 1, 10);
        await Promise.all([native.waitForNavigation(), native.getByRole('link', {name: 'Next', exact: true}).click()]);
        await searchPage(native, 2, 10);
        expect(new URL(native.url()).searchParams.get('q')).toBe(searchKeyword);
        const sharedURL = native.url();
        const shared = await context.newPage();
        try {
            const response = await shared.goto(sharedURL);
            expect(response.status()).toBe(200);
            expect(response.headers()['x-item-search']).toBe('document');
            await expect(shared).toHaveURL(sharedURL);
            await expect(shared.locator('[name=q]')).toHaveValue(searchKeyword);
            await searchPage(shared, 2, 10);
            await shared.reload();
            await expect(shared).toHaveURL(sharedURL);
            await expect(shared.locator('[name=q]')).toHaveValue(searchKeyword);
            await searchPage(shared, 2, 10);
        } finally {
            await shared.close();
        }
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
        expect(navigationHeaders.length).toBe(9);
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

// These are server-rendered ORM fixtures, not replacement HTML or injected CSS.
const detailTail = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'.repeat(3);
const detailName = '모바일 장비 日本語 Equipment ' + detailTail;
const materialName = '긴 재료 日本語 Material ' + detailTail;
const recipeName = '긴 제작법 日本語 Recipe ' + detailTail;
const collectionName = '긴 수집품 日本語 Collection ' + detailTail;
const detailSizes = info => info.project.name === 'mobile' ?
    [{width: 390, height: 844}, {width: 320, height: 740}] : [{width: 1440, height: 900}];

async function detailFits(page) {
    // Navigation/text readiness does not establish settled geometry. Re-read
    // every bound together on each observation, using the default expect timeout.
    await expect.poll(() => page.evaluate(() => {
        const article = document.querySelector('.item-detail').getBoundingClientRect();
        const layout = {width: innerWidth, body: document.body.scrollWidth,
            document: document.documentElement.scrollWidth, x: scrollX,
            left: article.left, right: article.right};
        return [
            {bound: 'body', fits: layout.body <= layout.width},
            {bound: 'document', fits: layout.document <= layout.width},
            {bound: 'scrollX', fits: layout.x === 0},
            {bound: 'article left', fits: layout.left >= 0},
            {bound: 'article right', fits: layout.right <= layout.width + 1},
        ].filter(check => !check.fits).map(check => ({...check, ...layout,
            // Diagnostic observations only: sheet attachment is not an assertion
            // that every stylesheet has been applied or layout has settled.
            readyState: document.readyState,
            bodyMargin: getComputedStyle(document.body).margin,
            stylesheets: Array.from(document.querySelectorAll('link[rel="stylesheet"]'), link => ({
                href: link.href, attached: link.sheet !== null, disabled: link.disabled,
            })),
        }));
    }), {message: 'Body, document and detail bounds fit the viewport together'}).toEqual([]);
}

async function orderedDetailNavigation(page, baseURL, order, navigate) {
    // Hold the later real stylesheet response until the browser has finished
    // receiving the first. Neither HTTP 200 nor completion proves CSS application;
    // the caller still observes actual geometry and rendered content afterwards.
    const matches = url => url.origin === new URL(baseURL).origin &&
        /\/(?:style|item-detail)\.css$/.test(url.pathname);
    const name = url => new URL(url).pathname.split('/').pop();
    const requested = [];
    const completed = [];
    let release;
    const barrier = new Promise(resolve => { release = resolve; });
    const handler = async route => {
        const stylesheet = name(route.request().url());
        requested.push(stylesheet);
        const response = await route.fetch();
        expect(response.status(), stylesheet).toBe(200);
        if (stylesheet === order[1]) await barrier;
        await route.fulfill({response});
    };
    const finished = request => {
        if (matches(new URL(request.url()))) completed.push(name(request.url()));
    };
    page.on('requestfinished', finished);
    await page.route(matches, handler);
    try {
        // goto must stop at commit; link clicks must use noWaitAfter. Waiting
        // for load here would wait for the stylesheet held by this same barrier.
        await navigate();
        await expect.poll(() => [...requested].sort(),
            {message: 'Both real detail stylesheets are requested exactly once'}).toEqual([...order].sort());
        await expect.poll(() => [...completed],
            {message: 'The first stylesheet finishes while the second is held'}).toEqual([order[0]]);
        release();
        await expect.poll(() => [...completed],
            {message: 'Both stylesheet responses finish in the controlled order'}).toEqual(order);
    } finally {
        release();
        await page.unrouteAll({behavior: 'wait'});
        page.off('requestfinished', finished);
    }
}

async function readableText(locator) {
    await expect(locator).toBeVisible();
    // Inspect rendered text rectangles, so ellipsis, fixed-height clipping and
    // hidden ancestors cannot pass just because textContent remains in the DOM.
    expect(await locator.evaluate(node => {
        const range = document.createRange();
        range.selectNodeContents(node);
        const box = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        const lines = Array.from(range.getClientRects()).filter(rect => rect.width && rect.height);
        let unclipped = true;
        for (let parent = node.parentElement; parent; parent = parent.parentElement) {
            const bounds = parent.getBoundingClientRect();
            const css = getComputedStyle(parent);
            if (Number(css.opacity) === 0 || css.visibility !== 'visible') unclipped = false;
            // Named scrollports may expose offscreen columns by scrolling;
            // hidden/clip ancestors provide no such reading path.
            if (/hidden|clip/.test(css.overflowX) && lines.some(rect =>
                rect.left < bounds.left - 1 || rect.right > bounds.right + 1)) unclipped = false;
            if (/hidden|clip/.test(css.overflowY) && lines.some(rect =>
                rect.top < bounds.top - 1 || rect.bottom > bounds.bottom + 1)) unclipped = false;
        }
        if (!node.closest('table') && lines.some(rect => rect.left < 0 || rect.right > innerWidth + 1)) {
            unclipped = false;
        }
        return unclipped && lines.length > 0 && style.textOverflow !== 'ellipsis' &&
            lines.every(rect => rect.left >= box.left - 1 && rect.right <= box.right + 1 &&
                rect.top >= box.top - 1 && rect.bottom <= box.bottom + 1) &&
            node.scrollWidth <= node.clientWidth + 1 && node.scrollHeight <= node.clientHeight + 1;
    }), 'All rendered text fits its own box without clipping').toBe(true);
}

async function visibleDetailFocus(locator, expectedURL = locator.page().url()) {
    await expect(locator).toBeFocused();
    await expect(locator).toBeInViewport();
    // Require full visibility within the existing assertion timeout.
    // Re-read one real DOM snapshot per attempt; never move focus or scroll here.
    await expect.poll(() => locator.evaluate(node => {
        const style = getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        const width = parseFloat(style.outlineWidth);
        const offset = parseFloat(style.outlineOffset);
        const outset = Math.max(0, width + offset);
        const box = {left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom};
        const outline = {left: rect.left - outset, right: rect.right + outset,
            top: rect.top - outset, bottom: rect.bottom + outset};
        const viewport = {left: 0, right: innerWidth, top: 0, bottom: innerHeight};
        const input = node.matches('input');
        // A tall table region can be only partly visible vertically. Its input
        // must fit in full, including the outline, on both axes.
        const contains = (outer, inner, vertical = true) =>
            inner.left >= outer.left && inner.right <= outer.right &&
            (!vertical || inner.top >= outer.top && inner.bottom <= outer.bottom);
        const region = node.parentElement.closest('.item-detail-table[role="region"]');
        let scrollport = null;
        if (region) {
            const bounds = region.getBoundingClientRect();
            scrollport = {left: bounds.left + region.clientLeft, top: bounds.top + region.clientTop};
            scrollport.right = scrollport.left + region.clientWidth;
            scrollport.bottom = scrollport.top + region.clientHeight;
        }
        // Include failed bounds in the poll diff, so a persistent failure can
        // be attributed without inferring its cause from this shared helper's line.
        const clipping = [
            {target: 'input', area: 'viewport', rect: box, bounds: viewport, vertical: input},
            {target: 'outline', area: 'viewport', rect: outline, bounds: viewport, vertical: input},
            ...(scrollport ? [
                {target: 'input', area: 'table scrollport', rect: box, bounds: scrollport, vertical: true},
                {target: 'outline', area: 'table scrollport', rect: outline, bounds: scrollport, vertical: true},
            ] : []),
        ].filter(({rect, bounds, vertical}) => !contains(bounds, rect, vertical));
        return {focused: document.activeElement === node, url: location.href,
            clipping: clipping.map(bounds => ({element: node.id || node.tagName, ...bounds})),
            style: style.outlineStyle, width, color: style.outlineColor, offset,
            box, outline, viewport, scrollport,
            scroll: region && {scrollLeft: region.scrollLeft, scrollWidth: region.scrollWidth,
                clientWidth: region.clientWidth, maxScroll: region.scrollWidth - region.clientWidth},
            outlineVisible: !/none|hidden/.test(style.outlineStyle) && width > 0 &&
                !['transparent', 'rgba(0, 0, 0, 0)'].includes(style.outlineColor),
            inputInViewport: contains(viewport, box, input),
            outlineInViewport: contains(viewport, outline, input),
            scrollportPresent: !input || scrollport !== null,
            inputInRegion: !scrollport || contains(scrollport, box),
            outlineInRegion: !scrollport || contains(scrollport, outline)};
    }), {message: 'Actual focus, input and outline fit the viewport and table scrollport'}).toMatchObject({
        focused: true, url: expectedURL, outlineVisible: true,
        inputInViewport: true, outlineInViewport: true, scrollportPresent: true,
        inputInRegion: true, outlineInRegion: true,
        clipping: [],
    });
}

async function detailTableAccess(page, region, pinned = false) {
    const geometry = await region.evaluate(node => ({width: node.clientWidth, scroll: node.scrollWidth,
        left: node.scrollLeft}));
    if (geometry.scroll > geometry.width) {
        const exposure = () => region.evaluate(node => {
            const left = node.getBoundingClientRect().left + node.clientLeft;
            const right = left + node.clientWidth;
            const position = {scrollport: {left, right}, scrollLeft: node.scrollLeft,
                scrollWidth: node.scrollWidth, clientWidth: node.clientWidth,
                maxScroll: node.scrollWidth - node.clientWidth,
                focused: document.activeElement && {tag: document.activeElement.tagName,
                    id: document.activeElement.id, region: document.activeElement === node},
                viewport: {width: innerWidth, height: innerHeight}};
            const cells = ['thead', 'tbody'].flatMap(section => ['first', 'last'].map(edge => {
                const cell = node.querySelector(`${section} tr > :${edge}-child`);
                const r = cell.getBoundingClientRect();
                const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                return {
                    section, edge, cell: {tag: cell.tagName, id: cell.id,
                        left: r.left, right: r.right, top: r.top, bottom: r.bottom},
                    inRegion: r.left >= left && r.right <= right, accessible: cell.contains(hit),
                    hit: hit && {tag: hit.tagName, id: hit.id},
                };
            }));
            return {...position, cells,
                lastColumnReached: cells.filter(cell => cell.edge === 'last').every(cell => cell.inRegion),
                failures: cells.filter(cell => !cell.inRegion || !cell.accessible)
                    .map(cell => ({...cell, ...position}))};
        });
        await page.keyboard.press('ArrowRight');
        if (pinned) {
            await expect.poll(async () => {
                const state = await exposure();
                return state.scrollLeft > geometry.left ? [] : [{...state, previousLeft: geometry.left}];
            }, {message: 'The first real ArrowRight advances the table'}).toEqual([]);
            await region.hover();
            // Wheel delivery is asynchronous. Keep observing real wheel movement
            // instead of switching to a key before that movement has arrived.
            // A progress sample is only an intermediate position, so continue
            // until the final column fits or the real scroll limit is reached.
            let state = await exposure();
            let attempts = 0;
            while (attempts < 64 && (attempts === 0 || !state.lastColumnReached) &&
                state.scrollLeft < state.maxScroll) {
                const previousLeft = state.scrollLeft;
                attempts++;
                await page.mouse.wheel(state.maxScroll - state.scrollLeft, 0);
                await expect.poll(async () => {
                    state = await exposure();
                    return state.scrollLeft > previousLeft || state.lastColumnReached ? [] :
                        [{...state, previousLeft, attempts, guard: 64}];
                }, {message: 'Real wheel scrolling advances or exposes the final column'}).toEqual([]);
            }
            expect(state.lastColumnReached ? [] : [{...state, attempts, guard: 64,
                atScrollLimit: state.scrollLeft >= state.maxScroll}],
                'The final column is reached before the scroll limit or 64-wheel guard').toEqual([]);
            await expect.poll(async () => (await exposure()).failures,
                {message: 'Input/header and final column remain exposed after horizontal scrolling'}).toEqual([]);
        } else {
            await expect.poll(() => region.evaluate(node => node.scrollLeft)).toBeGreaterThan(geometry.left);
        }
        return true;
    }
    // A narrow table may already fit at 390px. Require every cell to be
    // displayed inside the scrollport rather than requiring artificial overflow.
    const cells = await region.evaluate(node => {
        const bounds = node.getBoundingClientRect();
        const left = bounds.left + node.clientLeft;
        const right = left + node.clientWidth;
        return Array.from(node.querySelectorAll('table th, table td'), cell => {
            const rect = cell.getBoundingClientRect();
            const style = getComputedStyle(cell);
            return rect.width > 0 && rect.height > 0 && style.display !== 'none' &&
                style.visibility === 'visible' && rect.left >= left - 1 && rect.right <= right + 1;
        });
    });
    expect(cells.length, 'The fitting table retains its cells').toBeGreaterThan(0);
    expect(cells.every(Boolean), 'Every column is visible inside the fitting table region').toBe(true);
    return false;
}

async function detailTableSemantics(page) {
    const tables = await page.locator('.item-detail table').evaluateAll(nodes => nodes
        .filter(table => table.querySelector('tbody td, tbody th')).map(table => {
            const region = table.closest('[role="region"]');
            const headers = Array.from(table.querySelectorAll('th'));
            const cells = Array.from(table.querySelectorAll('td, th'));
            const columnCount = Array.from(table.querySelectorAll('thead tr:first-child th'))
                .reduce((sum, cell) => sum + cell.colSpan, 0);
            return {
                caption: table.caption && table.caption.textContent.trim(),
                name: region && (region.getAttribute('aria-label') ||
                    document.getElementById(region.getAttribute('aria-labelledby'))?.textContent.trim()),
                tabIndex: region && region.tabIndex,
                help: region && document.getElementById(region.getAttribute('aria-describedby'))?.textContent.trim(),
                headers: headers.length > 0 && headers.every(cell =>
                    ['row', 'col'].includes(cell.scope) && cell.textContent.trim()),
                associated: Array.from(table.tBodies).flatMap(body => Array.from(body.rows)).every(row =>
                    row.querySelector('th[scope="row"]') ||
                    Array.from(row.cells).reduce((sum, cell) => sum + cell.colSpan, 0) <= columnCount),
                visible: cells.every(cell => {
                    const style = getComputedStyle(cell);
                    const rect = cell.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0 && style.display !== 'none' &&
                        style.visibility === 'visible';
                }),
            };
        }));
    expect(tables.length).toBeGreaterThan(0);
    for (const table of tables) {
        expect(table.caption).toBeTruthy();
        expect(table.name).toBeTruthy();
        expect(table.help).toBeTruthy();
        expect(table.tabIndex).toBe(0);
        expect(table.headers).toBe(true);
        expect(table.associated).toBe(true);
        expect(table.visible).toBe(true);
    }
}

test('detail headings and core content fit desktop and narrow viewports', async ({page}, info) => {
    for (const size of detailSizes(info)) {
        await page.setViewportSize(size);
        for (const [id, name] of [['910001', detailName], ['112', 'Fixture Dawn Armor'],
            ['113', 'Fixture Goddess Necklace'], ['111', 'Regional Staff'],
            ['230', 'Fixture Red Gem'], ['240', 'Fixture Fire Skill Gem'], ['910002', materialName]]) {
            await item(page, id, name);
            await detailFits(page);
            await readableText(page.locator('#title'));
            const icon = page.locator('.item-detail-heading img');
            await expect(icon).toBeVisible();
            expect(await icon.evaluate(node => node.complete && node.naturalWidth > 0)).toBe(true);
            const order = await page.locator('.item-detail').evaluate(node => {
                const heading = node.querySelector('header').getBoundingClientRect();
                const facts = node.querySelector('.item-detail-facts').getBoundingClientRect();
                return {headingBottom: heading.bottom, factsTop: facts.top};
            });
            expect(order.headingBottom).toBeLessThanOrEqual(order.factsTop);
            if (id === '112') {
                const columns = await page.locator('.item-detail-columns').evaluate(node => {
                    const stats = node.querySelector('.item-detail-stats').getBoundingClientRect();
                    const enhancement = node.querySelector('.item-detail-enhancement').getBoundingClientRect();
                    return {statsTop: stats.top, statsBottom: stats.bottom, statsRight: stats.right,
                        enhancementTop: enhancement.top, enhancementLeft: enhancement.left};
                });
                if (size.width === 1440) {
                    expect(Math.abs(columns.statsTop - columns.enhancementTop)).toBeLessThanOrEqual(1);
                    expect(columns.enhancementLeft).toBeGreaterThanOrEqual(columns.statsRight);
                } else {
                    expect(columns.enhancementTop).toBeGreaterThanOrEqual(columns.statsBottom);
                }
            }
            if (id === '910001') {
                await readableText(page.locator('.item-detail > p').filter({hasText: '긴 설명 日本語 description'}));
                await stat(page, 'patk', '7,000');
                await expect(page.locator('.item-detail-stats')).toContainText('12345678901234567890');
                await expect(page.locator('.item-detail')).toContainText('Second description line 12345678901234567890');
                await evidence(page, info, `detail-heading-${size.width}`);
            }
        }
    }
});

test('detail tables retain semantics and scroll with the keyboard', async ({page}, info) => {
    for (const size of detailSizes(info)) {
        await page.setViewportSize(size);
        for (const id of ['910001', '910003', '910004', '230', '240']) {
            await page.goto(`/items/${id}`);
            await detailTableSemantics(page);
            await detailFits(page);
        }
        await item(page, '230', 'Fixture Red Gem');
        const table = page.locator('#gem-socket-bonuses');
        const before = await table.locator('tbody tr').allTextContents();
        expect(before).toHaveLength(16);
        await expect(table.locator('thead th')).toHaveText(['Lv', 'Slot', 'Stat', 'Value']);
        await expect(table).toContainText('-10');
        const region = page.getByRole('region', {name: 'Socket bonuses', exact: true});
        await region.focus();
        await visibleDetailFocus(region);
        if (await detailTableAccess(page, region)) {
            // Scroll to the final value through the browser's own focus/scroll path.
            await table.locator('tbody tr:last-child td:last-child').scrollIntoViewIfNeeded();
            await expect(table.locator('tbody tr:last-child td:last-child')).toBeInViewport();
        }
        expect(await table.locator('tbody tr').allTextContents()).toEqual(before);
        await detailFits(page);
        await evidence(page, info, `detail-table-${size.width}`);
    }
});

test('detail calculators support touch keyboard and reset values', async ({page}, info) => {
    const cases = [
        ['110', 'Fixture Dawn Sword', 'patk', '7,600', '8,020', '7,000'],
        ['112', 'Fixture Dawn Armor', 'pdef', '10,200', '10,740', '9,000'],
        ['113', 'Fixture Goddess Necklace', 'matk', '3,780', '3,978', '3,300'],
        ['111', 'Regional Staff', 'matk', '392', '462', '350'],
    ];
    for (const size of detailSizes(info)) {
        await page.setViewportSize(size);
        for (const [id, name, key, enhanced, transcended, initial] of cases) {
            await item(page, id, name);
            const detailURL = page.url();
            const anvil = page.getByRole('spinbutton', {name: 'Anvil', exact: true});
            const tc = page.getByRole('spinbutton', {name: 'Transcend', exact: true});
            for (const [input, label, maximum] of [[anvil, 'Anvil', id === '111' ? '40' : '30'],
                [tc, 'Transcend', '10']]) {
                expect(await input.evaluate(node => Array.from(node.labels).some(label =>
                    label.control === node && label.textContent.trim()))).toBe(true);
                await expect(input).toHaveValue('0');
                await expect(input).toHaveAttribute('min', '0');
                await expect(input).toHaveAttribute('max', maximum);
                await expect(input).toHaveAttribute('step', '1');
                await expect(input).toHaveAttribute('inputmode', 'numeric');
                const region = page.getByRole('region', {name: label, exact: true});
                await region.focus();
                await visibleDetailFocus(region);
                await detailTableAccess(page, region, size.width <= 390);
                await detailFits(page);
                await page.keyboard.press('Tab');
                await visibleDetailFocus(input, detailURL);
                await expect.poll(() => input.evaluate(node => {
                    const r = node.getBoundingClientRect();
                    return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2) === node;
                }), {message: 'The focused input is exposed above the other columns'}).toBe(true);
                const box = await input.boundingBox();
                expect(box.width).toBeGreaterThanOrEqual(88);
                expect(box.height).toBeGreaterThanOrEqual(44);
                if (info.project.name === 'mobile') await input.tap();
                else await input.click();
                await expect(input).toBeFocused();
            }
            await anvil.fill('5');
            await anvil.press('ArrowUp');
            await expect(anvil).toHaveValue('6');
            await stat(page, key, enhanced);
            if (id === '112') await stat(page, 'mdef', '5,700');
            if (id === '113') await stat(page, 'patk', '3,780');
            if (id !== '111') {
                await page.keyboard.press('Tab');
                await visibleDetailFocus(page.locator('#god_materials a').first(), detailURL);
            }
            await tc.fill('2');
            await stat(page, key, transcended);
            if (id === '112') await stat(page, 'mdef', '5,970');
            if (id === '111') {
                await stat(page, 'anvil_price', '600');
                await stat(page, 'anvil_total', '2,100');
            } else {
                await stat(page, 'god_chance', '98%');
                const quantities = {'110': ['36', '12'], '112': ['18', '6'], '113': ['12', '7']}[id];
                await expect(page.locator('#god_materials')).toContainText(`Regional Ore × ${quantities[0]}`);
                await expect(page.locator('#god_materials')).toContainText(`Fixture Dust × ${quantities[1]}`);
                await expect(page.locator('#god_materials a[href="/items/100"]')).toHaveText('Regional Ore');
            }
            await detailFits(page);
            if (id === '110') await evidence(page, info, `detail-calculator-${size.width}`);
            // The current calculator resets through its zero inputs; it has no
            // separate reset/step buttons. Keep this real interaction contract.
            await anvil.fill('0');
            await tc.fill('0');
            await stat(page, key, initial);
            await stat(page, 'tc_total', '0');
            await expect(page).toHaveURL(detailURL);
        }
    }
});

test('detail recipes collections and long links preserve navigation', async ({page}, info) => {
    for (const size of detailSizes(info)) {
        await page.setViewportSize(size);
        await item(page, '910003', recipeName);
        const materials = page.getByRole('region', {name: 'Materials', exact: true});
        await expect(materials).toContainText('x123456789');
        const material = materials.getByRole('link', {name: materialName, exact: true});
        await materials.focus();
        await page.keyboard.press('Tab');
        await visibleDetailFocus(material);
        await readableText(material);
        if (size.width <= 390) expect((await material.boundingBox()).height).toBeGreaterThanOrEqual(44);
        await detailFits(page);
        await evidence(page, info, `detail-recipe-${size.width}`);
        await page.keyboard.press('Enter');
        await expect(page).toHaveURL(/\/items\/910002$/);
        await expect(page.locator('#title')).toHaveText(materialName);
        await item(page, '910004', collectionName);
        await expect(page.locator('.item-detail')).toContainText('12345678901234567890');
        await page.getByRole('link', {name: detailName, exact: true}).click();
        await expect(page.locator('#title')).toHaveText(detailName);
        const references = page.getByRole('region', {name: 'Refferences', exact: true});
        await expect(references.getByRole('rowheader', {name: 'Crafted From', exact: true})).toBeVisible();
        const recipe = references.getByRole('link', {name: recipeName, exact: true});
        await recipe.scrollIntoViewIfNeeded();
        await readableText(recipe);
        await recipe.click();
        await expect(page.locator('#title')).toHaveText(recipeName);
        await page.getByRole('region', {name: 'Produce', exact: true})
            .getByRole('link', {name: detailName, exact: true}).click();
        await expect(page).toHaveURL(/\/items\/910001$/);
        await page.getByRole('link', {name: collectionName, exact: true}).click();
        await expect(page).toHaveURL(/\/items\/910004$/);
        await item(page, '240', 'Fixture Fire Skill Gem');
        await page.locator('.item-detail a[href="/skills/400"]').click();
        await expect(page.locator('#title')).toHaveText('Regional Fire');
    }
});

test('detail without JavaScript retains core content and links', async ({browser, baseURL}, info) => {
    const context = await browser.newContext({baseURL, javaScriptEnabled: false,
        viewport: detailSizes(info)[0]});
    let errors = [];
    try {
        errors = await watchNetworking(context, baseURL);
        const page = await context.newPage();
        for (const size of detailSizes(info)) {
            await page.setViewportSize(size);
            for (const order of [['style.css', 'item-detail.css'], ['item-detail.css', 'style.css']]) {
                await orderedDetailNavigation(page, baseURL, order, async () => {
                    const response = await page.goto('/items/910001', {waitUntil: 'commit'});
                    expect(response.status()).toBe(200);
                });
                await expect(page.locator('#title')).toHaveText(detailName);
                await detailFits(page);
                await readableText(page.locator('#title'));
                const description = page.locator('.item-detail > p')
                    .filter({hasText: '긴 설명 日本語 description'});
                await expect(description).toContainText('긴 설명 日本語 description ' + detailTail);
                await expect(page.locator('.item-detail')).toContainText('Second description line 12345678901234567890');
                await readableText(description);
                await stat(page, 'patk', '7000');
                await expect(page.locator('.item-detail-stats')).toContainText('12345678901234567890');
                await detailTableSemantics(page);
                const collection = page.getByRole('link', {name: collectionName, exact: true});
                await expect(collection).toHaveAttribute('href', '/items/910004');
                await orderedDetailNavigation(page, baseURL, order, () => collection.click({noWaitAfter: true}));
                await expect(page.locator('#title')).toHaveText(collectionName);
                await detailFits(page);
                await readableText(page.locator('#title'));
                await expect(page.locator('.item-detail')).toContainText('12345678901234567890');
                await detailTableSemantics(page);
                await page.getByRole('link', {name: detailName, exact: true}).click();
                await expect(page.locator('#title')).toHaveText(detailName);
                await page.getByRole('link', {name: recipeName, exact: true}).click();
                await expect(page.locator('#title')).toHaveText(recipeName);
                const materials = page.getByRole('region', {name: 'Materials', exact: true});
                await expect(materials).toContainText('x123456789');
                const material = materials.getByRole('link', {name: materialName, exact: true});
                await expect(material).toHaveAttribute('href', '/items/910002');
                await readableText(material);
                await orderedDetailNavigation(page, baseURL, order, () => material.click({noWaitAfter: true}));
                await expect(page.locator('#title')).toHaveText(materialName);
                await detailFits(page);
                await readableText(page.locator('#title'));
                const materialDescription = page.locator('.item-detail > p')
                    .filter({hasText: 'Core material description 日本語 한글'});
                await expect(materialDescription).toContainText('Core material description 日本語 한글 ' + detailTail);
                await readableText(materialDescription);
                await evidence(page, info, `detail-no-js-${size.width}-${order[0]}`);
            }
            await item(page, '230', 'Fixture Red Gem');
            await expect(page.locator('#gem-socket-bonuses tbody tr')).toHaveCount(16);
            await expect(page.locator('#gem-socket-bonuses')).toContainText('-10');
            await detailFits(page);
            await evidence(page, info, `detail-no-js-${size.width}`);
            await item(page, '240', 'Fixture Fire Skill Gem');
            await page.locator('.item-detail a[href="/skills/400"]').click();
            await expect(page.locator('#title')).toHaveText('Regional Fire');
        }
    } finally {
        await context.close();
        expect(errors, 'Detail without JavaScript browser errors').toEqual([]);
    }
});

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
