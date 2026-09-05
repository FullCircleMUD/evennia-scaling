# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for evennia-scaling.

A case is agreed in docs/test-plan.md first, then the test is written here
against it, then the code. Every test carries its case ID as its docstring,
so the coverage trail reads in both directions.

Discovered by Django's test runner via runtests.py at the repository root.
"""

import unittest
from datetime import timedelta

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

        from evennia_scaling.config import get_role

        with self.assertRaises(ImproperlyConfigured) as raised:
            get_role()
        self.assertIn("SCALING_ROLE", str(raised.exception))

    @override_settings(SCALING_ROLE="banana")
    def test_cf_03_an_unknown_role_lists_the_valid_ones(self):
        """CF-03: a typo is caught at boot, not at the first branch.

        Listing the two valid values is what makes the line actionable —
        otherwise it reports a problem without saying what would fix it.
        """
        from django.core.exceptions import ImproperlyConfigured

        from evennia_scaling.config import ROLE_ROUTER, ROLE_SHARD, get_role

        with self.assertRaises(ImproperlyConfigured) as raised:
            get_role()
        message = str(raised.exception)
        self.assertIn(ROLE_ROUTER, message)
        self.assertIn(ROLE_SHARD, message)

    def test_cf_04_ready_checks_the_required_settings(self):
        """CF-04: the accessor raising is not enough on its own.

        It raises when something first calls it, and on a router that may be
        the first player to connect — so a misconfigured instance boots
        cleanly and fails somewhere that says nothing about the setting.
        """
        from unittest import mock

        from django.apps import apps as django_apps

        config = django_apps.get_app_config("evennia_scaling")
        with mock.patch("evennia_scaling.config.get_role") as checking:
            config.ready()
        checking.assert_called_once()


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
