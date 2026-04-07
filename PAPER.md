# ApolloAgents: A Multi-Agent Architecture for Autonomous DJ Set Generation

**Pablo Formoso**
Independent Research · April 2026

---

## Abstract

This paper presents ApolloAgents, an AI-powered system that transforms a collection of audio tracks into a fully rendered DJ mix video through a coordinated pipeline of specialised language model agents. The system addresses the inherent complexity of DJ set curation — harmonic compatibility, energy arc design, rhythmic continuity, and audio quality — by decomposing the problem across six agents with distinct, bounded roles: a Genre Guard, a Catalog Manager, a Planner, a Critic, a Validator, and a human-in-the-loop Orchestrator. Each agent communicates through structured text protocols and a shared context object, avoiding the overhead of distributed message buses while preserving the modularity benefits of multi-agent design. A persistent session memory allows agents to learn from past sessions, progressively improving track avoidance, energy arc selection, and transition quality over time. The full pipeline — from prompt to lossless WAV mix to 1080p YouTube video with AI-generated artwork — runs without human intervention beyond two interactive checkpoints.

---

## 1. Introduction

Creating a DJ mix is a compositional act that balances multiple musical dimensions simultaneously. A skilled DJ considers harmonic compatibility between tracks (so key changes do not clash), BPM continuity (so tempo transitions feel natural rather than jarring), energy arc (so the set has a narrative shape — warmup, build, peak, release), and audio quality (so no individual track bleaches, clips, or drops into silence). This is a rich, multi-constraint optimisation problem that resists reduction to a single prompt or a simple ranking function.

Large language models excel at tasks requiring structured reasoning, preference modelling, and natural language interaction. However, a single general-purpose agent asked to "plan a 60-minute techno set" will tend to produce superficially plausible but musically shallow results: it lacks the domain specificity to analyse harmonic wheels, the numerical grounding to evaluate BPM clusters, and the self-critical distance to review its own choices objectively.

ApolloAgents decomposes the problem into a pipeline of agents, each specialised for a single phase of the workflow. This mirrors professional DJ practice: a promoter confirms the brief, a music researcher curates the catalog, a set planner proposes a running order, an A&R person critiques it, and an engineer handles the technical render. The system encodes this division of labour into distinct agents with clearly bounded system prompts, tool access, and output formats.

The contributions of this work are:

1. A practical multi-agent architecture for creative audio production, implemented without orchestration frameworks
2. A structured text protocol for inter-agent communication (CONFIRMED blocks, PROBLEMS/VERDICT format, Status: fields)
3. A lossless audio pipeline addressing the crossfade clipping problem endemic to naive pydub-based mixing
4. A persistent session memory that allows agents to improve recommendations based on accumulated user feedback
5. A full video production pipeline integrating spectral waveform visualisation, beat-reactive particles, and AI-generated artwork

---

## 2. Background

### 2.1 The Camelot Wheel

The Camelot Wheel is a harmonic mixing reference system developed by Mark Davis that maps Western musical keys onto a clock face. Each position represents a key (e.g., 8A = A minor, 8B = C major). Two tracks are considered harmonically compatible if their Camelot positions are:

- **Identical** — same key, always safe
- **Adjacent by number** (±1) — relative key shift, smooth transition
- **Adjacent by letter** (A↔B at same number) — parallel major/minor, slightly bolder

Transitions two steps apart are acceptable with technique; larger jumps risk audible key clash. ApolloAgents encodes this as a graph neighbour function:

```python
def _camelot_neighbors(key: str) -> set[str]:
    num = int(key[:-1])
    letter = key[-1].upper()
    opposite = "B" if letter == "A" else "A"
    return {
        key,
        f"{(num % 12) + 1}{letter}",       # +1 clockwise
        f"{((num - 2) % 12) + 1}{letter}", # -1 counter-clockwise
        f"{num}{opposite}",                 # parallel key
    }
```

The harmonic sort algorithm performs a greedy random walk on this graph to produce a compatible running order from a pool of clustered tracks.

### 2.2 BPM Matching

Professional DJ mixing involves beatmatching: aligning the tempo of the incoming track to the outgoing track before the crossfade begins. ApolloAgents implements tempo matching via `pyrubberband`, a Python wrapper around the Rubber Band Library which uses phase-vocoder time-stretching to change playback speed without altering pitch. Tracks within `BPM_MATCH_THRESHOLD` (5 BPM) are played at their native tempo; larger differences trigger a 16-second ramp (`TEMPO_RAMP_SEC`) that linearly interpolates BPM across `RAMP_STEPS = 24` micro-segments for a smooth transition.

