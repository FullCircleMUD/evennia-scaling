# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for evennia-scaling.

A case is agreed in docs/test-plan.md first, then the test is written here
against it, then the code. Every test carries its case ID as its docstring,
so the coverage trail reads in both directions.

Discovered by Django's test runner via runtests.py at the repository root.
"""

import json
import unittest
from datetime import timedelta

from django.conf import settings
from django.test import TestCase, override_settings

import evennia_scaling
from evennia_scaling.tickets import create_ticket


class TestScaffold(unittest.TestCase):
    """SC — the library is installed and the runner reaches it."""

    def test_sc_01_the_package_is_importable_and_versioned(self):
        """SC-01: proves the install and the runner, end to end.

        Not a behaviour of the library — a check that there is a library to
        test. It fails when the editable install is missing, when the test
        settings do not name the app, or when the runner cannot find this
        module at all, each of which otherwise looks like "no tests ran".
        """
        self.assertEqual(evennia_scaling.__version__, "0.0.1")

    def test_sc_02_the_log_shim_is_a_no_op_outside_evennia(self):
        """SC-02: a log call must never raise into its caller.

        The shim swallows the ImportError when Evennia is not bootstrapped,
        and deliberately does not fall back to stderr or a local file — a
        library that logs somewhere unexpected is worse than one that stays
        quiet.
        """
        from evennia_scaling.log import scaling_log

        self.assertIsNone(scaling_log("scaffold check"))
        self.assertIsNone(scaling_log("scaffold check", level="NONSENSE"))


class TestTickets(TestCase):
    """TK — tickets."""

    ACCOUNT = "27fd6a3e-1459-4618-992b-e1e1a0e3610e"
    CHARACTER = "ce8759ef-62cb-4351-b8b3-219a9fd2a7de"

    def test_tk_01_returns_the_ticket_as_data(self):
        """TK-01: the shape is defined here, not at the call site.

        Returned as a mapping rather than a bare token so the receiving
        instance reads back the same shape the sender minted. A bare token
        would leave whatever builds the handoff to assemble the rest, with
        nothing holding the two ends in agreement.
        """
        ticket = create_ticket(self.ACCOUNT, self.CHARACTER, "shard0")

        self.assertEqual(ticket["account_archive_id"], self.ACCOUNT)
        self.assertEqual(ticket["character_archive_id"], self.CHARACTER)
        self.assertEqual(ticket["to_instance"], "shard0")
        self.assertTrue(ticket["token"])

    def test_tk_02_each_call_mints_a_different_token(self):
        """TK-02: two tickets never share a token, same arguments or not."""
        first = create_ticket(self.ACCOUNT, self.CHARACTER, "shard0")
        second = create_ticket(self.ACCOUNT, self.CHARACTER, "shard0")
        self.assertNotEqual(first["token"], second["token"])

    def test_tk_03_token_is_canonical_lowercase_hex(self):
        """TK-03: so comparison stays plain string equality.

        A token that needed normalising before comparison would put that
        step in every caller, and one of them would forget.
        """
        token = create_ticket(self.ACCOUNT, self.CHARACTER, "shard0")["token"]

        self.assertIsInstance(token, str)
        self.assertEqual(token, token.lower())
        self.assertTrue(
            set(token) <= set("0123456789abcdef"),
            f"token is not plain hex: {token!r}",
        )

    def test_tk_04_writes_no_row_on_the_sending_instance(self):
        """TK-04: the only stored copy lives on the receiving instance.

        If this starts failing, the library has grown a second source of
        truth for where a transfer stands.
        """
        with self.assertNumQueries(0):
            create_ticket(self.ACCOUNT, self.CHARACTER, "shard0")

    def test_tk_05_the_table_is_in_the_game_database(self):
        """TK-05: pins the placement, so it is not moved to an alias.

        A library's tables go on an alias of its own when its data has to
        outlive the game database or be read by more than one instance. A
        ticket is neither — one instance writes and reads it seconds apart,
        and after a wipe there is no in-flight handoff whose ticket matters.

        Asserted through the router chain rather than by reading settings, so
        it fails if a router is added that sends these rows elsewhere.
        """
        from evennia_scaling.models import Ticket

        self.assertEqual(Ticket.objects.all().db, "default")

    def _ticket(self, to_instance="shard0"):
        return create_ticket(self.ACCOUNT, self.CHARACTER, to_instance)

    def test_tk_06_stores_every_field_of_the_ticket(self):
        """TK-06: what the sender minted is what the receiver holds.

        A field dropped here is one the receiver cannot check on redemption
        or hand back to whatever rebuilds the character.
        """
        from evennia_scaling.models import Ticket
        from evennia_scaling.tickets import store_ticket

        ticket = self._ticket()
        store_ticket(ticket)

        row = Ticket.objects.get(token=ticket["token"])
        self.assertEqual(row.account_archive_id, ticket["account_archive_id"])
        self.assertEqual(
            row.character_archive_id, ticket["character_archive_id"]
        )
        self.assertEqual(row.to_instance, ticket["to_instance"])

    @override_settings(SCALING_TICKET_LIFETIME_SECONDS=30)
    def test_tk_07_stamps_an_expiry_from_the_local_clock(self):
        """TK-07: the payload carries no expiry — this instance decides.

        An absolute time travelling in the payload would assume two
        instances agree on the hour, and skew would expire tickets early or
        late in a way nobody would think to look for.
        """
        from django.utils import timezone

        from evennia_scaling.tickets import store_ticket

        before = timezone.now()
        row = store_ticket(self._ticket())
        after = timezone.now()

        self.assertGreaterEqual(row.expires_at, before + timedelta(seconds=30))
        self.assertLessEqual(row.expires_at, after + timedelta(seconds=30))

    def test_tk_08_storing_sweeps_expired_tickets(self):
        """TK-08: cleanup rides on traffic rather than a scheduler.

        A busy instance sweeps constantly; a quiet one accumulates nothing,
        because nothing is arriving.
        """
        from django.utils import timezone

        from evennia_scaling.models import Ticket
        from evennia_scaling.tickets import store_ticket

        stale = self._ticket()
        store_ticket(stale)
        Ticket.objects.filter(token=stale["token"]).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        store_ticket(self._ticket())
        self.assertFalse(Ticket.objects.filter(token=stale["token"]).exists())

    def test_tk_09_the_sweep_spares_live_tickets(self):
        """TK-09: including the one just written.

        Sweeping after the write rather than before is what makes that
        certain — the new row is the one thing that must survive, and this
        order means a sweep can never race it.
        """
        from evennia_scaling.models import Ticket
        from evennia_scaling.tickets import store_ticket

        first = self._ticket()
        store_ticket(first)
        second = self._ticket()
        store_ticket(second)

        held = set(Ticket.objects.values_list("token", flat=True))
        self.assertEqual(held, {first["token"], second["token"]})


class TestConfig(TestCase):
    """CF — settings."""

    def test_cf_01_the_ticket_lifetime_defaults_to_ten_seconds(self):
        """CF-01: a consumer who sets nothing gets this.

        Exercised only through `store_ticket` otherwise, and always with the
        setting overridden — so the default could change and nothing would
        notice.
        """
        from evennia_scaling.config import get_ticket_lifetime

        self.assertEqual(get_ticket_lifetime(), 10)

    @override_settings(SCALING_ROLE=None)
    def test_cf_02_an_undeclared_role_is_refused(self):
        """CF-02: there is no harmless default to fall back on.

        `evennia-shards` can default to a dormant monolith mode and do
        nothing. Installing this library means at least a router and one
        shard, so an instance that does not know which it is cannot behave
        correctly in any direction.
        """
        from django.core.exceptions import ImproperlyConfigured

        from evennia_scaling.config import check_settings

        with self.assertRaises(ImproperlyConfigured) as raised:
            check_settings()
        self.assertIn("SCALING_ROLE", str(raised.exception))

    @override_settings(SCALING_ROLE="banana")
    def test_cf_03_an_unknown_role_lists_the_valid_ones(self):
        """CF-03: a typo is caught at boot, not at the first branch.

        Listing the two valid values is what makes the line actionable —
        otherwise it reports a problem without saying what would fix it.
        """
        from django.core.exceptions import ImproperlyConfigured

        from evennia_scaling.config import (
            ROLE_ROUTER,
            ROLE_SHARD,
            check_settings,
        )

        with self.assertRaises(ImproperlyConfigured) as raised:
            check_settings()
        message = str(raised.exception)
        self.assertIn(ROLE_ROUTER, message)
        self.assertIn(ROLE_SHARD, message)

    def test_cf_04_ready_checks_the_required_settings(self):
        """CF-04: validating at first use is not enough.

        That moment depends on what the library does — on a router it may be
        the first player to connect — so a misconfigured instance boots
        cleanly and fails somewhere that says nothing about the setting.
        """
        from unittest import mock

        from django.apps import apps as django_apps

        config = django_apps.get_app_config("evennia_scaling")
        with mock.patch("evennia_scaling.config.check_settings") as checking:
            config.ready()
        checking.assert_called_once()

    @override_settings(SCALING_SHARDS=None)
    def test_cf_05_an_undeclared_shard_roster_is_refused(self):
        """CF-05: there is nothing to guess.

        The roster is what a character's `current_shard` is validated
        against, so an instance without one can validate nothing.
        """
        from django.core.exceptions import ImproperlyConfigured

        from evennia_scaling.config import check_settings

        with self.assertRaises(ImproperlyConfigured) as raised:
            check_settings()
        self.assertIn("SCALING_SHARDS", str(raised.exception))

    @override_settings(SCALING_SHARDS=())
    def test_cf_06_an_empty_shard_roster_is_refused(self):
        """CF-06: no character can be played anywhere.

        Declared-but-empty is as unusable as undeclared, and installing this
        library means at least a router and one shard.
        """
        from django.core.exceptions import ImproperlyConfigured

        from evennia_scaling.config import check_settings

        with self.assertRaises(ImproperlyConfigured):
            check_settings()

    @override_settings(SCALING_SHARDS="shard0")
    def test_cf_07_a_bare_string_is_refused(self):
        """CF-07: the one wrong shape that silently succeeds.

        A string is iterable, so nothing raises and nothing looks wrong:
        `"shard0" in "shard0"` is True, but so is `"s"`, and a roster of
        letters matches no instance any deployment runs.
        """
        from django.core.exceptions import ImproperlyConfigured

        from evennia_scaling.config import check_settings

        with self.assertRaises(ImproperlyConfigured):
            check_settings()

    def test_cf_08_a_list_and_a_tuple_are_both_accepted(self):
        """CF-08: the shape check refuses a string, not a sequence.

        Settings files are written by hand and both spellings are natural,
        so refusing one would be a trap rather than a check.
        """
        from evennia_scaling.config import check_settings

        for roster in (["shard0", "shard1"], ("shard0", "shard1")):
            with self.subTest(roster=roster):
                with override_settings(SCALING_SHARDS=roster):
                    check_settings()

    @override_settings(SCALING_SHARDS=("shard0",))
    def test_cf_09_an_unset_world_anchor_is_refused(self):
        """CF-09: the library cannot guess which instance holds a room.

        Both anchors, because they are separate settings a deployment can
        forget independently — so each is checked with the other set, or one
        missing anchor would satisfy the case for both.
        """
        from django.core.exceptions import ImproperlyConfigured

        from evennia_scaling.config import (
            SETTING_DEFAULT_HOME_SHARD,
            SETTING_START_LOCATION_SHARD,
            check_settings,
        )

        for setting in (
            SETTING_START_LOCATION_SHARD,
            SETTING_DEFAULT_HOME_SHARD,
        ):
            with self.subTest(setting=setting):
                with override_settings(**{setting: None}):
                    with self.assertRaises(ImproperlyConfigured) as raised:
                        check_settings()
                    self.assertIn(setting, str(raised.exception))

    @override_settings(SCALING_ROUTER_ID=None)
    def test_cf_11_an_unset_router_id_is_refused(self):
        """CF-11: a shard cannot work out which peer the router is.

        Instances see no database and no settings but their own, so the one
        name a shard cannot derive is the one it needs whenever it cannot
        admit a session.
        """
        from django.core.exceptions import ImproperlyConfigured

        from evennia_scaling.config import check_settings

        with self.assertRaises(ImproperlyConfigured) as raised:
            check_settings()
        self.assertIn("SCALING_ROUTER_ID", str(raised.exception))

    @override_settings(
        SCALING_SHARDS=("router", "shard0"),
        SCALING_ROUTER_ID="router",
    )
    def test_cf_12_a_router_id_in_the_roster_is_refused(self):
        """CF-12: the router is not a shard.

        It holds accounts, not rooms a character stands in. Listing it as a
        shard would make it a legal `current_shard`, so a character could be
        sent to be played on the instance that is only ever a waypoint.
        """
        from django.core.exceptions import ImproperlyConfigured

        from evennia_scaling.config import check_settings

        with self.assertRaises(ImproperlyConfigured) as raised:
            check_settings()
        self.assertIn("SCALING_ROUTER_ID", str(raised.exception))

    @override_settings(SCALING_SHARDS=("shard0",))
    def test_cf_10_a_world_anchor_outside_the_roster_is_refused(self):
        """CF-10: a name nothing runs under answers nothing.

        The typo is the case that matters: the value is a plausible shard
        id, so nothing about it looks wrong until a character is sent there
        and no instance is listening.
        """
        from django.core.exceptions import ImproperlyConfigured

        from evennia_scaling.config import (
            SETTING_DEFAULT_HOME_SHARD,
            SETTING_START_LOCATION_SHARD,
            check_settings,
        )

        for setting in (
            SETTING_START_LOCATION_SHARD,
            SETTING_DEFAULT_HOME_SHARD,
        ):
            with self.subTest(setting=setting):
                with override_settings(**{setting: "shrad0"}):
                    with self.assertRaises(ImproperlyConfigured) as raised:
                        check_settings()
                    message = str(raised.exception)
                    self.assertIn("shrad0", message)
                    self.assertIn("shard0", message)


class TestAccountMixin(TestCase):
    """AC — the account mixin."""

    #: The archive is a second database, and Django blocks a test from
    #: touching an alias it has not declared.
    databases = {"default", "archive"}

    _next = 0

    def setUp(self):
        """Empty Evennia's identity map before each test.

        Evennia's models are `SharedMemoryModel`, so a query returns a
        cached instance keyed on (class, primary key). That cache is
        process-global and survives Django's per-test rollback — so a
        restore landing on a primary key an earlier test used hands back
        the earlier test's object, with its state. Evennia's own test base
        does the same thing.
        """
        from evennia.utils.idmapper.models import flush_cache

        super().setUp()
        flush_cache()

    def _account(self):
        """An account created as a consumer's would be.

        Through `create_account` rather than the model, so Evennia's creation
        hooks run — which is what this mixin hangs off.
        """
        from evennia.utils.create import create_account

        from tests.game_typeclasses import ScalingAccount

        TestAccountMixin._next += 1
        name = f"rowan{TestAccountMixin._next}"
        return create_account(
            name,
            f"{name}@example.com",
            "testpassword123",
            typeclass=ScalingAccount,
        )

    def test_ac_01_an_archived_account_is_found_by_username(self):
        """AC-01: the username is the only thing a player supplies.

        A real round trip rather than a mocked search, so it fails if the
        column we name and the column the archive holds ever disagree.
        """
        from evennia_archive.api import archive

        from tests.game_typeclasses import ScalingAccount

        account = self._account()
        archive(account)

        self.assertEqual(
            ScalingAccount.find_in_archive(account.username),
            account.archive_id,
        )

    def test_ac_02_an_unarchived_username_returns_none(self):
        """AC-02: a brand new account has nothing to come back from.

        The ordinary case on a first login, not a fault.
        """
        from tests.game_typeclasses import ScalingAccount

        self.assertIsNone(ScalingAccount.find_in_archive("nobody-at-all"))

    def _archived_account(self):
        """An account and its archived copy, with the live one deleted.

        The state an instance is in when someone arrives having played
        elsewhere: nothing local, everything in the archive.
        """
        from evennia_archive.api import archive

        account = self._account()
        archive(account)
        archive_id = account.archive_id
        username = account.username
        account.delete()
        return archive_id, username

    def test_ac_03_an_archived_account_is_rebuilt(self):
        """AC-03: nothing live is in the way, so this is a plain restore."""
        from evennia.accounts.models import AccountDB

        from tests.game_typeclasses import ScalingAccount

        archive_id, username = self._archived_account()

        rebuilt = ScalingAccount.rebuild_from_archive(archive_id)

        self.assertEqual(rebuilt.archive_id, archive_id)
        self.assertTrue(AccountDB.objects.filter(username=username).exists())

    def test_ac_04_a_stale_local_copy_is_replaced(self):
        """AC-04: `restore` is idempotent, so it would return the stale one.

        The delete is the mechanism rather than tidiness — without it this
        hands back whatever the instance was already holding.
        """
        from evennia_archive.api import archive

        from tests.game_typeclasses import ScalingAccount

        account = self._account()
        account.db.progress = "as archived"
        archive(account)
        account.db.progress = "changed since"

        rebuilt = ScalingAccount.rebuild_from_archive(account.archive_id)

        self.assertEqual(rebuilt.db.progress, "as archived")

    def test_ac_05_an_unarchived_identity_raises(self):
        """AC-05: the caller asked for something that is not there.

        Information rather than an empty result — the ticket path has to be
        able to say the account it was promised is missing.
        """
        from evennia_archive.api import NotArchived

        from tests.game_typeclasses import ScalingAccount

        with self.assertRaises(NotArchived):
            ScalingAccount.rebuild_from_archive(
                "0d1a4d9c-0000-4000-8000-000000000000"
            )

    def test_ac_06_the_accounts_local_characters_go_with_it(self):
        """AC-06: Evennia nulls `db_account` rather than cascading.

        Left alone they survive as orphans nothing references, and a later
        `restore` hands one of them back unchanged.
        """
        from evennia.objects.models import ObjectDB

        from tests.game_typeclasses import ScalingAccount

        account = self._account()
        # create_character returns (character, errors).
        character, errors = account.create_character(
            key="Rowan", typeclass="tests.game_typeclasses.ScalingCharacter"
        )
        self.assertFalse(errors, errors)
        character_pk = character.pk

        from evennia_archive.api import archive

        archive(account)
        ScalingAccount.rebuild_from_archive(account.archive_id)

        self.assertFalse(ObjectDB.objects.filter(pk=character_pk).exists())

    def test_ac_07_an_archived_account_is_refreshed_by_username(self):
        """AC-07: the login door knows a username and nothing else.

        `authenticate` is handed a string a player typed, so finding the
        identity is the work.
        """
        from evennia_archive.api import archive

        from tests.game_typeclasses import ScalingAccount

        account = self._account()
        account.db.progress = "as archived"
        archive(account)
        account.db.progress = "changed since"

        refreshed = ScalingAccount.refresh_from_archive(account.username)

        self.assertEqual(refreshed.db.progress, "as archived")

    def test_ac_08_an_unarchived_username_is_left_alone(self):
        """AC-08: a brand new account has nothing to come back from.

        The ordinary case on a first login. The local account has to
        survive it, or a first-time player is deleted on the way in.
        """
        from evennia.accounts.models import AccountDB

        from tests.game_typeclasses import ScalingAccount

        account = self._account()

        self.assertIsNone(ScalingAccount.refresh_from_archive(account.username))
        self.assertTrue(AccountDB.objects.filter(pk=account.pk).exists())

    def test_ac_09_a_superuser_is_not_refreshed(self):
        """AC-09: rebuilding one takes an operator's way in with it.

        Evennia expects #1 to be there. Archived and refreshed like any
        other account, a superuser would be deleted and restored — and a
        restore that renamed it on collision would lock the operator out.
        """
        from evennia.accounts.models import AccountDB
        from evennia_archive.api import archive

        from tests.game_typeclasses import ScalingAccount

        account = self._account()
        account.is_superuser = True
        account.save()
        archive(account)
        pk = account.pk

        self.assertIsNone(ScalingAccount.refresh_from_archive(account.username))
        # The same row, not a rebuilt one: a restore mints a new primary key.
        self.assertTrue(AccountDB.objects.filter(pk=pk).exists())

    def test_ac_10_credentials_are_checked_against_the_archived_copy(self):
        """AC-10: refreshing after `super()` would refuse a player's own password.

        Archived under one password, changed locally since. Authenticating
        with the archived one passes only if the refresh ran first.
        """
        from evennia_archive.api import archive

        from tests.game_typeclasses import ScalingAccount

        account = self._account()
        account.set_password("archived-password")
        account.save()
        archive(account)
        account.set_password("changed-since")
        account.save()

        found, errors = ScalingAccount.authenticate(
            account.username, "archived-password"
        )

        self.assertIsNotNone(found, errors)


    def test_ac_11_the_return_value_is_evennias(self):
        """AC-11: the override adds a step, it does not replace the check.

        A wrong password still fails, and still comes back as Evennia's
        `(None, errors)` rather than anything of ours.
        """
        from tests.game_typeclasses import ScalingAccount

        account = self._account()

        found, errors = ScalingAccount.authenticate(
            account.username, "not-the-password"
        )

        self.assertIsNone(found)
        self.assertTrue(errors)

    def test_ac_12_an_unarchived_account_still_authenticates(self):
        """AC-12: the refresh's result is deliberately ignored.

        A first-time player has nothing archived. Treating that as a failed
        login would lock out everyone who has never left the router.
        """
        from tests.game_typeclasses import ScalingAccount

        account = self._account()

        found, errors = ScalingAccount.authenticate(
            account.username, "testpassword123"
        )

        self.assertIsNotNone(found, errors)


    def _archived_character(self, account, key):
        """A character owned by `account`, archived, with the live copy gone.

        The state the router is in when someone comes back: the roster is
        in the archive and nothing local remains.
        """
        from evennia_archive.api import archive

        character, errors = account.create_character(
            key=key, typeclass="tests.game_typeclasses.ScalingCharacter"
        )
        self.assertFalse(errors, errors)
        archive(character)
        archive_id = character.archive_id
        character.delete()
        return archive_id

    @override_settings(SCALING_ROLE="router")
    def test_ac_13_a_router_restores_every_owned_character(self):
        """AC-13: found by the owner stamp, which survives the archive.

        `db_account` is a primary key and does not, so the stamp is the
        only link back to an owner that comes through a round trip.
        """
        from tests.game_typeclasses import ScalingAccount

        account = self._account()
        self._archived_character(account, "Rowan")
        self._archived_character(account, "Bram")

        ScalingAccount.restore_characters(account)

        self.assertEqual(
            sorted(character.key for character in account.characters.all()),
            ["Bram", "Rowan"],
        )

    @override_settings(SCALING_ROLE="router")
    def test_ac_14_restored_characters_join_the_roster(self):
        """AC-14: else the character-select menu is silently empty.

        Restoring without adding to the roster looks like it worked and
        leaves the player with nothing to choose from.
        """
        from evennia.objects.models import ObjectDB

        from tests.game_typeclasses import ScalingAccount

        account = self._account()
        self._archived_character(account, "Rowan")

        ScalingAccount.restore_characters(account)

        self.assertTrue(ObjectDB.objects.filter(db_key="Rowan").exists())
        self.assertEqual(
            [character.key for character in account.characters.all()], ["Rowan"]
        )

    @override_settings(SCALING_ROLE="shard")
    def test_ac_15_a_shard_restores_nothing(self):
        """AC-15: a shard receives one character, the one its ticket names.

        Restoring a whole roster here would put every character on an
        instance it is not being played on.
        """
        from evennia.objects.models import ObjectDB

        from tests.game_typeclasses import ScalingAccount

        account = self._account()
        self._archived_character(account, "Rowan")

        ScalingAccount.restore_characters(account)

        self.assertFalse(ObjectDB.objects.filter(db_key="Rowan").exists())
        self.assertEqual(list(account.characters.all()), [])

    @override_settings(SCALING_ROLE="router")
    def test_ac_16_another_accounts_characters_are_left_alone(self):
        """AC-16: the stamp's value is what makes the filter mean anything.

        Match the key and ignore the value and every archived character in
        the deployment lands on whichever account restores first.
        """
        from evennia.objects.models import ObjectDB

        from tests.game_typeclasses import ScalingAccount

        mine = self._account()
        theirs = self._account()
        self._archived_character(mine, "Rowan")
        self._archived_character(theirs, "Bram")

        ScalingAccount.restore_characters(mine)

        self.assertEqual(
            [character.key for character in mine.characters.all()], ["Rowan"]
        )
        self.assertFalse(ObjectDB.objects.filter(db_key="Bram").exists())


class TestCurrentShard(TestCase):
    """SH — where a character is in the game world."""

    def _character(self):
        """A character carrying the mixin, created as a consumer's would be.

        Through `create_object` rather than the model, so Evennia's creation
        hooks run — which is what mints the archive identity underneath.
        """
        from evennia.utils.create import create_object

        from tests.game_typeclasses import ScalingCharacter

        return create_object(ScalingCharacter, key="Rowan")

    def test_sh_01_is_stored_as_an_attribute(self):
        """SH-01: an Attribute survives archiving; a field would not.

        The archive copies Attribute rows. A value living anywhere else on
        the object would be dropped on the way in, and the character would
        arrive at its destination not knowing where it is.
        """
        from evennia_scaling.mixins import CURRENT_SHARD_KEY

        character = self._character()
        character.current_shard = "shard1"
        self.assertTrue(character.attributes.has(CURRENT_SHARD_KEY))

    def test_sh_02_accepts_a_shard_in_the_roster(self):
        """SH-02: and reads back exactly what was assigned."""
        character = self._character()
        character.current_shard = "shard1"
        self.assertEqual(character.current_shard, "shard1")

    def test_sh_03_refuses_a_shard_outside_the_roster(self):
        """SH-03: the cause is almost always a typo.

        Naming the value and the roster is what makes the line actionable —
        the two together are the whole diagnosis.
        """
        character = self._character()
        with self.assertRaises(ValueError) as raised:
            character.current_shard = "shrad0"
        message = str(raised.exception)
        self.assertIn("shrad0", message)
        self.assertIn("shard0", message)

    def test_sh_04_refuses_none(self):
        """SH-04: there is no un-set path.

        A refusal that read as "None is not in ('shard0', 'shard1')" would
        describe a typo rather than the mistake actually made, so the message
        has to name the attribute.
        """
        character = self._character()
        with self.assertRaises(ValueError) as raised:
            character.current_shard = None
        self.assertIn("current_shard", str(raised.exception))

    def test_sh_06_carries_the_archive_mixin(self):
        """SH-06: one mixin on the character, not two.

        Asserts the relationship and nothing more. Archive tests its own
        mixins; what its suite cannot see is this subclass.
        """
        from evennia_archive.mixins import ArchivableCharacterMixin

        from evennia_scaling.mixins import ScalingCharacterMixin

        self.assertTrue(
            issubclass(ScalingCharacterMixin, ArchivableCharacterMixin)
        )

    @override_settings(SCALING_START_LOCATION_SHARD="shard1")
    def test_sh_05_a_character_never_assigned_reads_as_the_start_shard(self):
        """SH-05: so a character created any way at all is somewhere.

        Nothing hooks creation. Evennia's `autocreate` writes the default on
        the first read, which is also what puts it through `at_set`.
        """
        character = self._character()
        self.assertEqual(character.current_shard, "shard1")


_STUBS = "tests.typeclass_stubs"
_SCALING_CHARACTER = f"{_STUBS}.ScalingCharacterStub"
_ARCHIVABLE_CHARACTER = f"{_STUBS}.ArchivableCharacterStub"
_LOOKALIKE = f"{_STUBS}.LookalikeStub"
_PLAIN = f"{_STUBS}.PlainStub"
_SCALING_ACCOUNT = f"{_STUBS}.ScalingAccountStub"
_ARCHIVABLE_ACCOUNT = f"{_STUBS}.ArchivableAccountStub"
_BAD_MRO = "tests.bad_mro_character_stub.BadCharacterOrder"
_BAD_MRO_ACCOUNT = "tests.bad_mro_account_stub.BadAccountOrder"
_BAD_IMPORT = "tests.bad_import_stub.Anything"


class TestStartupValidation(TestCase):
    """SV — startup validation of the consumer's typeclasses."""

    def _check(self):
        from evennia_scaling.config import check_settings

        return check_settings()

    @override_settings(BASE_CHARACTER_TYPECLASS=_SCALING_CHARACTER)
    def test_sv_01_a_character_carrying_the_mixin_passes(self):
        """SV-01: correctly configured, the check is quiet."""
        self.assertIsNone(self._check())

    @override_settings(BASE_CHARACTER_TYPECLASS=_PLAIN)
    def test_sv_02_a_character_without_the_mixin_is_refused(self):
        """SV-02: identity is minted at creation, so this cannot be fixed later.

        The message carries the setting, the class and the mixin, because
        those three together are the whole fix.
        """
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured) as raised:
            self._check()
        message = str(raised.exception)
        self.assertIn("BASE_CHARACTER_TYPECLASS", message)
        self.assertIn(_PLAIN, message)
        self.assertIn("ScalingCharacterMixin", message)

    @override_settings(BASE_CHARACTER_TYPECLASS=_ARCHIVABLE_CHARACTER)
    def test_sv_03_only_the_archive_mixin_is_told_to_use_ours(self):
        """SV-03: they followed archive's install guide and stopped.

        Telling them to add a mixin when they have added one is the least
        useful thing we could say, so the message names both.
        """
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured) as raised:
            self._check()
        message = str(raised.exception)
        self.assertIn("ScalingCharacterMixin", message)
        self.assertIn("ArchivableCharacterMixin", message)

    @override_settings(BASE_CHARACTER_TYPECLASS=_LOOKALIKE)
    def test_sv_04_a_hand_rolled_archive_id_is_refused(self):
        """SV-04: the attribute is a loose proxy for the real question.

        Identity has to be a uuid4 and unique across instances. Only the
        mixin guarantees that, so the mixin is what is tested for.
        """
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            self._check()

    @override_settings(BASE_CHARACTER_TYPECLASS=_BAD_MRO)
    def test_sv_05_an_mro_conflict_becomes_an_ordering_message(self):
        """SV-05: the interpreter's complaint says nothing about the fix.

        We can translate it because our check is what imports the module.
        """
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured) as raised:
            self._check()
        message = str(raised.exception)
        self.assertIn("ScalingCharacterMixin", message)
        self.assertIn("BASE_CHARACTER_TYPECLASS", message)

    @override_settings(BASE_ACCOUNT_TYPECLASS=_PLAIN)
    def test_sv_07_an_account_without_the_mixin_is_refused(self):
        """SV-07: the account side of SV-02.

        An account with no archive identity cannot be moved between
        instances, and identity is minted at creation.
        """
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured) as raised:
            self._check()
        message = str(raised.exception)
        self.assertIn("BASE_ACCOUNT_TYPECLASS", message)
        self.assertIn(_PLAIN, message)
        self.assertIn("ScalingAccountMixin", message)

    @override_settings(BASE_ACCOUNT_TYPECLASS=_ARCHIVABLE_ACCOUNT)
    def test_sv_08_an_account_with_only_the_archive_mixin(self):
        """SV-08: they followed archive's install guide and stopped."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured) as raised:
            self._check()
        message = str(raised.exception)
        self.assertIn("ScalingAccountMixin", message)
        self.assertIn("ArchivableAccountMixin", message)

    @override_settings(BASE_ACCOUNT_TYPECLASS=_LOOKALIKE)
    def test_sv_09_a_hand_rolled_account_archive_id_is_refused(self):
        """SV-09: the mixin is what guarantees a uuid4, not the attribute."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured):
            self._check()

    @override_settings(BASE_ACCOUNT_TYPECLASS=_BAD_MRO_ACCOUNT)
    def test_sv_10_an_account_mro_conflict_becomes_an_ordering_message(self):
        """SV-10: the account side of SV-05."""
        from django.core.exceptions import ImproperlyConfigured

        with self.assertRaises(ImproperlyConfigured) as raised:
            self._check()
        message = str(raised.exception)
        self.assertIn("ScalingAccountMixin", message)
        self.assertIn("BASE_ACCOUNT_TYPECLASS", message)

    @override_settings(BASE_GUEST_TYPECLASS=_PLAIN)
    def test_sv_11_the_guest_typeclass_is_not_checked(self):
        """SV-11: a guest carries nothing between instances.

        Checking it would stop every game that offers guests from booting.
        """
        self.assertIsNone(self._check())

    @override_settings(BASE_CHARACTER_TYPECLASS=_BAD_IMPORT)
    def test_sv_06_an_unrelated_import_error_is_left_alone(self):
        """SV-06: a consumer's own bug is not re-dressed as ours.

        Same exception class as the MRO conflict, so the filter has to tell
        them apart by content. Their module raises again at their own call
        site — a failed import is not left in `sys.modules`.
        """
        self.assertIsNone(self._check())


