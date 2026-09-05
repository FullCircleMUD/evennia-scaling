# SPDX-License-Identifier: BSD-3-Clause
"""Sending a session and what it is playing to another instance.

See docs/test-plan.md § HO.
"""

from evennia.utils.utils import delay
from evennia_portal_multiplex.move import (
    ALREADY_THERE,
    MOVED,
    NO_SUCH_SESSION,
    NOT_ATTACHED,
    REJECTED,
    STRANDED,
    send_session,
)

from .log import scaling_log
from .messages import SessionAuthorized
from .sessions import SCALING_TICKET_KEY
from .tickets import create_ticket

#: What each outcome of a move means here: how loudly to record it, and
#: whether there is anyone to tell.
#:
#: Everything that is not `MOVED` is logged — each one means a player did not
#: arrive somewhere, and the reason is worth a record.
#:
#: The player is told only where a message can reach them and means
#: something. A stranded session has no instance to deliver to and a session
#: the Portal has dropped has nobody behind it, so telling them is a message
#: into nothing rather than a kindness that fails quietly. `ALREADY_THERE` is
#: not a failure and needs no game text — the library would be inventing
#: wording only its caller can interpret.
_OUTCOMES = {
    MOVED: (None, None),
    NOT_ATTACHED: ("ERROR", "That instance is not available right now."),
    REJECTED: ("ERROR", "That instance would not take you right now."),
    STRANDED: ("ERROR", None),
    NO_SUCH_SESSION: ("WARNING", None),
    ALREADY_THERE: ("WARNING", None),
}


def report_outcome(moving, account, to_instance):
    """Record what a move came back as, and tell the player where possible.

    Attached to every move the library makes, including the bare session
    moves that carry nothing to archive — without it those would be the one
    kind that fails silently.

    Returns the Deferred, so a caller can chain onto it. Nothing has to.
    """

    def report(result):
        _, outcome = result
        level, message = _OUTCOMES.get(
            outcome, ("ERROR", "Something went wrong moving you.")
        )
        if level:
            scaling_log(
                f"moving {account} to {to_instance} came back {outcome!r}.",
                level=level,
            )
        if message:
            account.msg(message)
        return result

    def failed(failure):
        """An error the move did not turn into an outcome.

        A dropped AMP link, or a bug in the move. Without this it
        disappears into the Deferred and surfaces at garbage-collection
        time, if at all. The player is told because nothing is known about
        whether they can be reached, and silence is the worse guess.
        """
        scaling_log(
            f"moving {account} to {to_instance} failed: {failure}.",
            level="ERROR",
        )
        account.msg("Something went wrong moving you.")
        return failure

    moving.addCallbacks(report, failed)
    return moving


def move_session(account, session, to_instance):
    """Move a session with nothing to archive, and report the outcome.

    The recovery path: a session that has to go somewhere but carries
    nothing to rebuild there. No ticket, so it arrives unadmitted and meets
    a login screen.

    Reported like any other move — without that it would be the one kind
    that fails silently.
    """
    return report_outcome(
        send_session(session, to_instance), account, to_instance
    )


def transfer_to_instance(account, session, character, to_instance):
    """Move a session and what it is playing to another instance.

    Symmetric: going in character sends them to the character's shard,
    going out of character sends them back to the router, and only the
    destination differs. A game moving a character between shards calls
    this too, so the path a consumer uses is the path the library uses.

    Returns multiplex's Deferred of ``(moved, outcome)``. A destination
    that is down refuses the move, and a caller that swallows that leaves a
    player who asked to go in character seeing nothing at all.

    Six steps, in this order:

    1. Archive the account — here rather than when the session closes,
       because the destination rebuilds on arrival while this instance is
       still tearing its session down.
    2. Archive the character.
    3. Mint a ticket naming both, addressed to ``to_instance``.
    4. Send it over the bus, so the destination learns of the transfer
       independently of the session that is about to arrive.
    5. Delete the character locally.
    6. Hand the session over, carrying the ticket.

    **Deleting after the ticket is sent is deliberate.** A failure at the
    handoff leaves the character out of this database but present in the
    archive with a live ticket waiting, so a client reaching the
    destination still gets in.

    **The account is not deleted.** That waits for the session to actually
    close — deleting it out from under a live session disconnects it, which
    is Evennia's own documented behaviour.
    """
    import json

    # Imported here rather than at module scope: this module is reachable
    # from AppConfig.ready(), and archive's api pulls in its models, which
    # are not loadable that early.
    from evennia_archive.api import archive

    archive(account)
    archive(character)

    ticket = create_ticket(
        str(account.archive_id), str(character.archive_id), to_instance
    )
    SessionAuthorized.send(to_instance, payload=ticket)

    # `CmdIC` writes `_last_puppet` and logs against the character *after*
    # `puppet_object` returns, so deleting inline makes Evennia serialise a
    # dead object. `delay(0, ...)` is `reactor.callLater(0, ...)`, which
    # cannot run until this call stack unwinds — so the delete is
    # structurally after Evennia is done, not merely likely to be.
    delay(0, character.delete)

    return report_outcome(
        send_session(
            session,
            to_instance,
            json.dumps({SCALING_TICKET_KEY: ticket["token"]}),
        ),
        account,
        to_instance,
    )



