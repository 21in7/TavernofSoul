import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { register } from '../hooks/register.js';
import { guardedFetch } from '../hooks/transport.js';
import { fakeResponse, textIsPreserved, transcript } from '../fixture.mjs';
import { SYSTEM_ONE_URL } from '../vendor/src/request.js';

const metadata = JSON.parse(await readFile(new URL('../.claude-plugin/plugin.json', import.meta.url), 'utf8'));
const defaults = Object.fromEntries(Object.entries(metadata.userConfig)
  .filter(([, spec]) => spec.default !== undefined).map(([name, spec]) => [name, spec.default]));

function engine(options = {}, fetchFn = async (url, init) => fakeResponse(JSON.parse(init.body))) {
  const handlers = {}, logs = [], requests = [], compactCalls = [];
  register((name, handler) => { handlers[name] = handler; }, { ...defaults, ...options });
  const $ = {
    env: { get: async name => name === 'TYPESAFE_API_KEY' ? 'test-typesafe-private' : undefined },
    settings: { read: async () => ({}) },
    ui: { log: message => logs.push(message), toast: () => {} },
    http: { fetch: async (url, init) => { requests.push(init); return fetchFn(url, init); } },
    session: { usage: async () => ({ context: { percent: 70 } }),
      compact: async () => { compactCalls.push(true); } },
  };
  let fallback = false;
  return { handlers, $, logs, requests, compactCalls,
    get fallback() { return fallback; },
    compact: async messages => handlers['session.compact']($, { trigger: 'manual', messages }, async () => {
      fallback = true;
      return { messages };
    }) };
}

test('pruning preserves instructions and pairs, truncates rerunnable output, and pins recent results', async () => {
  const input = transcript();
  input.forEach((message, index) => { message.handle = 'handle-' + index; });
  const original = JSON.stringify(input);
  const host = engine();
  const { messages } = await host.compact(input);
  assert.equal(host.fallback, false);
  assert.equal(host.requests.length, 1);
  assert.equal(textIsPreserved(input, messages), true);
  assert.equal(JSON.stringify(input), original);
  const calls = messages.flatMap(message => message.toolUses).map(call => call.tool_use_id);
  const results = messages.flatMap(message => message.toolResults ?? []);
  assert.equal(calls.includes('obsolete'), false);
  assert.equal(results.some(result => result.tool_use_id === 'obsolete'), false);
  assert.equal(results.every(result => calls.includes(result.tool_use_id)), true);
  const changed = messages.find(message => message.toolResults?.some(result => result.tool_use_id === 'rerunnable'));
  assert.equal(changed.handle, undefined);
  assert.match(changed.toolResults[0].text, /fast-jev-compaction truncated/);
  assert.equal(messages.find(message => message.handle === 'handle-14'), input[14]);
  assert.equal(messages[0], input[0]);
  assert.equal(messages.find(message => message.handle === 'handle-7'), input[7]);
  assert.match(host.logs.join('\n'), /no summary/);
});

test('Jev sees text and tool inputs, while full tool results are omitted', async () => {
  const host = engine();
  await host.compact(transcript());
  const body = JSON.parse(host.requests[0].body);
  assert.equal(body.model, 'jev-1.13.0');
  assert.match(JSON.stringify(body.state), /운영 데이터를 변경하지/);
  assert.match(JSON.stringify(body.state), /downloader\/old-debug.txt/);
  assert.equal(JSON.stringify(body.state).includes('obsolete download log'), false);
  assert.equal(Object.keys(body.questions).some(name => name.endsWith('_t4')), false);
});

test('first message tool calls remain pinned even when their results are old', async () => {
  const messages = transcript();
  messages[0].toolUses = [{ tool_use_id: 'first', tool: 'Read', input: { file_path: 'AGENTS.md' } }];
  messages[2].toolResults.push({ tool_use_id: 'first', text: 'first result' });
  const host = engine();
  const output = await host.compact(messages);
  assert.equal(output.messages[0], messages[0]);
  assert.equal(output.messages.flatMap(message => message.toolResults ?? [])
    .some(result => result.tool_use_id === 'first' && result.text === 'first result'), true);
});

test('unpaired tool calls are retained rather than removing an in-flight operation', async () => {
  const messages = transcript();
  messages[3].toolUses.push({ tool_use_id: 'inflight', tool: 'Read', input: { file_path: 'pending.txt' } });
  const result = await engine().compact(messages);
  assert.equal(result.messages.flatMap(message => message.toolUses)
    .some(call => call.tool_use_id === 'inflight'), true);
});

