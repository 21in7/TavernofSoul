// Adapted from vendor/hooks/fast-jev.js; original MIT license is in vendor/LICENSE.
import { guardedFetch } from './transport.js';
import { compact, reductionRatio, resolveOptions } from '../vendor/src/compact.js';
import { buildJevRequest, DEFAULT_MODEL, parseJevResponse } from '../vendor/src/request.js';
const HOOK_DEFAULTS = {
    compactAtPercent: 60,
    minReductionRatio: 0.25,
    model: DEFAULT_MODEL,
};
function optionNumber(options, key, fallback) {
    const value = options[key];
    return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}
function optionString(options, key) {
    const value = options[key];
    return typeof value === 'string' && value.length > 0 ? value : undefined;
}
/** Reads the plugin's `userConfig` values; anything missing takes the defaults. */
export function resolveHookConfig(options) {
    const numbers = {};
    for (const key of [
        'keepThreshold',
        'preserveRecentMessages',
        'maxStateTokens',
        'maxRequestTokens',
        'truncateHeadChars',
    ]) {
        const value = options[key];
        if (typeof value === 'number' && Number.isFinite(value))
            numbers[key] = value;
    }
    const config = {
        ...numbers,
        compactAtPercent: optionNumber(options, 'compactAtPercent', HOOK_DEFAULTS.compactAtPercent),
        minReductionRatio: optionNumber(options, 'minReductionRatio', HOOK_DEFAULTS.minReductionRatio),
        model: optionString(options, 'model') ?? HOOK_DEFAULTS.model,
    };
    const apiKey = optionString(options, 'apiKey');
    if (apiKey)
        config.apiKey = apiKey;
    const goal = optionString(options, 'goal');
    if (goal)
        config.goal = goal;
    return config;
}
/** A `JevAsker` over the engine's `$.http.fetch`. */
export function jevAsker(fetchFn, apiKey, model) {
    return {
        async ask(state, questions) {
            const request = buildJevRequest({ apiKey, model }, state, questions);
            const response = await fetchFn(request.url, {
                method: request.method,
                headers: request.headers,
                body: request.body,
            });
            return parseJevResponse(response.status, response.ok, response.text);
        },
    };
}
function toolUseSummary(tool) {
    const summary = {
        tool_use_id: tool.tool_use_id,
        tool: tool.tool,
        input: tool.input,
    };
    if (tool.text !== undefined)
        summary.text = tool.text;
    if (tool.isError)
        summary.isError = true;
    return summary;
}
function toolResultSummary(result) {
    return {
        tool_use_id: result.tool_use_id,
        text: result.text,
        isError: result.isError ?? false,
    };
}
/**
 * Maps the library's output back onto session messages. Whatever came back
 * unchanged (a message, a tool use, a tool result) is the engine's own object,
 * handle included; anything rebuilt is a fresh message without a handle, so the
 * engine takes the edited content instead of its original.
 */