### 2.3 The Crossfade Clipping Problem

A widely overlooked issue in programmatic mixing is that crossfading two audio signals at full amplitude causes additive clipping. If both tracks peak at 0 dBFS, their sum during overlap reaches +6 dBFS — beyond the representable range — producing digital distortion. The system addresses this with two mitigations:

1. **Pre-mix gain reduction**: every track is attenuated by −3 dB before mixing (`segment = segment - 3`)
2. **Post-mix normalisation**: if the final mix peaks below −1 dBFS, it is normalised to recover headroom

Additionally, per-crossfade peak monitoring warns when the overlap zone exceeds −0.5 dBFS, allowing detection without requiring a full librosa analysis pass.

### 2.4 Multi-Agent Systems for Creative Tasks

Prior work has explored LLM agents for creative generation in domains including code synthesis, game design, and narrative writing. The ApolloAgents architecture draws inspiration from the AutoAgent pattern of specialised subagents with bounded tool access, but implements it directly against the Anthropic and OpenAI APIs rather than relying on an orchestration framework. This keeps the dependency surface minimal and makes the control flow inspectable in a single file.

---

## 3. System Architecture

### 3.1 Overview

ApolloAgents structures the mix creation process as an 8-phase sequential pipeline. Each phase is handled by a dedicated agent with a fixed system prompt, a curated subset of tools, and a structured output format. Shared mutable state is carried in a `context_variables` dictionary injected by the orchestrator.

```
User Prompt
    │
    ▼
Phase 1 · JANUS (Genre Guard)       — validates genre, duration, mood
    │  CONFIRMED block
    ▼
Phase 2 · HERMES (Catalog Manager)  — syncs WAV catalog on demand
    │
    ▼
Phase 3 · MUSE (Planner)            — proposes playlist w/ energy arc
    │  playlist in context_variables
    ▼
Phase 4 · Checkpoint 1              — user reviews, adjusts
    │
    ▼
Phase 5 · MOMUS (Critic)            — PROBLEMS / VERDICT output
    │  parsed verdict + problem list
    ▼
Phase 6 · Checkpoint 2              — user applies selected fixes
    │
    ▼
Phase 7 · Editor REPL               — free-form editing until build
    │  build_session triggered
    ▼
Phase 8 · THEMIS (Validator)        — audio quality analysis
    │
    ▼
Rating collection → MEMORY write
```

### 3.2 Agent Roles and Constraints

| Agent | Mythological Name | Tools Available | Output Protocol |
|---|---|---|---|
| Genre Guard | Janus | `list_genres` | CONFIRMED block |
| Catalog Manager | Hermes | `catalog_status`, `rebuild_catalog`, `fix_incomplete` | Free text |
| Planner | Muse | `get_catalog`, `propose_playlist` | Free text + playlist |
| Checkpoint | — | `show_playlist`, `swap_track`, `move_track` | PROCEED sentinel |
| Critic | Momus | `show_playlist`, `analyze_transition` | PROBLEMS/VERDICT |
| Editor | — | All except `validate_audio`, `read_memory` | Free text |
| Validator | Themis | `validate_audio` | Status: PASS/WARNING/FAIL |
| Orchestrator | Apollo | All | Manages state |

Tool access is enforced at system prompt level, not at the API schema level — each agent is only shown the tools it is permitted to use. This prevents tool misuse without requiring a separate permission layer.

### 3.3 Structured Text Protocols

Inter-agent communication relies on structured text blocks that can be parsed deterministically with lightweight string routines, avoiding the fragility of asking the LLM to produce JSON and the overhead of schema validation:

**Genre Guard output:**
```
CONFIRMED
genre: techno
duration_min: 60
mood: dark industrial build to a hard peak
```

**Critic output:**
```
PROBLEMS:
- [pos 2→3] key clash 5A → 11A — fix: swap pos 3 for a 6A track
- [pos 7→8] BPM jump 132 → 148 — fix: insert bridge track

VERDICT: NEEDS_FIXES
```

**Validator output:**
```
Status: WARNING
Issues (1):
- [00:34] High spectral flatness (0.47) — possible noise in 30s window
```

Each parser (`_parse_confirmed_block`, `_parse_critic_response`, `_parse_validator_response`) uses simple line-by-line iteration, making them robust to surrounding prose and easy to unit-test.

