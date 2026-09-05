# SPDX-License-Identifier: BSD-3-Clause
"""A typeclass module that fails on import for a reason of its own, for SV-06.

Stands in for a bug in the consumer's code. It raises ``TypeError`` — the same
exception class as the MRO conflict — so the test proves the filter tells them
apart by content rather than by type.
"""

raise TypeError("consumer module is broken in some way of its own")
