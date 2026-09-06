# SPDX-License-Identifier: BSD-3-Clause
"""Commands this library replaces.

Going out of character is a *deliberate* departure, and the command is the
only place that knows it was deliberate. `unpuppet_object` is reached from
`at_disconnect` and from `unpuppet_all()` at shutdown as well, so anything
destructive there would fire on a dropped connection.

See docs/test-plan.md § OC.
"""

from evennia.commands.default.account import (
    CmdCharCreate,
    CmdCharDelete,
    CmdIC,
    CmdOOC,
    CmdOption,
    CmdPassword,
    CmdQuell,
    CmdStyle,
)
from evennia.commands.default.general import CmdNick

from .config import ROLE_SHARD, get_role, get_router_id
from .log import scaling_log

#: Each override below carries its **whole** lockstring rather than an
#: appended fragment, so it can be read against what Evennia ships.
#: `ScalingCmdChannel` is why: its lock declares four access types, and
#: ``is_ooc()`` belongs only in the ``cmd:`` clause.
#:
#: These are restrictions Evennia does not have. `ic` while puppeted is a
#: supported flow there — it switches characters — and `quell` resets the
#: puppet's lock cache precisely so it works in character.
#:
#: Nothing else is changed. Permissions stay as Evennia set them.


class ScalingCmdPassword(CmdPassword):
    """A password change made on a shard is written to a copy that is discarded."""

    locks = "cmd:pperm(Player) and is_ooc()"


class ScalingCmdOption(CmdOption):
    """Protocol and display settings live on the account."""

    locks = "cmd:is_ooc()"


class ScalingCmdStyle(CmdStyle):
    """Display options, through the account's option handler.

    Evennia gives this no lock of its own, so this replaces the inherited
    ``cmd:all()`` rather than narrowing a stated one.
    """

    locks = "cmd:is_ooc()"


class ScalingCmdQuell(CmdQuell):
    """A permission mode stored as an account attribute."""

    locks = "cmd:pperm(Player) and is_ooc()"


class ScalingCmdCharCreate(CmdCharCreate):
    """A character created on a shard is created in that shard's database."""

    locks = "cmd:pperm(Player) and is_ooc()"


class ScalingCmdCharDelete(CmdCharDelete):
    """Deleting from a working copy's roster leaves the character elsewhere."""

    locks = "cmd:pperm(Player) and is_ooc()"


class ScalingCmdIC(CmdIC):
    """Going in character is a router operation.

    Not about state — its `_last_puppet` write is disposable — but `ic
    <other>` while already playing on a shard is a thing that should not be
    possible here at all.
    """

    locks = "cmd:is_ooc()"


class ScalingCmdNick(CmdNick):
    """One branch rewritten, rather than a lock.

    `nick` writes to whatever the caller *is*, so a nick set in character
    lands on the character and one set out of character lands on the
    account with no help from us. The `/account` switch is a nick
    *category*, not a target object.

    `clearall` is the exception: it reaches through to
    ``caller.account.nicks.clear()``, so clearing in character takes the
    account's nicks with it. Written without the reach-through, the one
    line covers both halves — the caller is the character in character and
    the account out of it, and nothing has to detect which.
    """

    def func(self):
        if "clearall" not in self.switches:
            return super().func()

        self.caller.nicks.clear()
        self.caller.msg("Cleared all nicks.")


# `ScalingCmdChannel` lives in `channel_command.py`, not here.
# `evennia.commands.default.comms` imports `evmenu`, which builds a class
# from Evennia's lazy `Command` export — not populated until
# `evennia._init()` runs *after* `django.setup()`. This module is imported
# from `AppConfig.ready()`, so it cannot reach `comms`.


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
