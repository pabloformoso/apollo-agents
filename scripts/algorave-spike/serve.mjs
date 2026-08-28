/*
 * Dependency-free static server for the algorave spike.
 *
 * Port 4031 on purpose: 4010/4020 are the running prod stack and 4011/4021 are
 * the dev pair (see CLAUDE.md "Deploy & operations"). Nothing here may collide
 * with a live session.
 *
 *   node serve.mjs            -> http://127.0.0.1:4031
 *   PORT=4032 node serve.mjs
 */
import { createServer } from 'node:http';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { extname, join, normalize, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

export const DEFAULT_PORT = 4031;
const ROOT = fileURLToPath(new URL('.', import.meta.url));

// The browser gets the prebuilt @strudel/web bundle straight out of node_modules.
// It carries core+mini+tonal+webaudio+transpiler in one file, which is what lets
// the import map below hand the page and the pattern module the SAME instance of
// the engine (two copies of @strudel/core would mean two Pattern classes).
const MOUNTS = [
  ['/vendor/strudel/', join(ROOT, 'node_modules', '@strudel', 'web', 'dist')],
  // So the page can read the engine version off the installed package instead of
  // hardcoding a number that would quietly drift from package.json.
  ['/vendor/strudel-pkg/', join(ROOT, 'node_modules', '@strudel', 'web')],
  ['/patterns/', join(ROOT, 'patterns')],
];

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.wasm': 'application/wasm',
  '.svg': 'image/svg+xml',
  '.wav': 'audio/wav',
};

/** Maps a URL path to a file on disk, or null if it escapes every mount. */
export function resolvePath(urlPath) {
  const clean = decodeURIComponent(urlPath.split('?')[0]);
  if (clean === '/' || clean === '/index.html') return join(ROOT, 'index.html');
  for (const [prefix, dir] of MOUNTS) {
    if (!clean.startsWith(prefix)) continue;
    const rel = normalize(clean.slice(prefix.length)).replace(/^([/\\]|\.\.[/\\])+/, '');
    const full = join(dir, rel);
    // normalize() above still lets `a/../../b` through on some inputs; verify.
    if (full !== dir && !full.startsWith(dir + sep)) return null;
    return full;
  }
  return null;
}

export function createSpikeServer() {
  return createServer(async (req, res) => {
    const file = resolvePath(req.url ?? '/');
    if (!file) {
      res.writeHead(404, { 'content-type': 'text/plain' });
      res.end('not found');
      return;
    }
    try {
      const info = await stat(file);
      if (!info.isFile()) throw new Error('not a file');
      res.writeHead(200, {
        'content-type': MIME[extname(file).toLowerCase()] ?? 'application/octet-stream',
        'content-length': info.size,
        'cache-control': 'no-store',
      });
      createReadStream(file).pipe(res);
    } catch {
      res.writeHead(404, { 'content-type': 'text/plain' });
      res.end(`not found: ${req.url}`);
    }
  });
}

/** Starts the server and resolves with { server, port, url }. */
export function startSpikeServer(port = Number(process.env.PORT) || DEFAULT_PORT) {
  return new Promise((resolve, reject) => {
    const server = createSpikeServer();
    server.once('error', reject);
    server.listen(port, '127.0.0.1', () => {
      const actual = server.address().port;
      resolve({ server, port: actual, url: `http://127.0.0.1:${actual}/` });
    });
  });
}

// Only run standalone when invoked directly, so record.mjs can import and reuse it.
const invokedDirectly =
  process.argv[1] && fileURLToPath(import.meta.url) === normalize(process.argv[1]);
if (invokedDirectly) {
  const { url } = await startSpikeServer();
  console.log(`algorave spike on ${url}`);
  console.log('  Play / Record 32 s / Render offline are on the page.');
}