### 3.4 Tool Schema Auto-Generation

Rather than maintaining hand-written tool schemas, ApolloAgents auto-generates Anthropic and OpenAI tool definitions from Python function signatures and docstrings at runtime:

```python
def _build_properties(fn) -> tuple[dict, list[str]]:
    sig = inspect.signature(fn)
    doc = inspect.getdoc(fn) or ""
    arg_docs = _parse_arg_docs(doc)
    for name, param in sig.parameters.items():
        if name == "context_variables":
            continue  # injected by orchestrator, never exposed to LLM
        ...
```

The `context_variables` parameter is automatically excluded from every tool schema. This means tools can carry orchestrator-managed state without polluting the LLM's parameter space.

---

## 4. Audio Processing Pipeline

### 4.1 Catalog Construction

Track metadata is computed once and stored in `tracks/tracks.json`. For each WAV file:

- **BPM detection**: `librosa.beat.beat_track()` with genre-specific clamping ranges (e.g., techno: 120–160 BPM, lofi-ambient: 60–110 BPM) to correct octave errors common in librosa's beat tracker
- **Key detection**: `librosa.feature.chroma_cqt()` mapped through a Camelot lookup table
- **ID generation**: slugified `genre_folder--display_name` string, stable across catalog rebuilds
- **Variant handling**: tracks sharing a `display_name` (e.g., a full version and a radio edit) share `variant_of` linkage and AI-generated artwork

### 4.2 Playlist Construction

Track selection follows a two-stage process:

1. **BPM clustering** — tracks are sorted by tempo and grouped into ±10 BPM clusters; the largest cluster is selected to ensure rhythmic cohesion
2. **Harmonic sort** — a greedy random walk on the Camelot compatibility graph orders tracks within the cluster, maximising smooth key transitions

The cluster + harmonic walk approach is intentionally stochastic: seeding `random` differently produces valid but varied orderings, giving the Planner agent multiple options to reason about.

### 4.3 Mix Rendering

The mix is assembled with pydub and pyrubberband:

1. Each track is loaded as a pydub `AudioSegment` and attenuated by −3 dB
2. If the BPM difference between consecutive tracks exceeds the threshold, the incoming track is time-stretched to meet in the middle over `TEMPO_RAMP_SEC` seconds using pyrubberband
3. Crossfades of `CROSSFADE_SEC = 12` seconds are applied between tracks
4. A per-crossfade peak check warns if the overlap zone exceeds −0.5 dBFS
5. The complete mix is exported as 32-bit WAV (lossless); normalisation is applied if headroom is available

### 4.4 Audio Quality Validation

THEMIS runs four librosa-based checks on the exported WAV:

| Check | Method | Threshold | Interpretation |
|---|---|---|---|
| Peak clipping | `max(abs(y)) >= 0.98` | Any occurrence | Digital distortion from gain staging |
| Spectral flatness | `librosa.feature.spectral_flatness()` per 30s window | mean > 0.4 | Noise, bleached audio, or excessive compression |
| Silence gaps | RMS < 0.005 for > 2s | Duration > 2s | Dropout, bad crossfade, or missing segment |
| RMS anomaly | 20·log10(rms[w]/rms[w-1]) | Drop > 12 dB | Sudden volume collapse between adjacent windows |

A spectral flatness value near 0 indicates a tonal, music-like signal; values approaching 1 indicate white noise. The 0.4 threshold was empirically calibrated against known-clean mixes and mixes with confirmed bleaching artefacts.

### 4.5 Video Rendering

The video pipeline uses moviepy and Pillow to produce a 1920×1080 24fps video with:

- **Background**: DALL-E 3 generated artwork, prompted per genre with a style-specific template (anime for lofi-ambient, dark-techno cyberpunk for techno, deep-house-neon for deep house). Artwork is deduplicated by `display_name` across sessions.
- **Spectral waveform visualiser**: real-time amplitude envelope with 6-band spectral coloring (sub-bass → treble), rendered per-frame via numpy operations
- **Beat-reactive particles**: 150 particles drifting at 15px/s, alpha-pulsing on detected beats with a 2-second decay envelope
- **Retro pixel titles**: Press Start 2P font with slide-in animation and sinusoidal glow pulse

A YouTube Short (1080×1920, 20 seconds) is generated alongside the full video, pulling the first 20 seconds with fade-in and fade-out and repositioning elements for the vertical aspect ratio.

