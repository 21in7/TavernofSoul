# Project-local fast-jev-compaction

Usage and boundaries: [docs/compaction.md](../../docs/compaction.md).

The upstream runtime is pinned in `vendor/UPSTREAM.json`; original TypeScript,
compiled JavaScript and the MIT license are kept in `vendor/`.
No npm installation is needed to run this plugin or its offline Node tests.
`hooks/register.js` adapts the upstream compiled entry point with the guarded
transport; `hooks/transport.js` is project code. `.claude-plugin/plugin.json`
pins the default Jev model and provides the upstream compaction options.

```bash
node harness/compaction/tests/compaction.test.mjs
make compaction-demo
make compaction-doctor
make check-compaction-engine
```

`engine-tests/` uses Claude Code's offline test kit and requires its CLI.
The ordinary Python harness runs `tests/` through Node without Claude Code,
credentials or network access. The synthetic transcript in `fixture.mjs`
does not contain real source, conversations, or live model measurements.
