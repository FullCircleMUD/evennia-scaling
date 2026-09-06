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

    def test_ac_07_an_absent_account_is_restored_by_username(self):
        """AC-07: the login door knows a username and nothing else.

        `authenticate` is handed a string a player typed, so finding the
        identity is the work. An account that is absent is a router whose
        database was rebuilt — the one case there is something to restore.
        """
        from evennia_archive.api import archive

        from tests.game_typeclasses import ScalingAccount

        account = self._account()
        account.db.progress = "as archived"
        archive(account)
        username = account.username
        account.delete()

        restored = ScalingAccount.refresh_from_archive(username)

        self.assertEqual(restored.db.progress, "as archived")

    def test_ac_08_an_unarchived_username_is_left_alone(self):
        """AC-08: a brand new account has nothing to come back from.

        The ordinary case on a first login. The local account has to
        survive it, or a first-time player is deleted on the way in.
        """
        from evennia.accounts.models import AccountDB

        from tests.game_typeclasses import ScalingAccount

        account = self._account()

        returned = ScalingAccount.refresh_from_archive(account.username)

        self.assertEqual(returned.pk, account.pk)
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

    def test_ac_10_a_live_account_is_left_where_it_is(self):
        """AC-10: the router's copy is the authoritative one.

        Nothing better exists to replace it with — an account can only
        change here. Replacing it anyway moves its primary key, and a
        Django website session names that key on every request.
        """
        from evennia_archive.api import archive

        from tests.game_typeclasses import ScalingAccount

        account = self._account()
        # Archived, or `find_in_archive` finds nothing and the old
        # behaviour returns early — passing for the wrong reason.
        archive(account)
        pk = account.pk

        returned = ScalingAccount.refresh_from_archive(account.username)

        self.assertEqual(returned.pk, pk)


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

        ScalingAccount.restore_missing_characters(account)

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

        ScalingAccount.restore_missing_characters(account)

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

        ScalingAccount.restore_missing_characters(account)

        self.assertFalse(ObjectDB.objects.filter(db_key="Rowan").exists())
        self.assertEqual(list(account.characters.all()), [])

    @override_settings(SCALING_ROLE="router")
    def test_ac_17_a_restored_account_gets_its_characters(self):
        """AC-17: an account that was absent has absent characters too.

        A login that restored the account alone would leave a player
        looking at an empty character-select menu.
        """
        from evennia_archive.api import archive

        from tests.game_typeclasses import ScalingAccount

        account = self._account()
        username = account.username
        self._archived_character(account, "Rowan")
        archive(account)
        account.delete()

        restored = ScalingAccount.refresh_from_archive(username)

        self.assertEqual(
            [character.key for character in restored.characters.all()],
            ["Rowan"],
        )

    def test_ac_18_a_stranded_character_comes_back_at_login(self):
        """AC-18: an ungraceful exit leaves a character only in the archive.

        The player never came back through the ticket door, so nothing
        restored their character on the router. Login is where that is
        noticed — and the account itself is still left where it is.
        """
        from evennia_archive.api import archive

        from tests.game_typeclasses import ScalingAccount

        account = self._account()
        self._archived_character(account, "Rowan")
        archive(account)
        pk = account.pk

        returned = ScalingAccount.refresh_from_archive(account.username)

        self.assertEqual(returned.pk, pk)
        self.assertEqual(
            [character.key for character in returned.characters.all()],
            ["Rowan"],
        )

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

        ScalingAccount.restore_missing_characters(mine)

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

        # A real home: Evennia stamps `DEFAULT_HOME` otherwise, and the
        # dbref it names does not exist in a fresh test database.
        home = create_object(key="Somewhere")
        return create_object(ScalingCharacter, key="Rowan", home=home)

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

    def test_sh_07_the_room_ref_is_stored_as_an_attribute(self):
        """SH-07: an Attribute survives archiving; a field would not.

        Half of a composite key is no use on its own, so this has to come
        through the round trip with `current_shard`.
        """
        from evennia_scaling.mixins import CURRENT_ROOM_REF_KEY

        character = self._character()
        character.current_room_ref = 5
        self.assertTrue(character.attributes.has(CURRENT_ROOM_REF_KEY))

    def test_sh_08_an_unassigned_room_ref_reads_as_none(self):
        """SH-08: a room key means nothing without a shard beside it.

        So there is no useful value to fall back to at read time — the pair
        is completed at the moment of use instead.
        """
        character = self._character()
        self.assertIsNone(character.current_room_ref)

    @override_settings(
        SCALING_DEFAULT_HOME_SHARD="shard1", DEFAULT_HOME="#99"
    )
    def test_sh_09_a_complete_pair_is_left_alone(self):
        """SH-09: they are where they left off, and that is where they go."""
        character = self._character()
        character.current_shard = "shard0"
        character.current_room_ref = 5

        self.assertEqual(character.ensure_location_for_transfer(), "shard0")
        self.assertEqual(character.current_shard, "shard0")
        self.assertEqual(character.current_room_ref, 5)

    @override_settings(
        SCALING_DEFAULT_HOME_SHARD="shard1", DEFAULT_HOME="#99"
    )
    def test_sh_10_a_broken_location_falls_back_to_home(self):
        """SH-10: their own home, not the game's.

        A game with a beginner shard and an advanced shard does not want a
        character with a broken location resolving to whatever room sits at
        the default on the advanced shard.
        """
        character = self._character()
        character.current_shard = "shard0"
        character.home_shard = "shard0"
        character.home_room_ref = 7

        self.assertEqual(character.ensure_location_for_transfer(), "shard0")
        self.assertEqual(character.current_room_ref, 7)

    def test_sh_11_the_home_pair_is_stored_and_checked(self):
        """SH-11: `character.home` is a dbref and does not survive the archive.

        So a home that means anything across instances is a pair of
        Attributes, and its shard half is checked like the other one — the
        same property, declared twice.
        """
        from evennia_scaling.mixins import (
            HOME_ROOM_REF_KEY,
            HOME_SHARD_KEY,
        )

        character = self._character()
        character.home_shard = "shard1"
        character.home_room_ref = 7

        self.assertTrue(character.attributes.has(HOME_SHARD_KEY))
        self.assertTrue(character.attributes.has(HOME_ROOM_REF_KEY))

        with self.assertRaises(ValueError) as raised:
            character.home_shard = "shrad1"
        # Named for the attribute being set, not the one the class was
        # written for — one property serves both shards.
        self.assertIn("home_shard", str(raised.exception))

    @override_settings(
        SCALING_DEFAULT_HOME_SHARD="shard1", DEFAULT_HOME="#99"
    )
    def test_sh_12_neither_pair_falls_back_to_the_default_home(self):
        """SH-12: the last resort, for a character that has no home."""
        character = self._character()
        character.current_shard = "shard0"

        self.assertEqual(character.ensure_location_for_transfer(), "shard1")
        self.assertEqual(character.current_shard, "shard1")
        self.assertEqual(character.current_room_ref, "#99")

    @override_settings(
        SCALING_DEFAULT_HOME_SHARD="shard1", DEFAULT_HOME="#99"
    )
    def test_sh_13_the_home_room_is_not_written_back(self):
        """SH-13: falling back to the default home is a recovery.

        Not a decision that this is where the character lives from now on.
        """
        character = self._character()
        character.current_shard = "shard0"

        character.ensure_location_for_transfer()

        self.assertIsNone(character.home_room_ref)

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


