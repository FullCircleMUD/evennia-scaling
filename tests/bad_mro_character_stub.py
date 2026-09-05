# SPDX-License-Identifier: BSD-3-Clause
"""A character typeclass module that cannot be imported, for SV-05.

Both mixins listed with archive's first, which Python refuses — a base class
cannot precede its own subclass. Importing this raises ``TypeError`` naming
both, which is what `check_settings` translates into an ordering message.
"""

from evennia_archive.mixins import ArchivableCharacterMixin

from evennia_scaling.mixins import ScalingCharacterMixin


class BadCharacterOrder(ArchivableCharacterMixin, ScalingCharacterMixin):
    """Never defines — the import raises before this body matters."""
