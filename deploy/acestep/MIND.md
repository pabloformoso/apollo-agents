# Managed Mind and Settings

The existing single-worker ACE supervisor also exposes authenticated `/v1/mind`
routes. Apollo proxies these through `/api/mind`; only administrators can change
settings or residency. Browser inference uses the authenticated same-origin
`/api/algorave/mind` gateway. The former `ALGORAVE_MIND_URL` override is no longer
used: the managed host service is loopback-only on port 4032.

## Host installation

Install `apollo-mind.service` beside `apollo-ace-control.service` in the user's
systemd unit directory, then run `systemctl --user daemon-reload`. Check the Node
version in its PATH matches the host installation. The main checkout needs its
Python virtualenv and `scripts/algorave-spike/node_modules` dependencies installed.
LM Studio must be running at localhost:1234, with the `lms` executable available
at `~/.lmstudio/bin/lms`. Restart the ACE controller only when no host operation
or Mind request is active; keep exactly one worker. Do not enable Mind at boot.

Settings persist atomically with mode 0600 at
`~/.config/apollo/mind-settings.json` (`APOLLO_MIND_SETTINGS_PATH` can override it
in the controller's environment). Secrets and server addresses stay in deployment
configuration, not the web form.

## Operator workflow

Open Model management in Algorave without leaving the performance, or Settings
in the main navigation. Choose an installed model, context and GPU offload; save,
then Start Mind and Load model. Saving does not reload a model. To change a loaded
model, Unload model and Load model after saving. Start/stop controls only the HTTP
service. Load/unload controls only the reserved LM Studio identifier `apollo-mind`;
other applications must not use that identifier.

Shared GPU is off by default. Enable it explicitly to permit ACE and Mind together.
Offload is a fraction of model layers, **not a VRAM cap**: memory fit depends on
both models, context and inference. Zero offload uses CPU. Other loaded models
still block ACE admission. Nothing automatically stops ACE or unloads other models.

In-flight managed inference blocks model changes, even after the browser disconnects.
Model-operation timeouts are uncertain: do not blindly retry. Verify `lms ps --json`
and the LM Studio server logs first. A timed-out load can reconcile when its alias
appears; unresolved unloads require operator verification and controller restart
after the operation has genuinely finished. Avoid controller restarts during work.

Rollout must wait for a performance-safe window: frontend reloads may interrupt
browser audio. This feature does not restore autoplay or automatically resume B2B.
