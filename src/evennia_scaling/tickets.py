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

Only `create_ticket` exists so far. See docs/test-plan.md § TK.
"""

import uuid


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