class _FakeMessage:
    """Stands in for a bus row — the two fields a handler reads."""

    def __init__(self, payload, from_instance="somewhere-else"):
        self.payload = payload
        self.from_instance = from_instance


class TestMessages(TestCase):
    """MS — messages between instances."""

    def _message(self):
        return _FakeMessage(
            create_ticket("account-a", "character-a", "shard0")
        )

    def test_ms_01_kind_is_session_authorized(self):
        """MS-01: the name both ends route on."""
        from evennia_scaling.messages import SessionAuthorized

        self.assertEqual(SessionAuthorized.kind, "session_authorized")

    def test_ms_02_payload_keys_match_a_ticket(self):
        """MS-02: a malformed ticket is refused where it was minted.

        Message-bus checks these before a send, so a missing field fails at
        the sender rather than arriving somewhere as a payload the far end
        cannot use.
        """
        from evennia_scaling.messages import SessionAuthorized

        ticket = create_ticket("account-a", "character-a", "shard0")
        self.assertEqual(
            set(SessionAuthorized.payload_keys), set(ticket.keys())
        )

    def test_ms_03_handling_stores_the_ticket(self):
        """MS-03: the receiver learns of a transfer before the session lands."""
        from evennia_scaling.messages import SessionAuthorized
        from evennia_scaling.models import Ticket

        message = self._message()
        SessionAuthorized().handle(message)

        stored = Ticket.objects.get(token=message.payload["token"])
        self.assertEqual(
            stored.account_archive_id, message.payload["account_archive_id"]
        )
        self.assertEqual(stored.to_instance, message.payload["to_instance"])

    def test_ms_04_a_handled_message_is_consumed(self):
        """MS-04: returning False would leave it to be retried forever."""
        from evennia_scaling.messages import SessionAuthorized

        self.assertIs(SessionAuthorized().handle(self._message()), True)

    def test_ms_05_registers_itself_on_import(self):
        """MS-05: a peer's message has to find a handler.

        Both ends need the class — the sender to call `send`, the receiver to
        dispatch — so registration is an import side effect.
        """
        from evennia_message_bus import get_type

        from evennia_scaling.messages import SessionAuthorized

        self.assertIs(get_type("session_authorized"), SessionAuthorized)


