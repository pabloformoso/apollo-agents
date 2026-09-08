"""What an account is allowed to do, from its Keycloak realm roles.

Apollo's endpoints used to check one thing: is this a logged-in user.
That was enough while there was one account. With a realm handing out
accounts — including ones for children — some actions need to stay with
the operator, because they are not "more data", they are shared,
expensive or public:

* **publishing to the catalog** writes into ``tracks/``, which every
  future session of every user then draws from.
* **starting a live session** goes out on air and holds the shared
  16 GB GPU for hours. That is exactly what starved ACE-Step of VRAM on
  2026-09-07 and made generation fail with an unexplained error.

Listening, rating and generating are per-user and reversible, so they
are granted to everyone the realm lets in.

Roles are read from ``realm_access.roles`` only. Client roles are
ignored on purpose: one place decides what a person can do, and it is
the realm.
"""
from __future__ import annotations

import os

#: Realm role granting everything. Named after the deployment rather
#: than the person, so a second operator is a role assignment.
ADMIN_ROLE = os.getenv("KEYCLOAK_ADMIN_ROLE") or "apollo-admin"

#: Capabilities, as referenced by the endpoints that guard them.
PUBLISH_TO_CATALOG = "publish_to_catalog"
START_LIVE_SESSION = "start_live_session"
GENERATE_MUSIC = "generate_music"
LISTEN_AND_RATE = "listen_and_rate"

#: Granted to every authenticated account, no role needed. These are
#: per-user and reversible: a bad rating is a bad rating, not a mess
#: anyone else has to clean up.
BASE_CAPABILITIES: frozenset[str] = frozenset(
    {LISTEN_AND_RATE, GENERATE_MUSIC}
)

#: Capabilities that need an explicit realm role.
ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "apollo-publisher": frozenset({PUBLISH_TO_CATALOG}),
    "apollo-broadcaster": frozenset({START_LIVE_SESSION}),
}

ALL_CAPABILITIES: frozenset[str] = BASE_CAPABILITIES | frozenset(
    c for caps in ROLE_CAPABILITIES.values() for c in caps
)


def capabilities_for(roles: set[str] | None) -> frozenset[str]:
    """What an account holding ``roles`` may do.

    ``None`` means an account with no realm behind it — a local row from
    before the realm existed. It keeps everything, so adding this module
    is not a breaking change. An empty SET, by contrast, is a realm
    account holding no roles: it listens and generates, nothing more.
    """
    if roles is None:
        # No realm behind this account, so it predates the realm — it is
        # the operator's own local login. Granting it everything is what
        # keeps this module from being a breaking change: nothing that
        # worked before roles existed stops working. Once a deployment is
        # pointed at a realm, every account arrives WITH a role set (even
        # an empty one) and the grants below apply.
        return ALL_CAPABILITIES
    if ADMIN_ROLE in roles:
        return ALL_CAPABILITIES
    granted = set(BASE_CAPABILITIES)
    for role in roles:
        granted |= ROLE_CAPABILITIES.get(role, frozenset())
    return frozenset(granted)


def has_capability(user: dict, capability: str) -> bool:
    """Whether ``user`` may do ``capability``.

    Reads the capability set that ``get_current_user`` attached to the
    user dict at authentication time. A user dict without one is treated
    as base-only rather than as all-powerful — an unauthenticated path
    that reaches here must fail closed.
    """
    caps = user.get("capabilities")
    if not isinstance(caps, (set, frozenset)):
        caps = BASE_CAPABILITIES
    return capability in caps
