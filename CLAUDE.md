# CLAUDE.md

> **Project-wide working rules and cross-repo context live in the FCM umbrella repo's `CLAUDE.md`**,
> loaded automatically when you work from the umbrella root. If you opened this repo directly instead
> of via the umbrella, relaunch from the umbrella root for the full context. This file holds only this
> repo's specific instructions.

Instructions for Claude (and other LLM agents) working in this repository.

## What this project is

`evennia-scaling` moves a character between independent Evennia instances. Every instance runs its own
Evennia database — there is no shared one — so a character does not *travel* so much as get archived on
the instance it leaves and rebuilt on the instance it arrives at. Tagline: **"Many Evennia instances,
each on its own database."**

**Transport is not this library's concern.** Getting a player's connection from one instance to another
belongs to [evennia-portal-multiplex](../evennia-portal-multiplex), which this library depends on. A
session is handed from one Server to another behind a single Portal, on the same socket, whatever
protocol the player is on. This library never touches a socket.

What it does:

1. Archive the account and the character on the instance being left (`evennia-archive`).
2. Mint a ticket naming both, and tell the receiving instance over `evennia-message-bus`.
3. Ask multiplex to move the session, carrying the ticket in its payload.
4. On arrival, validate the ticket and rebuild the account and character from the archive.

Step 4 is why a ticket exists at all: multiplex clears `uid`, `logged_in` and `puid` on the way, so the
session arrives unauthenticated. Without a ticket the player retypes their password on every hop.

The archive round trip is not new machinery. FullCircleMUD already deletes its Evennia database,
rebuilds the world from source, and restores accounts and characters from the archive. This library
points the same mechanism sideways, at another instance, instead of at a rebuilt copy of the same one.

For the big-picture overview, read [README.md](README.md).
For the design wiki, read [docs/INDEX.md](docs/INDEX.md).

## Project status

**Early.** Minting, storing and sweeping tickets exist; nothing is usable yet. See
[docs/progress.md](docs/progress.md).

`libraries/evennia-scaling-OLD/` is a reference to read, **never a source to copy from**. It answers
this problem a different way; anything taken from it is discussed and agreed first.

## Where to read first

1. [docs/test-plan.md](docs/test-plan.md) — the cases the library commits to. **A behavioural change
   starts here**, not in the code. **Start here.**
2. [README.md](README.md) — what the library is and its status.
3. [docs/INDEX.md](docs/INDEX.md) — map of all design docs.
4. [docs/interoperability.md](docs/interoperability.md) — this library against its siblings.

## Load-bearing architectural principles

1. **The library does not own game concepts.** Rooms, exits, zones, what a character carries and what
   makes a transfer legal at this moment belong to the consumer game. The library moves an account and
   a character between instances; deciding that one should move is the game's.

2. **No FCM-specific assumptions.** Any Evennia game running more than one instance is a candidate
   consumer. FCM typeclass names, zone vocabularies and world layout stay in FCM.

3. **Test-first.** A case lands in [docs/test-plan.md](docs/test-plan.md), then the test, then the
   code. See [test-first-process.md](../../design/test-first-process.md) for the process and the
   rationale.

4. **No instance can see another's game database.** This is the point of the approach, not an
   incidental property of it. Nothing may resolve an object by primary key across instances, join
   across them, or assume a query on one instance can see a row on another. Identity between instances
   travels as an archive key, and nothing else.

5. **Transport belongs to multiplex.** This library asks for a session to be moved and is told the
   outcome. It does not redirect, reconnect, or know what protocol a player is on.

6. **The archive, the bus and the multiplexer do their own jobs.** `evennia-archive` owns storing and
   rebuilding; `evennia-message-bus` owns getting a message from one instance to another;
   `evennia-portal-multiplex` owns moving the session. This library coordinates them and adds the
   decision — it does not reimplement any of them, and a defect in one is fixed in that library.

## Out of scope

- **Sharding over a shared database.** That is `evennia-shards`, which partitions one Postgres by
  `shard_id`. This library is the alternative approach, and the two are not co-installed.

`[TBD — needs discussion: what this means for evennia-shards. This is described as an alternate
approach to try, not as a replacement, and no decision has been made about shards' future.]`

Everything else is decided as concrete questions arise, by applying the principles above.

## Working conventions

