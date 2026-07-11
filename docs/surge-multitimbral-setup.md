# Multi-timbral Surge setup for the generative engine (E-2 / issue #67)

One Surge XT instance can hold **two timbres** via scene channel-split; drums
need a **second instance on a second MIDI port**. Ten minutes of setup, no
code. The spike prints the expected state at startup (`expected_setup()` from
`agent/generative/patches.py`) so you can match Surge to the contract.

## Role routing (what the engine emits)

| Role | MIDI channel (1-based) | Destination |
|---|---|---|
| bass | 1 | main instance, **Scene A** |
| pad | 2 | main instance, **Scene B** |
| drums (kick/snare/hats) | 10 | **drum instance** on the second port |
| controls (macros CC 41-44) | 1 | main instance (both scenes hear CCs) |

## 1. Create the second loopMIDI port

In loopMIDI, click **+** and name the new port `loopMIDI Drums` (any name
containing "Drums" works — the spike matches by substring).

## 2. Main instance — channel split

1. Open Surge XT (standalone), menu **Audio/MIDI Settings** → enable
   **loopMIDI Port 1** as MIDI input (and your speakers as output — remember
   the G733 incident).
2. In the top header, set **Scene Mode = Channel Split**. Surge routes
   channels **at or below the split channel to Scene A**, above it to
   Scene B. Set the split channel to **1** (menu on the Scene Mode control):
   ch 1 → Scene A (bass), ch 2+ → Scene B (pad).
3. MPE must stay **off** (channel split is bypassed when MPE is on).
4. Load the patches for your genre **per scene** (select Scene A, load the
   bass patch; Scene B, load the pad patch). Current registry
   (`agent/generative/patches.py`):

   | Genre | Scene A (bass) | Scene B (pad) |
   |---|---|---|
   | deep | FM Bass 1 *(Factory/Basses)* | MKS-70 Warm Pad *(Factory/Pads)* |
   | ambient | Deep End *(Factory/Basses)* | **Deep Space 1** *(Inigo Kennedy/Pads)* |
   | lofi | E-Bass *(Factory/Basses)* | Soft Suitcase *(Factory/Keys)* |

   > Loading a whole patch replaces BOTH scenes. Load the pad patch first,
   > then use **Scene A context menu → copy/paste scene** tricks, or load per
   > scene from the patch browser's scene-aware options. Simplest reliable
   > path: load pad patch → switch to Scene A → dial the bass sound in
   > manually or paste a saved scene. Save the combined result as a user
   > patch (e.g. `Apollo Ambient Split`) so setup is one load next time.

5. Wire **Macros 1-4** per the Apollo convention (energy / brightness /
   space / motion — see `docs/surge-xt-exploitation.md`), then save the
   user patch again. Macros are per-patch, so the saved split patch keeps
   them.

## 3. Drum instance

1. Launch a **second** Surge XT standalone instance.
2. Its Audio/MIDI Settings: MIDI input = **loopMIDI Drums** only (untick
   the main port!), audio output = same device.
3. Load the drums patch (`Drum One`, Factory/Percussion) — a stopgap: one
   patch pitches kick (C2/36), snare (D2/38) and hats (F#2/42). Acceptable
   for monitoring; a real drum sampler replaces this instance later.

## 4. Run

```bash
uv run python scripts/spike_generative.py --genre ambient --drum-port Drums
```

Without `--drum-port` everything goes to the main port exactly as before
(drums land in Scene B — fine for quick single-instance checks, wrong for
serious listening).

## Saved combined patches (recommended)

After the first manual setup per genre, save the main instance's state as
`Apollo <Genre> Split` in your user patches. Then genre switching is:
load one patch + confirm the drum instance. When patch loading becomes a
mind decision (E-5), these saved patches are what it will target.
