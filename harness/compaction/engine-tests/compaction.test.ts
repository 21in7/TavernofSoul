import { expect, mock, test } from 'claude-code/testing';
import { fakeResponse, textIsPreserved, transcript } from '../fixture.mjs';

test('real hook engine prunes history and preserves user instructions', async ($, on) => {
  mock.env(on, { TYPESAFE_API_KEY: 'offline-engine-key' });
  on('http.fetch', (_, event) => ({ value: fakeResponse(JSON.parse(event.init.body)) }));
  on('ui.log', () => ({ value: undefined }));
  on('ui.toast', () => ({ value: undefined }));
  const messages = transcript();
  const result = await $.session.compact({ trigger: 'manual', messages });
  expect(textIsPreserved(messages, result.messages)).toBe(true);
  expect(result.messages.flatMap(message => message.toolUses)
    .some(call => call.tool_use_id === 'obsolete')).toBe(false);
});

test('real hook engine delegates an HTTP failure to core', async ($, on) => {
  mock.env(on, { TYPESAFE_API_KEY: 'offline-engine-key' });
  on('http.fetch', () => ({ value: { status: 429, ok: false, text: 'untrusted diagnostic' } }));
  on('ui.log', () => ({ value: undefined }));
  on('ui.toast', () => ({ value: undefined }));
  on('session.compact', (_, event) => ({ messages: event.messages }));
  const messages = transcript();
  const result = await $.session.compact({ trigger: 'manual', messages });
  expect(textIsPreserved(messages, result.messages)).toBe(true);
  expect(result.messages.flatMap(message => message.toolUses)
    .some(call => call.tool_use_id === 'obsolete')).toBe(true);
});
