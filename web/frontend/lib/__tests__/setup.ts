import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

function makeStorage(): Storage {
  const store: Record<string, string> = {};
  return {
    get length() { return Object.keys(store).length; },
    clear: () => { for (const k of Object.keys(store)) delete store[k]; },
    getItem: (k: string) => (k in store ? store[k] : null),
    key: (i: number) => Object.keys(store)[i] ?? null,
    removeItem: (k: string) => { delete store[k]; },
    setItem: (k: string, v: string) => { store[k] = String(v); },
  };
}

beforeEach(() => {
  vi.stubGlobal("localStorage", makeStorage());
});

// Testing Library only registers its automatic unmount when it finds a global
// ``afterEach``, and this config runs with ``globals: false`` — so without this
// nothing rendered by a test was ever unmounted. Every ``useLiveSession``
// mounted with a session id kept its 1 s playback-pos ``setInterval`` alive
// after its test, and one firing after happy-dom had been torn down failed the
// run with ``ReferenceError: window is not defined`` (about 1 run in 4, all
// 748 tests green).
afterEach(() => {
  cleanup();
});