class _PlayingSession:
    """A Server session, reduced to what the sending paths read.

    Named apart from the arrival side's stand-in: both are sessions, and
    the two halves touch different fields.
    """

    def __init__(self, address="10.0.0.7", puppet=None):
        self.address = address
        self.puppet = puppet


class TestHandoff(TestCase):
    """HO — sending a session and what it plays to another instance."""

    #: The handoff writes to all three: the game database, the archive it
    #: copies into, and the bus it announces on.
    databases = {"default", "archive", "messagebus"}

    _next = 0

    def setUp(self):
        from evennia.utils.idmapper.models import flush_cache

        super().setUp()
        flush_cache()

    def _playing(self):
        """An account with a character it is playing, on the router."""
        from evennia.utils.create import create_account

        from tests.game_typeclasses import ScalingAccount

        TestHandoff._next += 1
        name = f"rowan{TestHandoff._next}"
        account = create_account(
            name,
            f"{name}@example.com",
            "testpassword123",
            typeclass=ScalingAccount,
        )
        character, errors = account.create_character(
            key=f"Char{TestHandoff._next}",
            typeclass="tests.game_typeclasses.ScalingCharacter",
        )
        self.assertFalse(errors, errors)
        return account, character

    def _transfer(self, account, character, to_instance="shard0"):
        """Run a transfer with the two outside calls captured.

        `send_session` reaches the Portal and `delay` reaches the reactor;
        neither exists in a test, and both are what the cases assert about.
        """
        from unittest import mock

        from twisted.internet.defer import Deferred

        from evennia_scaling.handoff import transfer_to_instance

        pending = Deferred()
        with mock.patch(
            "evennia_scaling.handoff.send_session", return_value=pending
        ) as send, mock.patch("evennia_scaling.handoff.delay") as delay:
            returned = transfer_to_instance(
                account, _PlayingSession(), character, to_instance
            )
        return returned, send, delay, pending

    def _fire(self, account, character, outcome, moved=False):
        """Run a transfer and fire the move's Deferred with an outcome.

        `send_session` answers over the network, so the outcome arrives
        after the call returns. Firing the Deferred by hand is what stands
        in for the Portal replying.
        """
        from unittest import mock

        from twisted.internet.defer import Deferred

        from evennia_scaling.handoff import transfer_to_instance

        pending = Deferred()
        with mock.patch(
            "evennia_scaling.handoff.send_session", return_value=pending
        ), mock.patch("evennia_scaling.handoff.delay"), mock.patch(
            "evennia_scaling.handoff.scaling_log"
        ) as log, mock.patch.object(
            type(account), "msg"
        ) as msg:
            transfer_to_instance(
                account, _PlayingSession(), character, "shard0"
            )
            pending.callback((moved, outcome))
        return log, msg

    def test_ho_08_a_successful_move_is_quiet(self):
        """HO-08: nothing went wrong, so there is nothing to say.

        Logging every successful move would bury the ones that failed.
        """
        account, character = self._playing()
        log, msg = self._fire(account, character, "moved", moved=True)

        log.assert_not_called()
        msg.assert_not_called()

    def test_ho_09_an_unattached_destination_is_logged_and_reported(self):
        """HO-09: the instance is down.

        The player asked to go somewhere and did not arrive, and an
        operator needs to know which instance was unreachable.
        """
        account, character = self._playing()
        log, msg = self._fire(account, character, "not_attached")

        self.assertIn("shard0", log.call_args.args[0])
        self.assertEqual(log.call_args.kwargs["level"], "ERROR")
        msg.assert_called_once()

    def test_ho_10_a_rejected_move_is_logged_and_reported(self):
        """HO-10: the destination would not take the session.

        It was put back, so the player is still here and reachable.
        """
        account, character = self._playing()
        log, msg = self._fire(account, character, "rejected")

        self.assertEqual(log.call_args.kwargs["level"], "ERROR")
        msg.assert_called_once()

    def test_ho_11_a_stranded_session_is_logged_and_not_reported(self):
        """HO-11: released, the build failed, the rollback failed too.

        There is no instance holding the session, so a message would go
        nowhere. The log is the only record there will be.
        """
        account, character = self._playing()
        log, msg = self._fire(account, character, "stranded")

        self.assertEqual(log.call_args.kwargs["level"], "ERROR")
        msg.assert_not_called()

    def test_ho_12_a_missing_session_is_logged_and_not_reported(self):
        """HO-12: usually a player who dropped mid-move.

        Nobody is behind the session to read a message.
        """
        account, character = self._playing()
        log, msg = self._fire(account, character, "no_such_session")

        self.assertEqual(log.call_args.kwargs["level"], "WARNING")
        msg.assert_not_called()

    def test_ho_13_already_there_is_logged_and_not_reported(self):
        """HO-13: not a failure, and not the library's to narrate.

        On a router it should be unreachable — the router is never in
        `SCALING_SHARDS` — so it means something upstream is wrong.
        """
        account, character = self._playing()
        log, msg = self._fire(account, character, "already_there")

        self.assertEqual(log.call_args.kwargs["level"], "WARNING")
        msg.assert_not_called()

    def test_ho_14_an_error_is_logged_and_reported(self):
        """HO-14: what arrives when the move itself broke.

        Without an errback it disappears into the Deferred and surfaces at
        garbage-collection time, if at all. The player is told because
        nothing is known about reachability and silence is the worse guess.
        """
        from unittest import mock

        from twisted.internet.defer import Deferred

        from evennia_scaling.handoff import transfer_to_instance

        account, character = self._playing()
        pending = Deferred()
        with mock.patch(
            "evennia_scaling.handoff.send_session", return_value=pending
        ), mock.patch("evennia_scaling.handoff.delay"), mock.patch(
            "evennia_scaling.handoff.scaling_log"
        ) as log, mock.patch.object(type(account), "msg") as msg:
            transfer_to_instance(
                account, _PlayingSession(), character, "shard0"
            )
            pending.errback(RuntimeError("the amp link went away"))

        self.assertEqual(log.call_args.kwargs["level"], "ERROR")
        msg.assert_called_once()

    def _archived_by_the_transfer(self, account, character, **kwargs):
        """What the transfer itself archived, as a list of objects.

        The call rather than the archive's contents: `evennia-archive`
        stores an account and a character when they are created, so
        everything the fixture builds is already in there and presence
        proves nothing about what this function did.
        """
        from unittest import mock

        with mock.patch("evennia_archive.api.archive") as archiving:
            self._transfer(account, character, **kwargs)
        return [call.args[0] for call in archiving.call_args_list]

    def test_ho_01_leaving_the_router_archives_the_account(self):
        """HO-01: the router is the only place an account can change.

        Archived now rather than when the session closes, because the
        destination rebuilds on arrival while this instance is still
        tearing its session down.

        The character is not archived here. It has not been played since it
        was last stored, so there is nothing newer to write.
        """
        account, character = self._playing()

        archived = self._archived_by_the_transfer(account, character)

        self.assertEqual(archived, [account])

    @override_settings(SCALING_ROLE="shard")
    def test_ho_15_leaving_a_shard_archives_the_character(self):
        """HO-15: the other half, and the reason the rule is a rule.

        A shard's account is a working copy. Archiving it would write that
        copy over the authoritative one, and the only difference it could
        carry is a change that should not have been possible.

        Sent to another shard rather than to the router because the suite's
        own instance id *is* the router, and the bus refuses to address
        itself. The rule is about where the session leaves, so either
        destination exercises it.
        """
        account, character = self._playing()

        archived = self._archived_by_the_transfer(
            account, character, to_instance="shard1"
        )

        self.assertEqual(archived, [character])

    def test_ho_16_a_superuser_is_refused(self):
        """HO-16: a superuser belongs to one instance and stays there.

        Both of the library's own triggers already step aside for one, so
        this is for a consumer calling `transfer_to_instance` directly —
        which the shard-to-shard case invites. It says so rather than
        failing quietly.
        """
        from unittest import mock

        account, character = self._playing()
        account.is_superuser = True
        account.save()
        account.msg = mock.Mock()

        with mock.patch("evennia_archive.api.archive") as archiving:
            returned, send, delay, _ = self._transfer(account, character)

        self.assertIsNone(returned)
        send.assert_not_called()
        delay.assert_not_called()
        account.msg.assert_called_once()
        archiving.assert_not_called()

    def test_ho_02_mints_a_ticket_naming_both_and_the_destination(self):
        """HO-02: the destination has to know who is arriving.

        Both ids and where it is addressed — a ticket missing any of them
        cannot admit anyone.
        """
        from unittest import mock

        account, character = self._playing()
        with mock.patch(
            "evennia_scaling.handoff.SessionAuthorized"
        ) as message:
            self._transfer(account, character)

        ticket = message.send.call_args.kwargs["payload"]
        self.assertEqual(ticket["account_archive_id"], account.archive_id)
        self.assertEqual(ticket["character_archive_id"], character.archive_id)
        self.assertEqual(ticket["to_instance"], "shard0")

    def test_ho_03_sends_the_ticket_over_the_bus(self):
        """HO-03: the destination learns of the transfer independently.

        The session carries the same ticket, and having both is what lets
        an arrival be checked against something it was told separately.
        """
        from unittest import mock

        account, character = self._playing()
        with mock.patch(
            "evennia_scaling.handoff.SessionAuthorized"
        ) as message:
            self._transfer(account, character, "shard1")

        self.assertEqual(message.send.call_args.args[0], "shard1")

    def test_ho_04_defers_the_character_delete(self):
        """HO-04: `CmdIC` still uses the character after this returns.

        It writes `_last_puppet` and logs against it, so an inline delete
        makes Evennia serialise a dead object. `delay(0, ...)` is
        `reactor.callLater(0, ...)`, which cannot run until the stack
        unwinds — structurally after, not merely likely to be.
        """
        account, character = self._playing()
        _, _, delay, _ = self._transfer(account, character)

        delay.assert_called_once_with(0, character.delete)

    def test_ho_05_hands_the_session_off_carrying_the_ticket(self):
        """HO-05: the payload is how the destination recognises it."""
        import json
        from unittest import mock

        from evennia_scaling.sessions import SCALING_TICKET_KEY

        account, character = self._playing()
        with mock.patch(
            "evennia_scaling.handoff.SessionAuthorized"
        ) as message:
            _, send, _, _ = self._transfer(account, character)

        ticket = message.send.call_args.kwargs["payload"]
        session, destination, payload = send.call_args.args
        self.assertEqual(destination, "shard0")
        # A mapping, not a string. Multiplex serialises it, and encoding it
        # here too lands a JSON string of a JSON string at the far end.
        self.assertEqual(payload, {SCALING_TICKET_KEY: ticket["token"]})

    def test_ho_06_does_not_delete_the_account(self):
        """HO-06: the session is still live and still needs it.

        Deleting an account out from under a live session disconnects it —
        Evennia's own `delete` does that deliberately.
        """
        from evennia.accounts.models import AccountDB

        account, character = self._playing()
        pk = account.pk
        self._transfer(account, character)

        self.assertTrue(AccountDB.objects.filter(pk=pk).exists())

    def test_ho_07_returns_the_outcome_of_the_move(self):
        """HO-07: a destination that is down refuses the move.

        Swallowing that means a player asks to go in character and sees
        nothing at all.
        """
        account, character = self._playing()
        returned, _, _, pending = self._transfer(account, character)

        self.assertIs(returned, pending)


