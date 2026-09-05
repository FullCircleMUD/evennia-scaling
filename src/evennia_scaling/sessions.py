# SPDX-License-Identifier: BSD-3-Clause
"""The Server session override, where a synced session's data arrives.

`load_sync_data` is called with everything ``SESSION_SYNC_ATTRS`` carries,
``server_data`` among it. A session moved by `evennia-portal-multiplex` brings
its payload there, and this is where the ticket in it is read back.

See docs/test-plan.md § SS.
"""

import json

from evennia_message_bus import process_inbox
from evennia_portal_multiplex.move import PAYLOAD_KEY, send_session

from .config import ROLE_SHARD, get_role, get_router_id
from .tickets import redeem_ticket

#: The key this library's token travels under, inside multiplex's payload.
#: That payload is a dict a consumer may put their own keys in, so ours is
#: named for the library rather than for what it holds.
SCALING_TICKET_KEY = "scaling_ticket"

#: Set by `AppConfig.ready()` to the generated class, so the dotted path in
#: SERVER_SESSION_CLASS resolves. Evennia looks the setting up by string.
ScalingServerSession = None


def token_from(session):
    """The ticket token a session arrived carrying, or ``None``.

    Absent, unreadable, and carrying no token are one answer. `json.loads`
    raises on a corrupt string and this runs on every session that arrives
    with a payload, so an unreadable one is treated as untickered rather than
    breaking the arrival.
    """
    payload = (getattr(session, "server_data", None) or {}).get(PAYLOAD_KEY)
    if not payload:
        return None
    try:
        return json.loads(payload).get(SCALING_TICKET_KEY)
    except (TypeError, ValueError):
        return None


def make_scaling_session(base):
    """Build the session class, subclassing whatever the consumer had.

    A factory rather than a module-level class so the base is supplied rather
    than resolved at import time — `AppConfig.ready()` passes the consumer's
    stashed `SERVER_SESSION_CLASS`, and a test passes its own.
    """

    class ScalingServerSession(base):
        """Reads a ticket off a session as it arrives from the Portal."""

        def load_sync_data(self, sessdata):
            # First, so Evennia's own sync and a consumer's override have
            # both run before anything here looks at the session.
            super().load_sync_data(sessdata)

            # Already authenticated: it did not arrive by transfer, and
            # admitting it again would fire the login hooks twice.
            if self.logged_in and self.uid:
                return

            token = token_from(self)

            # The session beats the bus. The sender commits the handoff row
            # and only then asks for the move, so the row is there — but the
            # bus polls on an interval and the session arrives over a live
            # AMP link in milliseconds. Draining here reads a row already
            # sitting there rather than waiting for a poll it is faster than.
            #
            # Only when a token arrived: an ordinary connection should not
            # pay for a database round trip.
            if token:
                process_inbox()

            # redeem_ticket checks the token itself, so a session that never
            # carried one needs no guard here — it comes back None.
            ticket = redeem_ticket(token)
            if ticket:
                from .handoff import reconstitute_for_ticket

                account = reconstitute_for_ticket(self, ticket)
                if account:
                    # Not sessionhandler.login(): `portal_connect` checks
                    # these two a few lines after we return and logs the
                    # session in itself, so calling it here would fire every
                    # login hook twice. Setting logged_in also suppresses
                    # the login screen, which `_run_cmd_login` only sends
                    # when it is false.
                    self.uid = account.id
                    self.logged_in = True
                    return

            # Nothing admits this session, so it has not been in character
            # yet — and the out-of-character game is the router's. On the
            # router we return and Evennia shows the login screen.
            if get_role() == ROLE_SHARD:
                send_session(self, get_router_id())

    return ScalingServerSession
