# SPDX-License-Identifier: BSD-3-Clause
"""Minimal Django settings for evennia-scaling unit tests.

Imports Evennia's defaults, adds the library to INSTALLED_APPS, and runs a
single in-memory sqlite database. No gamedir required.
"""
import os
import sys
import tempfile

import evennia

# Evennia 6.0.0+ ships migrations that import ``typeclasses.objects``
# (a gamedir module). Put Evennia's game_template on sys.path so the
# import resolves without requiring a real gamedir.
_game_template = os.path.join(os.path.dirname(evennia.__file__), "game_template")
if _game_template not in sys.path:
    sys.path.insert(0, _game_template)

from evennia.settings_default import *  # noqa: F401, F403, E402

# Evennia path bits — point at safe scratch locations so settings_default's
# path-derived defaults resolve without needing a real gamedir.
GAME_DIR = tempfile.gettempdir()
LOG_DIR = os.path.join(tempfile.gettempdir(), "evennia_scaling_test_logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Library under test
INSTALLED_APPS = list(INSTALLED_APPS) + [  # noqa: F405
    "evennia_archive",
    "evennia_message_bus",
    "evennia_scaling",
]

# One database. The library owns no tables yet; when it does, this grows a
# second alias and a router, as the siblings have.
# Each alias needs its own TEST name. Two ``:memory:`` databases are the
# same database, so without these the archive is the live database under
# another name and every round trip passes for the wrong reason.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "TEST": {"NAME": "file:evennia_scaling_test_default?mode=memory&cache=shared"},
    },
    # The archive. A second database with the same schema, holding accounts
    # and characters between instances — the library looks accounts up in it
    # and rebuilds them from it, so the suite needs a real one.
    "archive": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "TEST": {"NAME": "file:evennia_scaling_test_archive?mode=memory&cache=shared"},
    },
    # The bus. Shared storage too — a message written by one instance is
    # read by another.
    "messagebus": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "TEST": {"NAME": "file:evennia_scaling_test_bus?mode=memory&cache=shared"},
    },
}

DATABASE_ROUTERS = [
    "evennia_archive.db_router.ArchiveRouter",
    "evennia_message_bus.db_router.MessageBusRouter",
]

# `list(...)` rather than `+=`: Evennia declares this as a tuple.
#
# Archive's mixin writes `owns_character()` into a character's puppet, edit
# and delete locks. Without this the clause cannot resolve, and creating a
# character raises.
LOCK_FUNC_MODULES = list(LOCK_FUNC_MODULES) + [  # noqa: F405
    "evennia_archive.lockfuncs",
]

# This instance's role. Required — the library refuses to boot without it, so
# the suite has to declare one as any configured instance would.
SCALING_ROLE = "router"

# The rest of what the library refuses to boot without. Declared here for the
# same reason as the role: the suite is a configured instance, and a test that
# cares about one of these overrides it.
SCALING_ROUTER_ID = "router"

# This instance's name, as the bus knows it. The bus refuses to boot without
# one, so the suite declares it as any configured instance would.
MESSAGEBUS_INSTANCE_ID = "router"

# The typeclasses the library validates at boot. Stubs carrying the mixins,
# as any configured game's would be — check_settings resolves these during
# django.setup(), so they must not import Evennia.
BASE_ACCOUNT_TYPECLASS = "tests.typeclass_stubs.ScalingAccountStub"
BASE_CHARACTER_TYPECLASS = "tests.typeclass_stubs.ScalingCharacterStub"
SCALING_SHARDS = ("shard0", "shard1")
SCALING_START_LOCATION_SHARD = "shard0"
SCALING_DEFAULT_HOME_SHARD = "shard0"
SCALING_DEFAULT_HOME_UUID = "9c2f8b6d-4a71-4e35-b0c8-7d1e2a5f3049"

# Required Django bits
SECRET_KEY = "test-only-secret"
TEST_ENVIRONMENT = True
ROOT_URLCONF = "tests.urls"