class TestGoingInCharacter(TestCase):
    """IC — going in character."""

    databases = {"default", "archive", "messagebus"}

    _next = 0

    def setUp(self):
        from evennia.utils.idmapper.models import flush_cache

        super().setUp()
        flush_cache()

    def _playing(self):
        from evennia.utils.create import create_account

        from tests.game_typeclasses import ScalingAccount

        TestGoingInCharacter._next += 1
        name = f"rowan{TestGoingInCharacter._next}"
        account = create_account(
            name,
            f"{name}@example.com",
            "testpassword123",
            typeclass=ScalingAccount,
        )
        character, errors = account.create_character(
            key=f"Char{TestGoingInCharacter._next}",
            typeclass="tests.game_typeclasses.ScalingCharacter",
        )
        self.assertFalse(errors, errors)
        return account, character

    def _puppet(self, account, character, session=None):
        """Call `puppet_object` with the transfer and Evennia's both captured."""
        from unittest import mock

        from evennia.accounts.accounts import DefaultAccount

        with mock.patch(
            "evennia_scaling.handoff.transfer_to_instance"
        ) as transfer, mock.patch.object(
            DefaultAccount, "puppet_object"
        ) as evennias:
            account.puppet_object(
                session if session is not None else _PlayingSession(), character
            )
        return transfer, evennias

    @override_settings(SCALING_ROLE="shard")
    def test_ic_01_a_shard_puppets_normally(self):
        """IC-01: a character is played on a shard, so this is where it lands.

        The interception is the router's behaviour, not the library's.
        """
        account, character = self._playing()
        transfer, evennias = self._puppet(account, character)

        evennias.assert_called_once()
        transfer.assert_not_called()

    @override_settings(SCALING_ROLE="router")
    def test_ic_02_a_router_does_not_puppet(self):
        """IC-02: going in character means going somewhere else.

        Returning without puppeting is a shape the method already uses —
        Evennia does the same for no permission and for too many puppets.
        """
        account, character = self._playing()
        _, evennias = self._puppet(account, character)

        evennias.assert_not_called()

    @override_settings(SCALING_ROLE="router")
    def test_ic_03_a_router_hands_the_session_to_the_transfer(self):
        """IC-03: the destination is the character's own shard.

        Not a setting and not the caller's choice — where a character is in
        the world is what decides where the session goes.
        """
        account, character = self._playing()
        character.current_shard = "shard1"
        character.current_room_ref = 5
        session = _PlayingSession()

        transfer, _ = self._puppet(account, character, session)

        transfer.assert_called_once_with(
            account, session, character, "shard1"
        )

    @override_settings(SCALING_ROLE="router")
    def test_ic_04_a_character_they_cannot_puppet_is_refused(self):
        """IC-04: without the lock a builder could move someone else's character.

        The one check of Evennia's that still means something here.
        """
        account, character = self._playing()
        character.locks.add("puppet:false()")

        transfer, evennias = self._puppet(account, character)

        transfer.assert_not_called()
        evennias.assert_not_called()

    @override_settings(SCALING_ROLE="router")
    def test_ic_05_a_missing_object_or_session_raises(self):
        """IC-05: Evennia raises here, and `CmdIC` handles that.

        Returning quietly instead would leave the command reporting
        success for a puppet that never happened.
        """
        from unittest import mock

        account, character = self._playing()
        with mock.patch("evennia_scaling.handoff.transfer_to_instance"):
            with self.assertRaises(RuntimeError):
                account.puppet_object(_PlayingSession(), None)
            with self.assertRaises(RuntimeError):
                account.puppet_object(None, character)

    @override_settings(SCALING_ROLE="router")
    def test_ic_06_a_superuser_puppets_normally(self):
        """IC-06: a superuser belongs to the instance it was made on.

        Transferring one archives and deletes an account the instance
        needs, and Evennia expects #1 to be there.
        """
        account, character = self._playing()
        account.is_superuser = True
        account.save()

        transfer, evennias = self._puppet(account, character)

        evennias.assert_called_once()
        transfer.assert_not_called()


