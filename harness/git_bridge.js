/* Trusted-parent capabilities only. Evaluate this file before starting workflow;
 * no require(), process, fetch(), filesystem or connector discovery is used. */
(function (root) {
  'use strict';
  const VERSION = 'git-transport-v1', READY = 'transport-input-ready-v1';
  const MAX_RESPONSE = 8 * 1024 * 1024, MAX_RESULT = 32 * 1024 * 1024;
  const INLINE = 32768, CHUNK = 12288, MAX_OPS = 4096;
  const ALLOW = Object.freeze(['fetch', 'create_tree', 'create_commit', 'create_branch',
    'create_pull_request', 'merge_pull_request'].map(x => 'mcp__codex_apps__github_' + x));
  const fail = code => { throw new Error(code); };
  const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
  const hex = x => typeof x === 'string' && /^[a-f0-9]{64}$/.test(x);
  const quote = x => "'" + String(x).replace(/'/g, "'\\''") + "'";
  function utf8(text) {
    const bytes = [];
    for (const char of text) {
      const c = char.codePointAt(0);
      if (c >= 0xd800 && c <= 0xdfff) fail('invalid_utf8');
      if (c < 128) bytes.push(c);
      else if (c < 2048) bytes.push(192 | c >> 6, 128 | c & 63);
      else if (c < 65536) bytes.push(224 | c >> 12, 128 | c >> 6 & 63, 128 | c & 63);
      else bytes.push(240 | c >> 18, 128 | c >> 12 & 63, 128 | c >> 6 & 63, 128 | c & 63);
    }
    return bytes;
  }
  function decode(bytes) {
    // decodeURIComponent rejects overlong encodings, surrogates and partial UTF-8.
    const parts = [];
    for (let start = 0; start < bytes.length;) {
      let end = Math.min(start + 4096, bytes.length);
      while (end < bytes.length && (bytes[end] & 192) === 128) --end;
      if (end <= start) fail('invalid_utf8');
      let escaped = '';
      for (let i = start; i < end; ++i) escaped += '%' + bytes[i].toString(16).padStart(2, '0');
      parts.push(decodeURIComponent(escaped)); start = end;
    }
    return parts.join('');
  }
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  function base64(bytes) {
    let out = '';
    for (let i = 0; i < bytes.length; i += 3) {
      const a = bytes[i], b = bytes[i + 1], c = bytes[i + 2];
      out += alphabet[a >> 2] + alphabet[(a & 3) << 4 | (b || 0) >> 4] +
        (b === undefined ? '=' : alphabet[(b & 15) << 2 | (c || 0) >> 6]) +
        (c === undefined ? '=' : alphabet[c & 63]);
    }
    return out;
  }
  function unbase64(text) {
    if (typeof text !== 'string' || text.length % 4 ||
        !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(text)) fail('invalid_base64');
    const out = [];
    for (let i = 0; i < text.length; i += 4) {
      const a = alphabet.indexOf(text[i]), b = alphabet.indexOf(text[i + 1]);
      const c = alphabet.indexOf(text[i + 2]), d = alphabet.indexOf(text[i + 3]);
      out.push(a << 2 | b >> 4);
      if (c >= 0) out.push((b & 15) << 4 | c >> 2);
      if (d >= 0) out.push((c & 3) << 6 | d);
    }
    if (base64(out) !== text) fail('invalid_base64');
    return out;
  }
  // Portable SHA-256: functions.exec supplies no Node crypto or browser globals.
  function sha256(input) {
    const k = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
      0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
      0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
      0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
      0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
      0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
      0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
      0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
    const h = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    const bytes = new Uint8Array(Math.ceil((input.length + 9) / 64) * 64), bits = input.length * 8;
    bytes.set(input); bytes[input.length] = 128;
    for (let i = 0; i < 8; ++i) bytes[bytes.length - 1 - i] = Math.floor(bits / Math.pow(256, i)) & 255;
    const rr = (a, n) => a >>> n | a << (32 - n), w = new Array(64);
    for (let offset = 0; offset < bytes.length; offset += 64) {
      for (let i = 0; i < 16; ++i) {
        const j = offset + 4 * i; w[i] = bytes[j] << 24 | bytes[j+1] << 16 | bytes[j+2] << 8 | bytes[j+3];
      }
      for (let i = 16; i < 64; ++i) {
        const x = w[i-15], y = w[i-2];
        w[i] = (w[i-16] + (rr(x,7)^rr(x,18)^x>>>3) + w[i-7] + (rr(y,17)^rr(y,19)^y>>>10)) | 0;
      }
      let [a,b,c,d,e,f,g,j] = h;
      for (let i = 0; i < 64; ++i) {
        const t = (j + (rr(e,6)^rr(e,11)^rr(e,25)) + (e&f ^ ~e&g) + k[i] + w[i]) | 0;
        const u = ((rr(a,2)^rr(a,13)^rr(a,22)) + (a&b ^ a&c ^ b&c)) | 0;
        j=g; g=f; f=e; e=(d+t)|0; d=c; c=b; b=a; a=(t+u)|0;
      }
      [a,b,c,d,e,f,g,j].forEach((v,i) => { h[i]=(h[i]+v)|0; });
    }
    return h.map(x => (x>>>0).toString(16).padStart(8,'0')).join('');
  }
  function json(text) { try { return JSON.parse(text); } catch (_) { return fail('invalid_json_or_truncation'); } }
  function summary(output) {
    if (typeof output !== 'string' || utf8(output).length > 1024 * 1024) fail('workflow_output_invalid');
    const starts = [0];
    for (let i = 0; i < output.length; ++i) if (output[i] === '\n' && output[i+1] === '{') starts.push(i+1);
    for (const start of starts.reverse()) {
      try {
        const value = JSON.parse(output.slice(start));
        if (object(value) && typeof value.status === 'string') return value;
      } catch (_) { /* Only a complete final root object is eligible. */ }
    }
    return fail('workflow_summary_missing');
  }

  function create(cap) {
    if (!cap || !object(cap.tools) || !['load','store','attachArtifact','sleep','yield'].every(k => typeof cap[k] === 'function'))
      fail('parent_capabilities_required');
    const tools = cap.tools, now = cap.now || (() => Date.now());
    const key = cap.stateKey || 'trusted-git-bridge';
    const executable = cap.python || 'python3';
    let state;
    async function save() { await cap.store(key, state); }
    async function init(run) {
      if (!/^[0-9]+-[a-f0-9]{6}$/.test(run || '')) fail('invalid_run');
      const old = await cap.load(key);
      if (old !== undefined && old !== null) fail('existing_state_requires_reconciliation');
      state = {version: VERSION, run, operations: {}, events: [], phase: 'starting'};
      await event('bridge_start');
    }
    async function event(kind, extra = {}) {
      if (state.events.length >= 8192) fail('event_limit');
      state.events.push({kind, at_ms: now(), ...extra}); await save();
      if (cap.notify) await cap.notify({stage: kind}); // metadata only
    }
    async function pause(ms) {
      while (ms > 0) {
        const part = Math.min(30000, ms); await cap.sleep(part); ms -= part;
        await cap.yield();
      }
    }
    function shell(command, args) {
      return [executable, '-m', 'harness.git_transport', command, '--run-id', state.run, ...args].map(quote).join(' ');
    }
    function output(result, budget = 22000) {
      if (!object(result) || typeof result.output !== 'string' || result.isError === true ||
          result.truncated === true || result.output_truncated === true ||
          (result.original_token_count !== undefined &&
            (!Number.isInteger(result.original_token_count) || result.original_token_count < 0 ||
              result.original_token_count > budget))) fail('tool_output_truncated');
      // Diagnostic words may be legitimate source content. Wrapper metadata and
      // the bounded, fully parsed size/hash-checked frames establish completeness.
      if (result.output.length > 1024 * 1024 || utf8(result.output).length > 1024 * 1024)
        fail('tool_output_too_large');
      return result.output;
    }
    async function finish(first, initial = '') {
      let result = first, text = initial + output(first), turns = 0;
      if (utf8(text).length > 200000) fail('tool_output_too_large');
      while (result.session_id !== undefined && result.exit_code === undefined) {
        if (++turns > 7200) fail('transport_wait_limit');
        await cap.yield();
        result = await tools.write_stdin({session_id: result.session_id, chars: '', yield_time_ms: 1000, max_output_tokens: 22000});
        text += output(result);
        if (utf8(text).length > 200000) fail('tool_output_too_large');
      }
      if (!Number.isInteger(result.exit_code)) fail('missing_exit_code');
      return {text, code: result.exit_code};
    }
    async function invoke(command, args = [], response) {
      await event('transport_start', {operation: command});
      const started = now();
      let result;
      if (response === undefined) {
        result = await finish(await tools.exec_command({cmd: shell(command, args), login: false,
          yield_time_ms: 1000, max_output_tokens: 22000}));
      } else {
        const raw = utf8(JSON.stringify(response));
        if (raw.length > MAX_RESPONSE) fail('response_too_large');
        const encoded = base64(raw), lines = encoded.match(/.{1,2048}/g) || [];
        const frame = lines.join('\n') + '\n.\n';
        let first = await tools.exec_command({cmd: 'stty -echo && exec ' + shell(command, args.concat('--stdin-base64')),
          tty: true, login: false, yield_time_ms: 1000, max_output_tokens: 22000});
        let prefix = output(first), turns = 0;
        while (!prefix.includes(READY)) {
          if (!first.session_id || first.exit_code !== undefined || ++turns > 30) fail('stdin_not_ready');
          await cap.yield();
          first = await tools.write_stdin({session_id: first.session_id, chars: '', yield_time_ms: 1000, max_output_tokens: 22000});
          prefix += output(first);
          if (prefix.length > 256) fail('stdin_protocol_invalid');
        }
        if (prefix.replace(READY, '').trim() || first.exit_code !== undefined) fail('stdin_protocol_invalid');
        // No response bytes occur in a shell command or OS argv. No echo, no EOF.
        let last = first, collected = '';
        for (let offset = 0; offset < frame.length; offset += 65536) {
          if (!last.session_id || last.exit_code !== undefined) fail('stdin_ended_early');
          last = await tools.write_stdin({session_id: last.session_id, chars: frame.slice(offset, offset+65536),
            yield_time_ms: 1, max_output_tokens: 22000});
          if (offset + 65536 < frame.length) {
            collected += output(last);
            if (utf8(collected).length > 200000) fail('tool_output_too_large');
          }
        }
        result = await finish(last, collected);
      }
      const env = json(result.text.trim());
      if (!object(env) || env.version !== VERSION) fail('transport_envelope_invalid');
      if (!hex(env.operation_id) || !hex(env.sha256) || !Number.isInteger(env.bytes) ||
          env.bytes < 1 || env.bytes > MAX_RESULT || !Number.isInteger(env.native_exit_code) ||
          result.code !== env.native_exit_code) fail('transport_refused_or_truncated');
      let raw;
      if (Object.prototype.hasOwnProperty.call(env, 'inline')) {
        if (typeof env.inline !== 'string' || env.bytes > INLINE || env.chunks !== undefined) fail('inline_invalid');
        raw = utf8(env.inline);
      } else {
        const c = env.chunks;
        if (env.bytes <= INLINE || !object(c) || c.bytes !== CHUNK || c.encoding !== 'base64' ||
            c.count !== Math.ceil(env.bytes / CHUNK)) fail('chunk_metadata_invalid');
        raw = new Uint8Array(env.bytes);
        for (let i = 0; i < c.count; ++i) {
          const read = await finish(await tools.exec_command({cmd: shell('chunk', ['--operation-id', env.operation_id, '--index', String(i)]),
            login: false, yield_time_ms: 1000, max_output_tokens: 22000}));
          const part = json(read.text.trim());
          if (read.code !== 0 || part.version !== VERSION || part.operation_id !== env.operation_id ||
              part.index !== i || part.offset !== i*CHUNK || part.total_bytes !== env.bytes ||
              part.sha256 !== env.sha256 || part.bytes !== Math.min(CHUNK, env.bytes-i*CHUNK) ||
              typeof part.data !== 'string' || part.data.length > 16384) fail('chunk_invalid');
          const bytes = unbase64(part.data);
          if (bytes.length !== part.bytes) fail('chunk_size_invalid');
          raw.set(bytes, part.offset);
          await cap.yield();
        }
      }
      if (raw.length !== env.bytes || sha256(raw) !== env.sha256) fail('payload_digest_invalid');
      const native = json(decode(raw));
      if (!object(native)) fail('native_result_invalid');
      const failedWithoutRun = native.run_id === undefined && native.status === 'failed' &&
        env.native_exit_code !== 0 && native.request === undefined;
      if (native.run_id !== state.run && !failedWithoutRun) fail('native_result_invalid');
      state.native = native; state.nativeExitCode = env.native_exit_code;
      state.transport = env; await event('transport_end', {operation: command, duration_ms: now()-started});
      return {native, exitCode: env.native_exit_code};
    }
    async function observe(native) {
      const gh = native.github;
      if (object(gh) && typeof gh.pr_url === 'string' && !state.attached) {
        if (!/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/pull\/[1-9][0-9]*$/.test(gh.pr_url)) fail('pr_url_invalid');
        state.attached = 'pending'; await event('pr_observed');
        await cap.attachArtifact(gh.pr_url);
        state.attached = 'complete'; await save();
      }
    }
    async function drive(current) {
      for (let count = 0; count < MAX_OPS; ++count) {
        const n = current.native, gh = n.github || {};
        await observe(n);
        if (['needs_reconciliation','failed','awaiting_ci','cleanup_pending'].includes(gh.status) ||
            n.status === 'failed' || n.status === 'needs_reconciliation') return current;
        const job = n.request;
        if (job === null || job === undefined) return current; // archive pending is preserved, never passed
        if (current.exitCode !== 0 && !(gh.status === 'merged' && /^cleanup_/.test(gh.step || ''))) return current;
        if (!['awaiting_connector','waiting_for_ci'].includes(gh.status) &&
            !(gh.status === 'merged' && /^cleanup_/.test(gh.step || ''))) fail('native_state_invalid');
        if (!object(job) || !hex(job.request_id) || !ALLOW.includes(job.tool) ||
            !object(job.arguments) || typeof tools[job.tool] !== 'function') fail('request_tool_invalid');
        if (Object.keys(state.operations).length >= MAX_OPS || state.operations[job.request_id]) fail('duplicate_dispatch');
        const poll = n.poll_after_seconds;
        if (typeof poll !== 'number' || !Number.isFinite(poll) || poll < 0 || poll > 1800) fail('poll_invalid');
        if (poll) await pause(poll * 1000);
        const op = {phase: 'dispatching', tool: job.tool, arguments: job.arguments};
        state.operations[job.request_id] = op; await event('connector_dispatch');
        const started = now();
        let response;
        try { response = await tools[job.tool](job.arguments); }
        catch (error) {
          op.connectorException = String(error); // private, never public notification
          response = {isError: true, content: [{type: 'text', text: 'Connector call failed; reconcile the original request.'}]};
        }
        op.response = response; op.phase = 'responded';
        // Preserve backend created_at and the exact original response privately.
        await event('connector_response', {duration_ms: now()-started});
        current = await invoke('accept', ['--request-id', job.request_id], response);
        op.phase = 'accepted'; await save();
        await cap.yield();
      }
      return fail('operation_limit');
    }
    async function publish(run) {
      await init(run);
      return drive(await invoke('request'));
    }
    async function handoff(initial, mode) {
      if (!object(mode) || mode.readOnly !== false || mode.demo !== false || mode.git !== true) fail('workflow_mode_not_publishable');
      let result = initial, text = output(result, 16000), polls = 0;
      while (result.session_id !== undefined && result.exit_code === undefined) {
        if (++polls > 86400) fail('workflow_wait_limit');
        // Yield on every short poll so the parent can update the user within 60s.
        if (cap.notify) await cap.notify({stage: 'workflow_wait'});
        await cap.yield();
        result = await tools.write_stdin({session_id: result.session_id, chars: '', yield_time_ms: 1000, max_output_tokens: 16000});
        text += output(result, 16000);
        if (utf8(text).length > 1024*1024) fail('workflow_output_too_large');
      }
      if (result.exit_code !== 0) fail('workflow_failed');
      const final = summary(text);
      if (final.status !== 'awaiting_github' || final.simulated !== false || final.read_only === true ||
          final.no_git === true || final.github_enabled === false || !Array.isArray(final.changed_files) ||
          !final.changed_files.length || !object(final.github) || final.github.status !== 'awaiting_connector' ||
          final.github.step !== 'repository' || (final.archive && final.archive.status === 'pending')) fail('workflow_not_ready');
      const readyAt = now();
      await init(final.run_id);
      state.workflow = final;
      await event('workflow_ready', {ready_at_ms: readyAt, native_progress_time: final.current && final.current.time});
      return drive(await invoke('request'));
    }
    return Object.freeze({publish, handoff});
  }
  const api = Object.freeze({create, allowlist: ALLOW, sha256, utf8, base64, summary});
  root.TavernGitBridge = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(globalThis);
