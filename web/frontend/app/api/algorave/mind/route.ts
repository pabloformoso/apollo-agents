/** Same-origin authenticated gateway; host credentials never reach the browser. */
import { NextResponse } from "next/server";

const endpoint = `${process.env.APOLLO_API_URL ?? "http://127.0.0.1:4020"}/api/mind/infer`;
async function forward(request: Request) {
  const authorization = request.headers.get("authorization");
  if (!authorization) return NextResponse.json({ error: "Sign in to use Mind", detail: "" }, { status: 401 });
  try {
    const body = request.method === "POST" ? await request.text() : undefined;
    if (body && new TextEncoder().encode(body).length > 256 * 1024) {
      return NextResponse.json({ error: "Mind request is too large", detail: "" }, { status: 400 });
    }
    const response = await fetch(endpoint, {
      method: request.method, headers: { authorization, "content-type": "application/json" },
      body, cache: "no-store", signal: AbortSignal.timeout(request.method === "POST" ? 290000 : 10000),
    });
    const payload = await response.json();
    if (!response.ok && !payload.error) {
      payload.error = typeof payload.detail === "string" ? payload.detail : "Mind request was refused";
      payload.detail = "";
    }
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json({ error: "Mind is unreachable — keep playing your current pattern", detail: "Check Main LLM in Settings for the model and the Mind service." }, { status: 502 });
  }
}
export const GET = forward;
export const POST = forward;
