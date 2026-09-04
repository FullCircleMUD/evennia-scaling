# SPDX-License-Identifier: BSD-3-Clause
"""The ticket row, held by the instance a session is arriving at.

**This table lives in the consumer's own game database.** A library's tables
go on an alias of its own when its data has to outlive the game database or be
read by more than one instance. A ticket is neither: one instance writes and
reads it seconds apart, and after a wipe there is no in-flight handoff whose
ticket still matters. An alias would cost a database, a router and a migration
step a consumer has to configure, to protect rows that are garbage almost
immediately. TK-05 pins that — do not "fix" it into an alias.

The row has to be in *a* database rather than in memory: the two ends of a
handoff run in different processes and share none.
"""

from django.db import models


class Ticket(models.Model):
    """A single-use authorisation for a session about to arrive here.

    Written when the handoff message is handled, read when a session presents
    the token, deleted once it has been honoured.
    """

    #: The token is the primary key, so redeeming one is a single indexed
    #: lookup on the connection hot path rather than a scan.
    token = models.CharField(max_length=64, primary_key=True)

    #: Identities as archive ids, never primary keys — instances have
    #: separate databases, so a pk from the sender names an unrelated row
    #: here, or nothing at all.
    account_archive_id = models.CharField(max_length=64)
    character_archive_id = models.CharField(max_length=64)

    #: The instance this ticket was addressed to. Checked on redemption: a
    #: ticket for somewhere else arriving here means something is misrouted,
    #: and admitting it would hide that.
    to_instance = models.CharField(max_length=64, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)

    #: Stamped by this instance at store time from its own clock. An absolute
    #: time travelling in the payload would assume two instances agree on the
    #: hour, and skew would expire tickets early or late in a way nobody would
    #: think to look for.
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        verbose_name = "scaling ticket"
        verbose_name_plural = "scaling tickets"

    def __str__(self):
        return f"ticket for {self.character_archive_id} -> {self.to_instance}"
