"""Reasoned generative MIDI engine — spike core.

Two-plane architecture (docs/reasoned-generative-engine.md):

- FAST PLANE (pure Python, real-time): spec.py -> interpreter.py -> clock.py
  -> dispatch.py. No LLM anywhere in the tick path.
- SLOW PLANE (LLM, phrase cadence): state.py -> mind.py, emits the next
  pattern-spec plus a machine-readable `reason`.

The hand-off between planes is data (a validated PatternSpec), never audio.
Everything except dispatch.py is import-safe without the optional `synth`
dependency group (mido / python-rtmidi).
"""