class TestGoingOutOfCharacter(TestCase):
    """OC — going out of character."""

    databases = {"default", "archive", "messagebus"}

    _next = 0

    def setUp(self):
        from evennia.utils.idmapper.models import flush_cache

        super().setUp()
        flush_cache()

    def _playing(self):
        from evennia.utils.create import create_account

        from tests.game_typeclasses import ScalingAccount

        TestGoingOutOfCharacter._next += 1
        name = f"rowan{TestGoingOutOfCharacter._next}"
        account = create_account(
            name,
            f"{name}@example.com",
            "testpassword123",
            typeclass=ScalingAccount,
        )
        character, errors = account.create_character(
            key=f"Char{TestGoingOutOfCharacter._next}",
            typeclass="tests.game_typeclasses.ScalingCharacter",
        )
        self.assertFalse(errors, errors)
        return account, character

    def _unpuppet(self, account, sessions):
        """Release, with the archive and the log captured.

        Evennia's own `unpuppet_object` is stubbed: it needs a real session
        with a handler behind it, and what these cases are about is what
        happens either side of it.
        """
        from unittest import mock

        from evennia.accounts.accounts import DefaultAccount

        with mock.patch.object(DefaultAccount, "unpuppet_object"), mock.patch(
            "evennia_archive.api.archive"
        ) as archive, mock.patch(
            "evennia_scaling.mixins.scaling_log"
        ) as log:
            account.unpuppet_object(sessions)
        return archive, log

    @override_settings(SCALING_ROLE="shard")
    def test_oc_01_archives_the_character_and_not_the_account(self):
        """OC-01: a release is the moment a character's state is worth storing.

        The account is left alone. On a shard it is a working copy, so
        storing it could only write that copy over the authoritative one.
        """
        account, character = self._playing()
        archive, _ = self._unpuppet(account, _PlayingSession(puppet=character))

        archived = [call.args[0] for call in archive.call_args_list]
        self.assertIn(character, archived)
        self.assertNotIn(account, archived)

    @override_settings(SCALING_ROLE="shard")
    def test_oc_02_deletes_nothing_and_transfers_nothing(self):
        """OC-02: this also runs on a dropout and at shutdown.

        Deleting there would cost a player their position for a
        five-second disconnect, and make closing the browser mid-fight the
        way out of it.
        """
        from unittest import mock

        from evennia.accounts.models import AccountDB
        from evennia.objects.models import ObjectDB

        account, character = self._playing()
        with mock.patch(
            "evennia_scaling.handoff.transfer_to_instance"
        ) as transfer:
            self._unpuppet(account, _PlayingSession(puppet=character))

        transfer.assert_not_called()
        self.assertTrue(AccountDB.objects.filter(pk=account.pk).exists())
        self.assertTrue(ObjectDB.objects.filter(pk=character.pk).exists())

    @override_settings(SCALING_ROLE="shard")
    def test_oc_03_a_session_with_no_puppet_archives_nothing(self):
        """OC-03: there is nothing whose state needs capturing.

        Archiving the account anyway would write a copy nobody asked for
        over one another instance may hold.
        """
        account, _ = self._playing()
        archive, _ = self._unpuppet(account, _PlayingSession())

        archive.assert_not_called()

    @override_settings(SCALING_ROLE="router")
    def test_oc_04_a_router_logs_a_puppeted_character_as_a_breach(self):
        """OC-04: `puppet_object` never puppets here.

        So finding one puppeted means something got past the interception —
        a bug worth tracking down. Logged rather than handled, because
        guessing at a recovery would hide it.
        """
        account, character = self._playing()
        _, log = self._unpuppet(account, _PlayingSession(puppet=character))

        self.assertEqual(log.call_args.kwargs["level"], "ERROR")
        # Named, so the line says who to ask and what to look at.
        message = log.call_args.args[0]
        self.assertIn(account.archive_id, message)
        self.assertIn(character.archive_id, message)

    @override_settings(SCALING_ROLE="shard")
    def test_oc_05_a_superuser_is_not_archived(self):
        """OC-05: it does not travel, so a copy could only overwrite.

        The one the instance depends on is the one it would overwrite.
        """
        account, character = self._playing()
        account.is_superuser = True
        account.save()

        archive, _ = self._unpuppet(account, _PlayingSession(puppet=character))

        archive.assert_not_called()

    @override_settings(SCALING_ROLE="shard", MAX_NR_CHARACTERS=2)
    def test_oc_06_a_list_of_sessions_archives_every_character(self):
        """OC-06: `unpuppet_all()` passes them all, before every shutdown.

        Reading `.puppet` off the parameter works on every runtime path and
        raises on every shutdown, with nothing in any log.
        """
        account, first = self._playing()
        second, errors = account.create_character(
            key="Second", typeclass="tests.game_typeclasses.ScalingCharacter"
        )
        self.assertFalse(errors, errors)

        archive, _ = self._unpuppet(
            account,
            [_PlayingSession(puppet=first), _PlayingSession(puppet=second)],
        )

        archived = [call.args[0] for call in archive.call_args_list]
        self.assertIn(first, archived)
        self.assertIn(second, archived)

    @override_settings(SCALING_ROLE="router")
    def test_oc_08_a_superuser_on_the_router_is_not_a_breach(self):
        """OC-08: superusers do puppet on the router.

        Reporting them would bury the real thing under routine noise. The
        archive skip runs before the breach check, and that ordering is
        what makes this true.
        """
        account, character = self._playing()
        account.is_superuser = True
        account.save()

        _, log = self._unpuppet(account, _PlayingSession(puppet=character))

        log.assert_not_called()


