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
    """Raised when an arriving character has nowhere to stand at all.

    Every row of the cascade tried and none of them named a room in this
    database. That is a broken deployment rather than an unlucky character,
    so the message names all three.
    """


class RoomOnAnotherShard(Exception):
    """Raised when placement resolved a room, and it is not on this shard.

    Not a failure — the answer is a different instance. Carries what a
    transfer needs: the shard, the character, and the account, which
    `reconstitute_for_ticket` attaches as this passes through it.

    Raised rather than acted on because placement runs inside
    `load_sync_data`, before the session is logged in. Moving the session
    from here would hand it away while the caller is still about to set
    ``uid`` on it, so the frame that owns the session does the moving.
    """

    def __init__(self, shard, character):
        super().__init__(
            f"{character} belongs on {shard}, which is not this instance."
        )
        self.shard = shard
        self.character = character
        self.account = None


def place_in_world(character, account=None):
    """Put an arriving character somewhere in this instance's world.

    `restore` strips location, home and every other reference — they are
    primary keys into a database that no longer exists — so a character
    arrives standing nowhere at all.

    **A superuser goes to Limbo and the cascade does not run.** See
    `_place_superuser`. The account is passed because the character does
    not know whose it is yet, and this is called from the one frame that
    has both.

    **Three resolutions, then failure.** Where they are, where they live,
    and the one safe place in the deployment. Each names a shard and a room
    uuid, and each asks the same two questions: is that shard this one, and
    does that uuid name a room here.

    The sending side walked a cascade of the same shape, and this is not a
    repeat of it. That one checks *presence* — is there a shard and a room
    key. This one checks *resolvability*, which no sender can know, because
    the room is in a database it cannot see.

    **Rows two and three rewrite the pair before raising**, and that is what
    makes the cascade terminate: each hop advances it one row, so the next
    instance starts from where this one got to rather than from the top.

    **Row one rewrites nothing**, because it resolved nothing. The pair is
    already right and it is the session that is in the wrong place — which,
    since leaving stamps the destination, cannot happen by any path here.
    So it is logged as the breach it is.

    Raises `RoomOnAnotherShard` when the answer is elsewhere,
    `PlacementFailed` when there is no answer, and lets
    `DuplicateRoomUuid` through: a world source naming one room twice is
    not something to route around quietly.
    """
    from .config import (
        get_default_home_shard,
        get_default_home_uuid,
        get_shards,
    )
    from .mixins import find_room_by_uuid

    if account is not None and account.is_superuser:
        _place_superuser(character)
        return

    here = _this_instance()

    # Read before the cascade rewrites them, so the failure at the bottom
    # can say what was actually tried rather than what it last wrote.
    tried_room = character.current_room_uuid
    tried_home = character.home_room_uuid
    tried_home_shard = character.home_shard

    if character.current_shard != here:
        scaling_log(
            f"INVARIANT BREACH: {character} arrived here and belongs on "
            f"{character.current_shard}. Leaving stamps the destination, so "
            f"no path here produces this. Sending them on.",
            level="ERROR",
        )
        raise RoomOnAnotherShard(character.current_shard, character)

    room = find_room_by_uuid(character.current_room_uuid)
    if room:
        character.location = room
        return

    # Both halves, like the sending cascade: a home shard with no room
    # beside it is not somewhere to send anyone, and forwarding on it would
    # move a character to another instance to discover that there.
    home_shard = character.home_shard
    if home_shard in get_shards() and character.home_room_uuid:
        character.current_shard = home_shard
        character.current_room_uuid = character.home_room_uuid
        if home_shard != here:
            raise RoomOnAnotherShard(home_shard, character)

        room = find_room_by_uuid(character.home_room_uuid)
        if room:
            character.location = room
            return

    default_shard = get_default_home_shard()
    default_uuid = get_default_home_uuid()
    character.current_shard = default_shard
    character.current_room_uuid = default_uuid
    if default_shard != here:
        raise RoomOnAnotherShard(default_shard, character)

    room = find_room_by_uuid(default_uuid)
    if room:
        character.location = room
        return

    raise PlacementFailed(
        f"nothing places {character} on {here}. Their location was "
        f"{tried_room!r}, their home was {tried_home!r} on "
        f"{tried_home_shard!r}, and the default home {default_uuid!r} is not "
        f"in this database either."
    )


#: Evennia's initial setup makes Limbo, and makes it second — so on any
#: instance it set up, this is Limbo whatever the game has renamed it to.
LIMBO_PK = 2


