'use strict';
const path = require('node:path');
const {defineConfig} = require('@playwright/test');

function loopbackURL(value, protocol) {
    const url = new URL(value);
    if (url.protocol !== protocol || url.hostname !== '127.0.0.1' || !url.port ||
        url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
        throw new Error('Browser harness requires an explicit 127.0.0.1 test endpoint');
    }
    return url;
}

const base = loopbackURL(process.env.HARNESS_BROWSER_BASE_URL, 'http:');
const endpoint = process.env.HARNESS_BROWSER_WS_ENDPOINT;
if (endpoint) loopbackURL(endpoint, 'ws:');
if (!process.env.HARNESS_BROWSER_ARTIFACT_DIR) throw new Error('Missing browser artifact directory');
const artifacts = path.resolve(process.env.HARNESS_BROWSER_ARTIFACT_DIR);

module.exports = defineConfig({
    testDir: __dirname,
    testMatch: 'equipment.spec.js',
    fullyParallel: false,
    workers: 1,
    retries: 0,
    forbidOnly: true,
    timeout: 30000,
    globalTimeout: 300000,
    expect: {timeout: 5000},
    outputDir: path.join(artifacts, 'results'),
    reporter: [
        ['line'],
        ['json', {outputFile: path.join(artifacts, 'playwright.json')}],
        ['html', {outputFolder: path.join(artifacts, 'html'), open: 'never'}],
    ],
    use: {
        browserName: 'chromium',
        headless: true,
        baseURL: base.origin,
        serviceWorkers: 'block',
        trace: 'retain-on-failure',
        screenshot: 'only-on-failure',
        ...(endpoint ? {connectOptions: {
            wsEndpoint: endpoint,
            // Forward only this disposable Django server through the connection.
            exposeNetwork: `127.0.0.1:${base.port}`,
            timeout: 15000,
        }} : {}),
    },
    projects: [
        {name: 'desktop', use: {viewport: {width: 1440, height: 900}}},
        {name: 'mobile', use: {viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true}},
    ],
});