export function toSessionMessages(input, output) {
    const messages = new Map();
    const uses = new Map();
    const results = new Map();
    for (const message of input) {
        messages.set(message, message);
        for (const tool of message.toolUses)
            uses.set(tool, tool);
        for (const result of message.toolResults ?? [])
            results.set(result, result);
    }
    return output.map((message) => {
        const own = messages.get(message);
        if (own)
            return own;
        const rebuilt = {
            role: message.role,
            text: message.text,
            toolUses: message.toolUses.map((tool) => uses.get(tool) ?? toolUseSummary(tool)),
        };
        if (message.toolResults && message.toolResults.length > 0) {
            rebuilt.toolResults = message.toolResults.map((result) => results.get(result) ?? toolResultSummary(result));
        }
        return rebuilt;
    });
}
/** Runs the library over a session transcript; throws when the key is missing or Jev fails. */
export async function compactSession(messages, config, fetchFn) {
    if (!config.apiKey)
        throw new Error('TYPESAFE_API_KEY is not configured');
    const result = await compact(messages, jevAsker(fetchFn, config.apiKey, config.model), config);
    return { result, messages: toSessionMessages(messages, result.messages) };
}
function percent(ratio) {
    return `${Math.round(ratio * 100)}%`;
}
export function summarize(result) {
    const { stats } = result;
    const parts = [
        stats.kept > 0 ? `${stats.kept} kept` : '',
        stats.resultsDropped > 0 ? `${stats.resultsDropped} results truncated` : '',
        stats.callsDropped > 0 ? `${stats.callsDropped} call_dropped` : '',
        stats.pinned > 0 ? `${stats.pinned} pinned` : '',
    ].filter(Boolean);
    return `${percent(reductionRatio(result))} reduction; ${parts.join(', ') || 'no tool calls'}; state ~${stats.stateTokens} tokens (${stats.stateStage}) in ${stats.requests} request(s)`;
}
const UI_LOG_MAX_CHARS = 4096;
export function decisionLog(result) {
    return result.decisions
        .filter((d) => d.reason !== 'pinned')
        .map((d) => `${d.id}:${d.tool}:${d.action}/call=${d.keepCall.toFixed(2)}/result=${d.keepResult.toFixed(2)}`)
        .join(' ');
}
export function decisionLogLines(result, maxChars = UI_LOG_MAX_CHARS) {
    const entries = decisionLog(result).split(' ').filter(Boolean);
    if (entries.length === 0)
        return ['decisions: (none)'];
    const chunks = [];
    let current = '';
    for (const entry of entries) {
        const next = current ? `${current} ${entry}` : entry;
        if (current && next.length > maxChars - 24) {
            chunks.push(current);
            current = entry;
        }
        else
            current = next;
    }
    chunks.push(current);
    return chunks.map((chunk, index) => chunks.length === 1
        ? `decisions: ${chunk}`
        : `decisions (${index + 1}/${chunks.length}): ${chunk}`);
}
async function getApiKey($, config) {
    if (config.apiKey)
        return config.apiKey;
    const fromEnv = await $.env.get('TYPESAFE_API_KEY');
    if (fromEnv)
        return fromEnv;
    const settings = await $.settings.read();
    const env = settings['env'];
    if (env && typeof env === 'object') {
        const value = env['TYPESAFE_API_KEY'];
        if (typeof value === 'string' && value)
            return value;
    }
    return undefined;
}
function notify($, text) {
    $.ui.log(text);
    $.ui.toast(text, { timeoutMs: 15_000 });
}
export const register = (on, options) => {
    const configured = resolveHookConfig(options);
    let compacting = false;
    on('session.compact', async ($, event, next) => {
        try {
            const config = { ...configured, apiKey: await getApiKey($, configured) };
            const { result, messages } = await compactSession(event.messages, config, guardedFetch(async (url, init) => {
                const response = await $.http.fetch(url, init);
                return { status: response.status, ok: response.ok, text: response.text };
            }, async () => {
                const secrets = await Promise.all([
                    $.env.get('TYPESAFE_API_KEY'),
                    $.env.get('ANTHROPIC_API_KEY'),
                    $.env.get('ANTHROPIC_AUTH_TOKEN'),
                ]);
                if (typeof config.apiKey === 'string') secrets.push(config.apiKey);
                return secrets.filter(value => typeof value === 'string' && value.length > 0);
            }));
            for (const line of decisionLogLines(result))
                $.ui.log(line);
            if (reductionRatio(result) < config.minReductionRatio) {
                notify($, `fallback to built-in summary (below ${percent(config.minReductionRatio)} minimum: ${summarize(result)})`);
                return next(event);
            }
            notify($, `kept ${messages.length}/${event.messages.length} messages, no summary (${summarize(result)})`);
            return { messages };
        }
        catch (error) {
            notify($, `fallback to built-in summary (${error instanceof Error ? error.message : String(error)})`);
            return next(event);
        }
    });
    on('turn.complete', async ($, event, next) => {
        if (compacting)
            return next(event);
        try {
            const { context } = await $.session.usage();
            if ((context.percent ?? 0) < configured.compactAtPercent)
                return next(event);
            compacting = true;
            await $.session.compact();
        }
        catch (error) {
            $.ui.log(`auto-compact skipped (${error instanceof Error ? error.message : String(error)})`);
        }
        finally {
            compacting = false;
        }
        return next(event);
    });
};
export { resolveOptions };
