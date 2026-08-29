/*
 * serve.mjs tests — the static server's path mapping, added with the palette
 * registry (plan §10): `/palette.json` is served from the spike root so the
 * pages can fetch the same file validate.mjs gates against, WITHOUT mounting
 * the rest of the root (validate.mjs, wav.mjs and friends stay unreachable).
 *
 * Two layers, like test/validate.test.mjs: pure `resolvePath` unit tests, and
 * one real HTTP round-trip on an ephemeral port proving the registry actually
 * arrives as JSON with the fields the pages read.
 */
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { resolvePath, startSpikeServer } from '../serve.mjs';

const SPIKE_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');

describe('resolvePath', () => {
  it('serves the root page and the registry by exact path', () => {
    expect(resolvePath('/')).toBe(join(SPIKE_DIR, 'index.html'));
    expect(resolvePath('/index.html')).toBe(join(SPIKE_DIR, 'index.html'));
    expect(resolvePath('/palette.json')).toBe(join(SPIKE_DIR, 'palette.json'));
    expect(resolvePath('/palette.json?cachebust=1')).toBe(join(SPIKE_DIR, 'palette.json'));
  });

  it('the registry special-case does not open the rest of the spike root', () => {
    // Only palette.json is root-served; its siblings stay unmounted.
    expect(resolvePath('/validate.mjs')).toBeNull();
    expect(resolvePath('/serve.mjs')).toBeNull();
    expect(resolvePath('/package.json')).toBeNull();
    expect(resolvePath('/palette.json.bak')).toBeNull();
  });

  it('mounted prefixes still resolve, and traversal still cannot escape them', () => {
    expect(resolvePath('/patterns/playground.html')).toBe(
      join(SPIKE_DIR, 'patterns', 'playground.html'),
    );
    const escaped = resolvePath('/patterns/../validate.mjs');
    expect(escaped === null || escaped.startsWith(join(SPIKE_DIR, 'patterns'))).toBe(true);
  });
});

describe('GET /palette.json (real server, ephemeral port)', () => {
  it('returns the committed registry as JSON with the fields the pages read', async () => {
    const { server, url } = await startSpikeServer(0);
    try {
      const res = await fetch(new URL('/palette.json', url));
      expect(res.status).toBe(200);
      expect(res.headers.get('content-type')).toContain('application/json');
      const registry = await res.json();
      expect(Array.isArray(registry.sources)).toBe(true);
      expect(registry.sources.length).toBeGreaterThan(0);
      // Byte-for-byte the committed file — the server must not transform it.
      const committed = JSON.parse(readFileSync(join(SPIKE_DIR, 'palette.json'), 'utf8'));
      expect(registry).toEqual(committed);
    } finally {
      server.close();
    }
  });
});
