# SPDX-License-Identifier: BSD-3-Clause
"""Message types this library sends between instances.

One type so far. If more arrive, this becomes a package with a module per
message and its helpers, plus a shared helpers module — a single file growing
to thousands of lines is harder for a person to hold than several small ones.

`SessionAuthorized` says: *a session has been authorised to arrive at you;
here is the ticket it will present.* Past tense because it is true the moment
the ticket is minted and stays true through every retry — a name claiming
arrival would be wrong on every attempt but the last.

**The receiver learns of a transfer independently of the session.** The
session itself arrives over the Portal's AMP link carrying the same ticket;
this is the other half of that, and having both is what lets the destination
check an arrival against something it was told separately.

See docs/test-plan.md § MS.
"""

from evennia_message_bus import MessageType, register

from .tickets import store_ticket


class SessionAuthorized(MessageType):
    """A session is authorised to arrive here, carrying this ticket."""

    kind = "session_authorized"

    #: Exactly what `tickets.create_ticket` returns. Message-bus checks these
    #: before a send, so a malformed ticket is refused where it was minted
    #: rather than arriving somewhere as a payload the far end cannot use.
    payload_keys = (
        "token",
        "account_archive_id",
        "character_archive_id",
        "to_instance",
    )

    def handle(self, message) -> bool:
        """Store the ticket, so an arriving session can be checked against it.

        **One handler, both roles.** A router and a shard do the same thing
        with this message. When the two need to diverge the branch goes in
        then — a branch whose arms are identical is a claim about the future
        rather than a behaviour.

        Returns ``True`` to consume the message. Returning ``False`` would
        leave it on the bus to be retried forever.
        """
        store_ticket(message.payload)
        return True


register(SessionAuthorized)
