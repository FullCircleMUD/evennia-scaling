# SPDX-License-Identifier: BSD-3-Clause
"""evennia-scaling: many Evennia instances, each on its own database.

The package exposes no public surface yet. Exports land here as the library
is built, resolved lazily — importing the package runs while Django is still
building its app registry, so anything touching models must not be imported
at module scope.

See docs/INDEX.md for the design wiki and docs/test-plan.md for the cases
the library commits to.
"""

__version__ = "0.0.1"
