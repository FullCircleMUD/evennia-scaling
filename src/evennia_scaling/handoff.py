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


class PlacementFailed(Exception):
    """Raised when an arriving character cannot be put anywhere.

    Nothing raises it yet: placement puts an arriving character in this
    instance's `DEFAULT_HOME`, which always resolves. It exists so the
    arrival already handles the failure, and reading a character's own room
    key can land without anything around it changing.
    """


def place_in_world(character):
    """Put an arriving character somewhere in this instance's world.

    `restore` strips location, home and every other reference — they are
    primary keys into a database that no longer exists — so a character
    arrives standing nowhere at all.

    **Deliberately unfinished.** Where a character *should* appear is the
    room its own `current_room_ref` names, and reading that is work of its
    own. Until then this is Limbo, and everything around it — the rebuild,
    the admission, and the failure path — is built and tested.

    Raises `PlacementFailed` when it cannot place someone. That is the
    contract the arrival is written against.
    """
    from django.conf import settings
    from evennia.utils.search import search_object

    found = search_object(settings.DEFAULT_HOME)
    if not found:
        raise PlacementFailed(
            f"{settings.DEFAULT_HOME} does not resolve in this database, so "
            f"there is nowhere to put {character}."
        )
    character.location = found[0]


def account_for_ticket(ticket):
    """The local account the ticket names, ready to be logged in.

    **Only a shard rebuilds.** `rebuild_from_archive` is delete-then-restore
    and the delete is the whole difference between the roles: a shard's copy
    is left over from a previous visit and has to go, while the router's is
    the authoritative one and must not move. Remaking it there would give it
    a new primary key, and anything holding the old one — a Django website
    session, resolved on every request — stops working.

    So the router calls `restore`, which hands back a live account untouched.

    An account the router does not already hold is restored anyway and
    **logged**: a player at the door is not the moment to refuse, but the
    only ways to reach it are a rebuilt database or a ticket for an account
    this router has never seen.

    Raises `NotArchived` when the archive does not hold it. The caller
    turns that into a session it does not admit.
    """
    from django.conf import settings
    from evennia.utils.utils import class_from_module
    from evennia_archive.api import restore

    from .config import ROLE_SHARD, get_role

    archive_id = ticket["account_archive_id"]

    if get_role() == ROLE_SHARD:
        account_class = class_from_module(settings.BASE_ACCOUNT_TYPECLASS)
        return account_class.rebuild_from_archive(archive_id)

    if not _live_account(archive_id):
        scaling_log(
            f"account {archive_id} arrived on a ticket and is not in this "
            f"database. Restoring it, but it should have been here.",
            level="ERROR",
        )

    return restore(archive_id)


def _live_account(archive_id):
    """Whether an account carrying this archive id is already here.

    Only `account_for_ticket` needs it, and only to tell the two cases
    apart for the log — `restore` does the same lookup itself and will not
    say which branch it took.
    """
    from evennia.accounts.models import AccountDB
    from evennia_archive.mixins import ARCHIVE_ID_KEY

    return AccountDB.objects.filter(
        db_attributes__db_key=ARCHIVE_ID_KEY,
        db_attributes__db_strvalue=str(archive_id),
    ).exists()


def character_for_ticket(ticket, account):
    """Restore the character the ticket names and put it back on the roster.

    Both roles do this. The character was deleted on the instance it left,
    so the account's roster names something that is gone and the restored
    object comes back under a new primary key — restoring it is only half
    the job.

    No other character is touched. They were never deleted, and a character
    only changes on the shard it is being played on.

    `add` rather than writing the roster attribute, so
    ``at_post_add_character`` fires as it would for any other character.
    """
    from evennia_archive.api import restore

    character = restore(ticket["character_archive_id"])
    account.characters.add(character)
    return character


