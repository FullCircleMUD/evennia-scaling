# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for evennia-scaling.

A case is agreed in docs/test-plan.md first, then the test is written here
against it, then the code. Every test carries its case ID as its docstring,
so the coverage trail reads in both directions.

Discovered by Django's test runner via runtests.py at the repository root.
"""

import unittest

from django.test import TestCase

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