class TestOOCCommand(TestCase):
    """OC — the replaced `ooc` command."""

    databases = {"default", "archive", "messagebus"}

    _next = 0

    def setUp(self):
        from evennia.utils.idmapper.models import flush_cache

        super().setUp()
        flush_cache()

    def _playing(self, puppeted=True):
        from unittest import mock

        from evennia.utils.create import create_account

        from tests.game_typeclasses import ScalingAccount

        TestOOCCommand._next += 1
        name = f"rowan{TestOOCCommand._next}"
        account = create_account(
            name,
            f"{name}@example.com",
            "testpassword123",
            typeclass=ScalingAccount,
        )
        character, errors = account.create_character(
            key=f"Char{TestOOCCommand._next}",
            typeclass="tests.game_typeclasses.ScalingCharacter",
        )
        self.assertFalse(errors, errors)
        # `get_puppet` needs a real session handler behind it; what these
        # cases are about is what the command does with its answer.
        account.get_puppet = mock.Mock(
            return_value=character if puppeted else None
        )
        return account, character

    def _ooc(self, account):
        """Run the command, with everything it reaches out to captured."""
        from unittest import mock

        from evennia_scaling.commands import ScalingCmdOOC

        # Evennia's own class, reached through the bases: `ready()` replaces
        # `evennia.commands.default.account.CmdOOC` with ours, so importing
        # that name gives back the class under test.
        evennias_class = ScalingCmdOOC.__bases__[0]

        command = ScalingCmdOOC()
        command.account = account
        command.session = _PlayingSession()
        command.msg = mock.Mock()

        with mock.patch(
            "evennia_scaling.handoff.transfer_to_instance"
        ) as transfer, mock.patch(
            "evennia_scaling.handoff.send_session"
        ) as send, mock.patch(
            "evennia_scaling.commands.scaling_log"
        ) as log, mock.patch.object(
            evennias_class, "func"
        ) as evennias, mock.patch.object(
            type(account), "unpuppet_object"
        ) as unpuppet:
            command.func()
        return transfer, send, log, evennias, unpuppet, command

    @override_settings(SCALING_ROLE="shard")
    def test_oc_09_a_shard_transfers_the_session_to_the_router(self):
        """OC-09: nobody is ever out of character on a shard."""
        account, character = self._playing()
        transfer, _, _, _, _, command = self._ooc(account)

        transfer.assert_called_once_with(
            account, command.session, character, "router"
        )

    @override_settings(SCALING_ROLE="shard")
    def test_oc_10_a_shard_does_not_call_evennias_func(self):
        """OC-10: it ends by rendering the character-select menu.

        A shard holds one character and no roster, so a menu there offers a
        choice that does not exist.
        """
        account, _ = self._playing()
        _, _, _, evennias, _ = self._ooc(account)[:5]

        evennias.assert_not_called()

    @override_settings(SCALING_ROLE="shard")
    def test_oc_11_reads_the_character_before_the_unpuppet(self):
        """OC-11: unpuppeting clears `session.puppet`.

        Read after, and the transfer is handed nothing to archive.
        """
        account, character = self._playing()
        transfer, _, _, _, unpuppet, _ = self._ooc(account)

        unpuppet.assert_called_once()
        self.assertEqual(transfer.call_args.args[2], character)

    @override_settings(SCALING_ROLE="router")
    def test_oc_12_a_router_transfers_nothing(self):
        """OC-12: this is where out of character happens."""
        account, _ = self._playing()
        transfer, _, _, _, _, _ = self._ooc(account)

        transfer.assert_not_called()

    @override_settings(SCALING_ROLE="router")
    def test_oc_13_a_router_is_evennias_ordinary_behaviour(self):
        """OC-13: the router is where out of character happens.

        Including the state that should not exist — a character puppeted
        here — where falling through unpuppets them *and tells them so*,
        rather than changing their state and showing them nothing.
        """
        account, _ = self._playing()
        transfer, send, _, evennias, _, _ = self._ooc(account)

        evennias.assert_called_once()
        transfer.assert_not_called()
        send.assert_not_called()

    @override_settings(SCALING_ROLE="shard")
    def test_oc_14_a_shard_sends_a_stranded_session_home(self):
        """OC-14: a state no path here can produce.

        They can neither go out of character nor in as a character they do
        not have. Sent home without a ticket — a character-less ticket
        would mean changes across minting and reconstitution to improve an
        error path — and they log in again.
        """
        account, _ = self._playing(puppeted=False)
        transfer, send, log, _, _, command = self._ooc(account)

        self.assertEqual(log.call_args.kwargs["level"], "ERROR")
        send.assert_called_once_with(command.session, "router")
        transfer.assert_not_called()

    def test_oc_15_ready_installs_the_command(self):
        """OC-15: `CMDSET_ACCOUNT` names a gamedir module.

        It imports `evennia.default_cmds`, which is not populated while
        `ready()` runs, so the module attribute is replaced instead — which
        is what `AccountCmdSet.at_cmdset_creation` reads when a session is
        built, long after startup.
        """
        from django.apps import apps as django_apps
        from evennia.commands.default import account as account_commands

        from evennia_scaling.commands import ScalingCmdOOC

        django_apps.get_app_config("evennia_scaling").ready()
        self.assertIs(account_commands.CmdOOC, ScalingCmdOOC)

    @override_settings(SCALING_ROLE="shard")
    def test_oc_16_a_superuser_goes_ooc_where_it_stands(self):
        """OC-16: a superuser belongs to the instance it was made on.

        Without this it would be archived, its character deleted, and it
        would land on the router.
        """
        account, _ = self._playing()
        account.is_superuser = True
        account.save()

        transfer, _, _, evennias, _, _ = self._ooc(account)

        evennias.assert_called_once()
        transfer.assert_not_called()

    @override_settings(SCALING_ROLE="shard")
    def test_oc_17_the_stranded_recovery_reports_its_outcome(self):
        """OC-17: otherwise it is the one move that fails silently.

        It has no account or character to archive, so it is a bare session
        move — but the router being down matters just as much here.
        """
        from unittest import mock

        from twisted.internet.defer import Deferred

        from evennia_scaling.commands import ScalingCmdOOC

        account, _ = self._playing(puppeted=False)
        command = ScalingCmdOOC()
        command.account = account
        command.session = _PlayingSession()
        command.msg = mock.Mock()

        pending = Deferred()
        with mock.patch(
            "evennia_scaling.handoff.send_session", return_value=pending
        ), mock.patch("evennia_scaling.commands.scaling_log"), mock.patch(
            "evennia_scaling.handoff.scaling_log"
        ) as log:
            command.func()
            pending.callback((False, "not_attached"))

        self.assertEqual(log.call_args.kwargs["level"], "ERROR")


class _LockSession:
    """A session, reduced to the one field a `cmd` lock check is given."""

    def __init__(self, puppet=None):
        self.puppet = puppet


#: Each override and the lockstring it is meant to carry, written out so a
#: reader can check them against what Evennia ships.
_LOCKED = {
    "ScalingCmdPassword": "cmd:pperm(Player) and is_ooc()",
    "ScalingCmdQuell": "cmd:pperm(Player) and is_ooc()",
    "ScalingCmdCharCreate": "cmd:pperm(Player) and is_ooc()",
    "ScalingCmdCharDelete": "cmd:pperm(Player) and is_ooc()",
    "ScalingCmdOption": "cmd:is_ooc()",
    "ScalingCmdStyle": "cmd:is_ooc()",
    "ScalingCmdIC": "cmd:is_ooc()",
}


