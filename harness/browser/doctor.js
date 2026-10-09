'use strict';
const fs = require('node:fs');
const {chromium} = require('@playwright/test');

(async () => {
    if (Number(process.versions.node.split('.')[0]) < 20) throw new Error('Node.js >= 20 required');
    const expected = require('./package.json').devDependencies['@playwright/test'];
    const actual = require('@playwright/test/package.json').version;
    if (actual !== expected) throw new Error(`Playwright ${expected} required; found ${actual}`);
    const endpoint = process.env.HARNESS_BROWSER_WS_ENDPOINT;
    if (!endpoint && process.platform === 'linux') {
        const release = fs.readFileSync('/etc/os-release', 'utf8');
        if (/^ID=ubuntu$/m.test(release) && /^VERSION_ID="?20\.04"?$/m.test(release)) {
            throw new Error('Ubuntu 20.04: use make check-browser-container (supported Ubuntu browser image)');
        }
    }
    if (endpoint) {
        const url = new URL(endpoint);
        if (url.protocol !== 'ws:' || url.hostname !== '127.0.0.1' || !url.port ||
            url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
            throw new Error('Only a loopback Playwright test server is allowed');
        }
    }
    const browser = endpoint ? await chromium.connect(endpoint, {timeout: 15000}) :
        await chromium.launch({headless: true, timeout: 15000});
    try {
        console.log(JSON.stringify({status: 'passed', playwright: actual,
            chromium: browser.version(), mode: endpoint ? 'container' : 'native',
            node: process.version, architecture: process.arch}));
    } finally {
        await browser.close();
    }
})().catch(error => {console.error(error.stack); process.exitCode = 1;});
