/**
 * OIDC Authorization Code + PKCE — the parts where a mistake is a breach.
 *
 * `apollo-web` is a public client: it ships no secret, because anything
 * in a browser is not a secret. PKCE is what replaces one, so a weak
 * verifier, a `plain` challenge, or a `state` that is not actually
 * compared each quietly reduce the flow to "anyone who sees the code
 * wins" — while still logging the user in, which is why none of it is
 * visible without tests.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

import {
  buildAuthorizeUrl,
  challengeFor,
  createState,
  createVerifier,
  readCallback,
  safeReturnTo,
} from "../lib/oidc";

describe("PKCE verifier", () => {
  it("is within RFC 7636's 43..128 characters", () => {
    const v = createVerifier();
    expect(v.length).toBeGreaterThanOrEqual(43);
    expect(v.length).toBeLessThanOrEqual(128);
  });

  it("is base64url — no +, / or = to be mangled in a URL", () => {
    expect(createVerifier()).toMatch(/^[A-Za-z0-9\-_]+$/);
  });

  it("does not repeat", () => {
    const seen = new Set(Array.from({ length: 200 }, () => createVerifier()));
    expect(seen.size).toBe(200);
  });

  it("comes from the CSPRNG, not Math.random", () => {
    // A guessable verifier defeats the whole mechanism, and the two APIs
    // are one careless edit apart.
    const spy = vi.spyOn(crypto, "getRandomValues");
    const rand = vi.spyOn(Math, "random");
    createVerifier();
    expect(spy).toHaveBeenCalled();
    expect(rand).not.toHaveBeenCalled();
    spy.mockRestore();
    rand.mockRestore();
  });

  it("state is generated the same way", () => {
    expect(createState()).toMatch(/^[A-Za-z0-9\-_]+$/);
    expect(createState()).not.toBe(createState());
  });
});

describe("S256 challenge", () => {
  it("matches the RFC 7636 appendix B test vector", async () => {
    // The one published verifier/challenge pair — proves this is a real
    // SHA-256 of the ASCII verifier, base64url, and not some other digest.
    const verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk";
    expect(await challengeFor(verifier)).toBe(
      "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
    );
  });

  it("differs from the verifier — sending the verifier would be pointless", async () => {
    const v = createVerifier();
    expect(await challengeFor(v)).not.toBe(v);
  });
});

describe("authorize URL", () => {
  // ISSUER and CLIENT_ID are read at module load, so the module is
  // imported fresh with them stubbed. That also covers the reading
  // itself: a build with no realm configured must not produce a URL
  // that looks valid.
  const ISS = "https://keycloak.example.com/realms/apollo";
  const base = {
    challenge: "chal",
    state: "st",
    redirectUri: "https://apollo.example.com/auth/callback",
  };

  async function authorizeUrl() {
    vi.stubEnv("NEXT_PUBLIC_KEYCLOAK_ISSUER", ISS);
    vi.stubEnv("NEXT_PUBLIC_KEYCLOAK_CLIENT_ID", "apollo-web");
    vi.resetModules();
    const mod = await import("../lib/oidc");
    return new URL(mod.buildAuthorizeUrl(base));
  }

  beforeEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("points at the realm's authorization endpoint", async () => {
    const url = await authorizeUrl();
    expect(url.origin + url.pathname).toBe(
      `${ISS}/protocol/openid-connect/auth`,
    );
  });

  it("always asks for S256 — 'plain' is no protection at all", async () => {
    const url = await authorizeUrl();
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("code_challenge")).toBe("chal");
  });

  it("carries state, redirect_uri and the authorization_code response type", async () => {
    const url = await authorizeUrl();
    expect(url.searchParams.get("state")).toBe("st");
    expect(url.searchParams.get("response_type")).toBe("code");
    expect(url.searchParams.get("redirect_uri")).toBe(base.redirectUri);
  });

  it("names the client and never a secret — this is a public client", async () => {
    const url = await authorizeUrl();
    expect(url.searchParams.get("client_id")).toBe("apollo-web");
    expect(url.searchParams.get("client_secret")).toBeNull();
  });

  it("requests the openid scope, or it is not OIDC", async () => {
    const url = await authorizeUrl();
    expect(url.searchParams.get("scope")?.split(" ")).toContain("openid");
  });

  it("reports itself unconfigured when no realm is set", async () => {
    vi.resetModules();
    const mod = await import("../lib/oidc");
    expect(mod.isConfigured()).toBe(false);
  });
});

describe("reading the callback", () => {
  it("accepts a code when the state matches", () => {
    const r = readCallback(new URLSearchParams("code=abc&state=xyz"), "xyz");
    expect(r).toEqual({ kind: "code", code: "abc" });
  });

  it("refuses a mismatched state", () => {
    const r = readCallback(new URLSearchParams("code=abc&state=other"), "xyz");
    expect(r.kind).toBe("state-mismatch");
  });

  it("refuses a callback with NO state — that is what a forgery looks like", () => {
    expect(readCallback(new URLSearchParams("code=abc"), "xyz").kind).toBe(
      "state-mismatch",
    );
  });

  it("refuses when this tab never started a flow", () => {
    // Otherwise a link someone sends you logs you into their account.
    expect(readCallback(new URLSearchParams("code=abc&state=x"), null).kind).toBe(
      "state-mismatch",
    );
  });

  it("surfaces a refusal from the provider, with its description", () => {
    const r = readCallback(
      new URLSearchParams("error=access_denied&error_description=Nope"),
      "xyz",
    );
    expect(r).toEqual({ kind: "denied", error: "access_denied", description: "Nope" });
  });

  it("reports a provider error even when the state does not match", () => {
    // The error is the useful thing to show; a mismatch on top of it
    // would just hide why the provider said no.
    expect(
      readCallback(new URLSearchParams("error=access_denied"), "xyz").kind,
    ).toBe("denied");
  });

  it("reports a matching state that carries no code", () => {
    expect(readCallback(new URLSearchParams("state=xyz"), "xyz").kind).toBe(
      "missing-code",
    );
  });
});

describe("post-login destination", () => {
  it("keeps a same-origin path", () => {
    expect(safeReturnTo("/catalog")).toBe("/catalog");
  });

  it.each([
    "https://evil.example.com",
    "//evil.example.com",
    "http://evil.example.com/x",
  ])("refuses %s — an open redirect after a real login", (raw) => {
    expect(safeReturnTo(raw)).toBe("/dashboard");
  });

  it("falls back for empty or missing", () => {
    expect(safeReturnTo(null)).toBe("/dashboard");
    expect(safeReturnTo("")).toBe("/dashboard");
  });
});
