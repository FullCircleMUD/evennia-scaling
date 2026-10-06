# SPDX-License-Identifier: BSD-3-Clause
"""`tel/shard` — Evennia's `tel`, with a switch for changing instance.

`at_server_startstop.at_server_init` installs it, because `building` imports
`evmenu`, which needs `evennia._init()` to have run.

See docs/test-plan.md § TP.
"""

# The command being subclassed. Safe at module scope here — this module is
# only imported from `at_server_init`, never from `AppConfig.ready()`.
from evennia.commands.default.building import CmdTeleport


class ScalingCmdTeleport(CmdTeleport):
    """
    teleport object to another location, or yourself to another shard

    Usage:
      tel/switch [<object> to||=] <target location>
      tel/shard <shard>

    Examples:
      tel Limbo
      tel/quiet box = Limbo
      tel/tonone box
      tel/shard shard1

    Switches:
      quiet  - don't echo leave/arrive messages to the source/target
               locations for the move.
      intoexit - if target is an exit, teleport INTO
                 the exit object instead of to its destination
      tonone - if set, teleport the object to a None-location. If this
               switch is set, <target location> is ignored.
               Note that the only way to retrieve
               an object from a None location is by direct #dbref
               reference. A puppeted object cannot be moved to None.
      loc - teleport object to the target's location instead of its contents
      shard - go to Limbo on another shard. Superusers only.

    Teleports an object somewhere. If no object is given, you yourself are
    teleported to the target location.

    To lock an object from being teleported, set its `teleport` lock, it will be
    checked with the caller. To block
    a destination from being teleported to, set the destination's `teleport_here`
    lock - it will be checked with the thing being teleported. Admins and
    higher permissions can always teleport.

    """

    switch_options = CmdTeleport.switch_options + ("shard",)

    def parse(self):
        # MuxCommand's parse, for the switches. Evennia's own would search
        # for the argument as an object, and a shard name is not one.
        super(CmdTeleport, self).parse()
        if "shard" in self.switches:
            return

        # That parse rewrote `args` with the switches removed. Put the raw
        # argument back, or Evennia's parses it again and loses them.
        self.args = self.raw
        super().parse()

    def func(self):
        if "shard" not in self.switches:
            return super().func()

        # Read off `handoff` at call time, as `ScalingCmdOOC` does.
        from evennia_portal_multiplex.config import get_instance_id

        from .config import get_shards
        from .handoff import transfer_to_instance

        shard = self.args.strip()
        shards = ", ".join(get_shards())

        if not self.account.is_superuser:
            self.msg(
                "Only a superuser can change shard: anyone else arrives "
                "where they left, and that room is not on the new shard."
            )
            return

        if not shard:
            self.msg(f"Usage: tel/shard <shard>. The shards are {shards}.")
            return

        if shard == get_instance_id():
            self.msg(f"You are already on {shard}.")
            return

        if shard not in get_shards():
            self.msg(f"{shard!r} is not a shard. The shards are {shards}.")
            return

        transfer_to_instance(self.account, self.session, self.caller, shard)
