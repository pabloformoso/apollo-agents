"use client";
/**
 * Where the realm sends the browser back after a login.
 *
 * Three steps, and the page must survive a failure at any of them with
 * something a person can act on — a blank screen after being bounced to
 * an identity provider and back is the worst possible failure here,
 * because the user has no idea which side broke.
 *
 *   1. validate the callback (state, error, code)
 *   2. exchange the code for a realm token (PKCE, no secret)
 *   3. trade that for an Apollo token and store ONLY the Apollo one
 */
import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { keycloakExchange } from "@/lib/api";
import { saveAuth } from "@/lib/auth";
import {
  CALLBACK_PATH,
  clearFlow,
  exchangeCode,
  readCallback,
  readFlow,
  safeReturnTo,
} from "@/lib/oidc";
import { ApolloMark, Btn, Stripe } from "@/components/ember/primitives";

function CallbackInner() {
  const router = useRouter();
  const search = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  // React 18 mounts effects twice in dev StrictMode. An authorization
  // code is single-use, so a second exchange fails and would show an
  // error on a login that actually worked.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    (async () => {
      const flow = readFlow();
      const result = readCallback(
        new URLSearchParams(search.toString()),
        flow.state,
      );

      if (result.kind === "denied") {
        clearFlow();
        setError(
          result.description ||
            `The identity provider refused the sign-in (${result.error}).`,
        );
        return;
      }
      if (result.kind === "state-mismatch") {
        clearFlow();
        setError(
          "This sign-in could not be matched to a request from this tab. " +
            "Start again from the login page.",
        );
        return;
      }
      if (result.kind === "missing-code") {
        clearFlow();
        setError("The identity provider returned no authorization code.");
        return;
      }
      if (!flow.verifier) {
        clearFlow();
        setError(
          "The sign-in started in a different tab or session. Start again.",
        );
        return;
      }

      try {
        const redirectUri = `${window.location.origin}${CALLBACK_PATH}`;
        const tokens = await exchangeCode({
          code: result.code,
          verifier: flow.verifier,
          redirectUri,
        });
        // The ACCESS token, not the id token: realm roles live in
        // `realm_access.roles` there, and roles are what the backend
        // turns into capabilities.
        const res = await keycloakExchange(tokens.access_token);
        saveAuth(res.access_token, res.user);
        clearFlow();
        router.replace(safeReturnTo(flow.returnTo));
      } catch (err) {
        // The verifier is single-use — a retry with the same one cannot
        // succeed, so clear it and make the user start over.
        clearFlow();
        setError((err as Error).message);
      }
    })();
  }, [search, router]);

  if (error) {
    return (
      <div className="max-w-md">
        <p className="font-mono text-[10px] uppercase tracking-mono text-faint mb-3">
          sign-in failed
        </p>
        <p className="text-sm text-ember-text mb-6">{error}</p>
        <Link href="/login">
          <Btn>Back to sign in</Btn>
        </Link>
      </div>
    );
  }

  return (
    <div className="max-w-md">
      <p className="font-mono text-[10px] uppercase tracking-mono text-faint mb-3">
        signing in
      </p>
      <p className="text-sm text-faint">Completing sign-in…</p>
    </div>
  );
}

export default function CallbackPage() {
  return (
    <div className="h-screen overflow-hidden grid grid-cols-1 md:grid-cols-2 bg-ink text-ember-text font-sans">
      <div className="flex flex-col justify-center px-8 md:px-16">
        <ApolloMark />
        {/* useSearchParams needs a Suspense boundary to keep this route
            statically renderable. */}
        <Suspense
          fallback={<p className="text-sm text-faint mt-8">Completing sign-in…</p>}
        >
          <CallbackInner />
        </Suspense>
      </div>
      <Stripe alpha={0.18} className="hidden md:block" />
    </div>
  );
}
