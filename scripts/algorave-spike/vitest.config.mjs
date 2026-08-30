import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

// Why this alias exists (see README "API surprises"):
//   @strudel/core@1.2.6 -> repl.mjs -> `import { SalatRepl } from '@kabelsalat/web'`.
//   @kabelsalat/web@0.4.1 has no "exports" map and its "main" points at
//   dist/index.js, which is an IIFE bundle (`var kabelsalat=function(l){...}`),
//   not CommonJS. Node's ESM loader therefore reports
//   "does not provide an export named 'SalatRepl'" and NOTHING that touches
//   @strudel/core's package root can be imported from Node.
//   dist/index.mjs is the real ESM build and loads fine, so we point at it.
const kabelsalatWebEsm = fileURLToPath(
  new URL('./node_modules/@kabelsalat/web/dist/index.mjs', import.meta.url),
);

// Second API surprise, same family: Node strips a `#!` shebang before parsing a
// module, Vite/esbuild do NOT. `validate.mjs` keeps its shebang (it is chmod +x
// and meant to be runnable), so `import ... from '../validate.mjs'` blew up the
// WHOLE suite with "SyntaxError: Invalid or unexpected token" pointed at the
// import line — a diagnosis that names neither the shebang nor the file that
// carries it. Commenting the line out at transform time keeps the byte count
// per line intact (no source map needed) and leaves the file on disk exactly as
// committed: this is a test-harness fix, not a change to the validator.
const stripShebang = {
  name: 'apollo-strip-shebang',
  enforce: 'pre',
  transform(code, id) {
    if (!id.endsWith('.mjs') || !code.startsWith('#!')) return null;
    return { code: `//${code.slice(2)}`, map: null };
  },
};

export default defineConfig({
  plugins: [stripShebang],
  resolve: {
    alias: [{ find: /^@kabelsalat\/web$/, replacement: kabelsalatWebEsm }],
  },
  test: {
    environment: 'node',
    include: ['test/**/*.test.mjs'],
    // Vitest externalises node_modules by default, which hands resolution back to
    // Node's own ESM loader and silently bypasses `resolve.alias`. Inlining the
    // @strudel/* graph keeps it inside Vite's pipeline so the alias above applies.
    server: { deps: { inline: [/@strudel\//, /@kabelsalat\//] } },
    // The pattern tests are pure math; the WAV test reads one file. Neither is slow,
    // but the first import of @strudel/mini pays for a 115 KB PEG parser.
    testTimeout: 20_000,
  },
});
