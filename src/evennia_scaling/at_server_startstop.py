# SPDX-License-Identifier: BSD-3-Clause
"""Startup hooks, for the install that cannot happen in `AppConfig.ready()`.

`ready()` adds this module to ``AT_SERVER_STARTSTOP_MODULE``, so a consumer
installs nothing. That setting is a list of modules rather than a class to
subclass — the game's own ``server/conf/at_server_startstop.py`` stays in the
list and its hooks still run.

See docs/test-plan.md § LK.
"""


def at_server_init():
    """Point Evennia's channel command at ours.

    The earliest hook Evennia calls, and late enough: `evennia._init()` has
    run by now, so `comms` — which reaches Evennia's lazy ``Command`` export
    through `evmenu` — imports without raising.

    The import is inside the function rather than at module scope because
    this module is imported while `_init()` is still running, building the
    Server service.

    The swap itself is the same one the account commands get: Evennia's
    cmdsets read the module attribute when a session's cmdset is built.
    """
    from evennia.commands.default import comms

    from .channel_command import ScalingCmdChannel

    comms.CmdChannel = ScalingCmdChannel