class TestOOCLocks(unittest.TestCase):
    """LK — locking account changes to out of character."""

    def test_lk_01_is_ooc_is_true_without_a_puppet(self):
        """LK-01: out of character means nothing is being played."""
        from evennia_scaling.lockfuncs import is_ooc

        self.assertTrue(is_ooc(None, None, session=_LockSession()))

    def test_lk_02_is_ooc_is_false_while_puppeting(self):
        """LK-02: the whole point — a shard's copy of the account is discarded."""
        from evennia_scaling.lockfuncs import is_ooc

        self.assertFalse(
            is_ooc(None, None, session=_LockSession(puppet=object()))
        )

    def test_lk_03_is_ooc_is_true_without_a_session(self):
        """LK-03: a check outside a command is not a character standing somewhere.

        Refusing there would fail closed for a caller that never had a
        session to begin with.
        """
        from evennia_scaling.lockfuncs import is_ooc

        self.assertTrue(is_ooc(None, None))

    def test_lk_04_each_override_carries_its_lockstring(self):
        """LK-04: the whole string, not an appended fragment.

        Written out so it reads against what Evennia ships — a command
        whose lock declares several access types cannot be extended by
        appending.
        """
        from evennia_scaling import commands

        for name, lockstring in _LOCKED.items():
            with self.subTest(command=name):
                self.assertEqual(getattr(commands, name).locks, lockstring)

    def test_lk_05_an_override_changes_nothing_but_the_lock(self):
        """LK-05: catches a lockstring copied with a clause dropped.

        The subclass adds nothing and removes nothing, so its behaviour is
        its parent's and only its access changes.
        """
        from evennia_scaling import commands

        for name in _LOCKED:
            with self.subTest(command=name):
                override = getattr(commands, name)
                parent = override.__bases__[0]
                self.assertEqual(override.key, parent.key)
                self.assertEqual(override.aliases, parent.aliases)
                # Evennia's command metaclass adds `_keyaliases` and
                # `help_category` to every subclass, so "defines only
                # locks" is not assertable. What matters is that no code
                # changed: the parent's own methods are still the ones
                # that run.
                self.assertIs(override.func, parent.func)
                self.assertIs(override.parse, parent.parse)
                self.assertNotEqual(override.locks, parent.locks)

    def test_lk_06_ready_points_the_module_attributes_at_the_overrides(self):
        """LK-06: Evennia's cmdsets read the module attribute, not our module.

        `AccountCmdSet.at_cmdset_creation` calls `account.CmdPassword()`
        when a session's cmdset is built, so the assignment is what puts
        ours in front of it without touching Evennia's source.
        """
        from django.apps import apps as django_apps
        from evennia.commands.default import account as account_commands

        from evennia_scaling import commands

        django_apps.get_app_config("evennia_scaling").ready()

        for name in _LOCKED:
            with self.subTest(command=name):
                override = getattr(commands, name)
                installed = getattr(
                    account_commands, override.__bases__[0].__name__
                )
                self.assertIs(installed, override)

    def _channel(self, switches, puppeted):
        """Run the channel command, with Evennia's own `func` captured.

        Patching the parent rather than driving the real command: what
        these cases are about is whether the guard lets a call through,
        and Evennia's `func()` wants a parsed command and a database
        behind it.
        """
        from unittest import mock

        from evennia_scaling.channel_command import ScalingCmdChannel

        command = ScalingCmdChannel()
        command.switches = list(switches)
        command.session = _LockSession(puppet=object() if puppeted else None)
        command.msg = mock.Mock()

        with mock.patch.object(
            ScalingCmdChannel.__bases__[0], "func"
        ) as evennias:
            command.func()
        return evennias, command

    def test_lk_07_channel_account_switches_are_refused_in_character(self):
        """LK-07: the subscription and the aliases are on the account.

        A shard's copy of the account is discarded, so a change made
        there is thrown away with nothing in any log.
        """
        for switch in ("sub", "unsub", "alias", "unalias"):
            with self.subTest(switch=switch):
                evennias, command = self._channel([switch], puppeted=True)

                evennias.assert_not_called()
                command.msg.assert_called_once()

    def test_lk_08_channel_account_switches_pass_out_of_character(self):
        """LK-08: out of character is where these are meant to be used."""
        for switch in ("sub", "unsub", "alias", "unalias"):
            with self.subTest(switch=switch):
                evennias, command = self._channel([switch], puppeted=False)

                evennias.assert_called_once()
                command.msg.assert_not_called()

    def test_lk_09_channel_sending_is_untouched_in_character(self):
        """LK-09: four switches are restricted, not the command.

        Sending carries no switch at all, and the read-only switches
        write nothing — a player in character talks on channels as they
        always did. The lock is asserted here too, because removing it is
        what makes that true.
        """
        from evennia.commands.default.comms import CmdChannel

        from evennia_scaling.channel_command import ScalingCmdChannel

        self.assertEqual(ScalingCmdChannel.locks, CmdChannel.locks)

        for switches in ([], ["list"], ["all"], ["history"], ["who"], ["mute"]):
            with self.subTest(switches=switches):
                evennias, command = self._channel(switches, puppeted=True)

                evennias.assert_called_once()
                command.msg.assert_not_called()

    def test_lk_10_at_server_init_installs_the_channel_override(self):
        """LK-10: the same module-attribute swap the other seven get.

        Restored afterwards: this one replaces an attribute on Evennia's
        own module, and leaving it in place would follow the test run into
        everything else that reads `comms.CmdChannel`.
        """
        from evennia.commands.default import comms

        from evennia_scaling.at_server_startstop import at_server_init
        from evennia_scaling.channel_command import ScalingCmdChannel

        original = comms.CmdChannel
        try:
            at_server_init()
            self.assertIs(comms.CmdChannel, ScalingCmdChannel)
        finally:
            comms.CmdChannel = original

    def test_lk_11_ready_appends_our_startstop_module(self):
        """LK-11: appended, so the game's own module keeps its hooks.

        The setting's default is a bare string, which is what it is set to
        here — `make_iter` allows either, so appending has to coerce.
        """
        from django.apps import apps as django_apps
        from django.conf import settings
        from evennia.utils.utils import make_iter

        original = settings.AT_SERVER_STARTSTOP_MODULE
        try:
            settings.AT_SERVER_STARTSTOP_MODULE = (
                "server.conf.at_server_startstop"
            )
            django_apps.get_app_config("evennia_scaling").ready()

            listed = list(make_iter(settings.AT_SERVER_STARTSTOP_MODULE))
            self.assertIn("server.conf.at_server_startstop", listed)
            self.assertIn("evennia_scaling.at_server_startstop", listed)
        finally:
            settings.AT_SERVER_STARTSTOP_MODULE = original

    def test_lk_12_the_startstop_module_is_listed_once(self):
        """LK-12: `ready()` can run more than once, and the hook would too."""
        from django.apps import apps as django_apps
        from django.conf import settings
        from evennia.utils.utils import make_iter

        original = settings.AT_SERVER_STARTSTOP_MODULE
        try:
            settings.AT_SERVER_STARTSTOP_MODULE = (
                "server.conf.at_server_startstop"
            )
            config = django_apps.get_app_config("evennia_scaling")
            config.ready()
            config.ready()

            listed = list(make_iter(settings.AT_SERVER_STARTSTOP_MODULE))
            self.assertEqual(
                listed.count("evennia_scaling.at_server_startstop"), 1
            )
        finally:
            settings.AT_SERVER_STARTSTOP_MODULE = original