def reconstitute_for_ticket(session, ticket):
    """Rebuild what a redeemed ticket names, and return the local account.

    The arrival's half of a transfer. The ticket names the account and the
    character outright, so nothing is searched for — the identifiers are
    the lookup.

    Returns the account, because `load_sync_data` needs it: setting ``uid``
    and ``logged_in`` is what lets `portal_connect` log the session in, and
    there is nothing to set until the account exists here.

    **``None`` means the session is not admitted**, and the caller's
    existing bounce is what happens next — so every failure here is one
    return and no new branch.

    Both roles get the account and the character back. What differs is what
    happens next: a shard is where the character is played, so it is placed
    in the world and stamped as what to puppet, and a router is neither of
    those things.
    """
    from evennia_archive.api import NotArchived

    from .config import ROLE_SHARD, get_role

    try:
        account = account_for_ticket(ticket)
    except NotArchived:
        scaling_log(
            f"ticket named account {ticket['account_archive_id']}, which is "
            f"not in the archive. The session cannot be admitted.",
            level="ERROR",
        )
        return None

    character = character_for_ticket(ticket, account)

    if get_role() != ROLE_SHARD:
        return account

    try:
        place_in_world(character)
    except PlacementFailed as failure:
        scaling_log(
            f"{character} arrived and could not be placed: {failure} The "
            f"session cannot be admitted.",
            level="ERROR",
        )
        return None

    # The reference the archive dropped, put back. `at_post_login` reads
    # this to auto-puppet, and a bare `ic` resolves through it. Without it
    # Evennia says the character does not exist — which it does, just not
    # under the primary key the restored account remembers. This is the
    # only place both objects are in hand.
    account.db._last_puppet = character
    return account


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

    Returns multiplex's Deferred of ``(moved, outcome)``, or ``None`` for a
    superuser, who is refused. A destination that is down refuses the move,
    and a caller that swallows that leaves a player who asked to go in
    character seeing nothing at all.

    **A superuser is refused outright.** A superuser belongs to one
    instance and stays there — never transferred, never archived, never
    restored, never deleted. Both of this library's own triggers already
    step aside for one, so this is for a consumer calling here directly,
    which the shard-to-shard case invites. They are told, because a
    consumer who wrote that call meant something by it.

    Five steps, in this order:

    1. Archive whichever of the two could have changed here — here rather
       than when the session closes, because the destination rebuilds on
       arrival while this instance is still tearing its session down.
    2. Mint a ticket naming both, addressed to ``to_instance``.
    3. Send it over the bus, so the destination learns of the transfer
       independently of the session that is about to arrive.
    4. Delete the character locally.
    5. Hand the session over, carrying the ticket.

    **Archive what could have changed where you are leaving.** An account
    can only change on the router and a character can only change on a
    shard, so leaving the router archives the account and leaving a shard
    archives the character. Router to shard stores the account; shard to
    router and shard to shard store the character.

    Archiving the other one would be worse than wasted: a shard's account
    is a working copy, and writing it back over the authoritative one could
    only ever carry a change that should not have been possible.

    **Deleting after the ticket is sent is deliberate.** A failure at the
    handoff leaves the character out of this database but present in the
    archive with a live ticket waiting, so a client reaching the
    destination still gets in.

    **The account is not deleted.** That waits for the session to actually
    close — deleting it out from under a live session disconnects it, which
    is Evennia's own documented behaviour.
    """
    # Imported here rather than at module scope: this module is reachable
    # from AppConfig.ready(), and archive's api pulls in its models, which
    # are not loadable that early.
    from evennia_archive.api import archive

    from .config import ROLE_ROUTER, get_role

    if account.is_superuser:
        scaling_log(
            f"{account} is a superuser and was asked to transfer to "
            f"{to_instance}. Refused.",
            level="ERROR",
        )
        account.msg(
            "Superusers are local to their instance and cannot be "
            "transferred."
        )
        return None

    archive(account if get_role() == ROLE_ROUTER else character)

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

    # A dict, not a string: multiplex serialises the payload itself, and
    # encoding it here too lands a JSON string of a JSON string at the far
    # end — where reading it back yields a string rather than a mapping.
    return report_outcome(
        send_session(
            session, to_instance, {SCALING_TICKET_KEY: ticket["token"]}
        ),
        account,
        to_instance,
    )
