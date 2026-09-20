# The showcase — Apollo in five minutes

A script for showing Apollo to a room, and for recording the video the
README embeds. Everything in it is the ordinary product: the showcase
button on the home page sends a curated brief through the same
`POST /api/sessions` a typed sentence goes through, planning streams on
`/curate`, and "Apollo, take the booth" opens `/live`. What the showcase
adds is one click and the reasoning on screen.

The thing to show is not that music plays. It is that **Apollo says why**:
the brief it understood, the tracks it searched for and why, the
transition it planned, the moment its safety net stepped in, the pattern
the Mind rewrote and the reason it gave. That is the difference between
"an AI directs this" and "a playlist is playing", and it is what the
stream carries.

## Before the room fills

Do these once, in this order. Each is a screen the presentation should
not have to visit.

1. **Settings → Main LLM.** Stop ACE if it is running (they share the
   GPU), pick the model, **Load selected model**. Wait for
   `loaded: <model>` in the status line. Below it, **Start Mind** so the
   Algorave has its service up. Nothing else on that screen matters
   tonight.
2. **A YouTube broadcast, if the set goes out.** Link the channel from
   the YT pill on `/live` (it says so when it is not linked); start the
   broadcast in YouTube Studio; OBS takes the `/live?…&viewer=1` URL the
   **OBS feed ↗** button copies as a Browser Source. The OBS view is the
   same page in read-only mode — reasoning overlay included.
3. **Audio out of the operator's machine**, not OBS's: the OBS view boots
   no engine.
4. **Open `/dashboard` and leave it there.** The first click of the demo
   is on this page.

## The five minutes

| min | screen | what happens | what to say |
|---|---|---|---|
| 0:00 | `/dashboard` | Click **▶ Showcase**. A toast names the brief; you land on `/curate`. | "One sentence. Apollo reads it like a promoter's brief: genre, duration, venue, energy arc." |
| 0:15 | `/curate` | The planner's phases stream. The critic's thinking runs as a ticker. Tracks appear with the reasons the critic gave. | "This is the team: a planner picks, a critic checks the transitions, and it tells you what it changed and why. You still have the last word — swap, move, ignore." |
| 1:00 | `/curate` | Click **Apollo, take the booth →**. Tap to start the set. | "Now it performs. Watch the bottom-right." |
| 1:10 | `/live` Booth | The "why apollo does what it does" panel fills as the first turn streams. Switch to **Audience** for the room, **Immersive** for the stream. | Read the feed aloud once: *searching the catalog 74–82 BPM, key 9A · bass swap into … · bass drops 0:12 in.* "It is not choosing by tag. It is choosing by tempo, key and phrase, and it is telling you." |
| 2:00 | `/live` | Type in **talk to apollo**: "darker" or "more groove". The next turn reacts on the feed and in the chat. Toggle **♾ Endless** so the safety net has a chance to show itself. | "The room can talk to the DJ. And if the model is slow, the engine's own safety net picks — and says it was the safety net, not the DJ." |
| 3:00 | `/algorave` | Press **Play**. Give the Mind the pen. At the next phrase boundary it rewrites the pattern; the reason lands under the strip and the added lines light up. | "Same idea, other instrument: live coding, turn-taking on the phrase grid, the Mind explaining each mutation. The human keeps the pen whenever they want it." |
| 4:00 | `/algorave` → **Booth** | Show the **Why — what changed** history and the proposal diff. Take the pen back and edit one line: the edit is diffed and the Mind is told. | "Two collaborators, one buffer, and neither is a black box." |
| 4:40 | `/dashboard` | Back home. Point at Generate music. | "And when the catalog runs out, it writes new music with ACE-Step — scored, edited, published into the same catalog the DJ draws from." |

Five minutes ends before ACE. If there is a sixth, **Generate music →
Generate songs** with a short prompt is the encore; a take arrives in about
a minute on the shared GPU — after **unloading the main LLM** in Settings.

## Recording it

- Record the **operator's** screen with the stream audio, not OBS's
  output: the overlay is on both, and the operator's has the booth.
- `#immersive` on `/live` is the frame that reads best in a thumbnail.
- Keep the first 20 seconds on `/dashboard` → `/curate`: the reasoning
  starts there, and a video that opens on music already playing has
  skipped the point.
- Put the video on the channel, take its id, and replace `VIDEO_ID` in
  the README's "See it in action" block (both the thumbnail URL and the
  link).

## If something is off

- **The feed says "Nothing decided yet" for a whole track.** The DJ turn
  fires on engine events (approaching crossfade, running low, the room
  talking). Type something into *talk to apollo* — that is a turn.
- **Every ask on `/algorave` answers 409 "Load the main LLM".** The model
  is not resident on the GPU host, or the Mind service is down: Settings
  → Main LLM, then Start Mind.
- **OBS shows the page but no reasoning.** It reconnected before the
  first turn; the replay carries the last twelve reasoning events, so the
  next turn fills it. Nothing to do.
- **The showcase toast appears and `/curate` shows an error.** The
  backend could not reach the LLM: the Main LLM status line in Settings
  says whether it is loaded.