class TestNickCommand(TestCase):
    """LK — the replaced `nick` command.

    Real accounts and characters rather than stubs: what these cases are
    about is which object a nick lands on, and a stub's nickhandler would
    be the assertion answering itself.
    """

    databases = {"default", "archive", "messagebus"}

    _next = 0

    def setUp(self):
        from evennia.utils.idmapper.models import flush_cache

        super().setUp()
        flush_cache()

    def _playing(self):
        """An account and its character, each carrying a nick."""
        from evennia.utils.create import create_account

        from tests.game_typeclasses import ScalingAccount

        TestNickCommand._next += 1
        name = f"nicholas{TestNickCommand._next}"
        account = create_account(
            name,
            f"{name}@example.com",
            "testpassword123",
            typeclass=ScalingAccount,
        )
        character, errors = account.create_character(
            key=f"NickChar{TestNickCommand._next}",
            typeclass="tests.game_typeclasses.ScalingCharacter",
        )
        self.assertFalse(errors, errors)

        account.nicks.add("greet", "say Hello")
        character.nicks.add("wave", "emote waves")
        return account, character

    def _nick(self, caller, switches=(), lhs="", rhs=None, args=""):
        """Run the command as a given caller.

        The fields are set rather than parsed: `parse()` is Evennia's and
        untouched, so driving it here would be testing their parser.
        """
        from evennia_scaling.commands import ScalingCmdNick

        command = ScalingCmdNick()
        command.caller = caller
        command.switches = list(switches)
        command.cmdstring = "nick"
        command.args = args
        command.lhs = lhs
        command.rhs = rhs
        command.func()
        return command

    def test_lk_13_clearall_in_character_leaves_the_account_alone(self):
        """LK-13: the reach-through removed — a shard can clear a character."""
        account, character = self._playing()

        self._nick(character, switches=["clearall"])

        self.assertFalse(character.nicks.get("wave"))
        self.assertTrue(account.nicks.get("greet"))

    def test_lk_14_clearall_out_of_character_clears_the_account(self):
        """LK-14: the other half, and the same line does it.

        Out of character the caller *is* the account, so nothing detects
        anything — the character is left alone because it was never
        reached.
        """
        account, character = self._playing()

        self._nick(account, switches=["clearall"])

        self.assertFalse(account.nicks.get("greet"))
        self.assertTrue(character.nicks.get("wave"))

    def test_lk_15_setting_a_nick_still_reaches_evennias_func(self):
        """LK-15: the override rewrites one branch of a long `func()`.

        This is the case that catches the fall-through being broken —
        every switch but `clearall` is Evennia's and has to stay that way.
        """
        _, character = self._playing()

        self._nick(character, lhs="hi", rhs="say Hello", args="hi = say Hello")

        self.assertTrue(character.nicks.get("hi"))

    def test_lk_16_ready_points_nick_at_the_override(self):
        """LK-16: installed from `ready()` with the account commands.

        `general.py` imports nothing Evennia populates late, so this one
        needs no startup hook.
        """
        from django.apps import apps as django_apps
        from evennia.commands.default import general

        from evennia_scaling.commands import ScalingCmdNick

        django_apps.get_app_config("evennia_scaling").ready()

        self.assertIs(general.CmdNick, ScalingCmdNick)


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


