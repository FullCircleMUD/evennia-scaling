# SPDX-License-Identifier: BSD-3-Clause
"""Settings this library reads, each behind an accessor.

Settings are read here and nowhere else, so a default lives in one place and
a consumer overriding one changes every reader at once.
"""

SETTING_TICKET_LIFETIME = "SCALING_TICKET_LIFETIME_SECONDS"

#: How long a stored ticket stays redeemable, in seconds. The session is moved
#: over a live AMP link and arrives immediately, so a ticket is normally
#: redeemed in the same breath as it is written. What this covers is the case
#: where nobody arrives — a player who drops mid-move — and the only cost of
#: that is a row nobody sweeps until the next one is stored.
DEFAULT_TICKET_LIFETIME = 10


def get_ticket_lifetime() -> int:
    """Return ``SCALING_TICKET_LIFETIME_SECONDS``, defaulting to 10."""
    from django.conf import settings

    return int(
        getattr(settings, SETTING_TICKET_LIFETIME, DEFAULT_TICKET_LIFETIME)
    )


SETTING_ROUTER_ID = "SCALING_ROUTER_ID"

#: Which instance holds the accounts. A shard sends a session back to the
#: router whenever it cannot admit it, and cannot work out which of its peers
#: that is: instances share no database and no settings, so nothing a shard
#: can read names one. It has to be told.
#:
#: Unlike `SCALING_ROLE` this has a default. `router` is a sensible guess, and
#: a deployment that named its router something else is a deployment that will
#: say so.
DEFAULT_ROUTER_ID = "router"


def get_router_id():
    """Return ``SCALING_ROUTER_ID``, defaulting to ``router``."""
    from django.conf import settings

    return getattr(settings, SETTING_ROUTER_ID, DEFAULT_ROUTER_ID)


SETTING_ROLE = "SCALING_ROLE"

#: A router is where players log in and choose a character; a shard is where a
#: character is played. There is no third role. `evennia-shards` carries a
#: dormant `monolith` mode so a game can be built on it and grow into a split
#: deployment later; the equivalent is out of scope here, because installing
#: this library means at least a router and one shard.
ROLE_ROUTER = "router"
ROLE_SHARD = "shard"
ROLES = (ROLE_ROUTER, ROLE_SHARD)


def get_role():
    """Return this instance's role, refusing anything that is not one.

    Deliberately has no default. An accessor normally supplies one so a
    consumer who declared nothing still works, but there is no harmless
    default available here — with no monolith mode, an instance that does not
    know whether it is a router or a shard cannot do anything correct. So an
    undeclared role is a refusal rather than a guess, which is the position
    `evennia-message-bus` takes on its instance id for the same reason.

    `AppConfig.ready()` calls this, so the refusal happens at boot rather than
    wherever something first needs the role.
    """
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    role = getattr(settings, SETTING_ROLE, None)
    if role is None:
        raise ImproperlyConfigured(
            f"{SETTING_ROLE} is not set. Every instance running "
            f"evennia-scaling is either {ROLE_ROUTER!r} or {ROLE_SHARD!r}, "
            f"and there is no default — an instance that does not know which "
            f"it is cannot route a session or hold a character correctly."
        )
    if role not in ROLES:
        raise ImproperlyConfigured(
            f"{SETTING_ROLE} is {role!r}, which is not a role. Valid values "
            f"are {ROLE_ROUTER!r} and {ROLE_SHARD!r}."
        )
    return role