---

## 5. Session Memory

### 5.1 Design Rationale

A fundamental limitation of stateless LLM agents is that they repeat mistakes. A Planner that proposed a weak track in session 1 will propose it again in session 2 unless given explicit context about its previous performance. ApolloAgents addresses this with a persistent `agent/memory.json` file updated after every rated session.

### 5.2 Memory Schema

```json
{
  "schema_version": 1,
  "sessions": [
    {
      "session_name": "dark-techno-vibe",
      "timestamp": "2026-04-07T20:27:00",
      "genre": "techno",
      "duration_min": 60,
      "mood": "dark build to peak",
      "rating": 4,
      "notes": "peak section worked well",
      "critic_verdict": "NEEDS_FIXES",
      "critic_problems": ["[pos 3→4] key clash — swap track 4"],
      "validator_status": "PASS",
      "validator_issues": [],
      "tracks_swapped": ["Rave Doctrine"],
      "final_playlist": ["Hex Code", "Tesla Coil", "Acid Rain"]
    }
  ]
}
```

The file is capped at 50 sessions (oldest dropped on overflow) and written atomically via a temp file and `os.replace()` to prevent corruption on crash.

### 5.3 Memory Injection

Before each planning session, `read_memory(genre)` computes three summaries from the last 10 genre-matching sessions and injects them into the Planner and Critic system prompts:

1. **Avoid list** — tracks swapped out in 2 or more past sessions (user consistently rejected them)
2. **High-rated patterns** — mood, arc, and track combinations from sessions rated ≥ 4/5
3. **Recurring critic problems** — transition issue patterns appearing in 2 or more sessions

This gives both agents personalised, genre-specific context without requiring the LLM to process raw session history.

### 5.4 Swap Tracking

The orchestrator captures the initial playlist after Phase 3 and computes the symmetric difference with the final playlist before writing the memory record:

```python
tracks_swapped = sorted(
    initial_playlist_names - {t["display_name"] for t in final_playlist}
)
```

This identifies tracks the user chose to remove during editing — a signal stronger than explicit negative feedback, as it reflects revealed preference under time pressure.

---

## 6. Implementation Details

### 6.1 Provider Agnosticism

ApolloAgents supports both Anthropic Claude and OpenAI GPT models through a single `run_agent()` function that branches on the detected provider:

```python
_PROVIDER = "anthropic" if bool(os.getenv("ANTHROPIC_API_KEY")) else "openai"
```

Tool schemas are built separately for each provider format (`_build_anthropic_schemas`, `_build_openai_schemas`) from the same Python function signatures, ensuring consistent behaviour regardless of which LLM is used.

### 6.2 Single-File Core Pipeline

`main.py` (~2,600 lines) contains the entire audio and video pipeline. This was a deliberate architectural choice: for a project of this scope, a single inspectable file with clear section headers is more maintainable than a module hierarchy that would require navigating multiple files for every change. The agent layer (`agent/`) is kept separate because its iteration cycle (prompt engineering, tool signatures, memory schema) differs fundamentally from the DSP pipeline.

### 6.3 Testing Strategy

The test suite covers all pure logic components: Camelot compatibility functions, structured text parsers, and memory read/write behaviour. Components that depend on audio files, API keys, or subprocess execution are excluded from automated tests — these are validated through end-to-end session runs. The boundary is enforced by the `sys.exit()` guard being placed in `run()` rather than at module scope, allowing `agent.run` to be safely imported in test environments without API keys present.

---

## 7. Design Decisions and Trade-offs

### 7.1 No Orchestration Framework

Several multi-agent frameworks exist (LangGraph, AutoGen, CrewAI, AutoAgent) that provide graph-based routing, memory stores, and tool registries. ApolloAgents implements equivalent patterns directly against the provider SDKs. The trade-off is more boilerplate in `run.py` in exchange for no hidden abstractions, no additional dependencies, and full control over the conversation loop — important for a creative application where the exact sequencing of agent responses and checkpoint interactions matters.

### 7.2 Structured Text vs JSON

Requiring the LLM to produce JSON for inter-agent communication introduces fragility: models occasionally produce malformed JSON, trailing commas, or extra explanation text that breaks parsers. Structured text blocks with sentinel keywords (CONFIRMED, VERDICT, Status:) are more robust — partial matches still allow extraction, and fallback defaults (APPROVED, PASS) prevent cascading failures when the model deviates from format.

