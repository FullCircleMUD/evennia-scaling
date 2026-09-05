"""
Settings for shard1 — a Server attached to the router's Portal.

Usage, from the `shard1/` directory:

    evennia server_start --settings settings_shard1

**Only that verb.** AMP_PORT below points at the router's Portal, and the
launcher uses AMP_PORT to reach a Portal as well — so `evennia start`,
`stop`, `reload` or `istart` from this directory all issue instructions to
the **router's** Portal. `istart` in particular stops the Server that Portal
already has, which is the router's. `server_start` exists because it sends
nothing to any Portal at all.

Cascade:
    settings_shard1.py (this file)
        -> settings_common.py
            -> settings.py

A shard is where a character is played. It holds no accounts of its own — a
session it cannot admit goes back to the router.
"""

from server.conf.settings_common import *  # noqa: F401, F403

SERVERNAME = "Shard1"

SCALING_ROLE = "shard"

# Its own name: the only per-instance literal. Named once, for the library
# that asks first, and pointed at by the other.
MULTIPLEX_INSTANCE_ID = "shard1"
MESSAGEBUS_INSTANCE_ID = MULTIPLEX_INSTANCE_ID

# Never listened on: this instance runs no Portal. They are set, and set
# distinctly, so that starting it fully by accident fails on something
# obvious rather than on three instances silently fighting over port 4000.
TELNET_PORTS = [4030]
WEBSERVER_PORTS = [(4031, 4035)]
WEBSOCKET_CLIENT_PORT = 4032

# The router's Portal, not one of ours. This is what makes this Server attach
# there — and what makes every other launcher verb from this directory reach
# across to the router.
AMP_PORT = MULTIPLEX_AMP_PORT  # noqa: F405
