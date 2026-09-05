# SPDX-License-Identifier: BSD-3-Clause
"""Django AppConfig — where the library checks it can run at all.

`ready()` runs during ``django.setup()``, before anything the library does
can be reached. Settings with no safe default are checked here, so an
instance missing one says so at startup rather than at whatever moment first
happens to need it.
"""

from django.apps import AppConfig


class EvenniaScalingConfig(AppConfig):
    name = "evennia_scaling"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        """Refuse to start when a required setting is missing.

        `get_role` raises on its own, but only when something calls it — and
        on a router that may be the first player to connect. Calling it here
        turns a misconfiguration into one line at startup naming the setting.
        """
        from . import config

        config.get_role()
