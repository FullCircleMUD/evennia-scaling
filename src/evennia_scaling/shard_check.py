# SPDX-License-Identifier: BSD-3-Clause
"""`shard_check` — which instance this session is on.

`at_server_startstop.at_server_init` adds it to Evennia's `AccountCmdSet`, so
it is there out of character and, merged into the puppet's, in character.

See docs/test-plan.md § CK.
"""

from evennia.commands.command import Command
from evennia_portal_multiplex.config import get_instance_id

from .config import get_role


class CmdShardCheck(Command):
    """Say which instance you are on.

    Usage:
      shard_check
    """

    key = "shard_check"
    locks = "cmd:perm(Developer)"
    help_category = "System"

    def func(self):
        self.caller.msg(f"You are on {get_instance_id()} ({get_role()}).")
