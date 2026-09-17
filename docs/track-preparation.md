# Automatic preparation after publishing

Publishing from Generations now writes `processing_status: queued` in the
initial catalog entry. The web backend's single preparation worker then runs
one CPU analysis subprocess at a time, with a 15-minute timeout and two BLAS
threads. It reuses the pipeline's duration, madmom downbeat, waveform and MP3
functions; it does not run a full catalog rebuild or use the GPU.

The state is durable in `tracks.json`: queued → running → ready / failed.
Interrupted running jobs are requeued at startup. Failed jobs wait for an
explicit retry. The worker defers starting another analysis while a live
WebSocket session exists. A live session started during analysis does not
cancel that CPU-only analysis.

The Generations take row shows the persisted status after publication and
after reopening the library. GET `/api/generator/tracks/{id}/processing`
requires authentication; POST to the same path requires `publish_to_catalog`
and queues a failed or previously unprepared track, idempotently. Existing
catalog tracks are not mass-enqueued: previously published takes can use
“Prepare audio for sessions”. No ACE service is needed to analyse the copied WAV.

Automatic session selection excludes any track with an explicit processing
state other than ready. Legacy catalog eligibility remains unchanged. The
existing manual playlist override is unchanged; an operator can still choose
a track explicitly. Tracks are never deleted on an analysis failure.

Ready requires duration, a madmom-sourced grid, peaks and a completed MP3.
Unavailable dependencies, encoding failures or unreliable beat detection
leave an actionable failed status rather than silently accepting the librosa
fallback. Especially sparse ambient audio may not produce a reliable grid;
retrying the same audio does not guarantee a different detection result.

Web publishes and preparation commits use a common in-process lock. Catalog
writes are atomic, preserve permissions, and analysis merges only its results
into a freshly read catalog. This requires the existing single-backend-worker
deployment. Do not run CLI catalog writers concurrently; a shared database
catalog / cross-process coordination remains separate work.

Deploy through a green PR and restart the backend in a window without a live
session to start its lifespan worker. Verify with a newly published take,
observe ready/failed in the UI, and confirm ready metadata is persisted. The
current Jarvis backend imports madmom successfully and has ffmpeg installed.
No production catalog processing was triggered during implementation.
