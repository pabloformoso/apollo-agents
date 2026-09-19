# The Algorave Mind service, and the main LLM it thinks with

The Mind is an HTTP process on the GPU host (`apollo-mind.service`, the
algorave playground on loopback:4032). It turns an intent into Strudel.
**It owns no model.** It thinks with the **main LLM** — the one LM Studio
model Apollo chooses, loads and unloads from **Settings → Main LLM**
(`web/backend/main_llm.py`, over LM Studio's REST API) — the same model that
extracts briefs, plans sessions and drives the live DJ.

Until 2026-09-19 this file described a second model: the Mind loaded its own
copy under the alias `apollo-mind` with `lms load`, with its own settings file
and its own Load button. One physical LLM was managed as two, and pressing both
Load buttons put two copies on the 16 GB GPU ACE shares. That alias, that
settings file (`~/.config/apollo/mind-settings.json`) and the load/unload
routes are gone; `APOLLO_MIND_SETTINGS_PATH` is no longer read.

The ACE supervisor still exposes the authenticated `/v1/mind` routes, now
three: status, `start`/`stop` of the service, and `infer`. Apollo proxies them
through `/api/mind`; only administrators may start or stop. Browser inference
uses the authenticated same-origin `/api/algorave/mind` gateway.

## How a request reaches the model

1. The page asks `/api/algorave/mind` (Next, same origin).
2. Apollo's `/api/mind/infer` sets `model` to the main LLM's key
   (`main_llm.current_model()`), refusing any other name with 422.
3. The host supervisor forwards it only if `lms ps --json` shows that model
   resident and the service is active — otherwise 409 naming the fix. The
   playground never JIT-loads.
4. The playground runs with `--any-model`: it trusts the model each request
   names instead of an allow-list declared at startup (there is nothing to
   declare — the choice lives in Settings). A request naming no model is 400.

## Host installation

Install `apollo-mind.service` beside `apollo-ace-control.service` in the user's
systemd unit directory, then run `systemctl --user daemon-reload`. Check the Node
version in its PATH matches the host installation. The main checkout needs its
Python virtualenv and `scripts/algorave-spike/node_modules` dependencies installed.
LM Studio must be running at localhost:1234, with the `lms` executable available
at `~/.lmstudio/bin/lms` (the supervisor only reads `lms ps`). Restart the ACE
controller only when no Mind request is active; keep exactly one worker. Do not
enable Mind at boot.

## Operator workflow

In **Settings → Main LLM**: choose an installed model, context and flash
attention, then **Load selected model** (stop ACE first — they share the GPU,
and the load answers 409 while ACE holds it). Below it, **Start Mind** brings
the service up; it loads nothing. Open `/algorave` and play. The same panel is
reachable from the Algorave page's **Main LLM** button.

To change the model, load another from the same panel; the Mind follows on its
next request. **Unload model** is refused while the Mind reports an answer in
flight or an unresolved transport — the request outlives the browser, and the
model must outlive the request.

There is no shared-GPU opt-in any more. The protocol in the root CLAUDE.md is
symmetric: unload the main LLM before starting ACE, stop ACE before loading it.
The ACE supervisor refuses to start while any model is resident in LM Studio.

Model-operation timeouts belong to LM Studio's REST API now and surface in the
panel's error line. An inference transport timeout still leaves the host
supervisor `uncertain`: the model server may be processing after the client
disconnected, so `stop` and a new `infer` are refused until the controller is
restarted, and Apollo refuses to unload the model meanwhile. Verify on the host
(`lms ps --json`, the LM Studio logs) before restarting.

Rollout must wait for a performance-safe window: frontend reloads may interrupt
browser audio. This feature does not restore autoplay or automatically resume B2B.
