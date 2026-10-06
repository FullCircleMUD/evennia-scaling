# SPDX-License-Identifier: BSD-3-Clause
"""Startup hooks, for the install that cannot happen in `AppConfig.ready()`.

`ready()` adds this module to ``AT_SERVER_STARTSTOP_MODULE``, so a consumer
installs nothing. That setting is a list of modules rather than a class to
subclass — the game's own ``server/conf/at_server_startstop.py`` stays in the
list and its hooks still run.

See docs/test-plan.md § LK.
"""


def at_server_init():
    """Point Evennia's channel and teleport commands at ours.

    The earliest hook Evennia calls, and late enough: `evennia._init()` has
    run by now, so `comms` — which reaches Evennia's lazy ``Command`` export
    through `evmenu` — imports without raising.

    The import is inside the function rather than at module scope because
    this module is imported while `_init()` is still running, building the
    Server service.

    The swap itself is the same one the account commands get: Evennia's
    cmdsets read the module attribute when a session's cmdset is built.
    """
    # The module whose `CmdChannel` attribute is being replaced. Imported
    # here rather than at module scope because `comms` pulls in `evmenu`,
    # which needs `evennia._init()` to have run.
    from evennia.commands.default import comms

    from .channel_command import ScalingCmdChannel

    comms.CmdChannel = ScalingCmdChannel

    # `building` imports `evmenu` too, so `tel/shard` is installed here for
    # the same reason, by the same swap.
    from evennia.commands.default import building

    from .teleport import ScalingCmdTeleport

    building.CmdTeleport = ScalingCmdTeleport

    _install_shard_check()


def _install_shard_check():
    """Add `shard_check` to Evennia's `AccountCmdSet`.

    A new command rather than a replacement, so there is no module attribute
    to repoint: the cmdset's creation hook is wrapped instead. Here rather than
    in `ready()` for the channel override's reason — `cmdset_account` imports
    `comms`. Guarded, because the hook can run more than once.
    """
    from evennia.commands.default.cmdset_account import AccountCmdSet

    from .shard_check import CmdShardCheck

    if getattr(AccountCmdSet, "_scaling_shard_check_installed", False):
        return

    original = AccountCmdSet.at_cmdset_creation

    def at_cmdset_creation(self):
        original(self)
        self.add(CmdShardCheck())

    AccountCmdSet.at_cmdset_creation = at_cmdset_creation
    AccountCmdSet._scaling_shard_check_installed = True
