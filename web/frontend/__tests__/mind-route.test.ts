import { afterEach, expect, it, vi } from "vitest";
import { GET, POST } from "@/app/api/algorave/mind/route";

afterEach(() => vi.unstubAllGlobals());
it("refuses unauthenticated requests without contacting Mind", async () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  expect((await GET(new Request("http://localhost/api/algorave/mind"))).status).toBe(401);
  expect(fetcher).not.toHaveBeenCalled();
});
it("forwards auth and preserves actionable backend refusal", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Load the model first" }), { status: 409 }));
  vi.stubGlobal("fetch", fetcher);
  const response = await POST(new Request("http://localhost/api/algorave/mind", { method: "POST", headers: { authorization: "Bearer example" }, body: "{}" }));
  expect(response.status).toBe(409);
  expect((await response.json()).error).toBe("Load the model first");
  expect(fetcher).toHaveBeenCalledWith(expect.stringContaining("/api/mind/infer"), expect.objectContaining({ headers: expect.objectContaining({ authorization: "Bearer example" }) }));
});
it("does not expose private URLs or transport errors", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("http://private-host secret")));
  const response = await GET(new Request("http://localhost/api/algorave/mind", { headers: { authorization: "Bearer example" } }));
  expect(response.status).toBe(502);
  expect(await response.text()).not.toContain("private-host");
});
