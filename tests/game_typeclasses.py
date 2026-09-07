# SPDX-License-Identifier: BSD-3-Clause
"""A real character typeclass, for tests that create objects.

Separate from `typeclass_stubs.py` because this imports Evennia. Nothing may
point a settings-file typeclass at it: `check_settings` resolves those during
``django.setup()``, and importing Evennia's typeclasses that early is not
safe. Tests import it inside the test body instead.
"""

from evennia.accounts.accounts import DefaultAccount
from evennia.objects.objects import DefaultCharacter, DefaultRoom

from evennia_scaling.mixins import (
    ScalingAccountMixin,
    ScalingCharacterMixin,
    ScalingRoomMixin,
)


class ScalingCharacter(ScalingCharacterMixin, DefaultCharacter):
    """A character carrying the mixin, declared as a consumer would."""


class ScalingRoom(ScalingRoomMixin, DefaultRoom):
    """A room carrying the mixin, declared as a consumer would."""


class ScalingAccount(ScalingAccountMixin, DefaultAccount):
    """An account carrying the mixin, declared as a consumer would."""
