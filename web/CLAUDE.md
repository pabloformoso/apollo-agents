# web/ — FastAPI backend (:4020) + Next.js frontend (:4010)

Run both from the **main checkout** (worktrees lack tracks/.env/venv).
Ports 4010/4020 are the live prod stack — dev servers go on 4011/4021.

## Architecture decisions

- **Catalog loaders here must NOT filter session eligibility.**
  `pipeline.load_catalog` feeds stream-by-id, ratings and the library
  UI — a short track must still resolve. The eligibility screen lives
  in the SELECTION paths (`agent/eligibility.py` consumers).
- **`brief_parser` follows `AGENT_PROVIDER`, never a hardcoded
  vendor** (v3.11). It called Anthropic unconditionally, so on this
  box — no `ANTHROPIC_API_KEY` since the move to local LM Studio —
  every free-text brief silently parsed to all-null and the planner
  fell back to the conversational genre-guard. Detection is read at
  CALL time (not import) so a late-loaded `.env` still works, and
  `AGENT_PROVIDER=mock` short-circuits before any network. The local /
  Azure path asks for a JSON object rather than a forced tool call:
  small models are markedly better at emitting JSON than at
  function-calling, and `_normalize` treats the payload as untrusted
  either way.
- **Generator module (`generator.py` + `acestep_client.py`, G0)** —
  ACE-Step lives behind its own router (one `include_router` line in
  `app.py`, the `render.py` precedent). `GET /api/generator/health`
  returns `{available, blocked_by_live, stats}`; "unavailable" is a
  NORMAL answer, never a 5xx — `ACESTEP_BASE_URL` unset disables the
  feature with zero HTTP, and the box is off most of the time by
  design. Env is read at CALL time (the `brief_parser` lesson below).
  `live_session_active()` is Apollo's half of the **VRAM protocol**:
  ACE-Step retains ~12.5 GB of the shared 16 GB once loaded, so
  generating during a broadcast starves the DJ's LM Studio model. It
  reads the REAL registry — `ws_manager`'s `live`-channel entries,
  written by the primary live WS handler — never log output. G1's
  generation endpoints import this helper and refuse to release tasks
  while it is true; keep one definition of "a set is on air".