@override_settings(MESSAGEBUS_INSTANCE_ID="shard0")
class TestRedemption(TestCase):
    """TK — redeeming a ticket on arrival."""

    HERE = "shard0"

    def _stored(self, to_instance=HERE, character="character-a"):
        from evennia_scaling.tickets import store_ticket

        ticket = create_ticket("account-a", character, to_instance)
        store_ticket(ticket)
        return ticket

    def test_tk_10_redeems_a_live_ticket_for_this_instance(self):
        """TK-10: the fields are how the caller learns whom to rebuild.

        A bare True would say a session may be admitted without saying who
        it is.
        """
        from evennia_scaling.tickets import redeem_ticket

        ticket = self._stored()
        redeemed = redeem_ticket(ticket["token"])

        self.assertEqual(
            redeemed["account_archive_id"], ticket["account_archive_id"]
        )
        self.assertEqual(
            redeemed["character_archive_id"], ticket["character_archive_id"]
        )

    def test_tk_11_refuses_an_unknown_token(self):
        """TK-11: never issued, already redeemed, or expired and swept."""
        from evennia_scaling.tickets import redeem_ticket

        self.assertIsNone(redeem_ticket("never-issued"))

    def test_tk_12_refuses_a_ticket_for_another_instance(self):
        """TK-12: arriving here means something is misrouted.

        Left intact, so the instance it was addressed to can still honour it.
        """
        from evennia_scaling.models import Ticket
        from evennia_scaling.tickets import redeem_ticket

        ticket = self._stored(to_instance="somewhere-else")
        self.assertIsNone(redeem_ticket(ticket["token"]))
        self.assertTrue(Ticket.objects.filter(token=ticket["token"]).exists())

    def test_tk_13_refuses_an_expired_ticket(self):
        """TK-13: swept before the lookup, so it is simply absent."""
        from django.utils import timezone

        from evennia_scaling.models import Ticket
        from evennia_scaling.tickets import redeem_ticket

        ticket = self._stored()
        Ticket.objects.filter(token=ticket["token"]).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertIsNone(redeem_ticket(ticket["token"]))

    def test_tk_14_a_redeemed_ticket_cannot_be_redeemed_again(self):
        """TK-14: success deletes, which is why it is not a question."""
        from evennia_scaling.tickets import redeem_ticket

        ticket = self._stored()
        self.assertIsNotNone(redeem_ticket(ticket["token"]))
        self.assertIsNone(redeem_ticket(ticket["token"]))

    def test_tk_15_redeeming_consumes_siblings_for_the_same_character(self):
        """TK-15: a character can only be in one place.

        A retried handoff would otherwise leave a second ticket able to pull
        that character somewhere it has already left.
        """
        from evennia_scaling.models import Ticket
        from evennia_scaling.tickets import redeem_ticket

        first = self._stored()
        second = self._stored()

        redeem_ticket(first["token"])
        self.assertFalse(Ticket.objects.filter(token=second["token"]).exists())

    def test_tk_16_a_refusal_is_logged_with_the_failed_check(self):
        """TK-16: from outside every refusal is one None.

        This is the only place that knows which check failed, so a refusal
        that logged nothing would leave no way to tell them apart.
        """
        from unittest import mock

        from evennia_scaling.tickets import redeem_ticket

        ticket = self._stored(to_instance="somewhere-else")
        with mock.patch("evennia_scaling.tickets.scaling_log") as logged:
            redeem_ticket(ticket["token"])

        message = logged.call_args.args[0]
        self.assertIn("somewhere-else", message)
        self.assertEqual(logged.call_args.kwargs.get("level"), "WARN")

    def test_tk_17_no_token_is_silent(self):
        """TK-17: an absence is not a refusal.

        An ordinary connection presents no token, and logging that would
        bury the real refusals.
        """
        from unittest import mock

        from evennia_scaling.tickets import redeem_ticket

        with mock.patch("evennia_scaling.tickets.scaling_log") as logged:
            self.assertIsNone(redeem_ticket(None))
        logged.assert_not_called()


