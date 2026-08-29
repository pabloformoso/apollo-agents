// Seed pattern for the algorave playground — what the editor opens with.
//
// SOURCE OF TRUTH: agent/generative/strudel_mind.py :: FEW_SHOT_DEEPHOUSE
// Copied verbatim on purpose: the page is static, so it cannot read Python at
// run time. tests/test_algorave_playground.py fails if this copy drifts from
// that constant — re-copy it rather than editing it here.
//
// REPL dialect, not a module: one expression, double-quoted mini-notation, and
// no tempo call (the page owns tempo — 122 BPM, cps = 122/60/4).
//
// This WHOLE file — comments included — is what the page sends as the editor
// buffer, and validate.mjs screens it for five reserved words (see its own
// BANNED_TOKEN_RE). One of those written plainly in a comment here rejects the
// pattern before it is ever read as music. It cost a 502 on 2026-08-29.
// reason: seed groove — four-on-floor with the offbeat open hat, rolling A-minor bass
stack(
  s("bd*4").bank("RolandTR909").gain(0.92),
  s("[~ oh]*4").bank("RolandTR909").gain(0.55).pan(0.52),
  s("hh*16").bank("RolandTR909").gain("[0.44 0.38 0.40 0.39]*4").swingBy(1/8, 8).pan(0.46),
  s("~ cp ~ cp").bank("RolandTR909").gain(0.62).room(0.25),
  n("[0 ~] [~ 0] [0 ~] [~ 7] [0 ~] [~ 0] [0 0] [~ 0]").add(n("<0 5>"))
    .scale("A1:minor").s("sawtooth").lpf("<400 400 620 800>").lpq(6)
    .attack(0.005).decay(0.12).sustain(0.35).release(0.08).gain(0.72),
  note("<[a3,c4,e4,g4] [f3,a3,c4,e4]>").struct("~ ~ ~ x ~ ~ ~ x").s("triangle")
    .attack(0.008).decay(0.16).sustain(0.12).release(0.3).lpf(3600).lpq(3)
    .delay(0.4).delaytime(0.1875).delayfeedback(0.32).room(0.55).gain(0.52)
).mul(gain(0.55))
