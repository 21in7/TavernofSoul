// Project adapter; the pinned upstream implementation remains unchanged in vendor/.
import { SYSTEM_ONE_URL } from '../vendor/src/request.js';

export function redact(value, secrets) {
  if (typeof value === 'string') {
    const variants = secrets.filter(Boolean).flatMap(secret => [secret, JSON.stringify(secret).slice(1, -1)]);
    for (const secret of [...new Set(variants)].sort((a, b) => b.length - a.length)) {
      value = value.split(secret).join('[REDACTED]');
    }
    return value;
  }
  if (Array.isArray(value)) return value.map(item => redact(item, secrets));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([name, item]) =>
      [redact(name, secrets), redact(item, secrets)]));
  }
  return value;
}

// The upstream hook prints HTTP error bodies; discard them before its parser sees them.
// Validate probability bounds too, so malformed answers cannot remove history.
export function guardedFetch(fetchFn, getSecrets) {
  return async (url, init) => {
    try {
      if (url !== SYSTEM_ONE_URL || init?.method !== 'POST' || typeof init.body !== 'string') {
        throw new Error('invalid request');
      }
      const body = JSON.parse(init.body);
      body.state = redact(body.state, await getSecrets());
      const response = await fetchFn(url, { ...init, body: JSON.stringify(body) });
      if (!response.ok) return { status: response.status, ok: false, text: '' };
      if (typeof response.text !== 'string' || response.text.length > 1048576) {
        throw new Error('invalid response');
      }
      const data = JSON.parse(response.text);
      if (!data || !data.answers || typeof data.answers !== 'object' || Array.isArray(data.answers) ||
          Object.keys(data.answers).sort().join('\n') !== Object.keys(body.questions).sort().join('\n')) {
        throw new Error('invalid response');
      }
      for (const answer of Object.values(data.answers)) {
        if (!answer || answer.type !== 'noul' || typeof answer.noul !== 'number' ||
            !Number.isFinite(answer.noul) || answer.noul < 0 || answer.noul > 1) {
          throw new Error('invalid response');
        }
      }
      if (data.model !== body.model) throw new Error('model mismatch');
      return { status: response.status, ok: true, text: response.text };
    } catch {
      // No transport exception or malformed input is allowed into session diagnostics.
      throw new Error('Jev transport or response validation failed');
    }
  };
}