def move_session(account, session, to_instance):
    """Move a session with nothing to archive, and report the outcome.

    The recovery path: a session that has to go somewhere but carries
    nothing to rebuild there. No ticket, so it arrives unadmitted and meets
    a login screen.

    Reported like any other move — without that it would be the one kind
    that fails silently.
    """
    return report_outcome(
        send_session(session, to_instance), account, to_instance
    )


def transfer_to_instance(account, session, character, to_instance):
    """Move a session and what it is playing to another instance.

    Symmetric: going in character sends them to the character's shard,
    going out of character sends them back to the router, and only the
    destination differs. A game moving a character between shards calls
    this too, so the path a consumer uses is the path the library uses.

    Returns multiplex's Deferred of ``(moved, outcome)``. A destination
    that is down refuses the move, and a caller that swallows that leaves a
    player who asked to go in character seeing nothing at all.

    Six steps, in this order:

    1. Archive the account — here rather than when the session closes,
       because the destination rebuilds on arrival while this instance is
       still tearing its session down.
    2. Archive the character.
    3. Mint a ticket naming both, addressed to ``to_instance``.
    4. Send it over the bus, so the destination learns of the transfer
       independently of the session that is about to arrive.
    5. Delete the character locally.
    6. Hand the session over, carrying the ticket.

    **Deleting after the ticket is sent is deliberate.** A failure at the
    handoff leaves the character out of this database but present in the
    archive with a live ticket waiting, so a client reaching the
    destination still gets in.

    **The account is not deleted.** That waits for the session to actually
    close — deleting it out from under a live session disconnects it, which
    is Evennia's own documented behaviour.
    """
    import json

    # Imported here rather than at module scope: this module is reachable
    # from AppConfig.ready(), and archive's api pulls in its models, which
    # are not loadable that early.
    from evennia_archive.api import archive

    archive(account)
    archive(character)

    ticket = create_ticket(
        str(account.archive_id), str(character.archive_id), to_instance
    )
    SessionAuthorized.send(to_instance, payload=ticket)

    # `CmdIC` writes `_last_puppet` and logs against the character *after*
    # `puppet_object` returns, so deleting inline makes Evennia serialise a
    # dead object. `delay(0, ...)` is `reactor.callLater(0, ...)`, which
    # cannot run until this call stack unwinds — so the delete is
    # structurally after Evennia is done, not merely likely to be.
    delay(0, character.delete)

    moving = send_session(
        session,
        to_instance,
        json.dumps({SCALING_TICKET_KEY: ticket["token"]}),
    )

    def report(result):
        """Record what happened, and tell the player where that is possible."""
        _, outcome = result
        level, message = _OUTCOMES.get(
            outcome, ("ERROR", "Something went wrong moving you.")
        )
        if level:
            scaling_log(
                f"moving {account} to {to_instance} came back {outcome!r}.",
                level=level,
            )
        if message:
            account.msg(message)
        return result

    def failed(failure):
        """An error the move did not turn into an outcome.

        A dropped AMP link, or a bug in the move. Without this it
        disappears into the Deferred and surfaces at garbage-collection
        time, if at all. The player is told because nothing is known about
        whether they can be reached, and silence is the worse guess.
        """
        scaling_log(
            f"moving {account} to {to_instance} failed: {failure}.",
            level="ERROR",
        )
        account.msg("Something went wrong moving you.")
        return failure

    moving.addCallbacks(report, failed)
    return moving
