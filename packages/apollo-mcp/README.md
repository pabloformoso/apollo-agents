# apollo-mcp

An MCP server over Apollo's REST API, so an agent can generate with ACE-Step,
poll, download and review takes. It is a CLIENT of a running Apollo: it
imports nothing from the backend and needs no deploy.

It signs in **as the operator** (device-code login through the Apollo realm),
so its generations land in the operator's own `/generations` feed.

## What it can and cannot do

| Tool | Endpoint |
|---|---|
| `login_status` | local token file — never returns the token |
| `apollo_status` | `GET /api/generator/health` + `GET /api/generator/service` |
| `list_genres` | `GET /api/generator/genres` |
| `ace_service(start\|stop)` | `POST /api/generator/service/{action}` |
| `generate` | `POST /api/generator/tasks` |
| `get_task`, `wait_for_task` | `GET /api/generator/tasks/{id}` |
| `download_take` | `GET /api/generator/audio` |
| `list_generations`, `mark_take` | `GET /api/generator/generations`, `PATCH …/takes/{idx}` |
| `critique_take` | `POST /api/generator/critique` |
| `search_catalog`, `list_sessions` | `GET /api/catalog`, `GET /api/sessions` (read-only) |

**Not exposed, by design**: publishing to the catalog, edits, anything live,
YouTube, deleting. The token the MCP holds CAN do all of those — the
operator's capabilities come with the sign-in — so the limit is the tool list
itself: there is no code path from here to those endpoints. Before anything
that loads ACE (`generate`, `ace_service start`) the server also asks whether
a set is on air and refuses first; the backend's own 409 is the real guard.

## Setup

### 1. A realm client (once, in the Keycloak console)

Realm `apollo` → Clients → Create:

- Client ID `apollo-mcp`, **Client authentication OFF** (public client).
- Authentication flow: only **OAuth 2.0 Device Authorization Grant**.
- Client scopes → `apollo-mcp-dedicated` → Add mapper → *Audience*:
  included client audience `apollo-web`, add to access token ON.

The audience mapper is not optional: Apollo verifies that a realm token is
for `apollo-web` (`aud`, or `azp` when `aud` is absent), so without it the
exchange answers *"Apollo refused the realm token: Invalid identity token"*.
A separate client rather than enabling the device grant on `apollo-web`:
the browser's client stays exactly as it was, and the MCP's sessions can be
listed and revoked on their own.

### 2. Sign in (once a week)

```bash
uv run --project packages/apollo-mcp apollo-mcp login
```

It prints a URL; approve it in a browser. The realm token is traded at
`POST /api/auth/keycloak` for Apollo's own token, which lives **a week**
(the realm refresh token dies with the SSO session — 30 min idle by
default — so it is only used while it is still alive). Both are stored in
`~/.config/apollo-mcp/token.json`, mode 0600. That file is the operator's
key to Apollo for a week: `apollo-mcp logout` deletes it.

`apollo-mcp status` says whether it is still valid.

### 3. Register it with Claude Code

```bash
claude mcp add apollo -- uv run --project /home/pablo/code/apollo-agents/packages/apollo-mcp apollo-mcp
```

## Configuration

| Variable | Default |
|---|---|
| `APOLLO_MCP_BASE_URL` | `https://apollo.pabloformoso.com` (on jarvis, `http://127.0.0.1:4020` also works) |
| `APOLLO_MCP_ISSUER` | `https://keycloak.pabloformoso.com/realms/apollo` |
| `APOLLO_MCP_CLIENT_ID` | `apollo-mcp` |
| `APOLLO_MCP_TOKEN_FILE` | `~/.config/apollo-mcp/token.json` |
| `APOLLO_MCP_DOWNLOAD_DIR` | `~/.local/share/apollo-mcp/takes` |

## Tests

```bash
cd packages/apollo-mcp && uv run --extra test pytest
```

Against a mocked API (`respx`); nothing real is called.
