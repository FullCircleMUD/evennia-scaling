# SPDX-License-Identifier: BSD-3-Clause
"""Ticket primitives for cross-instance session handoff.

A ticket is what lets a session arriving at an instance be recognised as the
one a handoff announced. The instances share no game database, so minting and
storing happen in different places and the ticket travels between them.

**It is what authenticates the arrival.** A session moved by
`evennia-portal-multiplex` arrives with ``uid``, ``logged_in`` and ``puid``
cleared — deliberately, since those are primary keys belonging to the instance
it left. So the destination has a session and no idea who it is. Without a
ticket the player types their password again on every hop, which is the thing
this library exists to avoid.

`create_ticket` runs on the sending instance; `store_ticket` on the receiving
one. They are in different processes on different machines, so nothing is
shared between them but the ticket itself.

See docs/test-plan.md § TK.
"""

import uuid
from datetime import timedelta

from .log import scaling_log


def create_ticket(account_archive_id, character_archive_id, to_instance):
    """Mint a ticket for a handoff to ``to_instance``.

    Returns the ticket as a mapping — ``token``, ``account_archive_id``,
    ``character_archive_id``, ``to_instance`` — rather than a bare token, so
    the shape of a ticket is defined here and the receiving instance reads
    that same shape back. A bare token would leave whatever call site builds
    the handoff to assemble the rest, with nothing holding the two ends in
    agreement.

    **Two identities, because they do different jobs on arrival.** The
    account is what the session authenticates as; the character is what it
    then puppets. A ticket naming only the character would leave the
    receiving instance with nothing to log the session in as.

    Both are ``archive_id`` values, never primary keys — the field names say
    so deliberately. Instances have separate databases, so an ``account.id``
    from here identifies an unrelated row over there, and a name like
    ``account_id`` would invite exactly that mistake.

    Nothing is written. The only stored copy of a ticket lives on the
    receiving instance — see TK-04.
    """
    # ``uuid4().hex`` is already 32 lowercase hex characters, so the value
    # needs no normalising and comparison stays plain string equality.
    return {
        "token": uuid.uuid4().hex,
        "account_archive_id": account_archive_id,
        "character_archive_id": character_archive_id,
        "to_instance": to_instance,
    }


def purge_expired() -> int:
    """Delete every ticket past its expiry. Returns how many went.

    Called before a read and after a write rather than on a timer, so
    cleanup is proportional to traffic and the library owns no scheduler. A
    busy instance sweeps constantly; a quiet one accumulates nothing, because
    nothing is arriving.

    Sweeping before a read is what lets the read carry no expiry predicate:
    once expired rows are gone, found means valid.
    """
    from django.utils import timezone

    from .models import Ticket

    removed, _ = Ticket.objects.filter(expires_at__lte=timezone.now()).delete()
    return removed


def store_ticket(ticket):
    """Write a ticket this instance has been told to expect.

    Called when the handoff message is handled. The ticket crosses in the
    shared bus database and lives here in the local one — the bus is
    transport, not storage, and it deletes the message as soon as the handler
    says it is done.

    The expiry is stamped here, from this instance's clock. An absolute time
    carried in the payload would assume two instances agree on the hour, and
    skew would expire tickets early or late in a way nobody would think to
    look for.
    """
    from django.utils import timezone

    from .config import get_ticket_lifetime
    from .models import Ticket

    row = Ticket.objects.create(
        token=ticket["token"],
        account_archive_id=ticket["account_archive_id"],
        character_archive_id=ticket["character_archive_id"],
        to_instance=ticket["to_instance"],
        expires_at=timezone.now() + timedelta(seconds=get_ticket_lifetime()),
    )
    # After the write, not before: the new row is the one thing that must
    # survive, and doing it in this order means a sweep can never race it.
    purge_expired()
    return row


def redeem_ticket(token):
    """Admit an arriving session, consuming its ticket.

    Returns the ticket's fields on success and ``None`` on refusal. The row
    is gone by then, so this is the caller's only chance to learn whose
    account and character to rebuild — a bare ``True`` would say a session
    may be admitted without saying who it is.

    Not named ``is_authorized``: it is not a question you may ask twice.
    Success deletes, so a second call refuses a ticket that was good moments
    earlier.

    Each refusal is logged with the check that failed. From outside they are
    one ``None``, and this is the only place that knows which. An absent
    token is not a refusal and logs nothing — an ordinary connection presents
    none, and logging that would bury the real ones.
    """
    from evennia_message_bus import get_instance_id

    from .models import Ticket

    if not token:
        return None

    purge_expired()

    row = Ticket.objects.filter(token=token).first()
    if row is None:
        scaling_log(
            f"Ticket refused: no live ticket for token {token!r}. It was "
            f"never issued, has already been redeemed, or has expired.",
            level="WARN",
        )
        return None

    instance_id = get_instance_id()
    if row.to_instance != instance_id:
        scaling_log(
            f"Ticket refused: addressed to {row.to_instance!r} but presented "
            f"at {instance_id!r}. Something is misrouted.",
            level="WARN",
        )
        return None

    ticket = {
        "token": row.token,
        "account_archive_id": row.account_archive_id,
        "character_archive_id": row.character_archive_id,
        "to_instance": row.to_instance,
    }

    # By character rather than by token. A character can only be in one
    # place, so honouring one ticket has to invalidate any sibling —
    # otherwise a retried handoff leaves a second ticket able to pull that
    # character somewhere it has already left.
    Ticket.objects.filter(
        character_archive_id=row.character_archive_id
    ).delete()
    return ticket
