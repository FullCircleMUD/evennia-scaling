"""
Settings for shard0 — a Server attached to the router's Portal.

Usage, from the `shard0/` directory:

    evennia server_start --settings settings_shard0

**Only that verb.** AMP_PORT below points at the router's Portal, and the
launcher uses AMP_PORT to reach a Portal as well — so `evennia start`,
`stop`, `reload` or `istart` from this directory all issue instructions to
the **router's** Portal. `istart` in particular stops the Server that Portal
already has, which is the router's. `server_start` exists because it sends
nothing to any Portal at all.

Cascade:
    settings_shard0.py (this file)
        -> settings_common.py
            -> settings.py

A shard is where a character is played. The out-of-character game belongs to
the router, so a session this instance cannot admit goes back there.
"""

from server.conf.settings_common import *  # noqa: F401, F403

SERVERNAME = "Shard0"

SCALING_ROLE = "shard"

# Its own name: the only per-instance literal. Named once, for the library
# that asks first, and pointed at by the other.
MULTIPLEX_INSTANCE_ID = "shard0"
MESSAGEBUS_INSTANCE_ID = MULTIPLEX_INSTANCE_ID

# Never listened on: this instance runs no Portal. They are set, and set
# distinctly, so that starting it fully by accident fails on something
# obvious rather than on three instances silently fighting over port 4000.
TELNET_PORTS = [4020]
WEBSERVER_PORTS = [(4021, 4025)]
WEBSOCKET_CLIENT_PORT = 4022

# The router's Portal, not one of ours. This is what makes this Server attach
# there — and what makes every other launcher verb from this directory reach
# across to the router.
AMP_PORT = MULTIPLEX_AMP_PORT  # noqa: F405