- **Postgres is the deployment target; SQLite is for local development.** Design for Postgres
  semantics. SQLite has to work, because the demo harness and the test suite run on it, but its limits
  are not design constraints. The demo emulates shared Postgres storage with symlinks between instance
  databases — a method that has been carried to Postgres before.
- **Sibling libraries are installed editable from their local checkouts.** None are on PyPI, so
  `pyproject.toml` names them and the venv installs them editable:

      pip install -e ../evennia-portal-multiplex -e ../evennia-archive -e ../evennia-message-bus

  Order matters — siblings first, then `pip install -e .`, or pip goes looking on PyPI and fails. The
  demo's `examples/requirements.txt` does the same for its own venv.
- **Editing design docs.** Update or add design documents whenever an architectural decision is made
  or refined. Capture the *why*, not just the *what*. Index new docs in [docs/INDEX.md](docs/INDEX.md).
- **Don't put implementation detail in this file or README.** Link out to `docs/` instead. Keep
  CLAUDE.md and README.md stable; let `docs/` churn.
- **License.** BSD 3-Clause. Source files carry an SPDX header on the first line
  (`# SPDX-License-Identifier: BSD-3-Clause`).

## Documentation discipline (load-bearing)

Design documents in `docs/` must reflect decisions **actually discussed and agreed on with the project
owner**. They are not a place to forward-design the system from first principles or extrapolate
"reasonable defaults" from a starting point.

**Rules:**

1. **Only capture what was discussed and agreed.** If the conversation establishes a principle, do not
   extrapolate it into specifics that were not raised — ticket formats, retry policies, API shapes.
2. **Flag open questions explicitly.** Write `[TBD — needs discussion: <what is open>]` so a future
   session picks the topic up deliberately rather than inheriting an unagreed assumption.
3. **Smaller is better.** Three discussed points captured faithfully beat three discussed points plus
   seven invented ones.

**The tempting sources of unasked-for answers are `evennia-scaling-OLD` and `evennia-shards`.** Both
answer this problem differently, so both have shapes ready to be lifted. A shape lifted from either is
an invention unless it has been discussed here.

## Repository layout

```
evennia-scaling/
├── CLAUDE.md                  # this file
├── README.md
├── LICENSE                    # BSD 3-Clause
├── pyproject.toml
├── runtests.py                # standalone test runner; no gamedir required
├── .gitignore
├── docs/                      # design wiki (humans + LLMs)
│   ├── INDEX.md
│   ├── progress.md
│   ├── test-plan.md
│   ├── interoperability.md
│   └── archive/               # historical context, not authoritative
├── src/
│   └── evennia_scaling/       # library code (src layout)
│       ├── __init__.py
│       ├── config.py          # settings, each behind an accessor
│       ├── models.py          # the ticket row, in the game database
│       ├── migrations/
│       ├── tickets.py         # minting, storing and sweeping tickets
│       ├── log.py             # shim onto Evennia's logger → scaling.log
│       └── tests.py           # unit tests, run via runtests.py
├── tests/                     # standalone test infrastructure
│   ├── __init__.py
│   ├── test_settings.py
│   └── urls.py
└── examples/                  # demo harness. Only its venv and requirements so far
```

`examples/` holds a venv and its `requirements.txt`. The gamedirs come once there is enough library
for a settings cascade to name.

No `contrib/` — nothing opt-in exists, and the standards forbid scaffolding one empty.

## Tools and environment

- Python 3.10+ (pinned via `pyproject.toml`).
- Runtime dependencies: `evennia`, `evennia-portal-multiplex`, `evennia-archive`,
  `evennia-message-bus`.
- **Tests use Django's test runner** via `runtests.py`, which bootstraps Django then calls
  `evennia._init()`, as the siblings do. No gamedir required.
- Two venvs, both gitignored: `venv/` at the repo root for the library's own tests, and
  `examples/venv/` for the demo. Every library here keeps them separate.

## Sibling libraries to reference

- **[../evennia-portal-multiplex/](../evennia-portal-multiplex/)** — a hard dependency. Several Servers
  behind one Portal, and a session handed between them without its socket moving.
- **[../evennia-archive/](../evennia-archive/)** — a hard dependency. Stores and rebuilds accounts and
  characters; the reason a character can survive not existing anywhere for a moment.
- **[../evennia-message-bus/](../evennia-message-bus/)** — a hard dependency. Carries the handoff
  message between instances that share no database.
- **[../evennia-shards/](../evennia-shards/)** — the shared-database approach this one is an
  alternative to.