@override_settings(
    MESSAGEBUS_INSTANCE_ID="shard0",
    # The arrival resolves this for real, so it has to name a typeclass with
    # a manager behind it rather than the stub startup validation uses.
    BASE_ACCOUNT_TYPECLASS="tests.game_typeclasses.ScalingAccount",
)
class TestArrival(TestCase):
    """SS — admitting a session that arrived with a ticket.

    A separate class from the rest of `SS`: those exercise the override
    against a stand-in session, and these need real accounts, characters and
    an archive to rebuild them from.
    """

    databases = {"default", "archive", "messagebus"}

    _next = 0

    def setUp(self):
        from evennia.utils.idmapper.models import flush_cache

        super().setUp()
        flush_cache()

    def _arriving(self):
        """An account and character as the sending instance left them."""
        from evennia.utils.create import create_account

        from tests.game_typeclasses import ScalingAccount

        TestArrival._next += 1
        name = f"rowan{TestArrival._next}"
        account = create_account(
            name,
            f"{name}@example.com",
            "testpassword123",
            typeclass=ScalingAccount,
        )
        character, errors = account.create_character(
            key=f"Char{TestArrival._next}",
            typeclass="tests.game_typeclasses.ScalingCharacter",
        )
        self.assertFalse(errors, errors)
        return account, character

    def _session(self, token):
        """A session carrying a token, as multiplex delivers one."""
        from evennia_portal_multiplex.move import PAYLOAD_KEY

        from evennia_scaling.sessions import (
            SCALING_TICKET_KEY,
            make_scaling_session,
        )

        session = make_scaling_session(_session_base())()
        session.server_data = {
            PAYLOAD_KEY: json.dumps({SCALING_TICKET_KEY: token})
        }
        return session

    def _ticket_for(self, account, character, to_instance="shard0"):
        """A stored ticket naming an archived account and character."""
        from evennia_archive.api import archive

        from evennia_scaling.tickets import create_ticket, store_ticket

        archive(account)
        archive(character)
        ticket = create_ticket(
            str(account.archive_id), str(character.archive_id), to_instance
        )
        store_ticket(ticket)
        return ticket

    @override_settings(SCALING_ROLE="shard")
    def test_ss_11_a_redeemed_ticket_admits_the_session(self):
        """SS-11: `portal_connect` reads this pair and logs the session in.

        Calling `sessionhandler.login` here would fire every login hook
        twice; setting `logged_in` also suppresses the login screen.
        """
        from unittest import mock

        from evennia.accounts.models import AccountDB

        account, character = self._arriving()
        username = account.username
        ticket = self._ticket_for(account, character)
        session = self._session(ticket["token"])

        with mock.patch("evennia_scaling.handoff.place_in_world"):
            session.load_sync_data({})

        # Read after: the rebuild deletes and restores, so the object this
        # test created is gone and its id reads as None.
        rebuilt = AccountDB.objects.get(username=username)
        self.assertTrue(session.logged_in)
        self.assertEqual(session.uid, rebuilt.id)

    @override_settings(SCALING_ROLE="shard")
    def test_ss_12_a_shard_rebuilds_and_places_the_ticketed_character(self):
        """SS-12: a shard receives exactly one character, the one named.

        Restoring a roster here would put every character on an instance it
        is not being played on.
        """
        from unittest import mock

        account, character = self._arriving()
        expected = character.archive_id
        ticket = self._ticket_for(account, character)
        session = self._session(ticket["token"])

        with mock.patch("evennia_scaling.handoff.place_in_world") as place:
            session.load_sync_data({})

        placed = place.call_args.args[0]
        self.assertEqual(placed.archive_id, expected)

    @override_settings(SCALING_ROLE="router")
    def test_ss_13_a_router_places_nobody(self):
        """SS-13: a character is not standing anywhere on the router.

        The router is not part of the game world, so there is nowhere to
        put an arriving character and nothing to place them in.
        """
        from unittest import mock

        account, character = self._arriving()
        ticket = self._ticket_for(account, character)
        session = self._session(ticket["token"])

        with mock.patch("evennia_scaling.handoff.place_in_world") as place:
            session.load_sync_data({})

        place.assert_not_called()

    @override_settings(SCALING_ROLE="shard")
    def test_ss_14_the_character_becomes_last_puppet(self):
        """SS-14: the reference the archive drops, put back.

        `at_post_login` reads it to auto-puppet, and a bare `ic` resolves
        through it. Without it Evennia says the character does not exist —
        which it does, just not under the key the restored account
        remembers.
        """
        from unittest import mock

        from evennia.accounts.models import AccountDB

        account, character = self._arriving()
        expected = character.archive_id
        ticket = self._ticket_for(account, character)
        session = self._session(ticket["token"])

        with mock.patch("evennia_scaling.handoff.place_in_world"):
            session.load_sync_data({})

        rebuilt = AccountDB.objects.get(pk=session.uid)
        self.assertEqual(rebuilt.db._last_puppet.archive_id, expected)

    @override_settings(SCALING_ROLE="shard")
    def test_ss_15_an_unarchived_account_is_not_admitted(self):
        """SS-15: the ticket promised an account the archive does not hold.

        Admitting a session without one is a session `portal_connect` drops
        back to a login screen, on an instance that should never show one —
        so it is not admitted at all, and the bounce sends it home.
        """
        from unittest import mock

        from evennia_scaling.tickets import create_ticket, store_ticket

        ticket = create_ticket(
            "8b1f0000-0000-4000-8000-000000000000",
            "8b1f0000-0000-4000-8000-000000000001",
            "shard0",
        )
        store_ticket(ticket)
        session = self._session(ticket["token"])

        with mock.patch(
            "evennia_scaling.handoff.scaling_log"
        ) as log, mock.patch(
            "evennia_scaling.sessions.send_session"
        ) as sending:
            session.load_sync_data({})

        self.assertFalse(session.logged_in)
        self.assertEqual(log.call_args.kwargs["level"], "ERROR")
        sending.assert_called_once()

    @override_settings(SCALING_ROLE="shard")
    def test_ss_16_a_character_that_cannot_be_placed_is_not_admitted(self):
        """SS-16: nothing raises this yet, and the handling is the point.

        When the real placement lands it will, and the arrival already
        treats it as a session it cannot admit.
        """
        from unittest import mock

        from evennia_scaling.handoff import PlacementFailed

        account, character = self._arriving()
        ticket = self._ticket_for(account, character)
        session = self._session(ticket["token"])

        with mock.patch(
            "evennia_scaling.handoff.place_in_world",
            side_effect=PlacementFailed("no such room"),
        ), mock.patch(
            "evennia_scaling.handoff.scaling_log"
        ) as log, mock.patch(
            "evennia_scaling.sessions.send_session"
        ) as sending:
            session.load_sync_data({})

        self.assertFalse(session.logged_in)
        self.assertEqual(log.call_args.kwargs["level"], "ERROR")
        sending.assert_called_once()

    @override_settings(SCALING_ROLE="shard")
    def test_ss_17_a_shard_rebuilds_the_ticketed_account(self):
        """SS-17: a shard's copy is stale, so the delete is the point.

        `restore` on its own hands back whatever is already live, so
        without the delete an arriving session gets the copy left over
        from the last visit.
        """
        from evennia.accounts.models import AccountDB

        from evennia_scaling.handoff import account_for_ticket

        account, character = self._arriving()
        ticket = self._ticket_for(account, character)
        stale_pk = account.pk

        rebuilt = account_for_ticket(ticket)

        self.assertFalse(AccountDB.objects.filter(pk=stale_pk).exists())
        self.assertEqual(str(rebuilt.archive_id), ticket["account_archive_id"])

    def test_ss_18_a_router_keeps_its_live_account(self):
        """SS-18: the router's copy is the authoritative one.

        Deleting and remaking it moves its primary key, and a Django
        website session names that key on every request.
        """
        from evennia.objects.models import ObjectDB

        from evennia_scaling.handoff import account_for_ticket

        account, character = self._arriving()
        ticket = self._ticket_for(account, character)

        kept = account_for_ticket(ticket)

        self.assertEqual(kept.pk, account.pk)
        # The rebuild takes the account's characters with it, so a
        # surviving character is what says no rebuild happened.
        self.assertTrue(ObjectDB.objects.filter(pk=character.pk).exists())

    def test_ss_19_a_router_logs_an_account_it_did_not_have(self):
        """SS-19: the account should have been here.

        Restored anyway — a player at the door is not the moment to
        refuse — but the absence is worth a line, because the only way to
        reach it is a rebuilt database or a ticket for an account this
        router has never seen.
        """
        from unittest import mock

        from evennia_scaling.handoff import account_for_ticket

        account, character = self._arriving()
        ticket = self._ticket_for(account, character)
        account.delete()

        with mock.patch("evennia_scaling.handoff.scaling_log") as log:
            restored = account_for_ticket(ticket)

        self.assertEqual(str(restored.archive_id), ticket["account_archive_id"])
        self.assertEqual(log.call_args.kwargs["level"], "ERROR")

    def test_ss_20_the_ticketed_character_joins_the_roster(self):
        """SS-20: the roster names something that is gone.

        The character was deleted on the instance it left, and comes back
        under a new primary key — so restoring it is only half the job.
        """
        from evennia_scaling.handoff import character_for_ticket

        account, character = self._arriving()
        ticket = self._ticket_for(account, character)
        character.delete()

        restored = character_for_ticket(ticket, account)

        self.assertEqual(
            str(restored.archive_id), ticket["character_archive_id"]
        )
        self.assertIn(restored, account.characters.all())

    @override_settings(SCALING_ROLE="shard")
    def test_ss_23_an_unarchived_character_is_not_admitted(self):
        """SS-23: the mirror of SS-15, for the other half of the ticket.

        Without it this raises out through `load_sync_data` and into AMP,
        where the player sees nothing at all rather than being sent home
        with a message.
        """
        from unittest import mock

        from evennia_archive.api import archive

        from evennia_scaling.tickets import create_ticket, store_ticket

        account, _ = self._arriving()
        archive(account)
        ticket = create_ticket(
            str(account.archive_id),
            "8b1f0000-0000-4000-8000-000000000001",
            "shard0",
        )
        store_ticket(ticket)
        session = self._session(ticket["token"])

        with mock.patch(
            "evennia_scaling.handoff.scaling_log"
        ) as log, mock.patch(
            "evennia_scaling.sessions.send_session"
        ) as sending:
            session.load_sync_data({})

        self.assertFalse(session.logged_in)
        self.assertEqual(log.call_args.kwargs["level"], "ERROR")
        sending.assert_called_once()

    @override_settings(SCALING_ROLE="router")
    def test_ss_21_a_router_brings_the_character_back(self):
        """SS-21: the character was deleted on the shard it left.

        Without this the player returns to a character-select menu short
        one character, and every other case here still passes.
        """
        from evennia.accounts.models import AccountDB

        account, character = self._arriving()
        expected = str(character.archive_id)
        ticket = self._ticket_for(account, character)
        # As the shard left it: archived there, and gone from here.
        character.delete()
        session = self._session(ticket["token"])

        session.load_sync_data({})

        back = AccountDB.objects.get(pk=session.uid)
        self.assertIn(
            expected,
            [str(one.archive_id) for one in back.characters.all()],
        )

    @override_settings(SCALING_ROLE="router")
    def test_ss_22_a_router_sets_no_last_puppet(self):
        """SS-22: nothing is puppeted on the router.

        `_last_puppet` is what auto-puppet reads on arrival at a shard.
        Writing it here would name a character the player has not asked
        to play.
        """
        from evennia.accounts.models import AccountDB

        account, character = self._arriving()
        ticket = self._ticket_for(account, character)
        character.delete()
        session = self._session(ticket["token"])

        session.load_sync_data({})

        back = AccountDB.objects.get(pk=session.uid)
        self.assertIsNone(back.db._last_puppet)

