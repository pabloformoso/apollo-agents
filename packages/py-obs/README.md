# deus-obs

OpenTelemetry traces for LLM applications, exported over OTLP/HTTP to any
collector that speaks it — Arize Phoenix, Jaeger, an OpenTelemetry Collector.

Two properties are the point of the package:

1. **Unconfigured costs stdlib only.** `import deus_obs` pulls no third-party
   module, and `install()` with no endpoint returns *before* the
   `opentelemetry` import. Median of 7 fresh interpreters on the machine this
   was written on:

   | | |
   |---|---|
   | `python -c pass` | 9.7 ms |
   | `import deus_obs; install()` — unconfigured | 25.0 ms |
   | `import opentelemetry.sdk` + the OTLP/HTTP exporter | 101.6 ms |
   | `import deus_obs; install(endpoint)` — configured | 107.1 ms |

   ~80 ms per process, and it would otherwise be paid by every pytest
   collection and every CLI run in a repo where most processes never emit a
   span. (Of the 15 ms this package does cost, all of it is `dataclasses` and
   `typing`, already imported by most applications.)
2. **It is not this project's.** The name is deliberately not `apollo_*`.
   Lifting it into the next service is a directory copy — see
   [Taking it elsewhere](#taking-it-elsewhere).

```python
import deus_obs

cfg = deus_obs.install()        # reads the environment; returns what it did
print(cfg.status_line())        # -> deus_obs: tracing -> http://…/v1/traces (project=apollo)

@deus_obs.tool                  # transparent when unconfigured, and always to reflection
def pick_track(genre: str, context_variables: dict) -> str:
    ...

with deus_obs.session_scope(session_id, user_id=user):
    with deus_obs.span("build_playlist", genre=genre):
        ...

deus_obs.shutdown()             # flush, then stop
```

## Install

```bash
pip install deus-obs           # helpers + no-ops. Zero dependencies.
pip install deus-obs[otel]     # + the SDK and the OTLP/HTTP exporter
pip install deus-obs[llm]      # + OpenInference instrumentors (nothing imports these yet)
```

`deus-obs` on its own is a working, permanently-disabled installation. That is
a supported state, not a broken one: it is what a CI job or a batch script
should have.

## Configuration

Everything is environment variables. Nothing is required.

| Variable | Default | What it does |
|---|---|---|
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | — | Full traces URL, used **verbatim**. Highest-priority env var. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | Collector **base** URL. `/v1/traces` is appended in code. |
| `OBS_ENDPOINT` | — | Same as above, friendlier name. Lowest-priority endpoint. |
| `OBS_PROJECT` | value of `OBS_SERVICE` | Phoenix project the spans land in (`openinference.project.name`). |
| `OBS_SERVICE` | `unknown-service` | `service.name` on the resource. |
| `OBS_ENABLED` | `true` | `false`/`0`/`no`/`off` disables everything, endpoint or not. |
| `OBS_CAPTURE` | `metadata` | `off` \| `metadata` \| `preview` \| `full` — see below. |
| `OBS_SAMPLE_RATIO` | `1.0` | `ParentBased(TraceIdRatioBased(r))`. Clamped to `[0,1]`; a typo reads as `1.0`. |
| `OBS_CONSOLE` | `false` | Also print spans to stdout. Debugging only. |

Precedence for the endpoint, highest first:

```
install(endpoint=…)                  base URL, + /v1/traces
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT   verbatim
OTEL_EXPORTER_OTLP_ENDPOINT          base URL, + /v1/traces
OBS_ENDPOINT                         base URL, + /v1/traces
(nothing)                            no-op
```

Only the signal-specific variable is verbatim, because that is what the
OpenTelemetry environment specification says it means. Getting this backwards
gives you `…/v1/traces/v1/traces`, a 404 the exporter logs on a background
thread, and an application that looks completely healthy.

### `OBS_CAPTURE` fails closed

| Level | Inputs | Outputs |
|---|---|---|
| `off` | nothing | nothing |
| `metadata` *(default)* | argument **names** | return **type** |
| `preview` | values, `repr`, truncated to 256 chars | same |
| `full` | values, `repr`, capped at 32 KB | same |

The default is `metadata` because the instrumentation libraries in this space
default the other way and record whole prompts and whole tool payloads. In this
project a tool's arguments include `context_variables`, which carries API keys,
and the trace store is shared with two other projects. At `preview` and `full`,
argument names matching `context_variables`, `api_key`, `secret`, `token`,
`password`, `authorization`, `credential` or `private` have their values
replaced with `<redacted>` — but the level itself is the real control.

## API

Ten names. Everything else in the package is an implementation detail.

| | |
|---|---|
| `install(endpoint=None, *, project=None, service=None)` | Configure the process. Returns the **effective** `ObsConfig` — never raises, never prints. |
| `shutdown()` | Flush, then stop the provider. Call it from your shutdown path. |
| `flush()` | Push the batch buffer now. Returns whether there was a provider to ask. |
| `tracer(name=None)` | A tracer. Never `None`; a no-op when unconfigured. |
| `span(name, *, kind=None, **attrs)` | Context manager. |
| `tool` / `chain` / `agent` | Decorators. Bare, `@tool("name")` or `@tool(name=…)`. |
| `session_scope(session_id, *, user_id=None, **metadata)` | Context manager; stamps every span inside, including ones this package did not open. |
| `current_trace_id()` | 32 hex chars or `None` — a handle to put in a log line. |

`install()` returns a config rather than a tracer so the host can print one
honest startup line: a tracer cannot tell you whether the SDK was importable or
which project the spans will land in. `tracer()` is there for the other need.

### The decorators are transparent, including to reflection

`functools.wraps` sets `__wrapped__`, so `inspect.signature` follows through to
the original — asserted explicitly in `tests/test_decorators.py`. This is
load-bearing here: Apollo builds the tool schemas it hands to Claude and GPT by
reflecting over `inspect.signature`, `__name__` and `inspect.getdoc`
(`agent/run.py`). A wrapper that lost the signature would raise nothing and
hand every model a tool with no parameters.

They wrap even when telemetry is disabled, rather than returning the function
unchanged, because decoration happens at import time and `install()` happens
later — deciding at import time would decide "never" for the whole process. The
disabled path is one `is None` test against a module global.

Generator and async-generator functions are returned **unchanged**. A span
around one of those opens when the generator is created and closes on the first
`next()`, so it would time the setup and attribute none of the work: a span that
is present, plausible and wrong.

## Notes on the shape of this package

**Why not `arize-phoenix-otel`.** It is Phoenix's documented path and it does
two things: `Resource.create({"openinference.project.name": …})` and
`BatchSpanProcessor(OTLPSpanExporter(…))`. That is fifteen lines, which are in
`runtime.py`. Taking the dependency would put a vendor's name inside a package
whose whole premise is that it moves between projects, and would pin this code
to that vendor's release cadence for a string constant. If you are here to
"fix" this by adding it: the two lines it would replace are
`runtime._install_sdk`, and the project name is one `Resource` attribute.

**Why `opentelemetry-exporter-otlp-proto-http` and not `opentelemetry-exporter-otlp`.**
The meta-package also pulls the gRPC exporter and `grpcio`, a ~10 MB C
extension, to reach a port that the standard Phoenix image `EXPOSE`s and does
not publish. Paying for a wheel that cannot reach the collector.

**Why `BatchSpanProcessor`, always.** `SimpleSpanProcessor` puts an HTTP
round-trip in the caller's thread on every span, so every tool call would pay
the collector's latency. The one exception is `OBS_CONSOLE`, where there is no
round-trip and batching would defeat the point.

**Why `install()` never prints.** A library that writes to stdout has taken a
decision away from the application it was supposed to observe. The host prints
`cfg.status_line()`, or logs it, or ignores it.

## Taking it elsewhere

`packages/py-obs/` is self-contained and has no import of anything outside
itself. To lift it:

1. Copy the directory. Nothing in it mentions the host project.
2. Add it to the new project's dependencies. With `uv`, a path source:
   ```toml
   [dependency-groups]
   obs = ["deus-obs[otel]"]

   [tool.uv.sources]
   deus-obs = { path = "packages/py-obs", editable = true }
   ```
   Keep it out of the default groups. Then "no-op when unconfigured" is
   enforced by the CI job never installing the SDK at all, rather than by a
   runtime flag someone can flip by accident.
3. Call `install()` at startup, print `status_line()`, call `shutdown()` on the
   way out. `shutdown()` is not optional: the batch exporter ships on a
   five-second schedule, and under uvicorn's exit path the SDK's own `atexit`
   hook observably loses the last spans — a trace store that holds everything
   except the end of a session looks like coverage.
4. Set `OBS_PROJECT`. On a shared collector, the default project is where
   everyone's spans go to become unreadable.

### Containers

If the collector runs on the host and the app runs in a container, `localhost`
in an inherited `.env` means *the container*. The app posts to itself, gets
connection-refused on a background thread, drops every span, and looks healthy.
Close it in the compose file rather than in documentation:

```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      OTEL_EXPORTER_OTLP_ENDPOINT: "${APOLLO_OTLP_ENDPOINT:-}"
```

`environment:` wins over `env_file:`, and interpolating a *differently named*
variable means the host's `OTEL_*` value cannot leak in through the back door.

## Tests

```bash
pytest                 # with deus-obs installed plain: the otel tests skip
pytest                 # with deus-obs[otel]: they run
```

Both invocations must pass. The suite is written to be run twice, and the tests
that assert "nothing was imported" run in subprocesses, because `sys.modules` in
a pytest process is already full and `set_tracer_provider` is set-once.
