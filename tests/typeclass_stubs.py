# SPDX-License-Identifier: BSD-3-Clause
"""Stand-in typeclasses for the startup-validation tests.

**Nothing here imports Evennia.** `test_settings.py` points
``BASE_CHARACTER_TYPECLASS`` at one of these, and `check_settings` resolves
that during ``django.setup()`` — before Django has finished starting, and
before Evennia's typeclasses can safely be imported.

They are not real typeclasses and do not need to be: startup validation only
asks what a class inherits from. A character the suite actually creates
objects from lives in `game_typeclasses.py`, which is imported lazily.
"""

from evennia_archive.mixins import (
    ArchivableAccountMixin,
    ArchivableCharacterMixin,
)

from evennia_scaling.mixins import ScalingAccountMixin, ScalingCharacterMixin


class ScalingCharacterStub(ScalingCharacterMixin):
    """Correctly configured — ours, and archive's with it."""


class ScalingAccountStub(ScalingAccountMixin):
    """The account side of the same."""


class ArchivableAccountStub(ArchivableAccountMixin):
    """Archive's account mixin only — SV-08's case."""


class ArchivableCharacterStub(ArchivableCharacterMixin):
    """Archive's mixin only — SV-03's case.

    Someone who followed `evennia-archive`'s install guide and stopped there.
    """


class LookalikeStub:
    """Exposes ``archive_id`` without any mixin — SV-04's case.

    Identity has to come from the mixin so it is a uuid4 and unique across
    instances. A hand-rolled value satisfies the attribute and guarantees
    neither.
    """

    @property
    def archive_id(self):
        return "hand-rolled-identity"


class PlainStub:
    """Neither mixin — what an unmodified Evennia typeclass looks like."""