class _FakeSession:
    """A Server session, reduced to what `load_sync_data` touches."""

    def __init__(self, server_data=None, logged_in=False, uid=None):
        self.server_data = server_data or {}
        self.logged_in = logged_in
        self.uid = uid
        self.loaded = []


def _session_base():
    """A stand-in for Evennia's ServerSession, recording the sync."""

    class FakeServerSession(_FakeSession):
        def load_sync_data(self, sessdata):
            self.loaded.append(sessdata)

    return FakeServerSession


@override_settings(MESSAGEBUS_INSTANCE_ID="shard0", SCALING_ROLE="shard")
class TestServerSession(TestCase):
    """SS — the Server session override."""

    def _built(self, **kwargs):
        from evennia_scaling.sessions import make_scaling_session

        return make_scaling_session(_session_base())(**kwargs)

    def _payload(self, token):
        from evennia_portal_multiplex.move import PAYLOAD_KEY

        from evennia_scaling.sessions import SCALING_TICKET_KEY

        return {PAYLOAD_KEY: json.dumps({SCALING_TICKET_KEY: token})}

    def test_ss_01_subclasses_the_consumers_session_class(self):
        """SS-01: a consumer's own session class stays underneath ours."""
        from evennia_scaling.sessions import make_scaling_session

        base = _session_base()
        self.assertTrue(issubclass(make_scaling_session(base), base))

    def test_ss_02_ready_stashes_and_repoints_the_setting(self):
        """SS-02: Evennia resolves the setting later, by dotted path."""
        from django.apps import apps as django_apps

        theirs = "evennia.server.serversession.ServerSession"
        config = django_apps.get_app_config("evennia_scaling")
        with override_settings(SERVER_SESSION_CLASS=theirs):
            config.ready()
            self.assertEqual(
                settings.SERVER_SESSION_CLASS,
                "evennia_scaling.sessions.ScalingServerSession",
            )
            self.assertEqual(settings._SCALING_ORIGINAL_SESSION_CLASS, theirs)

    def test_ss_03_load_sync_data_calls_the_base(self):
        """SS-03: ours is the leaf, so theirs still runs underneath."""
        from unittest import mock

        session = self._built()
        with mock.patch(
            "evennia_scaling.sessions.redeem_ticket", return_value=None
        ), mock.patch("evennia_scaling.sessions.send_session"):
            session.load_sync_data({"sessid": 1})
        self.assertEqual(session.loaded, [{"sessid": 1}])

    def test_ss_04_an_authenticated_session_is_left_alone(self):
        """SS-04: it did not arrive by transfer.

        Admitting it again would fire the login hooks twice.
        """
        from unittest import mock

        session = self._built(logged_in=True, uid=1)
        with mock.patch(
            "evennia_scaling.sessions.redeem_ticket"
        ) as redeeming:
            session.load_sync_data({})
        redeeming.assert_not_called()

    def test_ss_05_reads_the_token_from_the_payload(self):
        """SS-05: multiplex carries it; this is where it is read back."""
        from unittest import mock

        session = self._built(server_data=self._payload("abc123"))
        with mock.patch(
            "evennia_scaling.sessions.redeem_ticket", return_value=None
        ) as redeeming, mock.patch(
            "evennia_scaling.sessions.process_inbox"
        ), mock.patch(
            "evennia_scaling.sessions.send_session"
        ):
            session.load_sync_data({})
        redeeming.assert_called_once_with("abc123")

    def test_ss_06_an_unreadable_payload_yields_no_token(self):
        """SS-06: absent, corrupt, or carrying no token are one answer.

        `json.loads` raises on a corrupt string, and this runs on every
        session that arrives with a payload — so an unreadable one is treated
        as untickered rather than breaking the arrival.
        """
        from unittest import mock

        from evennia_portal_multiplex.move import PAYLOAD_KEY

        for server_data in (
            {},
            {PAYLOAD_KEY: "not json at all"},
            {PAYLOAD_KEY: json.dumps({"something_else": "x"})},
        ):
            with self.subTest(server_data=server_data):
                session = self._built(server_data=server_data)
                with mock.patch(
                    "evennia_scaling.sessions.redeem_ticket",
                    return_value=None,
                ) as redeeming, mock.patch(
                    "evennia_scaling.sessions.send_session"
                ):
                    session.load_sync_data({})
                redeeming.assert_called_once_with(None)

    def test_ss_07_a_ticketed_session_drains_the_bus_first(self):
        """SS-07: the session is faster than the bus's polling interval.

        The sender commits the handoff row before asking for the move, so
        the row is there — draining reads it rather than waiting for a poll.
        """
        from unittest import mock

        session = self._built(server_data=self._payload("abc123"))
        with mock.patch(
            "evennia_scaling.sessions.process_inbox"
        ) as draining, mock.patch(
            "evennia_scaling.sessions.redeem_ticket", return_value=None
        ), mock.patch(
            "evennia_scaling.sessions.send_session"
        ):
            session.load_sync_data({})
        draining.assert_called_once()

    def test_ss_08_an_unticketed_session_does_not_drain_the_bus(self):
        """SS-08: an ordinary connection pays for no database round trip."""
        from unittest import mock

        session = self._built()
        with mock.patch(
            "evennia_scaling.sessions.process_inbox"
        ) as draining, mock.patch(
            "evennia_scaling.sessions.redeem_ticket", return_value=None
        ), mock.patch(
            "evennia_scaling.sessions.send_session"
        ):
            session.load_sync_data({})
        draining.assert_not_called()

    def test_ss_09_a_shard_sends_an_unadmitted_session_to_the_router(self):
        """SS-09: a shard holds no accounts, so there is nowhere else."""
        from unittest import mock

        session = self._built()
        with mock.patch(
            "evennia_scaling.sessions.redeem_ticket", return_value=None
        ), mock.patch("evennia_scaling.sessions.send_session") as sending:
            session.load_sync_data({})
        sending.assert_called_once_with(session, "router")

    @override_settings(SCALING_ROLE="router")
    def test_ss_10_a_router_leaves_an_unadmitted_session_alone(self):
        """SS-10: Evennia shows it the login screen."""
        from unittest import mock

        session = self._built()
        with mock.patch(
            "evennia_scaling.sessions.redeem_ticket", return_value=None
        ), mock.patch("evennia_scaling.sessions.send_session") as sending:
            session.load_sync_data({})
        sending.assert_not_called()
