# Progress

Running log of milestones with links to evidence. Reverse chronological — newest first.

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
