/**
 * OIDC Authorization Code + PKCE against the Keycloak realm.
 *
 * `apollo-web` is a PUBLIC client: it holds no secret, because anything
 * shipped to a browser is not a secret. PKCE is what replaces one — the
 * verifier never leaves this device, so an authorization code stolen in
 * transit (a redirect through a malicious extension, a shoulder-surfed
 * URL, a shared history) cannot be redeemed by anyone else.
 *
 * The realm token stops here. It is exchanged once at
 * `POST /api/auth/keycloak` for an Apollo token, and only that one is
 * stored. The reason is concrete: Apollo puts its token in the QUERY
 * STRING for audio, covers and the live WebSocket, because `<audio>`,
 * `<img>` and `WebSocket` cannot set an Authorization header — and a
 * realm access token in a URL lands in browser history, proxy logs and
 * nginx access logs, where it is the key to every other client in the
 * realm. Apollo's token is useless anywhere but Apollo.
 *
 * Everything here is pure or storage-only so the security-relevant parts
 * — verifier entropy, state comparison, callback validation — are unit
 * testable without a browser or a realm.
 */

/** Realm base, e.g. https://keycloak.example.com/realms/apollo */
export const ISSUER = (process.env.NEXT_PUBLIC_KEYCLOAK_ISSUER ?? "").replace(
  /\/+$/,
  "",
);

export const CLIENT_ID = process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID ?? "";

/** Where the realm sends the browser back. Must be registered on the client. */
export const CALLBACK_PATH = "/auth/callback";

const VERIFIER_KEY = "apollo_pkce_verifier";
const STATE_KEY = "apollo_oidc_state";
const RETURN_KEY = "apollo_oidc_return_to";

/** Whether this build was pointed at a realm. */
export function isConfigured(): boolean {
  return Boolean(ISSUER && CLIENT_ID);
}

export function authorizationEndpoint(): string {
  return `${ISSUER}/protocol/openid-connect/auth`;
}

export function tokenEndpoint(): string {
  return `${ISSUER}/protocol/openid-connect/token`;
}

export function endSessionEndpoint(): string {
  return `${ISSUER}/protocol/openid-connect/logout`;
}

function base64UrlEncode(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * A fresh PKCE verifier.
 *
 * 32 random bytes, base64url — 43 characters, inside RFC 7636's 43..128
 * and 256 bits of entropy. Uses `crypto.getRandomValues`; `Math.random`
 * is not a CSPRNG and a guessable verifier defeats the entire mechanism.
 */
export function createVerifier(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes);
}

/** Opaque CSRF value tying a callback to the request that started it. */
export function createState(): string {
  return createVerifier();
}

/** S256 challenge for a verifier. `plain` is never used — it is no protection. */
export async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(verifier),
  );
  return base64UrlEncode(new Uint8Array(digest));
}

/**
 * Build the authorization URL.
 *
 * Pure so a test can assert the exact parameters — a missing
 * `code_challenge` or a `plain` method downgrades the flow silently, and
 * the browser would still log in.
 */
export function buildAuthorizeUrl(opts: {
  challenge: string;
  state: string;
  redirectUri: string;
}): string {
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    response_type: "code",
    scope: "openid profile email",
    redirect_uri: opts.redirectUri,
    state: opts.state,
    code_challenge: opts.challenge,
    code_challenge_method: "S256",
  });
  return `${authorizationEndpoint()}?${params.toString()}`;
}

/**
 * What a callback URL means.
 *
 * Returns a discriminated result rather than throwing, so the callback
 * page renders an explanation instead of a stack trace. A `state`
 * mismatch is reported as its own kind: it is the signature of a forged
 * or replayed callback, not of a user who mistyped a password.
 */
export type CallbackResult =
  | { kind: "code"; code: string }
  | { kind: "denied"; error: string; description: string | null }
  | { kind: "state-mismatch" }
  | { kind: "missing-code" };

export function readCallback(
  search: URLSearchParams,
  expectedState: string | null,
): CallbackResult {
  const error = search.get("error");
  if (error) {
    return {
      kind: "denied",
      error,
      description: search.get("error_description"),
    };
  }
  const state = search.get("state");
  // Compared even when the realm sent no state: a callback that omits it
  // is exactly what a forged one looks like.
  if (!expectedState || state !== expectedState) {
    return { kind: "state-mismatch" };
  }
  const code = search.get("code");
  if (!code) return { kind: "missing-code" };
  return { kind: "code", code };
}

/**
 * Exchange an authorization code for realm tokens.
 *
 * Public client, so this is a browser-side POST with no secret. The
 * verifier is what proves the caller is the one that started the flow.
 */
export async function exchangeCode(opts: {
  code: string;
  verifier: string;
  redirectUri: string;
}): Promise<{ access_token: string; id_token?: string }> {
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: CLIENT_ID,
    code: opts.code,
    redirect_uri: opts.redirectUri,
    code_verifier: opts.verifier,
  });
  const res = await fetch(tokenEndpoint(), {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(
      `Identity provider refused the code exchange (${res.status}). ${detail.slice(0, 200)}`,
    );
  }
  return res.json();
}

// --- transient flow state -------------------------------------------------
//
// sessionStorage, not localStorage: this is per-tab and dies with the tab.
// A verifier surviving in localStorage after an abandoned login is a
// live credential sitting on disk for no reason.

export function stashFlow(verifier: string, state: string, returnTo: string): void {
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(STATE_KEY, state);
  sessionStorage.setItem(RETURN_KEY, returnTo);
}

export function readFlow(): {
  verifier: string | null;
  state: string | null;
  returnTo: string;
} {
  return {
    verifier: sessionStorage.getItem(VERIFIER_KEY),
    state: sessionStorage.getItem(STATE_KEY),
    returnTo: sessionStorage.getItem(RETURN_KEY) || "/dashboard",
  };
}

/** Clear the flow. Called on success AND on every failure — a verifier is single-use. */
export function clearFlow(): void {
  sessionStorage.removeItem(VERIFIER_KEY);
  sessionStorage.removeItem(STATE_KEY);
  sessionStorage.removeItem(RETURN_KEY);
}

/**
 * Only same-origin paths are accepted as a post-login destination.
 *
 * `returnTo` reaches us from a query parameter, so an absolute URL here
 * is an open redirect: log in legitimately, land on someone else's page.
 */
export function safeReturnTo(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return "/dashboard";
  return raw;
}