test('short histories make no request and fall back below the reduction threshold', async () => {
  const messages = transcript().slice(-4), host = engine();
  const result = await host.compact(messages);
  assert.equal(host.requests.length, 0);
  assert.equal(host.fallback, true);
  assert.equal(result.messages, messages);
});

for (const status of [401, 429, 529]) {
  test(`HTTP ${status} requests built-in compaction without leaking the response body`, async () => {
    const host = engine({}, async () => ({ status, ok: false, text: 'test-typesafe-private untrusted diagnostic' }));
    const messages = transcript(), output = await host.compact(messages);
    assert.equal(host.fallback, true);
    assert.equal(output.messages, messages);
    assert.equal(host.requests.length, 1);
    assert.equal(host.logs.join('').includes('test-typesafe-private'), false);
    assert.equal(host.logs.join('').includes('untrusted diagnostic'), false);
  });
}

for (const value of [-0.1, 1.1, '0.5', null]) {
  test(`invalid probability ${value} cannot remove history`, async () => {
    const host = engine({}, async (url, init) => {
      const response = fakeResponse(JSON.parse(init.body)), data = JSON.parse(response.text);
      Object.values(data.answers)[0].noul = value;
      response.text = JSON.stringify(data);
      return response;
    });
    const messages = transcript(), result = await host.compact(messages);
    assert.equal(host.fallback, true);
    assert.equal(result.messages, messages);
  });
}

test('missing key falls back without an HTTP request', async () => {
  const host = engine();
  host.$.env.get = async () => undefined;
  await host.compact(transcript());
  assert.equal(host.requests.length, 0);
  assert.equal(host.fallback, true);
});

test('registered keys are redacted from state while the authorization header remains usable', async () => {
  const host = engine();
  host.$.env.get = async name => name === 'TYPESAFE_API_KEY' ? 'test-typesafe-private' : 'test-provider-private';
  const messages = transcript();
  messages[3].text += ' test-typesafe-private test-provider-private';
  await host.compact(messages);
  const request = host.requests[0];
  assert.equal(request.headers.authorization, 'Bearer test-typesafe-private');
  assert.equal(request.body.includes('test-typesafe-private'), false);
  assert.equal(request.body.includes('test-provider-private'), false);
});

test('transport exceptions expose a fixed failure description and preserve the original transcript', async () => {
  const host = engine({}, async () => { throw new Error('test-typesafe-private network diagnostic'); });
  await host.compact(transcript());
  assert.equal(host.fallback, true);
  assert.match(host.logs.join('\n'), /transport or response validation failed/);
  assert.equal(host.logs.join('').includes('test-typesafe-private'), false);
});

test('different model and missing question answers both fall back', async () => {
  for (const mutate of [data => { data.model = 'jev-other'; }, data => { delete data.answers.call_t1; }]) {
    const host = engine({}, async (url, init) => {
      const response = fakeResponse(JSON.parse(init.body)), data = JSON.parse(response.text);
      mutate(data);
      return { ...response, text: JSON.stringify(data) };
    });
    await host.compact(transcript());
    assert.equal(host.fallback, true);
  }
});

test('request budgeting can batch decisions while keeping call/result pairs intact', async () => {
  const host = engine({ maxStateTokens: 1000, maxRequestTokens: 1200 });
  const result = await host.compact(transcript());
  assert.equal(host.fallback, false);
  assert.ok(host.requests.length > 1);
  assert.equal(textIsPreserved(transcript(), result.messages), true);
});

test('a state that cannot fit retains the original history without an HTTP request', async () => {
  const host = engine({ maxStateTokens: 1, maxRequestTokens: 1000 });
  const messages = transcript(), result = await host.compact(messages);
  assert.equal(host.fallback, true);
  assert.equal(host.requests.length, 0);
  assert.equal(result.messages, messages);
});

test('auto-compaction uses the context threshold and prevents recursive compaction', async () => {
  const host = engine();
  host.$.session.compact = async () => {
    host.compactCalls.push(true);
    await host.handlers['turn.complete'](host.$, {}, async () => ({}));
  };
  await host.handlers['turn.complete'](host.$, {}, async () => ({}));
  assert.equal(host.compactCalls.length, 1);
  host.$.session.usage = async () => ({ context: { percent: 20 } });
  await host.handlers['turn.complete'](host.$, {}, async () => ({}));
  assert.equal(host.compactCalls.length, 1);
});

test('guarded transport refuses an unexpected endpoint without calling it', async () => {
  let called = false;
  const fetchFn = guardedFetch(async () => { called = true; }, async () => []);
  await assert.rejects(fetchFn('https://other.example', { method: 'POST', body: '{}' }));
  assert.equal(called, false);
  assert.equal(SYSTEM_ONE_URL, 'https://api.typesafe.ai/v1/systemone');
});
