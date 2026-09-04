# SPDX-License-Identifier: BSD-3-Clause
"""Settings this library reads, each behind an accessor.

Settings are read here and nowhere else, so a default lives in one place and
a consumer overriding one changes every reader at once.
"""

SETTING_TICKET_LIFETIME = "SCALING_TICKET_LIFETIME_SECONDS"

#: How long a stored ticket stays redeemable, in seconds. The session is moved
#: over a live AMP link and arrives immediately, so a ticket is normally
#: redeemed in the same breath as it is written. What this covers is the case
#: where nobody arrives — a player who drops mid-move — and the only cost of
#: that is a row nobody sweeps until the next one is stored.
DEFAULT_TICKET_LIFETIME = 10


def get_ticket_lifetime() -> int:
    """Return ``SCALING_TICKET_LIFETIME_SECONDS``, defaulting to 10."""
    from django.conf import settings

    return int(
        getattr(settings, SETTING_TICKET_LIFETIME, DEFAULT_TICKET_LIFETIME)
    )
