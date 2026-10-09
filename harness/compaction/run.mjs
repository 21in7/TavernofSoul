import { readFile } from 'node:fs/promises';
import { register } from './hooks/register.js';
import { fakeResponse, textIsPreserved, transcript } from './fixture.mjs';

const mode = process.argv[2];
if (!['demo', 'smoke'].includes(mode)) throw new Error('Choose demo or smoke');
const live = mode === 'smoke';
const metadata = JSON.parse(await readFile(new URL('.claude-plugin/plugin.json', import.meta.url), 'utf8'));
const options = Object.fromEntries(Object.entries(metadata.userConfig)
  .filter(([, spec]) => spec.default !== undefined).map(([name, spec]) => [name, spec.default]));
const handlers = {};
register((name, handler) => { handlers[name] = handler; }, options);
const messages = transcript();
const logs = [];
let requests = 0, fallback = false;
const $ = {
  env: { get: async name => name === 'TYPESAFE_API_KEY'
    ? (live ? process.env.TYPESAFE_API_KEY : 'offline-demo-key') : undefined },
  settings: { read: async () => ({}) },
  ui: { log: text => logs.push(text), toast: () => {} },
  session: { usage: async () => ({ context: { percent: 10 } }), compact: async () => {} },
  http: { fetch: async (url, init) => {
    requests++;
    if (!live) return fakeResponse(JSON.parse(init.body));
    const response = await fetch(url, { ...init, redirect: 'error', signal: AbortSignal.timeout(15000) });
    return { status: response.status, ok: response.ok, text: await response.text() };
  } },
};
const result = await handlers['session.compact']($, { trigger: 'manual', messages }, async () => {
  fallback = true;
  return { messages };
});
const valid = textIsPreserved(messages, result.messages) && requests > 0 &&
  (!fallback || logs.some(line => line.startsWith('fallback to built-in summary (below')));
// No conversation text, result contents, credentials or response body is printed.
console.log(JSON.stringify({ status: valid ? 'passed' : 'failed', mode,
  source: live ? 'api' : 'fixture', agent_started: false, api_called: live && requests > 0,
  requests, model: options.model, messages_before: messages.length,
  messages_after: result.messages.length, text_preserved: textIsPreserved(messages, result.messages),
  outcome: fallback ? 'fallback_requested' : 'history_pruned', diagnostics: logs }, null, 2));
process.exitCode = valid ? 0 : 1;
