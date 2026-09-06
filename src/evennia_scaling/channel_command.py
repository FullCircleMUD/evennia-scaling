# SPDX-License-Identifier: BSD-3-Clause
"""The channel command's override, kept out of `commands.py`.

`evennia.commands.default.comms` imports `evmenu`, which builds a class from
Evennia's lazy ``Command`` export — not populated until `evennia._init()` runs
*after* ``django.setup()``. Importing `comms` at a module's own top level is
fine; importing that module from `AppConfig.ready()` is what raises. So this
one lives apart from `commands.py`, which `ready()` does import.

`at_server_startstop.at_server_init` installs it.

See docs/test-plan.md § LK.
"""

from evennia.commands.default.comms import CmdChannel

#: The switches that write to the account: the subscription itself, and
#: channel aliases, which are stored as nicks. Everything else is left
#: alone — `mute`/`unmute` write to the channel rather than the account,
#: the channel-management switches are already staff-locked, and
#: `list`/`all`/`history`/`who` only read.
ACCOUNT_SWITCHES = frozenset({"sub", "unsub", "alias", "unalias"})


class ScalingCmdChannel(CmdChannel):
    """Four switches restricted, not the command.

    Evennia's lock is kept. Locking the whole command would take channels
    away in character entirely: sending carries no switch, so a player
    would be able to read a channel and not answer on it.

    What is on the account is which channels you receive and what you call
    them, and a shard's copy of the account is discarded — so those four
    have to be made out of character or the change vanishes with nothing
    in any log.
    """

    def func(self):
        if ACCOUNT_SWITCHES.intersection(self.switches) and self.session.puppet:
            self.msg(
                "You have to be out of character to change which channels "
                "you are on. You can still talk and listen from here."
            )
            return
        return super().func()
