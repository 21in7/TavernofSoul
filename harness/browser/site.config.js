'use strict';
const path = require('node:path');
const {defineConfig} = require('@playwright/test');
const sites = {itos: 'https://itos.gihyeonofsoul.com', ktos: 'https://gihyeonofsoul.com'};
const region = process.env.HARNESS_SITE_REGION;
if (!sites[region]) throw new Error('Choose a configured public site region');
const endpoint = process.env.HARNESS_BROWSER_WS_ENDPOINT;
if (endpoint) {
    const url = new URL(endpoint);
    if (url.protocol !== 'ws:' || url.hostname !== '127.0.0.1' || !url.port ||
        url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
        throw new Error('Only a loopback browser engine is allowed');
    }
}
if (!process.env.HARNESS_BROWSER_ARTIFACT_DIR) throw new Error('Missing artifact directory');
const artifacts = path.resolve(process.env.HARNESS_BROWSER_ARTIFACT_DIR);
module.exports = defineConfig({
    testDir: __dirname, testMatch: 'site.spec.js', workers: 1, retries: 0,
    forbidOnly: true, timeout: 30000, globalTimeout: 240000,
    expect: {timeout: 5000}, outputDir: path.join(artifacts, 'results'),
    reporter: [['line'], ['json', {outputFile: path.join(artifacts, 'playwright.json')}],
        ['html', {outputFolder: path.join(artifacts, 'html'), open: 'never'}]],
    use: {
        browserName: 'chromium', headless: true, baseURL: sites[region],
        serviceWorkers: 'block', ignoreHTTPSErrors: false,
        trace: 'retain-on-failure', screenshot: 'only-on-failure',
        ...(endpoint ? {connectOptions: {wsEndpoint: endpoint, timeout: 15000}} : {}),
    },
    projects: [
        {name: 'desktop', use: {viewport: {width: 1440, height: 900}}},
        {name: 'mobile', use: {viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true}},
    ],
});
