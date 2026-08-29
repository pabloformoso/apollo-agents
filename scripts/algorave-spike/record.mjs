/*
 * Drives the spike page with Playwright and writes output/algorave/deephouse-30s.wav.
 *
 *   node record.mjs                 # route B (offline render), the default
 *   node record.mjs --route a       # route A (MediaRecorder tap, real time)
 *   node record.mjs --headed        # watch it happen
 *   node record.mjs --out path.wav
 *
 * Route B is the default because @strudel/webaudio 1.3.0 turned out to ship a
 * real offline renderer (renderPatternAudio -> OfflineAudioContext). It is
 * faster than real time and lossless, which is exactly what the plan's §3
 * "route B probe" was hoping for. Route A stays implemented and reachable: it is
 * the one that will still work when the audio comes from somewhere the offline
 * renderer cannot reach (a live /live page, an OBS-shaped graph).
 *
 * Uses playwright-core plus an explicit executablePath into the chromium already
 * on this box, so nothing is downloaded.
 */
import { execFile } from 'node:child_process';
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { existsSync, readdirSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright-core';

import { startSpikeServer } from './serve.mjs';
import { parseWav, summarise, windowRms } from './wav.mjs';

const execFileAsync = promisify(execFile);
const HERE = fileURLToPath(new URL('.', import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..');
const DEFAULT_OUT = join(REPO_ROOT, 'output', 'algorave', 'deephouse-30s.wav');
const BASE64_CHUNK = 4 << 20; // 4 MiB of base64 per round trip

// ---------------------------------------------------------------------------
// args
// ---------------------------------------------------------------------------
function parseArgs(argv) {
  const args = { route: 'b', out: DEFAULT_OUT, headed: false, seconds: 32, keepIntermediate: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--route') args.route = String(argv[++i]).toLowerCase();
    else if (a === '--out') args.out = resolve(argv[++i]);
    else if (a === '--seconds') args.seconds = Number(argv[++i]);
    else if (a === '--headed') args.headed = true;
    else if (a === '--keep-intermediate') args.keepIntermediate = true;
    else if (a === '--help' || a === '-h') args.help = true;
    else throw new Error(`unknown argument: ${a}`);
  }
  if (!['a', 'b'].includes(args.route)) throw new Error(`--route must be a or b, got ${args.route}`);
  return args;
}

// ---------------------------------------------------------------------------
// chromium discovery — never download, always reuse what is installed
// ---------------------------------------------------------------------------
export function findChromium() {
  if (process.env.SPIKE_CHROMIUM && existsSync(process.env.SPIKE_CHROMIUM)) {
    return process.env.SPIKE_CHROMIUM;
  }
  const root =
    process.env.PLAYWRIGHT_BROWSERS_PATH ||
    (process.platform === 'win32'
      ? join(process.env.LOCALAPPDATA ?? join(homedir(), 'AppData', 'Local'), 'ms-playwright')
      : process.platform === 'darwin'
        ? join(homedir(), 'Library', 'Caches', 'ms-playwright')
        : join(homedir(), '.cache', 'ms-playwright'));

  const relatives =
    process.platform === 'win32'
      ? ['chrome-win64/chrome.exe', 'chrome-win/chrome.exe']
      : process.platform === 'darwin'
        ? ['chrome-mac/Chromium.app/Contents/MacOS/Chromium']
        : ['chrome-linux/chrome'];

  let best = null;
  try {
    for (const entry of readdirSync(root)) {
      const build = /^chromium-(\d+)$/.exec(entry);
      if (!build) continue;
      for (const rel of relatives) {
        const exe = join(root, entry, ...rel.split('/'));
        if (existsSync(exe) && (!best || Number(build[1]) > best.revision)) {
          best = { revision: Number(build[1]), path: exe };
        }
      }
    }
  } catch {
    /* fall through to playwright's own resolution */
  }
  return best?.path ?? null;
}

// ---------------------------------------------------------------------------
// capture
// ---------------------------------------------------------------------------
async function capture({ route, headed, seconds }) {
  const { server, url } = await startSpikeServer(0); // ephemeral port; 4031 may be taken by `npm run serve`
  const executablePath = findChromium();
  console.log(`  server        ${url}`);
  console.log(`  chromium      ${executablePath ?? '(playwright default)'}`);

  const browser = await chromium.launch({
    headless: !headed,
    ...(executablePath ? { executablePath } : {}),
    args: [
      // Without this the AudioContext stays suspended in headless and route A
      // records 32 s of digital silence.
      '--autoplay-policy=no-user-gesture-required',
      // Fine for both routes: route A taps the graph, not the device.
      '--mute-audio',
      '--disable-features=AudioServiceOutOfProcess',
    ],
  });

  try {
    const page = await browser.newPage();
    const consoleErrors = [];
    page.on('console', (msg) => {
      const text = msg.text();
      if (msg.type() === 'error') consoleErrors.push(text);
      if (text.startsWith('[spike]') || msg.type() === 'error') console.log(`  page> ${text}`);
    });
    page.on('pageerror', (err) => consoleErrors.push(String(err)));

    await page.goto(url, { waitUntil: 'load' });
    await page.waitForFunction(() => typeof window.__spike === 'object', null, { timeout: 30_000 });
    // A real mousedown, because initStrudel arms initAudioOnFirstClick.
    await page.mouse.click(5, 5);

    // page.evaluate has no timeout of its own, which is what route A needs:
    // it blocks for the whole real-time capture.
    const started = Date.now();
    const meta = await page.evaluate(
      ([r, ms]) => window.__spike.run(r, { ms }),
      [route, Math.round(seconds * 1000)],
    );
    console.log(`  captured      ${meta.container}, ${(meta.bytes / 1024 / 1024).toFixed(2)} MiB in ${((Date.now() - started) / 1000).toFixed(1)} s`);

    const parts = [];
    for (let offset = 0; offset < meta.base64Length; offset += BASE64_CHUNK) {
      parts.push(
        await page.evaluate(([o, n]) => window.__spike.slice(o, n), [offset, BASE64_CHUNK]),
      );
    }
    const pageErrors = await page.evaluate(() => window.__spike.errors);
    if (pageErrors.length) console.warn(`  page errors   ${pageErrors.join(' | ')}`);

    const buffer = Buffer.from(parts.join(''), 'base64');
    if (buffer.length !== meta.bytes) {
      throw new Error(`base64 transfer lost data: got ${buffer.length} of ${meta.bytes} bytes`);
    }
    return { buffer, container: meta.container, consoleErrors };
  } finally {
    await browser.close();
    await new Promise((r) => server.close(r));
  }
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------
const USAGE = `record.mjs — capture the algorave spike to a 48 kHz stereo WAV

  --route a|b        a = MediaRecorder tap (real time, opus), b = offline render (default)
  --out <path>       default ${DEFAULT_OUT}
  --seconds <n>      route A capture length, default 32
  --headed           run chromium visibly
  --keep-intermediate  keep the pre-ffmpeg file next to the output
`;

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(USAGE);
    return;
  }

  console.log(`algorave spike — recording route ${args.route.toUpperCase()}`);
  const { buffer, container } = await capture(args);

  await mkdir(dirname(args.out), { recursive: true });
  const intermediate = args.keepIntermediate
    ? `${args.out}.raw.${container}`
    : join(tmpdir(), `algorave-spike-${process.pid}.${container}`);
  await writeFile(intermediate, buffer);

  // Always through ffmpeg, even for route B: it is what guarantees the
  // deliverable's contract (48 kHz, 2 ch, s16) no matter what the page produced.
  console.log('  ffmpeg        -> 48 kHz stereo pcm_s16le');
  await execFileAsync('ffmpeg', [
    '-hide_banner', '-loglevel', 'error', '-y',
    '-i', intermediate,
    '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le',
    args.out,
  ]);
  if (!args.keepIntermediate) await rm(intermediate, { force: true });

  const wav = parseWav(await readFile(args.out));
  const s = summarise(wav);
  const windows = windowRms(wav, 5);
  const quietest = windows.reduce((a, b) => (b.rms < a.rms ? b : a), windows[0]);

  console.log(`\nwrote ${args.out}`);
  console.log(`  duration      ${s.duration.toFixed(3)} s`);
  console.log(`  sample rate   ${s.sampleRate} Hz`);
  console.log(`  channels      ${s.channels}${s.trueStereo ? ' (true stereo)' : ' (dual mono)'}`);
  console.log(`  bit depth     ${s.bitDepth}`);
  console.log(`  RMS           ${s.rms.toFixed(5)}  (${s.dbfsRms.toFixed(2)} dBFS)`);
  console.log(`  peak          ${s.peak.toFixed(5)}  (${s.dbfsPeak.toFixed(2)} dBFS)`);
  console.log(`  quietest 5 s  ${quietest.rms.toFixed(5)} at ${quietest.start.toFixed(1)} s`);

  const problems = [];
  if (s.duration < 30) problems.push(`duration ${s.duration.toFixed(2)} s < 30 s`);
  if (s.sampleRate !== 48_000) problems.push(`sample rate ${s.sampleRate} != 48000`);
  if (s.channels !== 2) problems.push(`channels ${s.channels} != 2`);
  if (s.rms <= 0.02) problems.push(`RMS ${s.rms.toFixed(5)} <= 0.02 (too quiet)`);
  if (s.peak >= 0.99) problems.push(`peak ${s.peak.toFixed(5)} >= 0.99 (clipping)`);
  if (quietest.rms <= 0.005) problems.push(`silent window at ${quietest.start.toFixed(1)} s`);
  if (problems.length) {
    console.error(`\nFAILED the §5.2 recording smoke:\n  - ${problems.join('\n  - ')}`);
    process.exitCode = 1;
  } else {
    console.log('\nOK — meets the §5.2 recording smoke (>=30 s, 48 kHz stereo, audible, no clipping)');
  }
}

// Guarded so findChromium/capture can be imported (by a test, or by whatever
// drives this once it moves into the product) without kicking off a recording.
const invokedDirectly =
  process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1]);
if (invokedDirectly) await main();