def _place_superuser(character):
    """Put a superuser in Limbo, whatever their location pair says.

    A branch before the cascade rather than a row in it. A superuser is not
    playing by the rules the cascade is written for: they can `tel`
    anywhere the moment they arrive, so being routed by where their
    character was buys them nothing, and always appearing in one known room
    is worth more. It is also what makes a shard whose rooms carry no uuids
    yet reachable at all — by the one person who can go and fix that.

    **`DEFAULT_HOME` rather than a uuid**, and this is the one place a
    dbref belongs: it is resolved on the instance already being stood on,
    so it never has to mean anything across a database.

    **Then object `#2`.** Where `DEFAULT_HOME` is at its own default the two
    are the same lookup and this never fires; it fires where an operator
    repointed it at a room that has since gone. Nothing checks that `#2` is
    named Limbo, or is a room — a name is not what makes it the room, and
    making it something else takes deliberate work whose whole cost is a
    superuser standing inside that instead, one `tel` from anywhere.

    **The location pair is not written.** Nothing resolved, so there is
    nothing to record; it keeps what it held and restamps on their first
    move like anyone's.
    """
    from django.conf import settings
    from evennia.objects.models import ObjectDB
    from evennia.utils.search import search_object

    found = search_object(settings.DEFAULT_HOME)
    if found:
        character.location = found[0]
        return

    limbo = ObjectDB.objects.filter(pk=LIMBO_PK).first()
    if limbo:
        character.location = limbo
        return

    raise PlacementFailed(
        f"{character} is a superuser and this instance has no Limbo: "
        f"DEFAULT_HOME is {settings.DEFAULT_HOME!r}, which does not resolve, "
        f"and there is no object #{LIMBO_PK} either."
    )


def _this_instance():
    """Which instance this is, as the deployment names it.

    multiplex's accessor rather than a setting of ours: `check_settings`
    already requires `SCALING_SHARDS` to be spelled exactly as each
    instance's ``MULTIPLEX_INSTANCE_ID``, so a second setting for the same
    fact would only give the two somewhere to disagree.
    """
    from evennia_portal_multiplex.config import get_instance_id

    return get_instance_id()


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

    **Three failures, three returns.** An account the archive does not
    hold, a character it does not hold, and a character that cannot be
    placed anywhere. Each is a session this instance will not admit, and
    none of them raises out through `load_sync_data` into AMP — where a
    player sees nothing at all rather than being sent home with a message.

    **Two rise past here**, because the session override is the frame that
    can act on them. `RoomOnAnotherShard` needs the session moved, and
    `DuplicateRoomUuid` needs the player told; the caller's bounce to the
    router is wrong for the first and incomplete for the second. The
    account is attached to the first on its way through, because this is
    the only frame that has both it and the exception.
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

    try:
        character = character_for_ticket(ticket, account)
    except NotArchived:
        scaling_log(
            f"ticket named character {ticket['character_archive_id']}, "
            f"which is not in the archive. The session cannot be admitted.",
            level="ERROR",
        )
        return None

    if get_role() != ROLE_SHARD:
        return account

    try:
        place_in_world(character, account)
    except RoomOnAnotherShard as elsewhere:
        # Attached here and re-raised: placement knows the shard and the
        # character, and this frame is the only one that also has the
        # account the transfer needs.
        elsewhere.account = account
        raise
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

    Returns multiplex's Deferred of ``(moved, outcome)``, or ``None`` for
    account ``#1``, which is refused. A destination that is down refuses
    the move, and a caller that swallows that leaves a player who asked to
    go in character seeing nothing at all.

    **Account ``#1`` is refused outright.** It belongs to the instance it
    was made on and stays there — never transferred, never archived, never
    restored, never deleted. Both of this library's own triggers already
    step aside for it, so this is for a consumer calling here directly,
    which the shard-to-shard case invites. They are told, because a
    consumer who wrote that call meant something by it.

    A superuser that is not ``#1`` travels like any other account. See
    `is_instance_root`.

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

    from .config import ROLE_ROUTER, get_role, get_shards
    from .mixins import is_instance_root

    if is_instance_root(account):
        scaling_log(
            f"{account} is this instance's #1 and was asked to transfer to "
            f"{to_instance}. Refused.",
            level="ERROR",
        )
        account.msg(
            "This account belongs to this instance and cannot be "
            "transferred."
        )
        return None

    # Leaving is the moment the destination is known, and the stamp goes
    # before the archive, which is what carries it. A no-op for the
    # in-character path, where `to_instance` is what
    # `ensure_location_for_transfer` just returned; it does the work for a
    # consumer moving a character between shards, who would otherwise send
    # one to shard1 still saying shard0 and have the arrival read that as a
    # misdelivered session.
    #
    # Only for a shard. Going out of character transfers to the router, and
    # a character is not *in* the router — it waits on the shard
    # `current_shard` goes on naming.
    if to_instance in get_shards():
        character.current_shard = to_instance

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
