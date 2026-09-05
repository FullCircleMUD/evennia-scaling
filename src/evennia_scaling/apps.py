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

        config.check_settings()

        # Registering a message type is an import side effect, so the module
        # has to be imported somewhere that runs on every instance. Nothing
        # else does it on a receiving instance: the sender reaches `messages`
        # through `handoff`, and the receiver imports `handoff` only after a
        # ticket has been redeemed — which is what cannot happen without the
        # message. Left out, an arrival refuses a token that was genuinely
        # issued, because the bus row sits unhandled.
        from . import messages  # noqa: F401

        self._install_session_class()
        self._install_ooc_command()

    def _install_ooc_command(self):
        """Put our `ooc` where Evennia's default cmdset will pick it up.

        Not the class-setting treatment `SERVER_SESSION_CLASS` gets, even
        though `CMDSET_ACCOUNT` is a setting: it names a gamedir module that
        imports `evennia.default_cmds`, which is not populated while
        `ready()` is running, so resolving it here raises.

        The module attribute is replaced instead, which is what
        `AccountCmdSet.at_cmdset_creation` reads when a session is built —
        long after startup.
        """
        from evennia.commands.default import account as account_commands
        from . import commands

        account_commands.CmdOOC = commands.ScalingCmdOOC

        # The account-state commands, restricted to out of character. Each
        # override carries only a lockstring; assigning the module attribute
        # is what puts it in front of Evennia's own cmdsets, which read
        # `account.CmdPassword` when a session's cmdset is built.
        account_commands.CmdPassword = commands.ScalingCmdPassword
        account_commands.CmdOption = commands.ScalingCmdOption
        account_commands.CmdStyle = commands.ScalingCmdStyle
        account_commands.CmdQuell = commands.ScalingCmdQuell
        account_commands.CmdCharCreate = commands.ScalingCmdCharCreate
        account_commands.CmdCharDelete = commands.ScalingCmdCharDelete
        account_commands.CmdIC = commands.ScalingCmdIC

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
