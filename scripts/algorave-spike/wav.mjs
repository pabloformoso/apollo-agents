/*
 * A very small RIFF/WAVE reader — no dependencies.
 *
 * Shared by record.mjs (which prints the metrics after a capture) and
 * test/wav.test.mjs (which asserts them), so the numbers in the report and the
 * numbers in the test come from exactly the same code.
 *
 * Handles the two formats anything in this pipeline can emit: PCM s16 (format 1)
 * and IEEE float32 (format 3).
 */

const FORMAT_PCM = 1;
const FORMAT_FLOAT = 3;
const FORMAT_EXTENSIBLE = 0xfffe;

/**
 * @param {Buffer|Uint8Array} bytes raw file contents
 * @returns {{sampleRate:number, channels:number, bitDepth:number, frames:number,
 *            duration:number, channelData:Float32Array[]}}
 */
export function parseWav(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const tag = (offset) => String.fromCharCode(...bytes.subarray(offset, offset + 4));

  if (tag(0) !== 'RIFF' || tag(8) !== 'WAVE') throw new Error('not a RIFF/WAVE file');

  let fmt = null;
  let data = null;
  let cursor = 12;
  while (cursor + 8 <= bytes.length) {
    const id = tag(cursor);
    const size = view.getUint32(cursor + 4, true);
    const body = cursor + 8;
    if (id === 'fmt ') {
      fmt = {
        format: view.getUint16(body, true),
        channels: view.getUint16(body + 2, true),
        sampleRate: view.getUint32(body + 4, true),
        blockAlign: view.getUint16(body + 12, true),
        bitDepth: view.getUint16(body + 14, true),
      };
      if (fmt.format === FORMAT_EXTENSIBLE && size >= 40) {
        fmt.format = view.getUint16(body + 24, true); // first 2 bytes of the sub-format GUID
      }
    } else if (id === 'data') {
      data = { start: body, size: Math.min(size, bytes.length - body) };
    }
    cursor = body + size + (size % 2); // chunks are word-aligned
  }
  if (!fmt) throw new Error('no fmt chunk');
  if (!data) throw new Error('no data chunk');

  const { channels, bitDepth, sampleRate, format } = fmt;
  const bytesPerSample = bitDepth / 8;
  const frames = Math.floor(data.size / (bytesPerSample * channels));
  const channelData = Array.from({ length: channels }, () => new Float32Array(frames));

  for (let frame = 0; frame < frames; frame++) {
    const base = data.start + frame * bytesPerSample * channels;
    for (let ch = 0; ch < channels; ch++) {
      const at = base + ch * bytesPerSample;
      let sample;
      if (format === FORMAT_FLOAT && bitDepth === 32) sample = view.getFloat32(at, true);
      else if (format === FORMAT_PCM && bitDepth === 16) sample = view.getInt16(at, true) / 0x8000;
      else if (format === FORMAT_PCM && bitDepth === 24) {
        const raw = view.getUint8(at) | (view.getUint8(at + 1) << 8) | (view.getInt8(at + 2) << 16);
        sample = raw / 0x800000;
      } else if (format === FORMAT_PCM && bitDepth === 32) sample = view.getInt32(at, true) / 0x80000000;
      else if (format === FORMAT_PCM && bitDepth === 8) sample = view.getUint8(at) / 128 - 1;
      else throw new Error(`unsupported WAV encoding: format ${format}, ${bitDepth}-bit`);
      channelData[ch][frame] = sample;
    }
  }

  return { sampleRate, channels, bitDepth, format, frames, duration: frames / sampleRate, channelData };
}

/** Peak absolute sample and RMS across all channels. */
export function levels(wav) {
  let peak = 0;
  let sumSquares = 0;
  let count = 0;
  for (const channel of wav.channelData) {
    for (let i = 0; i < channel.length; i++) {
      const v = channel[i];
      const a = v < 0 ? -v : v;
      if (a > peak) peak = a;
      sumSquares += v * v;
      count++;
    }
  }
  return { peak, rms: count ? Math.sqrt(sumSquares / count) : 0 };
}

/** RMS of each fixed-length window, used to prove nothing went silent mid-take. */
export function windowRms(wav, windowSeconds = 5) {
  const size = Math.floor(wav.sampleRate * windowSeconds);
  const out = [];
  for (let start = 0; start + size <= wav.frames; start += size) {
    let sumSquares = 0;
    let count = 0;
    for (const channel of wav.channelData) {
      for (let i = start; i < start + size; i++) {
        sumSquares += channel[i] * channel[i];
        count++;
      }
    }
    out.push({ start: start / wav.sampleRate, rms: Math.sqrt(sumSquares / count) });
  }
  return out;
}

/**
 * RMS of a slice, optionally through a one-pole high-pass first.
 *
 * Broadband RMS is a poor witness for an arrangement: the kick is so dominant
 * that adding a clap and a chord stab barely moves it. Above ~1.5 kHz the kick
 * and the bass are gone, so what is left is exactly the material the section map
 * adds and takes away.
 *
 * @param {number} highpassHz 0 disables filtering
 */
export function sliceRms(wav, fromSecond, toSecond, highpassHz = 0) {
  const from = Math.max(0, Math.floor(fromSecond * wav.sampleRate));
  const to = Math.min(wav.frames, Math.floor(toSecond * wav.sampleRate));
  if (to <= from) throw new Error(`empty slice ${fromSecond}..${toSecond}s`);

  const dt = 1 / wav.sampleRate;
  const rc = highpassHz > 0 ? 1 / (2 * Math.PI * highpassHz) : 0;
  const alpha = highpassHz > 0 ? rc / (rc + dt) : 1;

  let sumSquares = 0;
  let count = 0;
  for (const channel of wav.channelData) {
    let previousIn = channel[from];
    let previousOut = 0;
    for (let i = from; i < to; i++) {
      const x = channel[i];
      const y = highpassHz > 0 ? alpha * (previousOut + x - previousIn) : x;
      previousIn = x;
      previousOut = y;
      sumSquares += y * y;
      count++;
    }
  }
  return Math.sqrt(sumSquares / count);
}

/** True when the two channels are not bit-identical (i.e. real stereo content). */
export function isTrueStereo(wav) {
  if (wav.channels < 2) return false;
  const [l, r] = wav.channelData;
  for (let i = 0; i < wav.frames; i++) if (l[i] !== r[i]) return true;
  return false;
}

export function summarise(wav) {
  const { peak, rms } = levels(wav);
  return {
    duration: wav.duration,
    sampleRate: wav.sampleRate,
    channels: wav.channels,
    bitDepth: wav.bitDepth,
    frames: wav.frames,
    peak,
    rms,
    dbfsPeak: peak > 0 ? 20 * Math.log10(peak) : -Infinity,
    dbfsRms: rms > 0 ? 20 * Math.log10(rms) : -Infinity,
    trueStereo: isTrueStereo(wav),
  };
}
