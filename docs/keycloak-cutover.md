# Switching Apollo over to Keycloak

The order matters. Once `KEYCLOAK_ISSUER` and `KEYCLOAK_CLIENT_ID` are set,
`POST /api/auth/login` starts answering **403**. An account that has no
Keycloak identity yet is then locked out of its own Apollo — including the
operator's.

This is the sequence that avoids that.

## 0. What is already true

The backend derives its mode rather than defaulting: with the variables
unset it behaves exactly as it did before any of this existed. Nothing is
switched on by deploying.

```
AUTH_MODE          : local
login local activo : True
keycloak config    : False
```

## 1. Realm, client, roles

Created on the Keycloak host, not from here. Three realm roles, with these
exact names — they are wired into `web/backend/permissions.py`:

| role | grants |
|---|---|
| `apollo-admin` | everything |
| `apollo-publisher` | publish a take into `tracks/` |
| `apollo-broadcaster` | start a live session |

An account with **no** role can listen, rate and generate. That is the
intended shape for a family account.

## 2. Create your own user in the realm

Then note its **subject id** — the `sub` claim. In the Keycloak admin console
it is the user's ID, a UUID.

## 3. Link your existing local row to it

This is the step that preserves everything. Your row keeps its `id`, and
therefore its ratings, playlists, sessions and published tracks.

```bash
docker compose exec -T backend python -c "
import sys; sys.path.insert(0,'/app/web')
from backend import db
u = db.get_user_by_username('YOUR_USERNAME')
db.link_user_to_keycloak(u['id'], 'THE-KEYCLOAK-SUB-UUID')
print('linked', u['username'], '->', db.get_user_by_id(u['id'])['keycloak_sub'])
"
```

After this the row has no usable password: `link_user_to_keycloak` replaces it
with a sentinel that bcrypt can never match. The account is reachable only
through the realm — which is the point, but it is why this comes *before*
step 4 and not after.

## 4. Turn it on

In the main checkout's `.env`:

```
KEYCLOAK_ISSUER=https://keycloak.pabloformoso.com/realms/apollo
KEYCLOAK_JWKS_URL=http://100.68.5.104:8180/realms/apollo/protocol/openid-connect/certs
KEYCLOAK_CLIENT_ID=apollo-web
NEXT_PUBLIC_KEYCLOAK_ISSUER=https://keycloak.pabloformoso.com/realms/apollo
NEXT_PUBLIC_KEYCLOAK_CLIENT_ID=apollo-web
```

**Why the JWKS URL is separate and internal.** nginx on the Keycloak host
answers **403** to the Apollo container — there is an IP allowlist that admits
the browser and not the Docker network. The container reaches Keycloak
directly on the tailnet at `:8180` instead. The issuer stays the *public*
URL regardless: it is what Keycloak stamps into every token, and the backend
compares it character for character.

Then recreate the backend — `restart` does **not** re-read `env_file`:

```bash
docker compose up -d --no-deps --force-recreate backend
docker compose restart frontend
```

## If it goes wrong

`APOLLO_AUTH_MODE=both` accepts local logins again alongside the realm. It
exists because the realm lives on the same machine as the shared GPU, and
that machine has had a bad week.

## What is not done yet

Logout does not end the realm session — signing out of Apollo leaves the
Keycloak session alive, so the next sign-in goes straight through without a
prompt. `endSessionEndpoint()` is already exported for this.