- **Generation endpoints (G1)** — `POST /api/generator/tasks` is the
  ONLY GPU-touching call, so it is the only one behind the 409 VRAM
  guard (`VRAM_CONFLICT_MESSAGE`, rendered verbatim by the wizard, hence
  English like the rest of the wizard's copy); polling and the audio
  proxy stay open during a live set.
  Refusal ladder: 503 disabled/unreachable → 409 live → 422 bad
  genre/field → 429 ACE queue full → 502 ACE broke. The body is
  `extra="forbid"` (a silently ignored knob only surfaces hours later as
  an ordinary take); `experimental` is a verbatim passthrough that may
  NOT shadow server-owned fields — `audio_format: "wav"` and
  `thinking: true` are the catalog contract, not preferences.
  **`bpm` defaults to the centre of the genre window** (spec §5.5:
  pinned at release time so `metas.bpm` comes back in-window and G2
  never has to re-detect it). That table is bound to
  `agent.tools._BPM_GENRE_RANGES`, NOT to the canonical
  `main.BPM_GENRE_RANGES`: importing `main` costs ~2.6 s and ~1800
  modules (librosa/numba/moviepy) inside a request handler. Since that
  copy is knowingly partial, the window table is used ONLY for the
  default and never as the genre allow-list — a genre the table misses
  but the catalog has (`aural`, `synthware`) still generates, logs
  `no BPM window for genre`, and lets the LM pick the tempo.
- **A poll must never 5xx** — the wizard polls every 3 s, so an
  ACE-Step transport blip, a 500, a malformed batch or an id the box
  does not know yet all answer `200 {status: "pending", degraded:
  true}`; only an auth/bad-request failure (a misconfiguration retrying
  cannot fix) becomes a 502. A take's `result_parse_error` is carried
  through, never raised. Keys are always present so the poll loop never
  feature-detects.
- **`GET /api/generator/audio` is a streaming proxy, not a redirect** —
  the browser never talks to :8001 (auth + LAN isolation live here).
  `path` is the take's `file`, forwarded UNREWRITTEN to
  `AceStepClient.stream_audio` but not unexamined: an absolute decoded
  path must sit under `ACESTEP_AUDIO_ROOT` (same rule as publish — see
  the validator bullet below), and a value carrying a host, a drive or
  traversal is a 400. `Range` is forwarded and upstream's 206 +
  range headers are mirrored, so `<audio>` seeking works as it does on
  `FileResponse` without buffering a 35 MB WAV. Auth accepts a bearer
  header OR `?token=`, the same escape hatch as `stream_track`.
- **One validator decides what "a take's audio" is** (G2b):
  `validate_ace_audio_path` — the proxy and the publisher both call it,
  so flipping the accepted location is a constant, not a refactor. Three
  shapes, and every ABSOLUTE path any of them names is root-checked on
  EVERY route: a bare absolute path, the decoded inner path of
  `/v1/audio?path=<encoded>`, and everything **publish** resolves must
  all sit under `ACESTEP_AUDIO_ROOT` (default
  `/home/pablo/code/ACE-Step-1.5/.cache/acestep/tmp/api_audio`,
  comma-separated for several, read at CALL time). The endpoint shape
  named an ACE *endpoint*, so the proxy used to forward its inner path
  unchecked (hosts and traversal only) and let ACE's validator decide —
  which made the read-only route the soft way in and let the two call
  sites disagree about one value. ACE is still the far-side authority;
  Apollo just does not forward a location it would refuse to publish.
  **Only the status differs now: the proxy answers 400, publish/edit
  422.** Confirmed with the ACE session 2026-08-29: the encoding is
  `quote(p, safe="")`, so slashes arrive as `%2F` and there are **no
  literal `/` in the query param** — decode once, then prefix-match.
  Decoding uses `unquote`, never `parse_qs`, which would turn a `+` in a
  filename into a space. A **relative** path is the one shape the root
  check cannot reach — ACE resolves it against a root only ACE knows, so
  there is no absolute path to prefix-match and guessing one would mean
  inventing the far side's layout; it still streams and can still never
  publish.
- **`POST /api/generator/publish` (G2b) runs the CLI's ingest, not a
  copy.** It downloads the take through `stream_audio` and calls
  `main.ingest_track` — the same function `python main.py --ingest`
  runs — with `main` imported **inside the handler** (~2.61 s, ~1800
  modules: unacceptable at module scope per the G1 rule, fine as a
  one-off for a rare human action, and the only way not to fork the
  catalog's id/filename conventions). Body carries the take's
  DECODED path + metas from the PAGE (`extra="forbid"`): ACE's job
  records expire but its result files never do, so the backend never
  re-queries an old task and there is no `task_id` in the contract.
  `lyrics` is TEXT (the sidecar's semantics), bridged to the ingest's
  file-taking `--lyrics` through one temp file. **Ingest refusals pass
  through as 422 with the message verbatim** — "bpm 90 is outside the
  'techno' window 120-160 BPM" is what the user has to act on, and
  paraphrasing it would fork the wording from the CLI; `main.IngestRefused`
  (a `SystemExit` subclass carrying `.message`) is what makes that
  possible without changing the CLI's behaviour. There is **no 409**:
  publishing touches the disk, not the GPU, so the VRAM protocol has
  nothing to protect here.
- **`POST /api/generator/edit` (G3) is GPU work, so it keeps the 409.**
  Repaint / cover / complete on an existing take: it re-releases through
  `release_task` with `task_type` set and `src_audio_path` pointing at
  the SOURCE take's decoded path — validated by the same
  `validate_ace_audio_path(resolve_file=True)` publish uses, because
  that value is handed to ACE as a filesystem location. Full `/tasks`
  ladder (503 → **409 VRAM** → 422 → 429 → 502); publish's "no 409"
  exemption does NOT apply — an edit loads the model exactly like a
  fresh generation. It answers `{task_id, queue_position, eta_seconds}`
  and is polled by the SAME `GET /tasks/{id}`: an edit *is* an ordinary
  task, and what makes it an edit is its source, which only the page
  remembers (no `task_id` in the contract, per the persistence rule).
  **Wrong-mode parameters are a 422, never ignored** — a
  `repainting_start` sent with `mode: "cover"` means the caller believes
  something untrue, and the only other evidence would be three minutes
  of wrong music. `repainting_*` are SECONDS with `-1` = "to the end",
  and repaint always ships `chunk_mask_mode: "explicit"` (without it the
  range is a hint, not a mask); cover pins `audio_cover_strength` to
  0.2 when unset, the same "don't let the model invent it" rule as `bpm`.
- **The edit's TMPDIR degradation: one 400 means "upload it instead".**
  ACE validates `src_audio_path` against its own process `gettempdir()`,
  which a foreign `TMPDIR` in its launch env moves — so the box can 400
  the very paths it handed out. On a 400 matching
  `ABSOLUTE_PATH_REFUSAL_MARKERS` (a whitespace-normalised marker SET,
  not an equality: the sentence is ACE's to reword and a fatal error
  costs the operator the edit) the handler downloads the take through
  `stream_audio` and re-releases it as `multipart/form-data` with the
  spec's `src_audio` field, same response shape, degradation logged.
  **Every other 400 stays a 502** — a mistyped `task_type` must not be
  answered by uploading 35 MB and failing identically. That is the only
  reason `acestep_client.release_task` grew a `files=` argument (JSON
  stays the default, so no existing caller changed shape); form values
  are flattened by `_form_value` — bools lower-case, `None` empty,
  structured values as JSON.
- **`POST /api/generator/critique` (G4): the bench scores, the LLM only
  reads.** An LLM cannot hear, so the number comes from
  `agent.generative.bench.bench_wav` — the same merge gate the generative
  engine is judged by — imported **inside the handler** (the librosa
  family, publish's rule) after the take is downloaded through
  `stream_audio`. The two layers fail independently and neither is an
  error: a genre with no committed references answers **200 with
  `passed: null` + the bench's own `note`** (every `BenchInputError`
  lands there — this endpoint is advisory by construction, and a 5xx
  would read as something the operator must fix before publishing), and
  any LLM trouble answers `critique: null`. **Scoring never gates
  publishing** — the panel's own label says so. `genre_folder` is mapped
  to a bench GENRE key (`_reference_genre`: `deep house`→`deep`,
  `lofi - ambient`→`lofi` via the folder's leading text, unknown folders
  pass through so the bench's message names them); it is deliberately
  NOT run through `_resolve_genre`, since nothing is written and the
  bench's refusal is the better sentence. The reported `bands` are the
  **effective** ones — the reference range widened by the bench's own
  margins (2.5× centroid, ±8 dB/oct tilt) — because that is the band
  that decides `passed`, and a chip contradicting the verdict beside it
  is worse than a wide band; the raw range rides along as
  `reference_min`/`reference_max`. `APOLLO_BENCH_REFERENCES` overrides
  the references file (read at CALL time; it is also how the tests inject
  bands measured around a synthetic take). **No 409**: the bench runs on
  the CPU and parks no VRAM. The LLM read does travel to the same
  tunnelled gateway the live DJ uses, but it is ONE completion under
  `CRITIQUE_TIMEOUT_SEC` (15 s, `asyncio.wait_for` over the SDK's own
  timeout — a thread that outlives it is abandoned), never retried; the
  guard protects GPU residency, not politeness. Provider detection is
  `brief_parser.detect_provider()` (one definition, read at CALL time,
  `AGENT_PROVIDER=mock` short-circuits before any SDK import); the model
  is `GENERATIVE_MODEL` > `AGENT_MODEL` > provider default, the #123
  precedent — the critic is generative-lane work and must be free to run
  off a different model from the tool-calling live DJ. The client is NOT
  `brief_parser`'s: that one carries a 45 s bound and `BRIEF_MODEL`.
- **The generations library (G6) is written by HOOKS, never by the
  page.** Two tables (`generations` + `generation_takes`, `db.init_db`,
  the playlists precedent) whose primary key IS ACE's `task_id` — there
  is no second identity to keep in sync. The existing endpoints record
  as they succeed, with **zero contract change**: `/tasks` inserts
  `pending` with the ACTUAL outgoing payload as `request_json`
  (server-pinned `bpm`/`audio_format` included, plus the `genre_folder`
  ACE never sees); the first done-poll upserts the takes; `/publish`
  marks one take `published` + `published_track_id`; `/edit` opens its
  own row, whose `task_type` + `src_audio_path` ARE the lineage. **A
  store failure logs and returns — it can never break the endpoint it
  hangs off** (`_store`), the 3-second poll least of all: a SQLite
  hiccup is even less of a reason to 5xx than an ACE blip. The upsert is
  idempotent and deliberately does NOT touch `state` /
  `published_track_id`: a re-poll must not resurrect a discarded take.
  Publish still carries no `task_id`, so the take is found by the one
  value both sides hold — the DECODED path, resolved through the SAME
  `validate_ace_audio_path` the publisher uses, so the two strings are
  equal by construction; an unmatched path is a log line, not a refusal.
  **Every mutation is user-scoped in the SQL itself**, not in the
  caller: task ids come from the browser, so `WHERE user_id = ?` is what
  stops one user's poll from rewriting another's row (and "unknown to
  the store" stays a normal poll — tasks predating G6 still work).
  The three read/repair routes: `GET /api/generator/generations` (a bare
  array like `/api/playlists`, newest first, `limit` 1–100 default 20,
  takes POLL-SHAPED plus `decoded_path`/`state`/`published_track_id`);
  `PATCH .../takes/{idx}` with `{state: "discarded"|"fresh"}` — a
  `Literal`, so asking for `published` is a 422, because published is
  earned by publishing and a track id no catalog entry backs is worse
  than a refusal (patching an already-published take is allowed and
  KEEPS its `published_track_id`: the catalog entry is a fact about the
  past, not a state the feed owns); and `POST .../refresh`, the resume
  lane for a tab that died mid-flight. **`stale` and `degraded` are
  different answers and must never be conflated** — ACE *answering*
  without the task means its 24 h record window closed, which is
  terminal (`stale`), while ACE not answering says nothing about the job
  (stays `pending`, `degraded: true`, the poll's own word). Note this
  inverts the poll endpoint's rule for the same input: an id ACE has not
  registered YET must not tear the wizard's card down, but a refresh is
  asked about a generation old enough to have been abandoned. A
  terminal generation answers **409** naming its status: `done`,
  `failed` and `stale` all have nothing left to poll for.
- **Publishing while `--build-catalog` is running is a human-scheduling
  problem, not a lock** (same class as the VRAM rule). The builder is
  serial, takes ~1.25 min/track, and writes `tracks.json` **only at the
  very end** — so a publish that lands mid-build is silently discarded
  when the builder overwrites the file. The backend deliberately does
  NOT introspect Docker to detect it: that check would be unreliable,
  untestable and one more thing to keep true. What the ingest path does
  give for free is that it re-reads `tracks.json` inside the same call
  that appends to it and backs it up first (`tracks.json.<stamp>.bak`),
  so the loser of a race loses one entry and the backup is the way back.
  Rule: don't publish while a catalog build is in flight — check with
  `docker ps | grep apollo-build` first.
- **Live WS roles**: `/live/stream` = PRIMARY (drives playback, sends
  `playback_pos` every ~250 ms and `track_ended`); `/live/viewer` =
  read-only follower (OBS). Viewers never send. A wrongly-primary OBS
  page tears the session down on disconnect (v3.6.2 fix).
- **Server-side stall watchdog** (v3.6.3, `app.py` + engine
  `check_stall`): the browser engine is ping-driven, so a frozen tab
  wedges the set; the watchdog synthesises the missing `track_ended`.
- **Endless safety top-up** (v3.9.4): `_try_endless_extend_inflight`
  runs from every `playback_pos` ping, not just past the crossfade
  point. The watchdog can only RAMP into a deck the browser already
  pre-loaded, so a track playing with `remaining_after == 0` can only
  ever be hard-cut. It self-gates (endless on + empty queue + grace
  elapsed) and a healthy agent holds `remaining >= 1`, so it engages
  only when the agent has stopped extending. Appending two tracks at
  end-of-track does NOT substitute: that gate only runs at zero, and
  the cursor advance puts the queue straight back to zero.
- **`[engine track_ended]` diagnostic** (v3.9.3): every `track_ended`
  logs the reported position vs `duration_sec` plus a `src=` label
  (`client` = browser message, `endgame` = last-2-s safeguard, `stall`
  = watchdog). A `src=client` line marked `PREMATURE` is the signature
  of a skip-on-load-failure. Before this the WS handler logged nothing,
  so a browser-side skip and a track finishing were identical in the
  backend log; don't reach for `[beatmatch]` or `[live_dj]` timestamps
  to reconstruct on-air time — the first is emitted at plan time (late
  whenever the endless queue is dry) and the second is gated by LLM
  latency, so both drift by a minute or more.

## Strudel in the app (§11 S3)

- **Strudel is NOT bundled, and that is load-bearing.** Its dist resolves its
  own AudioWorklet asset with
  `new URL("assets/clockworker-<hash>.js", import.meta.url)` — relative to the
  MODULE's URL — so the bundle and its `assets/` folder have to be neighbours
  on the server. Bundled, `import.meta.url` becomes a hashed chunk path, the
  asset 404s, and every AudioWorkletNode construction then throws
  *"AudioWorklet does not have a valid AudioWorkletGlobalScope"* — once per
  event, forever, while superdough cheerfully logs `[superdough] ready`.
  `app/vendor/strudel/[...path]/route.ts` serves the dist from node_modules
  under a stable prefix (the same mapping `serve.mjs` does), and
  `lib/strudel.ts` loads it from that URL through a `new Function` import no
  bundler can see. An eslint `no-restricted-imports` rule makes a static
  `@strudel/*` import an error, so a bundled second copy cannot creep back.
- **An alias is NOT enough, and looked like it was.** The first attempt used a
  Turbopack `resolveAlias` to force one `Pattern` class. The identity assertion
  went green in a real browser against a production build — and the page was
  silent. Structural checks pass while audio fails; **the only honest check is
  playing something and reading the console.**
- **Sample sources must be registered before anything plays.** `initStrudel`
  boots the engine but registers no sounds, so `.bank("RolandTR909")` resolves
  to nothing and every event logs `sound RolandTR909_bd not found!` while the
  transport runs happily. `lib/strudel.ts`'s `boot()` registers sources first,
  the way the playground does; a source that fails is reported, not thrown.
- **`pkill -f "next start"` does not kill a Next server.** It renames itself to
  `next-server (v16.2.4)`, so the pattern never matches, the port stays taken,
  every "restart" silently fails to bind, and you keep measuring a build from
  an hour ago. This cost a wrong conclusion (that `next start` does not serve
  `public/` — it does). Kill by port or by `next-server`, and check the PID's
  start time before trusting a measurement. Related: never combine the kill and
  the relaunch in one shell command — the pattern then matches the command's
  own argv and it kills itself.
- **A non-secure origin has no AudioWorklet at all**, and this is the one that
  will keep biting. `AudioContext.audioWorklet` is `undefined` outside a secure
  context, so superdough's registration dies with `Cannot read properties of
  undefined (reading 'addModule')` and every worklet-backed sound — supersaw,
  the effects chain — throws once per event. **Samples still load and play**,
  which is exactly what makes it read as a Strudel bug instead of a URL
  problem. Measured 2026-08-31: `127.0.0.1:4011` → `isSecureContext: true`,
  AudioWorklet defined; `100.68.5.104:4011` → `false`, undefined.
  Secure contexts are HTTPS plus the `localhost`/`127.0.0.1` exception, so it
  works on the box and fails over the tailnet by IP. `boot()` returns
  `secureContext` and the page must say so rather than swallow it.
  **This applies to the `:4031` playground too** — served by IP over plain
  HTTP, its supersaw and pads (#145) have never been able to sound over the
  tailnet. Tailscale HTTPS certs are not enabled on this tailnet
  (`CertDomains: None`), so `tailscale serve` cannot fix it until they are.
- **`initStrudel` does not await the worklets — `initAudio` does.** It only
  arms `initAudioOnFirstClick`, so evaluating straight afterwards races the
  registration and every event in the meantime logs "AudioWorkletNode cannot be
  created". Intermittent by nature (it depends on whether evaluate beats
  addModule), which is exactly why it first read as a flake. `boot()` awaits
  `initAudio()` and reports `workletError`. This is a DIFFERENT failure from
  the non-secure-origin one above and they must not be conflated: one is a
  race that a secure context still suffers, the other is the browser
  withholding the API entirely.

## The algorave route (§11 S4)

- **There are TWO algorave surfaces on purpose** (§11 S9): this route, and the
  `:4031` playground, which stays as the rehearsal room. They share `pen.js`
  and `palette.json`, so turn-taking and the sound vocabulary cannot diverge —
  but each page's own wiring can, and a fix here is not a fix there. What this
  route still lacks: persistence across a reload, `summarizeHumanEdit`, and
  genre/key selection. See `scripts/CLAUDE.md`.

- **`/live` and `/algorave` render the SAME mode switcher** —
  `components/ember/ModeSwitcher` — with the same hash sync. This is seam 3 of
  §11.3, and the extraction happened in the same PR that created the second
  consumer so the duplication never existed. If a third performance surface
  appears, it uses this too; do not copy the markup.
- **`cabin` is not renamed.** It is what the code has always called the Booth,
  and every URL hash, bookmark and OBS Browser Source carries it. The label is
  "Booth"; the id is `cabin`, and a tidier identifier is not worth breaking
  those for.
- **`Shell` takes an optional `hideNav`.** `/live` hides the nav by route
  because it is always broadcasting; `/algorave` hides it only in immersive
  mode, which the route alone cannot know.
- **A rave run gets an id from day one** (`lib/algorave-run.ts`, seam 5),
  minted in the browser and carried in `?run=`. Nothing server-side consumes
  it yet — the point is that the surface already addresses itself by id, so
  S5's mind calls and any later server session adopt it without changing how
  the page is reached, and the fusion of §11.1 stays a composition rather than
  a data migration. It is minted **in the click handler, not an effect**:
  that avoids a hydration mismatch, avoids `set-state-in-effect`, and adds no
  second consumer of `useSearchParams` — the hook whose prerender bailout was
  S1. `crypto.randomUUID` is unavailable outside a secure context, so it
  degrades to a readable random string rather than throwing.
- The buffer is a plain `<textarea>` on purpose: no editor library gets to own
  Ctrl/Cmd+Enter before S5 decides what the pen needs.

## The mind, from the app (§11 S5)

- **The browser never calls the mind directly, and it cannot.** The page must
  be a secure context or Strudel gets no AudioWorklet (S3), and an HTTPS page
  cannot `fetch` the plain-HTTP mind on :4032 — mixed content, blocked
  outright. `app/api/algorave/mind/route.ts` proxies it server-side, where no
  such rule applies.
- **That deletes the CORS problem rather than managing it.**
  `algorave_playground.py` compares origins byte-exact (`SPIKE_ORIGINS` plus
  `--allow-origin`), so every new surface used to mean another flag on a
  process someone must remember to restart — §11.5 risk 2. No browser origin
  reaches the mind now, so there is nothing to keep in sync. **The plan's task
  to widen `--allow-origin` is obsolete, not skipped.**
- **Seam 1 is checkable, so check it**: `grep -rn ':4032\|/api/algorave/mind'`
  over the frontend must hit exactly two files — the route handler (which knows
  the upstream address) and `lib/mind.ts` (which knows the browser endpoint).
  The page names neither. `ALGORAVE_MIND_URL` overrides the upstream; the
  default is the tailnet IP because the mind binds to that interface, not
  loopback (#144's HOST bind).
- **The mind's statuses mean different things and must not be flattened**: 400
  the page sent something malformed, 502 it could not produce valid Strudel
  (ask again), 503 the validator is not installed (`npm install`, not a retry),
  504 no answer in time. `MindError.worthRetrying` is that distinction, and the
  UI wording follows it.
- **The tie rule (#148) lives in `autoApplyDecision`** — pure, exported, and
  tested including the whitespace case. A proposal may only be applied WITHOUT
  ASKING when the buffer is byte-identical to what the mind was shown; if the
  human typed meanwhile their edit stands and the proposal drops to a manual
  diff. S5 computes and shows it; S6 hands it to the scheduler. The manual
  Apply button is never gated by it.
- The ~20 s wait is a designed state, not a spinner: it names the intent it is
  answering and counts. Measured 5.6 s on a warm e4b with a short buffer, so
  treat 20 s as the p50 to pace for, not a constant.

## Turn-taking: the pen, phrases and B2B (§11 S6)

- **The pen module has ONE copy, and it is the spike's.**
  `scripts/algorave-spike/patterns/pen.js` is imported by the spike's page, the
  spike's tests AND this app, through `@algorave/pen`. Making that work needed
  three aligned pieces: a `paths` entry in `tsconfig.json`, `turbopack.root`
  widened to the repo in `next.config.ts` (Turbopack's default root is
  `web/frontend`, which would refuse the import), and a matching alias in
  `vitest.config.ts`. Change one, change all three.
- **Do not reimplement anything the pen already exports.** S5 shipped its own
  line diff, its own request builder and its own tie rule before the module was
  shared — all three already existed there, better documented. That is the
  duplication seam 2 exists to prevent, and it happened anyway because the app
  code came first. `diffLines`, `mindRequest`, `autoApplyDecision` and
  `pushReason` are re-exported from `lib/mind.ts`; reach for those.
- **`decide` is modulo arithmetic on the absolute bar, deliberately.** A
  boundary missed because a call was in flight is SKIPPED, never queued — with
  subtraction it would stay due forever and fire the instant the previous
  answer landed. Verified live: phrase 2, and the log reads
  `bar 2 · asking the mind` then `bar 4/6/8 · boundary SKIPPED ·
  request-in-flight`.
- **The scheduler's log must report the bar the boundary fired at.** `ask` runs
  from an interval, so reading `barsNow` out of its closure logged the bar the
  closure was born on — an off-by-a-few that made the log untrustworthy, which
  defeats the point of showing the WHY at all. It reads `barsRef` now.
- **`TurnStrip` takes plain numbers and strings and imports nothing from the
  algorave** (seam 4). A crossfade IS a phrase boundary, so the same strip is
  meant to sit over the DJ lane's decks unchanged; a test mounts it with a
  deck-shaped prop set to keep that true before the DJ lane exists.
- Layout follows the original playground: **editor left, proposal right**,
  controls in a rail. Reading a diff means reading it against the code it
  changes, and stacked panes make that a scroll.

## The palette browser (§11 S7)

- **The registry is read, never copied.** `/api/algorave/palette` reads
  `scripts/algorave-spike/palette.json` from disk at request time, so adding a
  sound shows up without a rebuild and without a frontend change. That file is
  the one vocabulary the validator, `strudel_mind` and the pages share (§10);
  a second list in TS is exactly the drift the root CLAUDE.md warns about.
- **The browser exists to make the bank rule VISIBLE**, not merely enforced.
  Drums are offered only on a bank that actually carries them — the
  (sound, bank) matrix is data, and a pair outside it plays SILENCE live, which
  is the worst kind of wrong because it looks like it worked. Synths and
  sampled instruments are written with no bank at all, and `insertionFor` does
  not accept one for them, so the UI has no path to that mistake.
- **`insertIntoBuffer` is about the comma.** The last element of a `stack(...)`
  carries no trailing comma, so appending before the closing paren without
  moving it yields `a\nb)` — a syntax error that surfaces only on evaluate,
  which mid-set means the pattern stops. Every sound in the registry is
  inserted and parsed in a test for that reason.
- **Audition is off while a set is running.** `evaluate` replaces the running
  pattern, so a preview would take the room with it. The browser says so rather
  than offering a button that would cost a performance.
- **Known registry wart: `fx` is a drum no bank carries.** It is therefore in
  the mind's palette and unusable by it — the validator rejects whichever bank
  is tried. Pinned by a test so a NEW orphan fails; removing it is a registry
  decision, not a frontend one. The browser already renders it permanently
  disabled with "<bank> does not carry fx".

## Live validation — the same gate, applied to the human

- **The editor runs `validate.mjs`, not a checker of its own.** That process is
  what decides whether the MIND's output may play; running it against what the
  human types means both players are judged by one rule, and a disagreement
  between the editor and what the mind is allowed to write becomes impossible
  rather than merely unlikely. It answers in ~100 ms, which is what makes this
  viable on a 500 ms debounce.
- **`invalid` and `out of key` are different colours on purpose.** Invalid
  means the pattern will NOT play; out-of-key means it WILL play and clash.
  Flattening them would tell a performer to stop when they only need to listen,
  and plenty of good music is out of key deliberately. `readVerdict` is a pure
  fold and the distinction is tested, including the case where both are true —
  the one that stops the music wins the colour.
- **Genre and key are not decoration**: they are what the validator checks
  against and what fences the mind. Adding the two selects is what closed the
  last of the three gaps `scripts/CLAUDE.md` lists against the `:4031`
  playground, and it is why the note check has anything to compare to.
- **Turbopack claims `spawn()` arguments.** A literal `"validate.mjs"` in the
  args array fails the build with `Can't resolve ('validate.mjs' | <dynamic>)`
  — the bundler treats it as a module to resolve, when it is a sibling PROCESS.
  The name is assembled (`["validate", "mjs"].join(".")`) to keep the extension
  out of the literal. Any future `spawn` of a `.mjs` here needs the same.
- **Security posture, stated rather than assumed.** The validator EVALUATES the
  code in a Node subprocess; its screen (import/require/fetch/eval/process) is
  a denylist, not a sandbox. This route does not weaken the posture the mind's
  path already had, but it widens who supplies the input from "an LLM we
  prompt" to "whoever has the page open". Fine for a single-operator tool on a
  private tailnet; **revisit before `/algorave` is ever exposed publicly.**

## Human edits become state (§9.1)

- **A human edit is diffed, never typed.** Nobody live-coding narrates their
  own edits into a text box mid-phrase, so every evaluate of a CHANGED buffer
  becomes a `human: ±N lines — "…"` entry in the recent-reasons ring. The mind
  then sees it beside its own reasons, and its "do not repeat the recent
  reasons" rule notices that a human just moved something.
- **The baseline is the last EVALUATED text, and it moves on every evaluate —
  the mind's own included.** Without that, handing the pen back would report
  the mind's last mutation as if a human had made it. The rule is the
  playground's; `summarizeHumanEdit` is imported from the pen module, not
  rewritten (§11.3 seam 2).
- Nothing is attributed while the MIND holds the pen, and the first evaluate of
  a session reports nothing because there is no baseline to diff against.
- **Known limitation worth knowing before reading a summary:** adding a layer
  to a `stack(...)` also changes the line above it (a trailing comma appears),
  and the summary quotes the FIRST changed line — so it says "+1 line" and
  shows the comma edit rather than the new layer. The direction is right, which
  is what the ring is for, but it does not name the new sound.
- **A suspended AudioContext is resumed on evaluate.** A backgrounded tab or a
  sleeping device suspends it; `evaluate` then schedules onto a stopped clock
  and the page reads "playing" in total silence. From the playground's first
  real practice (2026-08-30) — the app had never carried the fix.

## Persistence, and `/algorave` being client-only

- **What is NOT saved is the important half.** The pen and the B2B mode never
  persist (§9.1, §9.2, the playground's rule kept): a freshly loaded page must
  never fire an LLM call by itself and never wake up alternating, so it is
  always HUMAN and always FREE on arrival. The transport is not saved either —
  nothing should start making sound because a browser refreshed. The saved
  shape has no field for any of them, so a reload cannot inherit an armed
  scheduler even by mistake; a test asserts that on the DATA rather than on the
  caller's discipline.
- **`/algorave` is `ssr: false`, and that retired a class of bug.** Three times
  in this lane a value only the browser knows — the run id, `midiSupport()`,
  the saved session — could not be read during render without a hydration
  mismatch, and each was worked around separately (mint in a click handler,
  drop the render-time check, …). A client-only mount lets state be initialised
  from the browser in a lazy `useState`: no effect, no `set-state-in-effect`,
  nothing to reconcile. The route stops prerendering, which for a page that is
  blank until an AudioContext exists is not a cost.
- Anything client-only added here should go in `AlgoraveClient.tsx`;
  `page.tsx` is only the dynamic wrapper.
- A wrong TYPE in storage is replaced with the default, not passed through: a
  string where `phraseBars` belongs would make `decide()` compare against NaN
  and the mind would never fire again.

## The editor and its autocomplete

- **Plain `@codemirror/*`, never `@strudel/codemirror`** — that package depends
  on `@strudel/core` and would bring a second `Pattern` class, the silent
  failure lib/strudel.ts documents. Our completions have to know the bank rule,
  the chromatic/one-shot rule and the live palette anyway; a generic Strudel
  mode knows none of them.
- **The rules live in `lib/completions.ts` as pure functions**, and CodeMirror
  is a thin layer over them. What is worth getting right is WHICH suggestions
  are legal at a point, and that is testable without a DOM.
- **`.bank("` is the whole point of the feature.** The validator has always
  rejected a bank that does not carry its sound, the browser shows the rule and
  the prompt explains it — and a wrong pair still plays SILENCE rather than
  failing. Completion is the first place the wrong bank is simply not offered:
  carriers rank first, non-carriers are labelled "does NOT carry X — silence",
  and a sound that takes no bank at all (a synth, a sampled instrument) offers
  an EMPTY list rather than a plausible mistake.
- Suggestions are built from the live registry, never a list in the file. A
  sound added to `palette.json` is completable with no frontend change, exactly
  as it is browsable without one. The one hand-written list is the METHOD names
  — those are Strudel's own vocabulary, not our data, and they are kept in step
  with the idiom paragraph in `strudel_mind.py` so the mind and the human are
  offered the same words.
- **The editor is controlled but CodeMirror owns the document.** The `value`
  prop is pushed in only when it differs from what the view holds, or every
  keystroke fights a re-render and the cursor jumps. That matters more here
  than usual: the mind rewrites this buffer while a human may be typing in it.
- The extensions are built ONCE; callbacks and the palette are read through
  refs. Rebuilding on a palette load would throw away the cursor mid-set.
- **`data-testid="buffer"` is now the CodeMirror container, not a textarea.**
  Playwright's `fill()` / `inputValue()` no longer apply — drive `.cm-content`
  with `keyboard.type`, or read the doc through the view.

## Chromatic or one-shot — the rule the registry does not record (2026-09-01)

- **58 of 61 sampled instruments were being written with `note()`, and only 3
  should be.** A sampled instrument is addressed one of two ways and the SAMPLE
  MAP decides: an entry that is an OBJECT is keyed by note name and chromatic
  (`piano`, `balafon`, `fmpiano` — that is the whole list), while a flat ARRAY
  is a set of one-shots walked with `.n(i)`. `palette.json` records neither.
- **`note()` over a one-shot set is not an error and makes no noise.** It picks
  one sample and transposes it — for a drum kit, one hit at three pitches
  instead of the kit. That is why it survived: it plays. `conga` had been
  written this way since the day it was added.
- **Derived, not curated.** `/api/algorave/palette` fetches each source's map
  (cached per process) and returns `pitched: Record<string, boolean>`. Curating
  it by hand would be a second copy of something the data already states, and
  it would go stale the next time a source is added.
- **Unknown falls back to `.n()`**, deliberately: `.n()` on a chromatic map
  still plays its samples, while `note()` on a one-shot silently transposes.
  When the CDN cannot be reached, take the cheaper mistake.
- The prompt now states the RULE rather than listing examples by hand — a hand
  list was already stale at 61 sounds.
- `__tests__/fixtures/dirt-shapes.json` is generated from the real maps, so the
  test asserts against the library rather than against anyone's belief about it.

## Two silent bugs the palette browser hid (2026-08-31)

Both shipped green and neither raised anything. Worth knowing the shapes.

- **Only `drum-machines` was registered.** `boot()` defaulted to
  `FALLBACK_SOURCES`, so `piano.json` and `vcsl.json` were never fetched and
  every sampled instrument — the piano and the nine VCSL sounds of #146/#147 —
  resolved to nothing. No error, no sample fetch, no sound: the browser offered
  them and they did not play. The page now boots with the registry's OWN
  `sources`; the fallback is only for a registry that could not be read.
- **`insertIntoBuffer` used `lastIndexOf(")")`.** The opening buffer ends
  `).cpm(124/4)`, so that paren closes `cpm`, and every insertion became
  `cpm(124/4, note(...).s("piano"))` — **valid JavaScript, no layer, no sound**.
  `stackCloseIndex` counts depth from `stack(` and is string-aware, so a `)`
  inside `"bd(3,8)"` closes nothing.

**The lesson is about the test, not the code.** The acceptance criterion was
"the inserted buffer parses", and it passed for a year of runs while the
insertion was wrong — a criterion a broken implementation can satisfy is not a
criterion. It now asserts the line became a top-level LAYER of the stack
(`stackLayers`). Same shape as S3's "one `Pattern` class" going green on a
silent page: **structural checks pass while the music is wrong.**

## MIDI out — `.midi("port")`

- **Written here rather than installed, and that is not a preference.**
  `@strudel/midi` depends on `@strudel/core` and would arrive with its own copy
  — a SECOND `Pattern` class, the silent failure S3 spent a day proving. A
  method registered on a Pattern the scheduler does not run simply never fires.
  `lib/strudel-midi.ts` adds `.midi()` to OUR single bundle's prototype using
  hooks it already exports: `onTrigger`, `valueToMidi`, `getAudioContext`.
- **`installMidi` is idempotent per PROTOTYPE, not per module.** A module-level
  flag installs on the first Pattern it ever sees and silently skips any other.
  Caught by a test, which is the only place that difference shows.
- **The clock conversion is the part to read twice.** `onTrigger` hands over
  `targetTime` in the AUDIO clock; `output.send` wants the PERFORMANCE clock.
  Without `performance.now() + (target - audioNow) * 1000` every note still
  plays, at a time that looks plausible and is not — drifting with how long the
  page has been open. Nothing throws.
- **The validator has a no-op `.midi()`** (`validate.mjs`). Without it, the
  moment a human routes a layer to a synth every later mutation the mind writes
  carries `.midi(...)` and is rejected as a syntax error — the mind silently
  unable to touch the set again. A no-op is exactly right for gating: MIDI
  changes where notes GO, not what they are, so `queryArc` sees the same events.
- **Do not call `midiSupport()` during render.** It reads
  `window.isSecureContext`, which the server cannot know, and doing so produced
  a hydration mismatch (React #418). The button is always offered; `enableMidi()`
  reports which way it failed on the click.
- **WebMIDI needs a secure context**, exactly like AudioWorklet. And the notes
  reach the ports of the machine with the TAB open — the performer's, not the
  server's. That is what makes this a better fit than Strudel's OSC/SuperDirt
  path, where SuperCollider would make the sound on the server in an empty room.

## The OBS view (§11 S8)

- **`afterFiles` rewrites beat DYNAMIC routes, not static ones.** `next.config`
  rewrites `/api/:path*` to the FastAPI backend, and a `rewrites()` returning an
  array is `afterFiles` — checked AFTER static filesystem routes but BEFORE
  dynamic ones. So `/api/algorave/mind` wins and `/api/algorave/run/[id]` loses:
  every call silently became a proxy attempt to :4020 and came back
  `ECONNREFUSED`, with nothing in the route handler to debug because it never
  ran. The run id is a **query param** for that reason. Any new algorave
  endpoint must keep its segment static.
- **The viewer gate is three-state and shared** (`lib/viewer.ts`, seam 3). The
  v3.6.2 lesson it carries is worth restating: a `?viewer=1` page that treats
  "not yet resolved" as "operator" attaches to the PRIMARY endpoint, displaces
  the operator and kills the session on teardown — an OBS Browser Source that
  silently ends the set it is mirroring. Gate every attach on `resolved`.
- **The mirror goes through the server because it has to.** OBS's Browser
  Source is a separate browser, so `BroadcastChannel` and `localStorage` cannot
  reach it. `/api/algorave/run?id=` is an in-memory store keyed by the run id
  from seam 5 — a run is a performance, not a record, so nothing is persisted
  and a restart costs a reload. If it ever needs to survive one or span
  processes, it belongs behind FastAPI, and only `lib/algorave-run.ts` knows the
  endpoint, so that is a one-file move.
- **The viewer boots no engine.** OBS captures video; the audio comes from the
  operator's desktop. A second engine would double every sound.
- **A failed publish is swallowed on purpose.** The operator is performing, and
  a mirror that cannot be reached must never interrupt what the room hears.

## Frontend playback substrate (v3.4+, `lib/audio_buffer_decks.ts` + `lib/live.ts`)

- **A `playback_pos` ping's `track_id` and `currentTime` must come from
  the same object** (v3.9.5): both are read off the active deck, never
  the id from `currentTrackIdRef` and the clock from the deck. Those
  refs flip at different moments during a crossfade, so the ping went
  out with the INCOMING track's id and the OUTGOING deck's position;
  the engine compared that near-end position against the new, shorter
  track's duration and ended it on arrival, leaving both decks audible
  (2026-08-23). The backend cannot defend against this — a
  misattributed position is indistinguishable from a real one, and
  every wall-clock heuristic breaks legitimate resumes where the deck
  is legitimately far ahead of `_track_started_mono`.
- AudioBufferSourceNode decks, PCM decoded via `BufferCache`.
- **The cache is a working set, not an archive** (v3.9): after every
  successful schedule it is pruned to {current, preloaded-next}.
  Never remove the prune — an endless session that keeps every
  decoded track OOMs the renderer (~50–100 MB/track; the 2026-08-01
  30 h collapse).
- **Load-failure taxonomy** (v3.9): fetch-stage failures leave the
  deck INERT (the E2E suite drives the UI against 404ing mock streams
  and depends on that); decode failures/timeouts send a synthetic
  `track_ended` (skip), capped at 3 consecutive, streak reset on a
  healthy schedule. `BufferCache.load` races a 20 s deadline.

## Frontend generator surface (G1, `lib/generator.ts` + `components/ember/Generator*`)

- **Entry lives in the Editor's track row** — the "Generate (ACE)" tile
  sits beside "Add a track", because that row IS the wizard's
  track-selection stage; generating and picking are two ways into the
  same slot. `GenerateTrackTile` renders NOTHING while
  `/api/generator/health` is loading or `available` is false: the ACE box
  is off most of the time by design, so absent is the normal look, not an
  error state. `blocked_by_live` renders it disabled with the VRAM
  tooltip — a courtesy, since the POST's **409 is the authoritative
  guard** and its message is shown verbatim (never paraphrase a protocol
  refusal). Health is read once on mount, deliberately not polled.
- **A degraded poll is a blip, not a failure.** `applySnapshot` /
  `applyPollError` are pure folds so the transitions are testable without
  timers: a `degraded` snapshot keeps the task pending AND keeps the ETA
  it could not refresh, so the countdown ticks on through the blip. A
  thrown poll degrades too — only 401/403/404 ends the loop, otherwise a
  wrong turn spins forever. Cadence is 3 s with an immediate first poll.
- **The ETA is `(server estimate, capture time)`, not a local timer.**
  Every poll that carries `eta_seconds` restamps both, so the countdown
  resets to the server's newer number instead of drifting off a stale one.
- **Takes play through the existing `PlayerProvider`.** `Playable =
  Track & { stream_url?: string }` — catalog tracks still resolve via
  `streamUrl(id)`; a take is not a catalog entry and carries the
  `/api/generator/audio` proxy URL instead. The JWT rides the query
  string there for the same reason it does on `streamUrl`: `<audio>`
  can't set an Authorization header.
- Genres in the form come from `/api/catalog` (the same fetch
  `TrackPicker` makes) — ACE writes into a real genre folder. The BPM
  default is NOT duplicated client-side: the helper text says the server
  fills the centre of the genre's window. A third copy of
  `BPM_GENRE_RANGES` in TS is exactly the drift the root CLAUDE.md warns
  about.
- **Publish is per-take, confirmed, and one-way** (G2b). The G1
  placeholder is now a real button: `idle → confirm → publishing →
  published | failed`, all pure folds in `lib/generator.ts` so the
  machine is testable without a DOM. The confirm step exists because
  `display_name` becomes the WAV's filename and the track's name in
  every set forever — it is prefilled from the prompt
  (`suggestDisplayName`) and the genre from the form, both editable.
  A take that came back without `metas.bpm`/`keyscale` cannot publish at
  all (`canPublishTake`): the ingest refuses to guess, and guessed
  metadata is how the catalog got its poisoned BPMs. `decodedTakePath`
  is the page's half of the persistence rule — ACE's `file` is decoded
  ONCE here (with `decodeURIComponent`, never `URLSearchParams`, which
  would eat a `+` in a filename) and the decoded path is what publish
  sends. After the first take publishes, later takes in the same batch
  are offered `variant of <that name>` — the only way two takes of one
  prompt link as a single piece for the no-repeat machinery. Server
  refusals render VERBATIM, the same rule as the 409.
- **An edit renders as a CHAINED card inside its source's row** (G3).
  "Edit" is a sibling of "Publish" and steps aside while that take is
  publishing. The panel is mode-switched — repaint gets start/end in
  seconds over `metas.duration` (`-1` = to the end), cover gets a
  strength slider, complete gets neither — and an empty prompt override
  reuses the take's OWN prompt, which the page holds and the backend
  never re-queries. `editRangeError` is the one check that exists
  nowhere else: only the page knows how long the source is. On success
  the panel closes and a `ChainedTaskCard` appears **nested in the
  source's `<li>`** — the DOM tree IS the lineage, so an edit of an edit
  sits a level deeper — labelled `edited from <source> · <mode>`, where
  `<source>` becomes the source's CATALOG name once it is published.
  That card is an ordinary generation card: it adopts the task handle as
  `useGeneratorTask`'s lazy initial state (no effect, hence no
  set-state-in-effect) and its takes publish and edit like originals,
  offered `variant of` the SOURCE take's published name first
  (`variantOptionsFor`). `chainAppended` dedupes by task id, or a
  double-clicked submit would render two cards polling one task with
  separate publish state.
- **"Score" is the read-only sibling of Publish and Edit** (G4). It sits
  in every take row — chained takes included, since they render through
  the same `TakeRow` — and stays enabled whatever else the row is doing:
  it writes nothing. `canScoreTake` is as weak as `canEditTake` (audio is
  all the bench needs), so a take whose metas never parsed is scoreable
  though it cannot publish. The panel is pure folds in `lib/generator.ts`
  — `bandTone` is the ONE comparison, `scoreChips` the fold over it, both
  tested directly — so the component does no arithmetic: chips carry
  value + band and read in/out, LUFS/LRA/crest are toned `advisory`
  because nothing advisory can fail, and a response with no verdict folds
  to NO chips (the note is the whole answer). `scoreStarted` keeps the
  previous numbers on screen during a re-score — blanking would read as
  "those were wrong". The section label, `bench score · informs, never
  blocks`, is the UI's half of "scoring never gates publishing".
- **`/generations` reuses the take row, it does not re-implement it**
  (G6). `TakeRow` + `ChainedTaskCard` moved out of `GeneratorDialog` into
  `components/ember/GeneratorTakes.tsx` unchanged; the feed and the wizard
  import the SAME component, so play / Score / Edit / Publish behave
  identically in both and an edit still chains inside its source's row.
  The move added exactly two OPTIONAL props the dialog never passes —
  `actions` (the feed's Discard / Restore, left of Score) and
  `published` + `publishedTrackId` (the store's word that a take is
  already in the catalog, which the wizard cannot know: it only ever sees
  its own publishes). A take this row published itself still renders the
  full `pub.result` block — key, BPM, the ingest note — and the stored
  chip only fills in when there is no local result.
  **Every state the feed shows is a pure fold** (`generationsMerged`,
  `takeStateSet`, `generationReplaced`, `readGeneration`, the `feed*`
  trio), so the page does no reasoning: it renders `readGeneration`'s
  answer. That fold is where **`failed` ≠ `stale` ≠ `degraded`** is
  enforced on screen — ACE's verdict, ACE having forgotten (terminal,
  quiet, no resume), and Apollo not reaching ACE at all (still pending,
  keeps its Resume) are three different sentences, and only `pending`
  gets the button, which is also what keeps the refresh's 409-on-terminal
  out of reach. Discard is optimistic and rolled back VERBATIM when the
  PATCH refuses it — a row left hidden after a refusal would be a lie
  about the store — and a publish reconciles through `notePublished`
  rather than a re-fetch. `generationsFromPayload` reads the listing as a
  bare array OR a `{generations}` envelope: the plan wrote one and the
  router answers the other, and that is a spelling, not a feed worth
  breaking. Merge is by `created_at` (not arrival) so an overlapping
  "load more" cannot interleave an older card above a newer one, and the
  offset advances by what the SERVER sent, not by what the merge kept.
  Pagination is a plain "load more" guarded by a ref, since the button
  only goes disabled on the next render and a double fetch would skip a
  page. Nav lives in `Shell`'s `ROUTES` — the one place pages register —
  and the wizard dialog carries a `view all generations` link.

## Testing

- Unit: `npx vitest run` in `web/frontend` (hook tests use the
  FakeWebSocket + FakeAudioContext harness in `__tests__/live.test.ts`).
- E2E: `npx playwright test` — the transition spec stubs
  `decodeAudioData` and shims stream fetches; other specs rely on the
  404→inert contract above. `generator-wizard.spec.ts` uses the same
  `addInitScript` fetch shim to script `/api/generator/*` (including two
  degraded polls), so it passes whether or not ACE is running.
  `generator-publish.spec.ts` picks up where it stops and walks take →
  confirm → refusal → published chip → variant, capturing the POST body
  so the DECODED-path contract is asserted on the wire.
  `generator-edit.spec.ts` walks take → publish → edit (repaint 10–20 s)
  → chained card → edited take, so the lineage label, the nesting, the
  `variant of` default and the edit's wire body are all asserted in one
  pass; its second test pins the 409 rendering verbatim with the panel
  left open. `generator-score.spec.ts` walks take → Score → chips +
  paragraph, and scores a SECOND take whose stubbed answer is the
  verdict-less one, so both the band readings and the reference-less note
  are covered in a single pass (the stub branches on the `file` it is
  sent); it also asserts Publish stays enabled the whole way. Locators there are scoped through
  `generator-chained-card`, not the outer take — once a card nests,
  `take.getByTestId(...)` matches twice and strict mode bites.

## Known issues

- **eslint baseline: 17 errors + 6 warnings across 11 files** (measured
  2026-08-31 on `main`). The long-standing "2 errors in `lib/live.ts`"
  note was stale — the debt spread while nothing measured it, because CI
  does not run `npm run lint`. Treat those numbers as a ceiling: a change
  may not raise either count in the files it touches. Fixing the existing
  ones is its own change, not a drive-by.
- **Every page reaching `useAutoSession` or `useAuthQueryBootstrap` needs
  its own Suspense boundary.** Both call `useSearchParams()`, which opts
  the route out of the prerender pass; without a boundary ABOVE the
  calling component, `next build` fails on that route — and `next dev`
  never notices. The boundary cannot live inside the hook (a hook cannot
  wrap its own caller), so the pattern is: rename the page component to
  `<Name>Inner` and export a default that wraps it in `<Suspense>`. Five
  pages already do this; CI now runs `npm run build`, so a sixth that
  forgets fails the PR instead of shipping.
- `tests/web/test_youtube_chat.py` fails LOCALLY only; passes in CI.
