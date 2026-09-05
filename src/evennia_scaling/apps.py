# SPDX-License-Identifier: BSD-3-Clause
"""Django AppConfig — how the library gets into a running Evennia.

`ready()` runs during ``django.setup()``, before anything the library does can
be reached. Two things happen here: settings with no safe default are checked,
so an instance missing one says so at startup rather than at whatever moment
first needs it; and the class settings Evennia resolves later are repointed.
"""

from django.apps import AppConfig


class EvenniaScalingConfig(AppConfig):
    name = "evennia_scaling"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        """Check what must be configured, then install the overrides."""
        from . import config

        config.get_role()
        self._install_session_class()

    def _install_session_class(self):
        """Subclass whatever `SERVER_SESSION_CLASS` names, and repoint it.

        The consumer's class is stashed and built on top of rather than
        replaced — ours is the leaf, so our method runs and `super()` runs
        theirs. A game with its own session class keeps it.

        The generated class is assigned onto its module because Evennia
        resolves the setting by dotted path, not by value.

        `ready()` can run more than once, so repointing a setting that
        already names ours returns rather than layering a second time.
        """
        from django.conf import settings
        from evennia.utils.utils import class_from_module

        from . import sessions

        ours = "evennia_scaling.sessions.ScalingServerSession"
        original = settings.SERVER_SESSION_CLASS
        if original == ours:
            return

        settings._SCALING_ORIGINAL_SESSION_CLASS = original
        sessions.ScalingServerSession = sessions.make_scaling_session(
            class_from_module(original)
        )
        settings.SERVER_SESSION_CLASS = ours
