"""
Common configuration shared by every instance in the demo.

One source tree, three settings files. `router/` holds all the code and all
four settings files; `shard0/` and `shard1/` symlink back to it and own only
their own `server/` directory. Identity is config, never a separate checkout.

Cascade:
    settings_router.py / settings_shard0.py / settings_shard1.py
        -> settings_common.py (this file)
            -> settings.py

Anything every instance needs goes here, so there is one place to change it
and no way for the three to drift. Anything that differs — a name, a role, a
set of ports — goes in the per-instance file and nowhere else.

What each instance owns vs shares:

    evennia.db3      per instance   its own world, its own Limbo, its own #1
    logs/            per instance   so a log line belongs to one instance
    archive.db3      shared         a character between instances lives here
    messagebus.db3   shared         how instances tell each other anything
    everything else  shared         symlinks back to router/

The two shared databases are symlinked from each shard back to the router's.
On one machine that is what stands in for the shared Postgres a real
deployment would use — the semantics are the same, and the arrangement has
been carried to Postgres before.
"""

import os
import sys

# ── macOS only: use a bundled, non-Apple SQLite build ────────────────
#
# macOS ships /usr/lib/libsqlite3.dylib, which drives sqlite3_initialize()
# through libdispatch. libdispatch does not survive fork(), so once any
# SQLite connection has been opened, a daemonizing (forking) start deadlocks
# on the child's first SQLite call — silently, with no error or timeout.
# `evennia start` forks on Unix; `--nodaemon` and Windows do not, which is
# why this only bites daemonized starts on macOS.
if sys.platform == "darwin":
    try:
        import sqlean
        import sqlean.dbapi2

        class _ScalingConnection(sqlean.dbapi2.Connection):
            def getlimit(self, category):
                # Django uses this only to size bulk_create batches.
                return 999

        _sqlean_connect = sqlean.dbapi2.connect

        def _connect(*args, **kwargs):
            kwargs.setdefault("factory", _ScalingConnection)
            return _sqlean_connect(*args, **kwargs)

        sqlean.dbapi2.connect = _connect
        sqlean.connect = _connect
        sqlean.SQLITE_LIMIT_VARIABLE_NUMBER = 9
        sqlean.dbapi2.SQLITE_LIMIT_VARIABLE_NUMBER = 9

        sys.modules["sqlite3"] = sqlean
        sys.modules["sqlite3.dbapi2"] = sqlean.dbapi2
    except ImportError:
        pass

from server.conf.settings import *  # noqa: F401, F403, E402

######################################################################
# Apps
######################################################################

INSTALLED_APPS = list(INSTALLED_APPS) + [  # noqa: F405
    "evennia_archive",
    "evennia_message_bus",
    "evennia_portal_multiplex",
    "evennia_scaling",
]

######################################################################
# Who the router is
######################################################################
#
# The one shared literal in the whole deployment. Every other name either
# points at this or is an instance's own, declared in its own file.
#
# A shard sends a session back to the router whenever it cannot admit one,
# and cannot work out which of its peers that is: instances see no database
# and no settings but their own. So this is shared knowledge and lives in the
# file every instance reads.
MULTIPLEX_DEFAULT_INSTANCE = "router"

# Same instance, named for the library that asks. Assignment rather than a
# second literal, so the two cannot drift.
SCALING_ROUTER_ID = MULTIPLEX_DEFAULT_INSTANCE

######################################################################
# Databases
######################################################################
#
# Two aliases beyond the game's own. Both are shared storage: a character
# archived on one instance is rebuilt on another, and a message sent by one
# is read by another. The paths are the same string on every instance — on
# the shards they resolve through a symlink to the router's copy.

DATABASES["archive"] = {  # noqa: F405
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": os.path.join(GAME_DIR, "server", "archive.db3"),  # noqa: F405
}

from evennia_message_bus.config import messagebus_database  # noqa: E402

DATABASES["messagebus"] = messagebus_database(  # noqa: F405
    os.path.join(GAME_DIR, "server", "messagebus.db3")  # noqa: F405
)

# Append, never assign: each library ships its own router and a consumer
# running two of them needs both in the list.
DATABASE_ROUTERS = list(globals().get("DATABASE_ROUTERS", []))
for _router in (
    "evennia_archive.db_router.ArchiveRouter",
    "evennia_message_bus.db_router.MessageBusRouter",
):
    if _router not in DATABASE_ROUTERS:
        DATABASE_ROUTERS.append(_router)

######################################################################
# Locks
######################################################################
#
# `list(...)` rather than `+=`: Evennia declares this as a tuple, and `+=`
# with a list raises TypeError before the server starts.
#
# The archive's mixin writes `owns_character()` into a character's puppet,
# edit and delete locks. Without this the clause cannot resolve, evaluates
# false, and an account is refused its own character with nothing in any log.
LOCK_FUNC_MODULES = list(LOCK_FUNC_MODULES) + [  # noqa: F405
    "evennia_archive.lockfuncs",
]

######################################################################
# The launcher verb that starts a Server without a Portal
######################################################################
#
# Declared for all three even though only the shards use it. Without it
# `evennia server_start` does not resolve, and it fails silently — the verb
# falls through to Django and is reported as an unknown command.
EXTRA_LAUNCHER_COMMANDS = {
    "server_start": "evennia_portal_multiplex.launcher.server_start",
}

######################################################################
# One Portal, on the router
######################################################################
#
# The AMP port the router's Portal listens on, and therefore the port the
# shards dial. One constant, used three times, because a mismatch means a
# Server that never attaches and a registry that never hears of it.
MULTIPLEX_AMP_PORT = 4006
