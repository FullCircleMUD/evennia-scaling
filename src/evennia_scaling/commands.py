# SPDX-License-Identifier: BSD-3-Clause
"""Commands this library replaces.

Going out of character is a *deliberate* departure, and the command is the
only place that knows it was deliberate. `unpuppet_object` is reached from
`at_disconnect` and from `unpuppet_all()` at shutdown as well, so anything
destructive there would fire on a dropped connection.

See docs/test-plan.md § OC.
"""

from evennia.commands.default.account import CmdOOC

from .config import ROLE_SHARD, get_role, get_router_id
from .log import scaling_log


class ScalingCmdOOC(CmdOOC):
    """Leave the shard rather than standing about on it out of character.

    A total override — `super().func()` is never called except for a
    superuser. Evennia's ends by rendering the character-select menu, which
    is the one screen a shard must not show: a shard holds one character
    and no roster, so a menu there offers a choice that does not exist.
    Nothing else in it is worth inheriting — `account.get_puppet(session)`
    is the whole of what going out of character needs to resolve.

    A consumer gating this — refusing to let someone leave mid-fight, say —
    subclasses and checks before calling `super().func()`. A consumer with
    their own `rent` or `quit` calls `transfer_to_instance` directly; there
    is no separate primitive, because leaving is the same six steps as
    arriving with a different destination.
    """

    def func(self):
        from .handoff import move_session, transfer_to_instance

        account = self.account
        session = self.session

        # Evennia's own behaviour is right in two cases, and it already
        # covers both halves of them: unpuppet and render the menu, or say
        # they are already out of character.
        #
        # A superuser stays on the instance it belongs to — without this it
        # would be archived, its character deleted, and it would land on the
        # router. And a router is where out of character happens, so there
        # is nothing here to improve on.
        if account.is_superuser or get_role() != ROLE_SHARD:
            return super().func()

        # Read before the unpuppet, which clears session.puppet.
        character = account.get_puppet(session)

        if not character:
            # Out of character on a shard with nothing puppeted, which no
            # path here allows: they can neither go out of character nor in
            # as a character they do not have. Send them home. No ticket,
            # even where there is an account — a character-less one would
            # mean changes across minting and reconstitution to improve an
            # error path. They log in again.
            scaling_log(
                f"INVARIANT BREACH: {account} was out of character on a "
                f"shard with nothing puppeted, which no path here allows. "
                f"Sending them to the router without a ticket; they will "
                f"have to log in again.",
                level="ERROR",
            )
            move_session(account, session, get_router_id())
            return

        account.unpuppet_object(session)
        transfer_to_instance(account, session, character, get_router_id())
