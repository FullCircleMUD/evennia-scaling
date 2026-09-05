# Progress

Running log of milestones with links to evidence. Reverse chronological — newest first.

## 2026-09-05 — leaving an instance

116 tests. A session and its character now leave an instance correctly. Nothing arrives yet — the
receiving half is not built, so a transfer ends with a session at a destination that does not know what
to do with it.

- **`transfer_to_instance`** — the whole of leaving, and the same six steps whichever way a session is
  going: archive the account, archive the character, mint a ticket naming both, announce it over the
  bus, delete the character locally, hand the session to `evennia-portal-multiplex`. A consumer moving
  a character between shards calls it too, so the path a game uses is the path the library uses.
- **The character is deleted after the ticket is sent**, and deferred by a reactor tick. `CmdIC` writes
  `_last_puppet` and logs against the character after `puppet_object` returns, so an inline delete makes
  Evennia serialise a dead object. `delay(0, ...)` cannot run until the call stack unwinds, so the
  ordering is structural rather than likely.
- **The outcome is reported.** Multiplex answers with `(moved, outcome)` on a Deferred. One table decides
  how loudly each outcome is recorded and whether there is anyone left to tell — a stranded session has
  no instance to deliver to, and a dropped one has nobody behind it. An errback covers what the move
  never turned into an outcome.
- **`puppet_object`** — the in-character trigger. On a router it checks the puppet lock, does not
  puppet, and transfers to the character's own shard. Superusers puppet normally: they belong to the
  instance they were made on.
- **`ScalingCmdOOC`** — the out-of-character trigger, replacing Evennia's `ooc` on a shard only. On a
  router, and for a superuser anywhere, Evennia's own command runs unchanged.
- **`unpuppet_object`** — archives and stops. It is also reached from `at_disconnect` and from
  `unpuppet_all()` at shutdown, so anything destructive there would fire on a dropped connection.
- **The stranded recovery.** Out of character on a shard with nothing puppeted is a state no path here
  can produce, and one nothing they type can escape. It is logged as a breach and the session is sent to
  the router without a ticket, to log in again.

**A trap the tests found.** `ready()` replaces `evennia.commands.default.account.CmdOOC` with ours, so a
test importing that name gets the class under test back — and patching "Evennia's" `func` patches ours.
Every case around the command passed for the wrong reason until it reached the real one through
`ScalingCmdOOC.__bases__[0]`.

## 2026-09-05 — the typeclass mixins and the boot checks

79 tests. The transfer is still not built, so nothing moves anyone yet.

- **`ScalingCharacterMixin`** — one member, `current_shard`, an `AttributeProperty` so the value
  survives the archive round trip. It is the character's location in the in-character world, at shard
  granularity, and it changes as the character moves. Validated against `SCALING_SHARDS` on write, which
  also keeps the router out, since the router can never be in the roster.
- **`ScalingAccountMixin`** — six classmethods. `find_in_archive` looks an account up by its username
  through `find_by_column`; `rebuild_from_archive` deletes the local copy and its characters and
  restores from the archive; `refresh_from_archive` adds the username lookup and the superuser guard;
  `authenticate` refreshes before Evennia checks the credentials; `restore_characters` rebuilds the
  roster from the archive's owner stamp, on the router only.
- **The delete is the mechanism.** `restore` is idempotent, so restoring over a stale copy does nothing
  at all. Deleting first is what makes an arrival correct regardless of how the instance was left.
- **Boot checks** — `check_settings()` collects every problem and raises once, so a consumer gets one
  list rather than one restart per mistake. It covers the four required settings, the shard roster and
  both configured typeclasses.
- **Five settings** — `SCALING_ROUTER_ID` (now required), `SCALING_SHARDS`, the two world anchors, and
  the role. Each is checked at boot and read through an accessor that does nothing else.

**Two fixture traps, both recorded in the test plan.** Two `:memory:` aliases are one database unless
each declares its own `TEST["NAME"]` — without that every archive round trip passes for the wrong
reason. And Evennia's identity map is process-global and survives Django's per-test rollback, so a
restore landing on a primary key an earlier test used hands back the earlier test's object.

## 2026-09-04 — receiving a ticket

12 tests, both linters clean. Nothing is usable yet.

- **The ticket table** — in the game database, not on an alias of the library's own. A library's
  tables go on their own alias when the data must outlive the game database or be read by more than
  one instance, and a ticket is neither. TK-05 pins that so a later session does not move it.
- **`store_ticket`** — writes the row when a handoff message is handled, stamping the expiry from this
  instance's clock. An absolute time carried in the payload would assume two instances agree on the
  hour.
- **`purge_expired`** — sweeps after the write rather than before, so it cannot race the row just
  written, and on traffic rather than a timer, so the library owns no scheduler.
- **`config.py`** — the ticket lifetime, ten seconds. The session arrives immediately over AMP, so
  what the lifetime covers is a player who drops mid-move.

## 2026-09-04 — scaffold and ticket minting

Six tests. Nothing usable.

- **The scaffold** — `pyproject.toml`, the `src/` layout, `tests/` infrastructure on Evennia's settings
  defaults, the `log.py` shim writing to `scaling.log`, and two cases proving the install and the
  runner reach each other.
- **`create_ticket`** — mints the ticket that lets an arriving session be recognised. Four cases.
- **Dependencies** — `evennia-portal-multiplex`, `evennia-archive` and `evennia-message-bus`, named in
  `pyproject.toml` and installed editable from their checkouts. None are on PyPI, so pip is satisfied
  by what is already in the environment rather than going looking.

**Why a ticket exists.** A session moved by `evennia-portal-multiplex` arrives with `uid`, `logged_in`
and `puid` cleared — deliberately, since those are primary keys belonging to the instance it left. The
destination therefore has a session and no idea who it is. The ticket is what lets it log that session
in without asking for a password again.
