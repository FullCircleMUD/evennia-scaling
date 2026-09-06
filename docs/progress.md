# Progress

Running log of milestones with links to evidence. Reverse chronological — newest first.

## 2026-09-06 — a ticket that names nothing is refused, not raised

155 tests.

Found by running the round trip on a fresh database: `ic` produced no response at all, and shard0's log
had a `NotArchived` coming out through AMP. The character had never been archived — leaving the router
archives the account alone, which assumed a character reaches the archive when it is created. It did
not.

- **`evennia-archive` now archives an account and a character at creation**, which is what that
  assumption needed. That is its change, not this library's, but this is what depends on it.
- **`reconstitute_for_ticket` catches `NotArchived` for the character too.** The account's was caught
  and the character's was not, so the same failure either bounced the session home with a message or
  broke the connection, depending on which half of the ticket was missing. Three failures, three
  returns. Case `SS-23`.

`HO-01`, `HO-15` and `HO-16` were rewritten with it. They asserted what the archive *held*, which stops
meaning anything once creating an account or a character puts it there — so they now assert what
`transfer_to_instance` archived, by watching the call. A better assertion in any case: it says what the
function did rather than what happened to end up in a table.

## 2026-09-05 — one place each thing can change

154 tests. A transfer works end to end in both directions, and the rule behind it is written down:
[where-state-changes.md](where-state-changes.md).

- **An account changes only on the router; a character only on the shard it is played on.** Two
  instances can hold the same account at once, so one of them has to be the real one.
- **Leaving archives what could have changed there** — router to shard stores the account, shard to
  anywhere stores the character. Storing the other one writes a copy that cannot have changed over one
  that is authoritative.
- **The router stopped rebuilding its account.** On arrival and at login it is found and returned, not
  deleted and remade. Its primary key stops moving, which is what a Django website session names on
  every request.
- **`reconstitute_for_ticket` became three functions** — `account_for_ticket`, `character_for_ticket`
  and the orchestration left over. Both roles now bring the ticket's character back and put it on the
  roster; only a shard places it and stamps `_last_puppet`.
- **`restore_missing_characters`** — renamed for what it does, and it returns what it restored. A
  character that never came home from a shard is noticed at login.
- **Nine commands that change account state** are out of character only. Seven by lockstring; `channel`
  guards four switches and `nick` rewrites one branch, so both keep working in character.
- **A superuser is refused a transfer outright** and told why. It belongs to one instance.

Known limit, recorded rather than solved: a character missing from the router looks the same whether it
was stranded by an ungraceful exit or is being played on a shard right now.

## 2026-09-05 — where a character lives, as a second pair

123 tests. Still all on the departure side: working out what the arrival needs turned into work the
sender has to do, so the arrival has one thing to handle rather than a set of half-configured states.

- **The home pair** — `home_shard` and `home_room_ref`. `character.home` is a dbref and does not survive
  the archive, so a home that means anything across instances has to be stored the same way a location
  is. The shard half defaults to the game's home shard; the room half does not default, and its absence
  is what sends the cascade on.
- **`ensure_location_for_transfer` became a cascade** — where they are, then where they live, then the
  one safe place in the game. Their own home is the second step and the default home the third, because
  a game with a beginner shard and an advanced shard does not want a character with a broken location
  resolving to whatever room sits at the default on the advanced shard.
- **One `_ShardProperty`, declared twice.** "Is this a shard in this deployment" is not specific to
  either pair. It names itself in its refusal, reading its own key off the descriptor.
- **The resolved location is written back; the home pair never is.** Falling back to the default home is
  a recovery, not a decision about where a character lives from now on.

**What this buys the arrival**, which is still unbuilt: both halves are present and the shard is in the
roster, because the sender could not have transferred them otherwise. So the arrival reads the room key
and has one failure to handle — a key that does not resolve in this database.

A rejected shape, recorded so it is not rediscovered: making `SCALING_SHARDS` a mapping of shard to home
room, so a broken location could fall back to a home *on the shard the character was already going to*.
It resolves somewhere in every case, which is worse than not resolving — the beginner arrives on the
advanced shard after all.

Known limit: an arriving character has no `character.home`, because the archive drops it. If their room
is destroyed while they are playing, Evennia falls them back to that shard's `DEFAULT_HOME`. A local
recovery from a local failure, and not what the deployment-wide home pair means.

## 2026-09-05 — where a character is, as a pair

120 tests.

- **`current_room_ref`** — the other half of a character's location. `current_shard` says which
  instance; this says which room in that instance's database. A shard alone does not say where a
  character stands.
- **`ensure_location_for_transfer()`** — completes the pair before a transfer and returns the shard.
  Either half unusable means there is nowhere to send them, because the destination *is* one half of the
  pair — so it is settled on the sending side rather than on arrival, and the arrival can assume both
  are present.
- Named for the transfer rather than the character's location, because they are different things:
  `character.location` is the room the character stands in now, and the two drift apart the moment a
  character walks anywhere.

Nothing restamps the pair yet, so a character transfers back to where they were last stamped rather than
where they stood.

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
