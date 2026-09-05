"""
Settings for the router — the instance whose Portal every Server attaches to.

Usage, from the `router/` directory:

    evennia start --settings settings_router

Cascade:
    settings_router.py (this file)
        -> settings_common.py
            -> settings.py

This is the only instance that runs a Portal, and the only one started
normally. It must be running before a shard can attach: `evennia server_start`
needs a live Portal at the address it dials.

It is also where players log in and choose a character — the accounts live
here, and a shard holds none of its own.
"""

from server.conf.settings_common import *  # noqa: F401, F403

SERVERNAME = "Router"

SCALING_ROLE = "router"

# Its own name is the shared one, because it is the instance being named.
# An assignment rather than a second "router" that would have to match.
MULTIPLEX_INSTANCE_ID = MULTIPLEX_DEFAULT_INSTANCE  # noqa: F405
MESSAGEBUS_INSTANCE_ID = MULTIPLEX_INSTANCE_ID

TELNET_PORTS = [4000]
WEBSERVER_PORTS = [(4001, 4005)]
WEBSOCKET_CLIENT_PORT = 4002

# This instance's Portal listens here; the shards dial it.
AMP_PORT = MULTIPLEX_AMP_PORT  # noqa: F405
