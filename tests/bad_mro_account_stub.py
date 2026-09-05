# SPDX-License-Identifier: BSD-3-Clause
"""An account typeclass module that cannot be imported, for SV-10.

Both mixins listed with archive's first, which Python refuses — a base class
cannot precede its own subclass.
"""

from evennia_archive.mixins import ArchivableAccountMixin

from evennia_scaling.mixins import ScalingAccountMixin


class BadAccountOrder(ArchivableAccountMixin, ScalingAccountMixin):
    """Never defines — the import raises before this body matters."""