### 7.3 Checkpoints as First-Class Design

Most automated pipelines treat human review as an afterthought — a final approval gate. ApolloAgents places two interactive checkpoints inside the pipeline, before and after the Critic. This reflects a key insight: the Critic's value is in surfacing problems, not in enforcing fixes. The user may disagree with a Critic recommendation, prefer a different fix, or accept a known issue. Automating the application of Critic feedback would override this judgment. The checkpoints make the pipeline collaborative rather than autonomous.

### 7.4 Lossless Intermediate Format

All intermediate audio is kept as 32-bit WAV. The only lossy encoding step is the final AAC pass at 320kbps during video mux. This ensures that BPM time-stretching artefacts (which accumulate with re-encoding) stay at the minimum possible level, and that the Validator's spectral analysis operates on uncompressed data.

---

## 8. Results and Observations

Over the development period spanning versions 0.0 through 1.0, the following qualitative improvements were observed:

**Audio quality**: The introduction of −3 dB pre-mix gain and the crossfade peak monitor eliminated the spectral bleaching that affected early sessions. THEMIS now consistently reports PASS on sessions produced with default settings.

**Harmonic coherence**: The Camelot-based harmonic sort reduced key clash warnings from appearing in the majority of early sessions to being a rare MOMUS flag, typically appearing only when the catalog lacks compatible options for a specific BPM cluster.

**Agent memory utility**: After 5+ sessions per genre, the avoid list meaningfully constrains the Planner's choices. Tracks that were consistently swapped out — typically those with unusual tempo or poor recording quality — no longer appear in initial proposals.

**Checkpoint value**: User edits at Checkpoint 1 (pre-Critic) typically address energy arc concerns; edits at Checkpoint 2 (post-Critic) address specific transition fixes flagged by MOMUS. Separating these concerns reduces cognitive load compared to presenting all feedback simultaneously.

---

## 9. Future Work

**Per-transition ratings**: The current memory model captures session-level ratings. A finer-grained signal — rating individual transitions immediately after the mix plays — would allow the system to learn which specific key pairs and BPM jumps the user tolerates, rather than inferring it from swap tracking.

**BPM stretch safety bounds**: pyrubberband at ratios beyond approximately 1.5× produces audible artefacts. A pre-mix check that flags tracks requiring extreme stretching and suggests alternatives (via MOMUS or the Editor) would prevent a class of audio quality issues that the current Validator detects but cannot prevent.

**Dynamic energy arc planning**: MUSE currently provides energy arc rationale in prose but does not model the arc quantitatively. Representing the set as a sequence of (energy_level, key, bpm) tuples and using the LLM to reason over this structure explicitly would allow more principled warmup/peak/release planning.

**Genre cross-pollination**: Multi-genre sessions (e.g., a transition from deep house to techno) are not currently supported — the Genre Guard enforces a single genre per session. Relaxing this constraint, while maintaining harmonic and BPM continuity across the boundary, is a natural extension.

---

## 10. Conclusion

ApolloAgents demonstrates that a structured multi-agent pipeline can successfully address the creative and technical complexity of DJ set production. By assigning bounded roles to specialised agents, enforcing structured text protocols for inter-agent communication, and maintaining a persistent session memory, the system produces musically coherent, technically clean mixes with minimal human intervention. The two interactive checkpoints preserve user agency at the moments where subjective musical judgment matters most, while the automated agents handle the combinatorial and analytical work that would otherwise require deep domain expertise.

The full system — agent pipeline, audio DSP, video renderer, and test suite — is available as open source under the MIT License.

---

## References

1. Davis, M. (2004). *The Camelot System for Harmonic Mixing*. Mixed In Key LLC.
2. McFee, B. et al. (2015). *librosa: Audio and Music Signal Analysis in Python*. Proceedings of the 14th Python in Science Conference.
3. Rubber Band Library. Breakfast Quay. https://breakfastquay.com/rubberband/
4. Anthropic. (2024). *Claude API Documentation*. https://docs.anthropic.com
5. OpenAI. (2024). *GPT-4o Technical Report*. https://openai.com/research/gpt-4o
6. HKUDS. (2024). *AutoAgent: Automatic Agent Creation and Coordination Framework*. https://github.com/HKUDS/AutoAgent

---

*ApolloAgents is open source — MIT License. Source code and examples at [github.com/pabloformoso/apollo-agents](https://github.com/pabloformoso/apollo-agents).*
