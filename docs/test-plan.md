# Test plan

Every test case the library commits to covering, and the test function that covers it. The library is
built test-first: cases are agreed here, tests are written against them, then the implementation is
written to pass. The **Test function** column is the auditable trail — it is filled in as each test is
written, so an empty cell means the case is agreed but not yet covered.

Case IDs are stable and referenceable. Do not renumber; retire an ID rather than reuse it. Every test
function carries its case ID as its docstring, so the trail reads in both directions.

All test functions live in `src/evennia_scaling/tests.py`.

Behaviour is agreed here first, before any test or code — see
[test-first-process.md](../../../design/test-first-process.md).

| Prefix | Covers |
|---|---|
| `CF` | Settings, each behind an accessor |
| `MS` | Messages between instances |
| `SS` | The Server session override — where an arriving session is admitted |
| `SC` | The scaffold — the library is installed and the runner reaches it |
| `AC` | The account mixin |
| `HO` | Handoff — sending a session and what it plays to another instance |
| `IC` | Going in character |
| `LK` | Locking account changes to out of character |
| `OC` | Going out of character |
| `PL` | Placement — putting an arriving character somewhere in this instance's world |
| `RM` | The room mixin — a room's identity across instances |
| `SH` | Where a character is in the game world |
| `SV` | Startup validation of the consumer's typeclasses |
| `TK` | Tickets — what lets an arriving session be recognised |

## Fixtures

The fake objects the suite needs, named and purposed.

| Fixture | Purpose |
|---|---|
| `tests/typeclass_stubs.py` | Stand-in classes for startup validation — correctly configured, archive's mixin only, a hand-rolled `archive_id`, and neither. **Imports no Evennia**: `test_settings.py` points `BASE_CHARACTER_TYPECLASS` at one, and `check_settings` resolves it during `django.setup()` |
| `tests/game_typeclasses.py` | Real account and character typeclasses, for tests that create objects. Imports Evennia, so it is imported inside a test body and never named in settings |
| `tests/bad_mro_character_stub.py` | Both mixins with archive's first. Raises `TypeError` on import — SV-05 |
| `tests/bad_mro_account_stub.py` | The account side of the same — SV-10 |
| `tests/bad_import_stub.py` | Raises `TypeError` on import for an unrelated reason — SV-06 |
| `TestArrival` | Its own class for `SS-11` to `SS-16`: the rest of `SS` uses a stand-in session, and these need real accounts, characters and an archive to rebuild from. It reads ids **before** the arrival runs — the rebuild deletes and restores, so an object a test created is gone and its id reads as `None` |
| `_PlayingSession` | A Server session as the sending paths see it — an address and what it puppets |
| `_FakeSession` | A Server session as the arrival path sees it — sync data, `logged_in`, `uid` |

Tests that create Evennia objects flush the identity map in `setUp`. Evennia's models are
`SharedMemoryModel`, so a query returns a cached instance keyed on (class, primary key), and that cache
is process-global — Django rolls the transaction back between tests and nothing rolls the cache back.
A restore landing on a primary key an earlier test used otherwise hands back the earlier test's object.

The two database aliases each need their own `TEST["NAME"]`. Two `:memory:` databases are one database,
and every archive round trip would pass for the wrong reason.

## Cases

One section per function or surface, each with its own prefix and its own table.

### SC — the scaffold

Not behaviour of the library, but a check that there is a library to test. These fail when the editable
install is missing, when the test settings do not name the app, or when the runner cannot find the test
module — each of which otherwise looks like "no tests ran".

| ID | Case | Test function |
|---|---|---|
| SC-01 | The package is importable and carries its version | test_sc_01_the_package_is_importable_and_versioned |
| SC-02 | A log call outside an Evennia engine is a silent no-op rather than an error | test_sc_02_the_log_shim_is_a_no_op_outside_evennia |

### CF — settings

Settings are read through an accessor in `config.py` and nowhere else, so a default lives in one place
and a consumer overriding one changes every reader at once.

**Checking and reading are separate jobs.** A setting with no safe default is validated once, at boot,
in `check_settings()`; its accessor then only reads. A setting with a default is never checked — booting
without it is what the default is for. See
[library-standards.md](../../../design/library-standards.md) § Reading settings.

So the cases split the same way: a refusal is a case against `check_settings`, and a default is a case
against its accessor.

**The defaults are commitments.** A consumer who sets nothing gets them, so a case pins each one — the
value can change, but not by accident and not without the plan saying so.

**A setting with no safe default is checked at boot.** `SCALING_ROLE` has none: an instance that does
not know whether it is a router or a shard cannot behave correctly in any direction, so refusing is the
honest answer and guessing hides the mistake until it costs more. `evennia-shards` can default to a
dormant `monolith` mode and do nothing; installing this library means at least a router and one shard,
so there is no equivalent to fall back on.

Validating at first use is not enough. That moment depends on what the library does — on a router it may
be the first player to connect — so a misconfigured instance boots cleanly and fails somewhere that says
nothing about the setting. `AppConfig.ready()` calls `check_settings()` so the failure happens at
startup, naming what to add.

**Two roles, and no third.** A router is where players log in and choose a character; a shard is where
a character is played.

`restore_missing_characters` branches on the role, and the arrival path sends an unadmitted session
back to the router only on a shard. So the setting earns its keep.

**The shard roster has no safe default either.** `SCALING_SHARDS` names every shard in the deployment,
and a character's `current_shard` is validated against it. There is nothing to guess: an empty roster
means no character can be played anywhere, and installing this library means at least a router and one
shard.

It is duplicated knowledge — each entry has to equal some instance's `MULTIPLEX_INSTANCE_ID` — and
nothing can check that, because no instance can read another's settings. So the accessor checks the
only things visible from here: that it is declared, that it holds something, and that its shape is a
sequence of names rather than one name. A bare string is the shape worth refusing outright, because it
is the one that silently succeeds — `"shard0"` iterates as `"s"`, `"h"`, `"a"` and matches nothing.

**`SCALING_ROUTER_ID` has no safe default.** A shard sends a session back to the router whenever it
cannot admit one, and cannot work out which of its peers that is — instances see no database and no
settings but their own. Guessing `"router"` is right only for a deployment that happens to use that
word, and wrong it is silent: sessions are sent to an instance nobody runs and bus rows expire unread.
Every other identity setting in the stack is already required.

It is not the same thing as multiplex's `MULTIPLEX_DEFAULT_INSTANCE`, which is where an unbound session
lands. Multiplex knows nothing about roles, so a deployment naming its router there has said where
traffic goes, not which instance manages the out-of-character game.

The router is also not a shard, so a value that appears in `SCALING_SHARDS` is refused.

**The world anchors have no safe default either.** `SCALING_START_LOCATION_SHARD` and
`SCALING_DEFAULT_HOME_SHARD` say which shard holds the two rooms Evennia's `START_LOCATION` and
`DEFAULT_HOME` name. Two settings rather than one, because a game may put the two rooms on different
shards.

Both are checked the same way, and either failing refuses the boot: unset, because the library cannot
guess which instance holds a room; or naming something outside `SCALING_SHARDS`, because a name nothing
runs under sends characters to an instance that never answers. Neither shows up as a misconfiguration
at the point it bites — the first character created is already in front of a player.

**`SCALING_DEFAULT_HOME_UUID` names the one room a character can always be sent to**, and it is the room
half of the pair `SCALING_DEFAULT_HOME_SHARD` opens. Required, because no uuid the library invented would
name anything.

Checked twice: that it is set, and that it parses as a uuid. The second matters because the value is
carried as a string and compared as one — a truncated or hand-mangled uuid satisfies every other test
and simply matches nothing, so the last resort in the placement cascade silently has no room in it.

Not checked here: whether it names a room that exists. That room is on one shard and every other
instance boots without it, so the question can only be asked where the answer means something — see
`PL-09`.

**`SCALING_KEEP_LOCATION_IN_UNMARKED_ROOM` has a safe default, so it is not checked at boot.** It says
what a character's recorded location becomes when they walk into a room with no uuid — see `SH-19` and
`SH-20` for the two behaviours. It defaults to keeping the last recorded room, which is the answer that
does not punish a player for losing their connection somewhere the game cannot reproduce.

It is also the default a consumer can most easily reverse. Clearing after `super().at_post_move()` is a
line; restoring a value the library has already cleared means reading it first.

| ID | Case | Test function |
|---|---|---|
| CF-01 | The ticket lifetime defaults to ten seconds when the setting is absent | test_cf_01_the_ticket_lifetime_defaults_to_ten_seconds |
| CF-02 | An undeclared `SCALING_ROLE` is refused, naming the setting | test_cf_02_an_undeclared_role_is_refused |
| CF-03 | A value that is neither role is refused, listing the two that are | test_cf_03_an_unknown_role_lists_the_valid_ones |
| CF-04 | `ready()` checks the required settings, so a misconfigured instance does not start | test_cf_04_ready_checks_the_required_settings |
| CF-05 | An undeclared `SCALING_SHARDS` is refused, naming the setting | test_cf_05_an_undeclared_shard_roster_is_refused |
| CF-06 | An empty shard roster is refused — no character can be played anywhere | test_cf_06_an_empty_shard_roster_is_refused |
| CF-07 | A bare string is refused rather than iterated letter by letter | test_cf_07_a_bare_string_is_refused |
| CF-08 | A list and a tuple are both accepted as the roster | test_cf_08_a_list_and_a_tuple_are_both_accepted |
| CF-09 | An unset world anchor is refused, naming the setting | test_cf_09_an_unset_world_anchor_is_refused |
| CF-10 | A world anchor naming something outside `SCALING_SHARDS` is refused, naming the roster | test_cf_10_a_world_anchor_outside_the_roster_is_refused |
| CF-11 | An unset `SCALING_ROUTER_ID` is refused, naming the setting | test_cf_11_an_unset_router_id_is_refused |
| CF-12 | A `SCALING_ROUTER_ID` that is also in `SCALING_SHARDS` is refused | test_cf_12_a_router_id_in_the_roster_is_refused |
| CF-13 | `SCALING_KEEP_LOCATION_IN_UNMARKED_ROOM` defaults to keeping the last recorded room | test_cf_13_keeping_the_location_in_an_unmarked_room_is_the_default |
| CF-14 | An unset `SCALING_DEFAULT_HOME_UUID` is refused, naming the setting | test_cf_14_an_unset_default_home_uuid_is_refused |
| CF-15 | A `SCALING_DEFAULT_HOME_UUID` that does not parse as a uuid is refused, naming the value | test_cf_15_a_default_home_uuid_that_is_not_a_uuid_is_refused |

### AC — the account mixin

`ScalingAccountMixin` carries `ArchivableAccountMixin`, so a consumer adds one mixin to their account
class rather than two.

**An account is found in the archive by its username.** It is the only thing a player supplies at a
login screen, and it is unique — Django enforces that on the column, and the archive runs the same
schema, so the constraint holds there too.

`evennia_archive.find_by_column("accountdb", "username", identifier)` is the search.

`find_in_archive(identifier)` is the seam a consumer overrides to identify an account by something other
than its username — a wallet address, say. One argument, named for what it is rather than what we do
with it, and the library calls it positionally, so renaming it in an override is safe.

It is not `find_in_archive(column, value)`. That generic form already exists as `find_by_column`, and a
passthrough would add nothing — the point of this method is to *be* the one place that decides which key
identifies an account.

**Rebuilding is delete-then-restore.** `restore()` is idempotent — given an identity that is already
live it hands back the existing object rather than rebuilding it — so restoring over a stale copy does
nothing at all. The delete is the mechanism, not tidiness.

That is what makes correctness a property of arriving rather than of leaving. Whatever an instance still
holds from a previous visit — after a crash, a boot, a dropped connection, a shutdown — is thrown away
and rebuilt before anyone gets in, which is why none of the ways of *leaving* an instance is handled.

**The account's local characters go with it.** Evennia's `AccountDB.delete` nulls `db_account` rather
than cascading, and clears the account's attributes with the roster among them — so the characters
would survive as orphans nothing references, and `restore()` would later hand one of those back
unchanged.

Deleting them is safe because **the archive is authoritative for a character**. It holds the latest copy
at all times: the library archives at the end of chargen and again whenever a character leaves a shard,
and nothing on the router changes a character's state in between. Those two are the library's to
maintain — without them this is where a character's progress would be lost.

They are found by the owner stamp rather than by `db_account` or the roster. The stamp is the link that
survives an archive round trip, and it is what `restore_missing_characters` searches by, so the delete and the
restore agree by construction.

`restore_missing_characters` is a separate step, gated on the role inside itself so a caller never branches. On a
shard it does nothing: a shard holds one character, the one its ticket names.

**`refresh_from_archive` is the login door's wrapper**, and the only place a username is all that is
known. `authenticate` is handed a string a player typed; finding the identity is the work. Every other
way in already holds an `archive_id` and calls `rebuild_from_archive` directly — the ticket carries one.

**An account that is already here is returned untouched.** The router's copy is the authoritative one,
so there is nothing better to replace it with — and replacing it moves its primary key, which anything
outside the game holding that key is then naming a row that no longer exists. A Django website session
resolves it on every request.

Only an account that is *absent* is restored, which is a router whose database was rebuilt. No delete,
because there is nothing there to delete.

It adds one decision to that lookup: **account `#1` is never restored.** Evennia expects one on every
instance, and replacing it with an archived copy takes an operator's way in with it. The guard runs
first, and its local lookup is `filter(username=identifier)`.

**It restores the roster on both paths.** For a restored account that is the obvious half — its
characters are absent too. For an account that was already here it is the *stranded character* case: a
player who left ungracefully while in character never came back through the ticket door, so their
character is still only in the archive. Login is where that is noticed and fixed.

`restore_missing_characters` is safe to run over characters that are already present. `restore` returns a live
one unchanged, and Evennia's `add` skips one already on the roster — so it restores what is missing and
disturbs nothing else.

**Missing can also mean "being played on a shard right now."** A player linkdead on a shard who
reconnects to the router looks identical from here, and restoring then puts a stale copy of a live
character on the router. It recovers: the archive stays authoritative, and going in character rebuilds
from it. Until then the select menu shows an old copy
[TBD — needs discussion: whether the router should be able to tell the two apart, which needs the shard
to say so].

That local lookup is a second tie to the username, and it is not a seam. A consumer who overrides
`find_in_archive` to identify accounts some other way must override this method too, or the guard is
handed something that is not a username, matches nothing, and stops protecting anything while still
reading correctly. See installing.md § Identifying an account by something other than its username.

**Every identifier this library passes or receives is an `archive_id`** — the uuid4 the mixin mints, and
`ArchiveRecord`'s primary key. The archive's own row keys never leave archive.

**`authenticate` is where the refresh happens, and the order is the point.** There is no seam inside
Evennia's login flow — it looks the account up and checks the password in one call — but it is a
classmethod on the account typeclass, so overriding it *is* the seam. Refreshing before `super()` means
credentials are checked against the archived copy rather than whatever this instance was still holding.
Refreshing after would refuse a player their own password because they changed it somewhere else.

The refresh's result is ignored. An account with nothing archived is a first-time player, and the login
has to proceed exactly as Evennia would.

No role gate. A shard is never reached through this door: an unticketed session is sent to the router
before a login screen renders.

**`restore_missing_characters` rebuilds the roster, and only on the router.** The character-select menu reads
live objects, so an account restored without its characters logs in to an empty menu — which looks like
it worked.

They are found by the owner stamp `evennia-archive` writes at character creation. `db_account` is a
primary key and does not survive the archive, so the stamp is the only link back to an owner that does.

**Gated on the role inside the method**, so a caller never branches — and so a login straight to a shard
cannot reach it either. A shard receives exactly one character, the one its ticket names; restoring a
whole roster there would put every character on an instance it is not being played on.

Adding to the roster is `account.characters.add(...)` rather than writing the attribute, because that
also fires `at_post_add_character`.

| ID | Case | Test function |
|---|---|---|
| AC-01 | An archived account is found by its username | test_ac_01_an_archived_account_is_found_by_username |
| AC-02 | A username with nothing archived returns `None` | test_ac_02_an_unarchived_username_returns_none |
| AC-03 | An archived account with no live copy is rebuilt and returned | test_ac_03_an_archived_account_is_rebuilt |
| AC-04 | A stale live copy is replaced rather than returned | test_ac_04_a_stale_local_copy_is_replaced |
| AC-05 | An archive id that is nothing in the archive raises | test_ac_05_an_unarchived_identity_raises |
| AC-06 | Rebuilding an account deletes its local characters, so nothing stale survives it | test_ac_06_the_accounts_local_characters_go_with_it |
| AC-07 | An account that is absent locally is restored from its username | test_ac_07_an_absent_account_is_restored_by_username |
| AC-08 | A username with nothing archived is left alone | test_ac_08_an_unarchived_username_is_left_alone |
| AC-09 | Account `#1` is not restored, even with an archived copy | test_ac_09_account_one_is_not_refreshed |
| AC-10 | An account that is already here is returned untouched — its primary key does not move | test_ac_10_a_live_account_is_left_where_it_is |
| AC-11 | The return value is Evennia's, unchanged | test_ac_11_the_return_value_is_evennias |
| AC-12 | An account with nothing archived still authenticates | test_ac_12_an_unarchived_account_still_authenticates |
| AC-13 | On the router, every character carrying this account's owner stamp is restored | test_ac_13_a_router_restores_every_owned_character |
| AC-14 | Restored characters are on the account's roster | test_ac_14_restored_characters_join_the_roster |
| AC-15 | On a shard, nothing is restored | test_ac_15_a_shard_restores_nothing |
| AC-16 | Characters owned by a different account are not restored | test_ac_16_another_accounts_characters_are_left_alone |
| AC-17 | A restored account gets its characters back with it | test_ac_17_a_restored_account_gets_its_characters |
| AC-18 | An account that was already here gets any stranded character back at login | test_ac_18_a_stranded_character_comes_back_at_login |
| AC-19 | The instance root is `#1` **and** a superuser — neither half names it alone | test_ac_19_the_instance_root_is_both_halves |

### SH — where a character is in the game world

`current_shard` is the character's current location in the in-character world, at shard granularity. A
character that moves from `shard0` to `shard1` has its `current_shard` change with it. It is not a home
shard and not a permanent assignment.

**The router is not part of the game world.** It is where the out-of-character game is conducted, so a
character is never in it — the character object can be instantiated there while the player is out of
character, but it is not standing anywhere in the world. `current_shard` keeps naming the shard the
character is in, which is what going in character reads to know where to send them.

An `AttributeProperty`, so the value is an Attribute and survives the archive round trip — a field
would not. Validation lives in `at_set`, which is the descriptor's write hook.

**One rule: the value must be in `SCALING_SHARDS`.** That is also what keeps the router out, since
`CF-12` refuses a `SCALING_ROUTER_ID` that appears in the roster — so there is no separate router
check and no second place for the two to disagree. It is not a guarantee that the named instance is
running: the roster is the deployment as intended, and a shard that is down is still a real part of the
world.

**`None` is refused like any other value.** There is no un-set path: a character that has never been
assigned a shard reads as `SCALING_START_LOCATION_SHARD`, and Evennia's `autocreate` writes that
default back on the first read, so assigning `None` would be reverted by the next read anyway.

The refusal is a `ValueError`, not `ImproperlyConfigured`. The settings are fine; a caller passed a
value that is not a shard, at runtime.

**`at_set` returns what gets stored, and ours returns it unchanged.** No trimming and no case folding —
tidying `"Shard0 "` into `"shard0"` would hide the typo rather than report it.

**`.db` bypasses all of this.** Evennia's own documentation says so: `character.db.current_shard = "x"`
writes through the AttributeHandler and the descriptor never runs. Nothing can close that door from
here.

#### Where a character is, as a pair

A shard alone does not say where a character stands. **`current_shard` and `current_room_uuid` are one
composite key** — which instance, then which room in that instance's world.

`current_room_uuid` holds the room's `scaling_room_uuid`, not a dbref. A dbref names a row in one
database and means nothing in the next, so it cannot survive either a transfer or a world rebuild. The
uuid is assigned to the room by the consumer and reproduced whenever the world is redeployed, so it
still names the same room after either.

It has no default and reads as `None` until something sets it. A room key is meaningless without a shard
beside it, so there is no useful value to fall back to at read time; the pair is completed at the moment
of use instead.

**Its shape is checked; its meaning is not.** Which uuids exist is the consumer's world, and the room it
names is on another instance, so there is no way to ask whether it names anything. What can be checked
is that it is a uuid at all — a dbref or a room name in this field is a mistake that would otherwise
surface as a character arriving in the wrong place.

**Parsing is the check, and the value is stored as it was given.** `at_set` returns it unchanged, the
same as `current_shard` does — the check says whether it is a uuid, and says nothing about how it should
be written.

Storing a canonicalised form was the alternative and it is wrong here. `evennia-world-builder` holds the
matching identity — an author-supplied `entity_id` on the room — and stores the string as written,
absorbing the variation at lookup with `db_key__iexact`. A uuid canonicalised on this side would stop
matching a room whose `entity_id` was written in uppercase. Sibling libraries agree on the shape: a
uuid is a `str` here, never a `uuid.UUID`, so the value that goes in is the value that comes out.

**A non-string is refused**, world-builder's rule for the same identity. `uuid.UUID` would happily
accept a `uuid.UUID` back, and letting one in means half the stored values are objects that compare
unequal to every string beside them.

**`None` is accepted here, unlike `current_shard`.** Unset is a real state for a room key: it is what a
character has before anything stamps one, and what the cascade's third step leaves behind.

**A character carries two pairs, and there is a third behind them.**

| | Shard | Room |
|---|---|---|
| Where they are | `current_shard` | `current_room_uuid` |
| Where they live | `home_shard` | `home_room_uuid` |
| The one safe place in the game | `SCALING_DEFAULT_HOME_SHARD` | — |

**`ensure_location_for_transfer()` walks that cascade and returns the shard.** Either half of a pair
being unusable — a shard outside `SCALING_SHARDS`, or no room key — makes the whole pair unusable,
because *the destination is one half of it*. There is nowhere to send them until both halves agree,
which is why this happens before the transfer rather than on arrival.

The home pair is the right second step, and the default home the wrong one to reach first. A game with a
beginner shard and an advanced shard does not want a character with a broken location resolving to
whatever room sits at the default on the advanced shard — they would arrive somewhere that kills them.
Their own home is where they belong; the default home is the last resort for a character that has none.

Neither home attribute has a default. One at that step would make the cascade never reach the third.

**What it resolved is written back to the location pair, and never to the home pair.** The location is
now true, and the arrival reads one place for it. Falling back to the default home is a recovery, not a
decision that this is where the character lives from now on.

**The third step writes the shard and leaves the room half unset.** There is no room uuid to write: the
one safe place is `DEFAULT_HOME`, a dbref belonging to whichever instance is asked, and putting that in
a field that holds uuids would leave the arrival unable to tell which kind of value it is holding. An
unset room half is also the more honest claim — this cascade knows which shard, and does not know the
room. The arrival places them at its own `DEFAULT_HOME`.

The shard half of a check looks redundant, since `at_set` refuses anything outside the roster — but
`.db` bypasses that, and a shard removed from the roster after a character was stamped goes stale the
same way.

**One property serves both shards.** "Is this a shard in this deployment" is not specific to the current
one, so `current_shard` and `home_shard` are the same `_ShardProperty` declared twice. It names itself in
its refusal, reading its own key off the descriptor rather than hardcoding one.

**And one serves both room halves**, for the same reason and in the same way. "Is this a uuid" is not
specific to where the character is or where they live.

`home_shard` defaults to `SCALING_DEFAULT_HOME_SHARD` — the game's home shard is the sensible home for a
character that has not been given one. The room half has no default, and its absence is what sends the
cascade on to the third step.

Named for the transfer rather than for the character's location, because it is not the same thing:
`character.location` is the room object the character stands in *now*, on the instance running it, and
the two drift apart the moment a character walks anywhere.

The arrival can therefore assume both halves are present, because the sending side guaranteed it.

#### Keeping the pair true as a character walks

The pair is stamped on `at_post_move`, which Evennia calls after a move has completed and again at
creation with no source location — so a character built in a room is stamped without a special case.

**It is the only seam that fits.** `at_object_receive` is the room's hook, and rooms have no business
writing to characters. Overriding the `location` property would catch a bare assignment too, but that
descriptor is Evennia's and replacing it is fragile. What `at_post_move` misses is exactly that bare
assignment — `character.location = room` — which is what the arrival does, and there the uuid is
already known because it is what the room was resolved from.

**`DefaultCharacter` overrides this hook already**, to make the character look at the room it arrived
in. Ours calls `super()` first, and `SH-22` pins that: this is the inherited-behaviour case the section
above has been holding open, and it is the one a player notices immediately.

**The room is asked, not tested for the mixin.** `getattr(location, "scaling_room_uuid", None)` — a room
that exposes one has one, and whether it got there from `ScalingRoomMixin` is not this library's
business.

**Nothing is stamped on a router.** A character is never *in* the router, and the router's id is by
definition not in `SCALING_SHARDS`, so stamping there would raise on the shard half — at character
creation, which is a router operation.

**The shard half is this instance's `MULTIPLEX_INSTANCE_ID`**, read through multiplex's own accessor
rather than a second setting of ours. `CF-06` onward already require `SCALING_SHARDS` to be spelled
exactly as each instance's id, so a setting of our own would only give the two somewhere to disagree.

**The shard half is never cleared.** `_ShardProperty` refuses `None`, and there is nothing to clear
anyway: a character standing in an unrecorded room is still on this shard. An incomplete pair is what
the cascade already reads as unusable, so the room half alone carries the meaning.

**The mixin carries `ArchivableCharacterMixin`**, so a consumer adds one mixin to their character class
rather than two.

`SH-06` asserts that relationship and nothing more. **These cases cover what this library's classes
could break, not what its dependencies do** — `evennia-archive` tests its own mixins, and duplicating
that here would be testing someone else's code through ours.

The case to add, when it applies: **wherever this mixin overrides a method it inherits, a case pins that
the override has not lost the behaviour the inherited version provided.** That is the change an
inherited-behaviour test can catch and the base class's own suite cannot, because its suite knows
nothing about this subclass. `SH-22` is the one such case today, over `at_post_move`.

| ID | Case | Test function |
|---|---|---|
| SH-01 | The value is stored as an Attribute, so it survives the archive round trip | test_sh_01_is_stored_as_an_attribute |
| SH-02 | A shard in `SCALING_SHARDS` is accepted and reads back unchanged | test_sh_02_accepts_a_shard_in_the_roster |
| SH-03 | A value not in `SCALING_SHARDS` is refused, naming the value and the roster | test_sh_03_refuses_a_shard_outside_the_roster |
| SH-04 | `None` is refused, saying what it means rather than reading as a typo | test_sh_04_refuses_none |
| SH-05 | A character never assigned a shard reads as `SCALING_START_LOCATION_SHARD` | test_sh_05_a_character_never_assigned_reads_as_the_start_shard |
| SH-06 | `ScalingCharacterMixin` extends `ArchivableCharacterMixin`, so one mixin on the character satisfies both | test_sh_06_carries_the_archive_mixin |
| SH-07 | `current_room_uuid` is stored as an Attribute, so it survives the archive round trip | test_sh_07_the_room_uuid_is_stored_as_an_attribute |
| SH-08 | A character never assigned one reads as `None` | test_sh_08_an_unassigned_room_uuid_reads_as_none |
| SH-09 | `ensure_location_for_transfer` leaves a character with both halves alone | test_sh_09_a_complete_pair_is_left_alone |
| SH-10 | A character with a broken location and a usable home is sent home | test_sh_10_a_broken_location_falls_back_to_home |
| SH-11 | The home pair is stored as Attributes, and `home_shard` refuses a shard outside the roster | test_sh_11_the_home_pair_is_stored_and_checked |
| SH-12 | A character with neither a usable location nor a usable home gets the default home shard, and the room half is left unset rather than filled with a dbref | test_sh_12_neither_pair_falls_back_to_the_default_home_shard |
| SH-13 | The resolved location is written back; the home room uuid is not | test_sh_13_the_home_room_is_not_written_back |
| SH-14 | A well-formed uuid string is accepted and reads back exactly as it was given | test_sh_14_a_room_uuid_is_stored_as_given |
| SH-15 | A string that is not a uuid is refused, naming the attribute it was set on | test_sh_15_refuses_a_value_that_is_not_a_uuid |
| SH-16 | A `uuid.UUID` object is refused — a uuid travels as a string between these libraries | test_sh_16_refuses_a_uuid_object |
| SH-17 | `None` is accepted, because unset is a real state for a room key | test_sh_17_a_room_uuid_accepts_none |
| SH-18 | Moving into a room with a uuid stamps both halves — that uuid, and this instance's id | test_sh_18_a_move_stamps_the_pair |
| SH-19 | Moving into a room with no uuid leaves the pair alone, by default | test_sh_19_an_unmarked_room_leaves_the_pair_alone |
| SH-20 | With `SCALING_KEEP_LOCATION_IN_UNMARKED_ROOM` off, the room half is cleared and the shard is still stamped | test_sh_20_an_unmarked_room_can_clear_the_room_half |
| SH-21 | On a router nothing is stamped — a character is never in the router, and its id is not a shard | test_sh_21_a_router_stamps_nothing |
| SH-22 | `super().at_post_move` still runs, so the character still sees the room it moved into | test_sh_22_the_inherited_look_still_happens |

### PL — placement

`place_in_world(character)` puts an arriving character somewhere in this instance's world. The archive
strips location, home and every other reference on the way in, so a character arrives standing nowhere
at all.

**Three resolutions, then failure.** Each names a shard and a room, and each asks the same two questions
in the same order: is that shard this one, and does that room resolve here.

| | Shard | Room |
|---|---|---|
| 1 | `current_shard` | `current_room_uuid` |
| 2 | `home_shard` | `home_room_uuid` |
| 3 | `SCALING_DEFAULT_HOME_SHARD` | `SCALING_DEFAULT_HOME_UUID` |

**This is not `ensure_location_for_transfer` again.** The sender checks *presence* — is there a shard in
the roster and a room key beside it. The arrival checks *resolvability* — does that uuid name a room in
this database, which no sender can know. Same shape, different question, and both are needed.

**All three rows are one lookup.** The third is a setting rather than something on the character, but it
is a room uuid like the other two and resolves through `find_room_by_uuid` like the other two.

**Evennia's `DEFAULT_HOME` is not this.** It is a dbref, so it names nothing after a rebuild; it exists
on every instance, so falling back to it locally puts the beginner in the advanced shard's Limbo — the
behaviour the `SH` section rejects; and out of the box it is `#2`, a technical room for the contents of
destroyed objects rather than anywhere a game wants a player to wake up. This library stops reading it.
Evennia goes on using it for its own purposes.

**There is no fourth row.** If the default home uuid does not resolve on its own shard the deployment is
broken, and a floor that quietly drops the player into Limbo would hide it.

#### A superuser goes to Limbo

**A superuser is placed at this instance's `DEFAULT_HOME`, and the cascade does not run.** Not a row in
it and not a fallback after it — a branch before it.

A superuser is not playing the game the way the rules above are written for. They can `tel` anywhere the
moment they arrive, so being routed by where their character *was* buys them nothing, and always
appearing in one known room is worth more. It is also what makes an instance reachable at all: a shard
whose rooms carry no uuids yet — a fresh one, or one whose world has not been built — has nowhere the
cascade can land anybody, and the person who needs to get in and fix that is exactly this one.

**`DEFAULT_HOME` rather than a uuid**, and this is the one place a dbref is right. It is resolved on the
instance already being stood on, so it never has to mean anything across a database — which is the whole
reason the rest of this uses uuids. Evennia's initial setup makes the room, so it is there on every
instance.

**`is_superuser`, not `is_instance_root`.** `#1` never travels, so any superuser arriving here is
already not `#1`, and the plain check says what it means.

**Their location pair is left alone.** Nothing resolved, so there is nothing to record; it keeps what it
held and restamps on their first move like anyone's.

**If `DEFAULT_HOME` does not resolve, object `#2` is tried.** Evennia's initial setup makes Limbo, and it
makes it second — so on any instance it set up, `#2` is Limbo. Where `DEFAULT_HOME` is at its own default
the two are the same lookup and the fallback never fires; it fires only where an operator repointed
`DEFAULT_HOME` at a room that has since gone, and there `#2` is a better answer than sending the one
person who can fix it back to the router.

Nothing checks that `#2` is *named* Limbo, or that it is a room at all. This demo renames shard0's to
`Shard0_Limbo`, and a game is free to call its start room anything — a name is not what makes it the
room. Getting `#2` to be something else takes deliberate work, and the cost of it is a superuser standing
inside whatever that is, one `tel` from anywhere they meant to be.

`PlacementFailed` still applies if neither resolves, which means the instance has no Limbo at all.

#### When the shard is not this one

All three rows raise `RoomOnAnotherShard`, naming it.

**Rows 2 and 3 rewrite the location pair to what they resolved before raising**, and that is what makes
the cascade terminate: each hop advances it one row, so the next instance starts from where this one got
to rather than from the top. Without the rewrite the same instance resolves the same unreachable pair
forever.

**Row 1 rewrites nothing**, because it has resolved nothing — the pair is already right and it is the
session that is in the wrong place. It terminates in one hop: the destination's row 1 tests equal and
places them.

**Row 1 is also a breach, and is logged as one.** Leaving stamps `current_shard` with the destination
(see `HO-18`), so a session that arrives where the character's own shard is not this one cannot be
produced by any path here. Falling through to the home pair instead would route a player home over what
is really a delivery fault, and say nothing about it.

**The transfer is not issued here.** `place_in_world` runs inside `load_sync_data`, before the session is
logged in; moving the session from here would hand it away while the caller is still about to set `uid`
and `logged_in` on it. So the exception carries what a transfer needs and rises to the frame that owns
the session. See `SS-24`.

#### When nothing resolves

`PlacementFailed`, naming all three pairs that were tried. The session is not admitted, it goes to the
router, and it is logged as an error — a deployment where a character has no reachable location at all
is broken, not unlucky.

#### A duplicate uuid is not routed around

`DuplicateRoomUuid` from the finder is left to rise rather than caught and treated as "did not resolve".
Falling through would place the character somewhere plausible and leave two rooms claiming one identity
in the world source, unnoticed. The player is told to report it — the one failure here they can do
anything about.

| ID | Case | Test function |
|---|---|---|
| PL-01 | A character whose current pair resolves here is placed in that room | test_pl_01_the_current_pair_is_placed |
| PL-02 | A `current_shard` that is not this shard raises `RoomOnAnotherShard` naming it, rewrites nothing, and is logged as a breach | test_pl_02_another_shards_current_pair_is_forwarded |
| PL-03 | A current room uuid that resolves to nothing here falls through to the home pair | test_pl_03_an_unresolvable_current_room_falls_through |
| PL-04 | A home pair on another shard rewrites the location pair to it and raises `RoomOnAnotherShard` | test_pl_04_a_home_on_another_shard_is_forwarded |
| PL-05 | A home pair that resolves here places the character and writes the location pair back, leaving the home pair alone | test_pl_05_a_home_on_this_shard_is_placed |
| PL-06 | A home room uuid that resolves to nothing here falls through to the default home | test_pl_06_an_unresolvable_home_room_falls_through |
| PL-07 | A default home on another shard rewrites the pair to it and raises `RoomOnAnotherShard` | test_pl_07_a_default_home_on_another_shard_is_forwarded |
| PL-08 | A default home on this shard places the character in the room its uuid names | test_pl_08_the_default_home_is_placed |
| PL-09 | Nothing resolving anywhere raises `PlacementFailed`, naming all three pairs | test_pl_09_nothing_resolvable_raises |
| PL-10 | A duplicate room uuid raises rather than falling through to the next row | test_pl_10_a_duplicate_uuid_is_not_routed_around |
| PL-11 | A superuser is placed at `DEFAULT_HOME` whatever their location pair says, and the cascade does not run | test_pl_11_a_superuser_goes_to_the_default_home |
| PL-12 | A superuser's location pair is left alone — nothing resolved, so there is nothing to record | test_pl_12_a_superusers_pair_is_left_alone |
| PL-13 | A `DEFAULT_HOME` that does not resolve falls back to object `#2` | test_pl_13_a_superuser_falls_back_to_object_two |
| PL-14 | Neither resolving raises `PlacementFailed` — the instance has no Limbo at all | test_pl_14_a_superuser_with_no_limbo_raises |

### RM — the room mixin

A character's location survives a transfer as a room uuid, and something has to carry the other end of
it. `ScalingRoomMixin` adds `scaling_room_uuid` to a room typeclass, and that is the whole of it.

**The uuid is assigned, never minted.** That is the point of the mixin rather than an omission from it.
A room minting its own identity would mint a fresh one every time the world was rebuilt, which is
exactly when the identity has to hold still — the dbrefs change on a rebuild and this is what survives
them. So it is the consumer's world source that supplies the value, and a room created without one has
none.

A game using `evennia-world-builder` already has the value: `entity_id`, author-supplied in YAML and
reproduced on every deploy. A game building its world another way assigns it however it likes. Either
way this library only reads it.

**Rooms are never archived**, so this mixin does not carry an archive one and the attribute is not
there to survive a round trip. It is an `AttributeProperty` because a typeclass cannot add a column.

**Nothing checks at boot that the room typeclass carries it**, though `BASE_ROOM_TYPECLASS` exists and
could be checked exactly as `SV` checks the other two. The difference is what a missing mixin costs. A
character typeclass without one produces characters that can never be archived, so the transfer breaks
outright, in front of a player, on a path that has already archived them somewhere else — worth refusing
to start over. A room typeclass without one transfers fine and every character lands in the destination's
`DEFAULT_HOME`. Degraded, not broken, and a room with no uuid is a normal room besides.

The cost of that choice is that the degradation is silent: nothing is logged, no transfer fails, and
every character appears in the same place. It is called out in
[installing.md](installing.md) § Rooms, which is where a consumer would be reading.

**The value is checked by the same `_RoomUuidProperty` the character's two halves use**, so `SH-14` to
`SH-17` cover the rule itself. `RM-03` covers only that this attribute is wired to it — repeating the
refusals here would test one class through two doors.

#### Finding a room by its uuid

`find_room_by_uuid(room_uuid)` is the other direction: a uuid in, the live room out. A module-level
function rather than a method, because the caller has a uuid and no room — the same reason
`is_instance_root` is one.

**It returns the room or `None`.** A uuid nothing carries is a normal case: the world was redeployed
without that room, or the character's last location was somewhere this instance does not have. A `None`
uuid returns `None` without querying, so a caller holding an unstamped character does not have to guard.

**Matching ignores case.** The value is stored as the consumer wrote it, so the room's and the
character's copies can differ in case while naming the same uuid — see the `SH` section on why neither
is canonicalised.

**Two rooms carrying the same uuid raise `DuplicateRoomUuid`.** There is no right answer to pick from,
and picking one silently means a character standing in a room that is not where the game thinks they
are. The exception names both dbrefs, because fixing it means editing the world source and the operator
needs to know which two entries collided.

Its own exception rather than `PlacementFailed`: this function is callable by a consumer for their own
reasons, and an exception about placement would say nothing about what went wrong. Translating it is the
arrival's job.

| ID | Case | Test function |
|---|---|---|
| RM-01 | `scaling_room_uuid` is stored as an Attribute under that key | test_rm_01_the_room_uuid_is_stored_as_an_attribute |
| RM-02 | A room created without one reads as `None` — the mixin never mints | test_rm_02_a_new_room_has_no_uuid |
| RM-03 | The attribute is the checked property, so a value that is not a uuid is refused | test_rm_03_refuses_a_value_that_is_not_a_uuid |
| RM-04 | `find_room_by_uuid` returns the live room carrying that uuid | test_rm_04_finds_the_room_carrying_the_uuid |
| RM-05 | A uuid no room carries returns `None` | test_rm_05_an_unknown_uuid_returns_none |
| RM-06 | A `None` uuid returns `None` without a query — an unrecorded location is normal | test_rm_06_no_uuid_returns_none |
| RM-07 | Matching ignores case, so a room whose uuid was written in uppercase is still found | test_rm_07_matching_ignores_case |
| RM-08 | Two rooms carrying the same uuid raise `DuplicateRoomUuid`, naming both | test_rm_08_a_duplicate_uuid_raises |

### SV — startup validation of the consumer's typeclasses

Nothing can transfer without a stable identity, and identity is minted at creation — so a character
typeclass missing the mixin produces characters that can never be archived, and the mistake cannot be
corrected after the fact. It surfaces at transfer time, in front of a player, on a path that has
already archived them somewhere else. The library refuses to start instead.

The check reads Evennia's `BASE_CHARACTER_TYPECLASS` and asks whether it carries
`ScalingCharacterMixin`. It tests for **the mixin, not for an `archive_id` attribute**. `evennia-archive`
takes identity minted any way, but this library needs a uuid4 that is unique across instances, and a
hand-rolled value satisfies the attribute while guaranteeing neither.

It joins the other clauses in `check_settings()`, so a deployment with a bad typeclass *and* a missing
setting is told both at once.

Two limits, both deliberate:

- **It stops every management command, `migrate` among them**, because `check_settings()` runs in
  `AppConfig.ready()` during `django.setup()`. There is no install-now-configure-later path when the
  misconfiguration otherwise surfaces as nothing happening.
- **It checks the configured default only.** A game creating characters of some other typeclass gets no
  warning. This is a boot-time smoke test, not a guarantee, and the message should not imply otherwise.

`SV-03` exists because that consumer did something reasonable: they followed `evennia-archive`'s install
guide and stopped. Telling them to add a mixin when they have added one is the least useful thing we
could say, so the message names ours as the replacement for theirs.

`SV-05` and `SV-06` are one `try` and a decision about when to speak. Listing both mixins with archive's
first cannot work — Python refuses a base that precedes its own subclass — and the interpreter's MRO
complaint says nothing about what to do. We can translate it, because our check is what imports the
module. But the same `except` sees every `TypeError` a consumer's module raises at import, so it
translates only when the message carries both the MRO phrase and our mixin's name.

**Anything else is let go rather than re-raised.** A traceback that reaches this library should mean
this library is the problem. A module that fails to import is not left in `sys.modules`, so the
consumer's next import re-executes and raises again at their own call site with their own traceback.
The trade, accepted knowingly: a character class we cannot import is one we cannot check, so a genuinely
unarchivable character behind an unrelated import error reaches first login rather than startup. That
needs their module to be broken *and* missing the mixin, and the broken module is the louder problem.

**Both configured typeclasses are checked**, through one function called twice, so the account's
messages and the character's cannot drift apart.

`BASE_GUEST_TYPECLASS` is deliberately not checked. A guest account carries nothing worth moving between
instances, and checking it would stop every game that offers guests from booting.

| ID | Case | Test function |
|---|---|---|
| SV-01 | A character typeclass carrying the mixin passes | test_sv_01_a_character_carrying_the_mixin_passes |
| SV-02 | One without it is refused, naming the setting, the class and the mixin to add | test_sv_02_a_character_without_the_mixin_is_refused |
| SV-03 | One carrying `ArchivableCharacterMixin` but not ours is refused, naming ours as the replacement | test_sv_03_only_the_archive_mixin_is_told_to_use_ours |
| SV-04 | One exposing an `archive_id` attribute without the mixin is refused | test_sv_04_a_hand_rolled_archive_id_is_refused |
| SV-05 | An MRO conflict naming our mixin is translated into an ordering message | test_sv_05_an_mro_conflict_becomes_an_ordering_message |
| SV-06 | An import failing any other way is left alone, not re-dressed as ours | test_sv_06_an_unrelated_import_error_is_left_alone |
| SV-07 | An account typeclass without the mixin is refused, naming the setting, the class and the mixin to add | test_sv_07_an_account_without_the_mixin_is_refused |
| SV-08 | One carrying `ArchivableAccountMixin` but not ours is refused, naming ours as the replacement | test_sv_08_an_account_with_only_the_archive_mixin |
| SV-09 | One exposing an `archive_id` attribute without the mixin is refused | test_sv_09_a_hand_rolled_account_archive_id_is_refused |
| SV-10 | An MRO conflict naming our account mixin is translated into an ordering message | test_sv_10_an_account_mro_conflict_becomes_an_ordering_message |
| SV-11 | `BASE_GUEST_TYPECLASS` is not checked | test_sv_11_the_guest_typeclass_is_not_checked |

### HO — handoff

`transfer_to_instance(account, session, character, to_instance)` moves a session and what it is playing
to another instance. Symmetric: going in character sends them to the character's shard, going out of
character sends them back to the router, and only the destination differs. A consumer moving a character
between shards calls the same function, so the path a game uses is the path the library uses.

Six steps: stamp where the character is going, archive what could have changed here, mint a ticket naming
the account and the character, send it over the bus, delete the character locally, hand the session to
`evennia-portal-multiplex`.

**Leaving stamps `current_shard` with the destination**, when the destination is a shard. Leaving is the
moment the shard is known, and the stamp before the archive is what carries it. For this library's own
in-character path it changes nothing — the destination *is* `ensure_location_for_transfer()`, which
returns `current_shard`. It does the work for a consumer moving a character between shards, who would
otherwise send a character to `shard1` carrying a `current_shard` of `shard0`, and have the arrival read
that as a session delivered to the wrong instance and send it back.

Guarded on the roster, because going out of character transfers to the router, and the router is never a
legal `current_shard` — a character is not in the router, it is out of character while its character
waits on a shard.

The room half is not stamped with it. Which room on the destination is not something leaving can know,
and a consumer who wants a particular one sets the pair before calling.

**Archive what could have changed where you are leaving.** An account can only change on the router and
a character can only change on a shard, so leaving the router archives the account and leaving a shard
archives the character. Across the three transitions: router to shard archives the account, shard to
router and shard to shard archive the character.

Archiving the other one would be worse than wasted. A shard's account is a working copy, and writing it
back over the authoritative one could only ever carry a change that should not have been possible.

This rests on a character being in the archive before it can be sent anywhere, which
`evennia-archive` guarantees: it stores an account and a character at the hook that mints their
identity, so leaving the router has nothing newer to write.

**Archived here** rather than when the session closes, because the destination rebuilds on arrival
while the departing instance is still tearing its session down.

**Account `#1` is refused outright.** It belongs to the instance it was made on and stays there —
never transferred, never archived, never restored, never deleted. Both of the library's own triggers
already step aside for it, so this refusal is for a consumer calling this directly, which the
shard-to-shard case invites. It says so rather than failing quietly, because a consumer who wrote that
call meant something by it.

**The instance root is `#1` and a superuser, and neither half names it alone.** `is_superuser` on its
own catches a second privileged account, which is exactly the one a game wants to be able to move
between instances — `HO-17` pins that. `pk == 1` on its own catches whatever happens to be first in a
database where Evennia's initial setup never ran, which is every test database. Together they name the
account that setup creates and requires. `is_instance_root` is the one place it is decided, and `AC-19`
covers it.

Every other case patches that predicate rather than faking a primary key. Faking one on the model class
breaks anything that then touches the database, and it would be asserting the predicate again in each
place instead of the guard that calls it.

**The character is deleted after the ticket is sent.** A failure at the handoff then leaves the
character out of this database but present in the archive, with a live ticket already waiting — so a
client reaching the destination still gets in.

**The account is not deleted here.** That waits for the session to actually close: deleting it out from
under a live session is not something to do hopefully.

**The delete is deferred by a reactor tick, and has to be.** `CmdIC` writes
`account.db._last_puppet = character` and logs against the character *after* `puppet_object` returns.
Deleting inline means Evennia then serialises a dead object and raises — found live in the old library,
not reasoned about, and its own `except RuntimeError` handler reads the character's name, so raising out
fails the same way. `delay(0, ...)` resolves to `reactor.callLater(0, ...)`, which cannot run until the
current call stack unwinds; commands run in the reactor thread, so the delete is *structurally* after
Evennia has finished with the character. A busy server delays it; nothing can reorder it.

**The outcome is handled here, not by the caller.** `send_session` returns a Deferred of
`(moved, outcome)`. Handling it here means the in-character and out-of-character paths — and a
consumer's own shard-to-shard move — all report the same way, from one table:

| Outcome | What happened | Logged | Player told |
|---|---|---|---|
| `MOVED` | it worked | no | no |
| `NOT_ATTACHED` | the destination is not attached to the Portal — that instance is down | ERROR | yes |
| `REJECTED` | the destination refused or failed to build; the session was put back | ERROR | yes |
| `STRANDED` | released, the build failed, and the rollback failed too | ERROR | no |
| `NO_SUCH_SESSION` | the Portal no longer holds that session, usually a player who dropped mid-move | WARNING | no |
| `ALREADY_THERE` | asked to move a session to where it already is | WARNING | no |

**Everything that is not `MOVED` is logged**, because every one of them means a player did not arrive
somewhere and the reason is worth having a record of.

**The player is told only when a message can reach them and means something.** A stranded session has no
instance to deliver to, and a session the Portal has dropped has nobody behind it. Telling them is not
a kindness that fails quietly — it is a message into nothing.

`ALREADY_THERE` is not a failure and needs no game text; the library would be inventing wording for a
situation only its caller can interpret. It is logged because on a router it should be unreachable —
the router is never in `SCALING_SHARDS`, so a character's `current_shard` is never here.

**An errback as well as a callback.** The outcomes above are answers; an errback is what arrives when the
move itself broke — a dropped AMP connection, a bug in the move. Without one it disappears into the
Deferred and surfaces at garbage-collection time, if at all. The player is told, because at that point
nothing is known about whether they can be reached and silence is the worse guess.

The Deferred is still returned, so a caller can chain onto it. Nothing has to.

| ID | Case | Test function |
|---|---|---|
| HO-01 | Leaving the router archives the account and not the character | test_ho_01_leaving_the_router_archives_the_account |
| HO-15 | Leaving a shard archives the character and not the account | test_ho_15_leaving_a_shard_archives_the_character |
| HO-16 | Account `#1` is refused: nothing archived, no ticket, no move, and they are told why | test_ho_16_account_one_is_refused |
| HO-17 | A superuser that is not `#1` transfers like any other account | test_ho_17_another_superuser_transfers |
| HO-02 | The ticket names both archive ids and the destination | test_ho_02_mints_a_ticket_naming_both_and_the_destination |
| HO-03 | The ticket is sent to the destination over the bus | test_ho_03_sends_the_ticket_over_the_bus |
| HO-04 | The character's deletion is deferred to the reactor, not done inline | test_ho_04_defers_the_character_delete |
| HO-05 | The session is handed off to the destination, carrying the ticket | test_ho_05_hands_the_session_off_carrying_the_ticket |
| HO-06 | The account is not deleted — that waits for the session to close | test_ho_06_does_not_delete_the_account |
| HO-07 | The outcome of the move comes back to the caller | test_ho_07_returns_the_outcome_of_the_move |
| HO-08 | A move that succeeds is not logged and says nothing to the player | test_ho_08_a_successful_move_is_quiet |
| HO-09 | A destination that is not attached is logged, and the player is told | test_ho_09_an_unattached_destination_is_logged_and_reported |
| HO-10 | A rejected move is logged, and the player is told | test_ho_10_a_rejected_move_is_logged_and_reported |
| HO-11 | A stranded session is logged, and the player is not told | test_ho_11_a_stranded_session_is_logged_and_not_reported |
| HO-12 | A session the Portal no longer holds is logged, and the player is not told | test_ho_12_a_missing_session_is_logged_and_not_reported |
| HO-13 | Moving to where the session already is is logged, and the player is not told | test_ho_13_already_there_is_logged_and_not_reported |
| HO-14 | An error the move did not turn into an outcome is logged, and the player is told | test_ho_14_an_error_is_logged_and_reported |
| HO-18 | Leaving for a shard stamps `current_shard` with it, before the character is archived | test_ho_18_leaving_stamps_the_destination_shard |
| HO-19 | Leaving for the router does not stamp — the router is never a legal `current_shard` | test_ho_19_leaving_for_the_router_stamps_nothing |

### IC — going in character

On a router, going in character means going somewhere else. `ScalingAccountMixin.puppet_object`
intercepts it: on a router it transfers the session to the character's shard and never puppets; on a
shard it defers to Evennia, which puppets normally.

**`puppet_object` rather than `CmdIC`**, because the command resolves the character and then calls this
— so Evennia's resolution stays Evennia's. `evennia-shards` overrides the command instead and
reimplements that resolution, which it has to: it needs `_last_puppet` written before the redirect,
since that is how its destination learns which character to puppet. Our ticket carries the character's
`archive_id`, so nothing needs writing first and the lower seam is available.

Returning without puppeting is a shape `puppet_object` already uses — Evennia does the same for no
permission, for a character puppeted elsewhere, and for too many puppets.

Of the checks Evennia runs before puppeting, most concern state a router never has: an existing puppet
on the session, a character already puppeted, a simultaneous-puppet limit. Two are kept. A missing
object or session still raises, and `obj.access(self, "puppet")` still applies — without it a builder
could send someone else's character to a shard.

**Superusers never move.** They belong to the instance they were made on: Evennia expects `#1` to be
there, and archiving one, deleting it and rebuilding it elsewhere takes an operator's way in with it.
They are an administration tool rather than a way to play, so every part of the transfer steps aside for
them — here, at the refresh on login, and wherever else the machinery would pick them up.

The destination comes from `ensure_location_for_transfer()` rather than from `current_shard` directly.
The destination is one half of the character's location pair, so the pair has to be complete before
there is anywhere to send them — see § SH.

Nothing here handles the outcome of the move. `transfer_to_instance` owns that, so the in-character
path, the out-of-character path and a consumer's own shard-to-shard move all report the same way.

| ID | Case | Test function |
|---|---|---|
| IC-01 | On a shard, `puppet_object` defers to Evennia and puppets normally | test_ic_01_a_shard_puppets_normally |
| IC-02 | On a router, the character is not puppeted | test_ic_02_a_router_does_not_puppet |
| IC-03 | On a router, the session, character and the completed destination are handed to the transfer | test_ic_03_a_router_hands_the_session_to_the_transfer |
| IC-04 | A character the account cannot puppet is refused, and nothing is transferred | test_ic_04_a_character_they_cannot_puppet_is_refused |
| IC-05 | A missing object or session raises `RuntimeError`, as Evennia's does | test_ic_05_a_missing_object_or_session_raises |
| IC-06 | Account `#1` puppets normally, even on a router | test_ic_06_account_one_puppets_normally |

### OC — going out of character

`ScalingAccountMixin.unpuppet_object` lets Evennia release the character normally, then archives the
character it released. **It archives and stops.**

**The character alone.** A character is only played on a shard, so a release is the moment its newest
state is worth storing. The account is not touched here for the same reason `transfer_to_instance`
leaves it alone: on a shard it is a working copy, and on a router nothing is ever puppeted for this to
be reached from.

It is not only reached from `ooc`. `at_disconnect` calls it on every dropped connection and
`unpuppet_all()` calls it at shutdown. Archiving is safe and useful on all three; deleting the character
is not — a five-second dropout would cost a player their position, and closing the browser mid-fight
would become the way out of it. So the delete and the transfer hang off the command that knows the
player asked for it.

The character reference is taken *before* `super()`, which clears `session.puppet`. Unpuppeting itself
destroys nothing: it removes the session from the object, clears the account link, fires the hooks and
drops the `puppeted` tag. The character stands where it was, which is what makes linkdead work.

**`session` is one session or a list of them.** Evennia's own body opens with `make_iter` for the same
reason: `unpuppet_all()` — called before every reset and shutdown — passes `self.sessions.all()`.
Reading `.puppet` off the parameter works on every runtime path and raises on every shutdown, with
nothing in any log, and it does so with nobody connected because an account with no sessions still
passes an empty list.

Archiving only what a live session is puppeting is also what makes this safe: a character left behind
unpuppeted is not archived, so a shutdown cannot overwrite a newer copy held by another instance.

**The breach log.** `puppet_object` never puppets on a router, so a character puppeted there means
something got past the interception — a bug worth tracking down. It is logged rather than handled,
because guessing at a recovery would hide it. It names the account and the character with their archive
ids, so the line says who to ask and what to look at.

Account `#1` is the exception, and not an accident: it *does* puppet on the router, so reporting it
would bury the real thing under routine noise. Any other account puppeting there is a breach, including
a superuser that is not `#1` — under this rule one travels like anyone else, so finding it puppeted on
the router means the same thing it means for anybody. The archive skip runs before the breach check, so
the ordering of those two is load-bearing and `OC-05` and `OC-08` between them pin it.

#### The command

`ScalingCmdOOC` replaces Evennia's `CmdOOC`. Going out of character is a *deliberate* departure, and the
command is the only place that knows it was deliberate — `unpuppet_object` is reached from
`at_disconnect` and from `unpuppet_all()` as well.

**The override is the shard's behaviour only.** On a router — and for account `#1` anywhere — the command
is Evennia's, unchanged: unpuppet and render the character-select menu, or say they are already out of
character. That is exactly right for the instance whose job is the out-of-character game, and it means
the one hardcoded string this command would otherwise carry is Evennia's to word.

It matters in a state that should not exist. `puppet_object` never puppets on a router, so a character
puppeted there is the breach `unpuppet_object` logs. If it happens anyway and they type `ooc`, falling
through unpuppets them **and tells them so** — where handling it ourselves would change their state and
show them nothing.

**On a shard, `super().func()` is never called.** Evennia's ends by rendering the character-select menu,
which is the one screen a shard must not show: a shard holds one character and no roster, so a menu
there offers a choice that does not exist. Nothing else in it is worth inheriting —
`account.get_puppet(session)` is the whole of what going out of character needs to resolve.

A consumer gating this — refusing to let someone leave mid-fight, say — subclasses and checks before
calling `super().func()`. A consumer with their own `rent` or `quit` calls `transfer_to_instance`
directly; there is no separate primitive, because leaving is the same six steps as arriving with a
different destination.

`OC-14` recovers a state no path here can produce: out of character on a shard with nothing puppeted.
They can neither go out of character nor in as a character they do not have. Sent home without a ticket
— a character-less ticket would mean changes across minting and reconstitution to improve an error path
— and they log in again.

That move reports its outcome like any other, through the same table `transfer_to_instance` uses. It has
no account or character to archive, so it is a bare session move; without the shared reporting it would
be the one move in the library that fails silently.

| ID | Case | Test function |
|---|---|---|
| OC-01 | The character is archived and the account is not | test_oc_01_archives_the_character_and_not_the_account |
| OC-02 | Nothing is deleted and nothing is transferred | test_oc_02_deletes_nothing_and_transfers_nothing |
| OC-03 | A session with nothing puppeted archives nothing | test_oc_03_a_session_with_no_puppet_archives_nothing |
| OC-04 | On a router, a puppeted character is logged as an invariant breach | test_oc_04_a_router_logs_a_puppeted_character_as_a_breach |
| OC-05 | Account `#1` is not archived on unpuppet | test_oc_05_account_one_is_not_archived |
| OC-06 | A list of sessions is handled, and every puppeted character is archived | test_oc_06_a_list_of_sessions_archives_every_character |
| OC-08 | Account `#1` unpuppeting on the router is not logged as a breach | test_oc_08_account_one_on_the_router_is_not_a_breach |
| OC-09 | On a shard, going out of character transfers the session to the router | test_oc_09_a_shard_transfers_the_session_to_the_router |
| OC-10 | On a shard, Evennia's `func` is not called, so no character-select menu is rendered | test_oc_10_a_shard_does_not_call_evennias_func |
| OC-11 | The character is read before the unpuppet, which releases it | test_oc_11_reads_the_character_before_the_unpuppet |
| OC-12 | On a router, nothing is transferred | test_oc_12_a_router_transfers_nothing |
| OC-13 | On a router, `ooc` is Evennia's ordinary behaviour | test_oc_13_a_router_is_evennias_ordinary_behaviour |
| OC-14 | On a shard, a session with nothing puppeted is sent to the router without a ticket, and logged | test_oc_14_a_shard_sends_a_stranded_session_home |
| OC-15 | `AppConfig.ready()` installs the command, so a consumer's own survives | test_oc_15_ready_installs_the_command |
| OC-16 | Account `#1` goes out of character where it stands, and is not transferred | test_oc_16_account_one_goes_ooc_where_it_stands |
| OC-17 | The stranded recovery reports its outcome, like any other move | test_oc_17_the_stranded_recovery_reports_its_outcome |

### LK — locking account changes to out of character

**An account has one authoritative copy and it lives on the router.** A shard rebuilds the account from
the archive so an arriving session has something to be, and that copy is a *working copy* — discarded
when the character leaves. So a command that changes account state a player would be upset to lose has
to be out of character only, or the change is written to the copy that gets thrown away and vanishes
with no error and nothing in any log.

That is what makes the router's copy authoritative, which in turn is what lets it stay put: an account
that cannot have changed elsewhere never has to be rebuilt, so its primary key is stable and anything
holding it — a website session, most obviously — keeps working.

**Seven of the nine are a lock rather than a code change.** `is_ooc()` is a lockfunc; Evennia passes
the session to a `cmd` access check, so a lockfunc can see whether anything is puppeted. Each command
is subclassed with nothing but its lockstring, and `ready()` points the module attribute at the
subclass — Evennia's own cmdsets read `account.CmdPassword` when a session's cmdset is built, so they
pick ours up without their source changing.

Each subclass carries its **whole** lockstring rather than an appended fragment, so it can be read
against what Evennia ships.

`channel` and `nick` are guards inside `func()` instead, because for both of them only part of the
command touches the account and the rest has to keep working in character.

**These are restrictions Evennia does not have.** `ic` while puppeted is a supported flow there — it
switches characters — and `quell` resets the puppet's lock cache precisely so it works in character. A
consumer who knows Evennia will notice.

**Nothing else is changed.** Permissions stay as Evennia set them: a consumer wanting `charcreate`
builder-only does that themselves.

| ID | Case | Test function |
|---|---|---|
| LK-01 | `is_ooc()` is true when the session has no puppet | test_lk_01_is_ooc_is_true_without_a_puppet |
| LK-02 | `is_ooc()` is false when the session is puppeting | test_lk_02_is_ooc_is_false_while_puppeting |
| LK-03 | `is_ooc()` is true when there is no session at all — a check outside a command is not a puppet | test_lk_03_is_ooc_is_true_without_a_session |
| LK-04 | Every overridden command carries the lockstring it is meant to | test_lk_04_each_override_carries_its_lockstring |
| LK-05 | Each override keeps everything else its parent had — only the lock differs | test_lk_05_an_override_changes_nothing_but_the_lock |
| LK-06 | `ready()` points each module attribute at the override, so Evennia's cmdsets pick it up | test_lk_06_ready_points_the_module_attributes_at_the_overrides |
| LK-07 | In character, each of the four account-writing channel switches is refused and told where to go | test_lk_07_channel_account_switches_are_refused_in_character |
| LK-08 | Out of character, those same switches reach Evennia's `func()` | test_lk_08_channel_account_switches_pass_out_of_character |
| LK-09 | Sending and the read-only switches are untouched in character, and no lock is added | test_lk_09_channel_sending_is_untouched_in_character |
| LK-10 | `at_server_init()` points `comms.CmdChannel` at the override | test_lk_10_at_server_init_installs_the_channel_override |
| LK-11 | `ready()` appends our module to `AT_SERVER_STARTSTOP_MODULE`, keeping the game's own | test_lk_11_ready_appends_our_startstop_module |
| LK-12 | A second `ready()` does not list the module twice | test_lk_12_the_startstop_module_is_listed_once |
| LK-13 | `nick/clearall` in character clears the character's nicks and leaves the account's | test_lk_13_clearall_in_character_leaves_the_account_alone |
| LK-14 | `nick/clearall` out of character clears the account's nicks | test_lk_14_clearall_out_of_character_clears_the_account |
| LK-15 | Every other switch is Evennia's — a nick set in character still lands on the character | test_lk_15_setting_a_nick_still_reaches_evennias_func |
| LK-16 | `ready()` points `general.CmdNick` at the override | test_lk_16_ready_points_nick_at_the_override |


`LK-05` is the one that catches a copied lockstring with a clause dropped. It asserts no *code* changed
— the parent's `func` and `parse` are still what run — rather than "defines only `locks`", because
Evennia's command metaclass adds `_keyaliases` and `help_category` to every subclass.

**The channel override is installed later in the boot than the other seven.**
`evennia.commands.default.comms` imports `evmenu`, which builds a class from Evennia's lazy `Command`
export — not populated until `evennia._init()` runs *after* `django.setup()`. So it cannot be imported
from `AppConfig.ready()`, which is why the class lives in `channel_command.py` rather than in
`commands.py`.

The seam is `at_server_init()`, the earliest hook Evennia calls on every module named in
`AT_SERVER_STARTSTOP_MODULE`. `ready()` appends our module to that setting, so no consumer has to
install anything. The setting is a list of *modules*, not a class to subclass — the game's own
`server/conf/at_server_startstop.py` stays in the list and its hooks still run.

**The channel restriction is four switches, not the command.** `sub` and `unsub` write the
subscription and `alias` and `unalias` write channel nicks, all onto the account. Everything else is
left alone: `mute`/`unmute` write to the channel rather than the account, the channel-management
switches are already staff-locked, `list`/`all`/`history`/`who` only read, and sending has no switch at
all. So a player in character sends and receives normally and is turned away only when changing what
they are subscribed to.

`CmdObjectChannel` is the character-caller variant and stays open — a character on a channel is not an
account change. Replacing `comms.CmdChannel` cannot reach it in any case: it resolved its base when its
class was created.

**`nick` is an override of one branch rather than a lock.** It writes to whatever the caller currently
*is*, so a nick set in character lands on the character and one set out of character lands on the
account, with no help from us. The `/account` switch is a nick *category*, not a target object.

The exception is `clearall`, which reaches through to `caller.account.nicks.clear()`. The override
writes that branch without the reach-through and hands every other switch to `super().func()` — so
`clearall` clears whatever the caller is and nothing else, which is both halves of the rule in the same
few lines. `general.py` imports nothing Evennia populates late, so this one is installed from `ready()`
with the account commands.

### MS — messages between instances

`SessionAuthorized` carries a ticket to the instance a session is about to arrive at, so the receiver
learns about a transfer independently of the session that then shows up. Past tense in the name because
it is true the moment the ticket is minted and stays true through every retry — a name claiming arrival
would be wrong on every attempt but the last.

**One type, one handler.** A router and a shard do the same thing with the message: store the ticket so
an arriving session can be checked against it. When the two roles need to diverge, the branch goes in
then — a branch whose arms are identical is a claim about the future rather than a behaviour.

**`payload_keys` is exactly what `create_ticket` returns.** Message-bus checks those keys before a send,
so a malformed ticket is refused where it was minted rather than arriving somewhere as a payload the far
end cannot use.

**The class registers itself on import.** Both ends need it — the sender to call `send`, the receiver to
find a handler for an arriving message — so the registration is an import side effect and the module has
to be imported somewhere that runs on every instance.

| ID | Case | Test function |
|---|---|---|
| MS-01 | The kind is `session_authorized` | test_ms_01_kind_is_session_authorized |
| MS-02 | `payload_keys` names exactly what `create_ticket` returns, so a malformed ticket is refused before it is sent | test_ms_02_payload_keys_match_a_ticket |
| MS-03 | Handling a message stores the ticket | test_ms_03_handling_stores_the_ticket |
| MS-04 | A handled message is consumed rather than left to be retried | test_ms_04_a_handled_message_is_consumed |
| MS-05 | The class registers itself on import, so a peer's message finds a handler | test_ms_05_registers_itself_on_import |

### SS — the Server session override

`load_sync_data` is where a session's synced data arrives on the Server, and it is where an arriving
session gets admitted or sent away. Installed by reading whatever `SERVER_SESSION_CLASS` the consumer
configured, subclassing it and repointing the setting — ours is the leaf, so our method runs and
`super()` runs theirs underneath.

**The ticket rides in multiplex's payload.** A moved session carries whatever the mover put in
`session.server_data[PAYLOAD_KEY]`, as JSON. This library puts the token there under
`SCALING_TICKET_KEY` and reads it back here. Multiplex neither reads it nor has an opinion about it.

**Only the token travels.** The ticket itself is already in this instance's table, put there by the bus
message. Sending the fields as well would be a second copy able to disagree with the first.

**A malformed payload is not an error.** `json.loads` raises on a corrupt string, and this runs on
every session that arrives carrying one — so a payload that cannot be read yields no token, exactly as
an absent one does, and the session is treated as untickered.

**The bus is drained before redeeming.** The sender commits the handoff row and only then asks for the
move, so the row is there — but the bus polls on an interval and the session arrives over a live AMP
link in milliseconds. Draining here reads a row already sitting there rather than waiting for a poll
the session is faster than. Only when a token arrived: an ordinary connection should not pay for a
database round trip.

**A session already authenticated is left alone.** It did not arrive by transfer, and admitting it
again would fire the login hooks twice.

**A shard that cannot admit a session sends it to the router.** A shard is where a character is played;
a session nothing has admitted has not been in character yet, and the out-of-character game is the
router's. On the router there is nothing to do: Evennia shows the login screen.

#### Admitting a redeemed ticket

`reconstitute_for_ticket(session, ticket)` rebuilds what the ticket names and hands back the account.
`None` means the session is not admitted, and the bounce above is what happens next — so every failure
here is one `return None` and no new branch.

It is three functions. `account_for_ticket` gets the account, `character_for_ticket` gets the
character, and `reconstitute_for_ticket` calls both and does what is left.

**Only a shard rebuilds the account.** `rebuild_from_archive` is delete-then-restore, and the delete is
the whole difference: on a shard the local copy is stale and has to go, on the router it is the
authoritative one and must not move. So the router calls `restore` directly, which hands back a live
account untouched.

An account the router does not already hold is restored anyway, and **logged as an error** — it should
have been there.

**Both roles restore the character the ticket names and add it to the account's roster.** It was deleted
on the instance it left, so the roster names something that is gone and the restored object has a new
primary key. No other character is touched: they were never deleted, and a character only changes on
the shard it is played on.

**Three failures, three `return None`.** An account the archive does not hold, a character it does not
hold, and a character that cannot be placed anywhere. Each is a session this instance will not admit, and
the caller's existing bounce is what happens next — so none of them adds a branch, and none of them
raises out through `load_sync_data` into AMP, where a player sees nothing at all.

**Two more rise past it, because the session override is the frame that can act on them.**
`RoomOnAnotherShard` needs the session moved, and `DuplicateRoomUuid` needs the player told. Neither is
a `return None`, because the caller's bounce to the router is wrong for the first and incomplete for the
second. `reconstitute_for_ticket` attaches the account to `RoomOnAnotherShard` as it passes — placement
knows the character and the destination, and this is the only frame that also knows the account.

**`_last_puppet` is the reference the archive drops.** `at_post_login` reads it to auto-puppet, and a
bare `ic` resolves through it. Without it Evennia says the character does not exist — which it does,
just not under the primary key the restored account remembers. This is the only place both objects are
in hand.

**A router does not set it, so a bare `ic` there does not work** — Evennia answers `Usage: ic
<character>` and `ic <name>` is how you go in character. That is the accepted behaviour rather than a
gap to close: naming the character is the right habit the moment an account has more than one, and a
bare `ic` that silently picks the wrong one is how a player loses track of which they are playing.

**`uid` and `logged_in` are set rather than calling `sessionhandler.login`.** Evennia's `portal_connect`
checks that pair a few lines after `load_sync_data` returns and logs the session in itself; calling it
here would fire every login hook twice. Setting `logged_in` also suppresses the login screen, which
`_run_cmd_login` only sends when it is false.

**Where a character ends up is `PL`'s business, not this section's.** The cases here assert that
`place_in_world` is called with the right character and that each of its three outcomes is handled: a
placement that worked, one that failed everywhere, and one that resolved somewhere this instance is not.

| ID | Case | Test function |
|---|---|---|
| SS-01 | The generated class subclasses whatever session class the consumer had configured | test_ss_01_subclasses_the_consumers_session_class |
| SS-02 | `ready()` stashes the consumer's class and repoints `SERVER_SESSION_CLASS` at ours | test_ss_02_ready_stashes_and_repoints_the_setting |
| SS-03 | `load_sync_data` calls the base, so Evennia's own sync and a consumer's override still run | test_ss_03_load_sync_data_calls_the_base |
| SS-04 | A session already carrying `logged_in` and `uid` is left alone | test_ss_04_an_authenticated_session_is_left_alone |
| SS-05 | The token is read from multiplex's payload | test_ss_05_reads_the_token_from_the_payload |
| SS-06 | A payload that is absent, unparseable, or carries no token yields none | test_ss_06_an_unreadable_payload_yields_no_token |
| SS-07 | A session carrying a token drains the bus before redeeming | test_ss_07_a_ticketed_session_drains_the_bus_first |
| SS-08 | A session carrying no token does not drain the bus | test_ss_08_an_unticketed_session_does_not_drain_the_bus |
| SS-09 | A shard sends a session it cannot admit to the router | test_ss_09_a_shard_sends_an_unadmitted_session_to_the_router |
| SS-10 | A router leaves a session it cannot admit alone | test_ss_10_a_router_leaves_an_unadmitted_session_alone |
| SS-11 | A redeemed ticket rebuilds the account and admits the session | test_ss_11_a_redeemed_ticket_admits_the_session |
| SS-12 | On a shard, the character the ticket names is rebuilt and handed to `place_in_world` | test_ss_12_a_shard_rebuilds_and_places_the_ticketed_character |
| SS-13 | On a router, no character is placed | test_ss_13_a_router_places_nobody |
| SS-14 | The rebuilt character becomes `_last_puppet`, so auto-puppet finds it | test_ss_14_the_character_becomes_last_puppet |
| SS-15 | An account the archive does not hold leaves the session unadmitted, logged | test_ss_15_an_unarchived_account_is_not_admitted |
| SS-16 | A character that cannot be placed leaves the session unadmitted, logged | test_ss_16_a_character_that_cannot_be_placed_is_not_admitted |
| SS-17 | On a shard, `account_for_ticket` rebuilds — a stale local copy is deleted first | test_ss_17_a_shard_rebuilds_the_ticketed_account |
| SS-18 | On a router, `account_for_ticket` returns the live account unchanged, deleting nothing | test_ss_18_a_router_keeps_its_live_account |
| SS-19 | On a router, an account that is not there is restored, and the absence is logged as an error | test_ss_19_a_router_logs_an_account_it_did_not_have |
| SS-20 | `character_for_ticket` restores the character the ticket names and adds it to the roster | test_ss_20_the_ticketed_character_joins_the_roster |
| SS-21 | On a router, the character the ticket names comes back and is on the account's roster | test_ss_21_a_router_brings_the_character_back |
| SS-22 | On a router, `_last_puppet` is not set — nothing is puppeted there | test_ss_22_a_router_sets_no_last_puppet |
| SS-23 | A character the archive does not hold leaves the session unadmitted, logged | test_ss_23_an_unarchived_character_is_not_admitted |
| SS-24 | A character that resolved to another shard is transferred there rather than admitted or sent to the router | test_ss_24_a_character_belonging_elsewhere_is_transferred |
| SS-25 | A duplicate room uuid tells the player to report it, leaves the session unadmitted, and logs it | test_ss_25_a_duplicate_room_uuid_is_reported_to_the_player |

### TK — tickets

A ticket is what lets a session arriving at an instance be recognised as the one a handoff announced.
The instances share no game database, so minting and storing happen in different places and the ticket
travels between them.

**It is what authenticates the arrival.** A session moved by `evennia-portal-multiplex` arrives with
`uid`, `logged_in` and `puid` cleared — deliberately, since those are primary keys belonging to the
instance it left. So the destination has a session and no idea who it is. Without a ticket the player
types their password again on every hop, which is the thing this library exists to avoid.

**A ticket names two identities, not one.** They do different jobs on arrival: the account is what the
session authenticates *as*, and the character is what it then puppets. A ticket naming only the
character leaves the receiving instance with nothing to log the session in as.

**Both are `archive_id` values, never primary keys.** The field names say so deliberately. Instances
have separate databases, so an `account.id` from the sending instance identifies an unrelated row on
the receiving one, and a name like `account_id` would invite exactly that mistake.

**Nothing is written when a ticket is minted.** The only stored copy lives on the receiving instance.
TK-04 pins that: if it ever starts failing, the library has grown a second source of truth for where a
transfer stands.

**A ticket is not pinned to an address.** Pinning one would make a stolen token useless elsewhere, but
the token never touches the client: it travels from one Server to the Portal and on to another Server,
over their AMP links. There is nothing to intercept. The address the Portal reports is also the same
for every instance, so the check would either always pass or refuse on something incidental.

**The table lives in the consumer's game database.** A library's tables go on an alias of its own when
its data has to outlive the game database or be read by more than one instance. A ticket is neither: it
is written and read by one instance seconds apart, and after a wipe there is no in-flight handoff whose
ticket still matters. An alias would cost a database, a router and a migration step a consumer has to
configure, to protect rows that are garbage almost immediately. TK-05 pins that, so it is not later
"fixed" into an alias by someone applying the alias rule without reading the reason.

It has to be in *a* database rather than in memory: the two ends of a handoff run in different
processes, and a database is what crosses that boundary.

| ID | Case | Test function |
|---|---|---|
| TK-01 | `create_ticket` returns a mapping carrying the token, both archive ids and the destination instance | test_tk_01_returns_the_ticket_as_data |
| TK-02 | Each call mints a different token | test_tk_02_each_call_mints_a_different_token |
| TK-03 | The token is a canonical lowercase hex string, so comparison is plain string equality | test_tk_03_token_is_canonical_lowercase_hex |
| TK-04 | The sending instance stores nothing — `create_ticket` writes no row to any database | test_tk_04_writes_no_row_on_the_sending_instance |
| TK-05 | The ticket table is in the game database, not on an alias of the library's own | test_tk_05_the_table_is_in_the_game_database |

#### Storing, on the receiving instance

`store_ticket` writes the row when the handoff message is handled. The ticket crosses in the shared bus
database and lives here in the local one — the bus is transport, not storage, and it deletes the
message as soon as the handler says it is done.

**The receiver stamps the expiry, from its own clock.** An absolute time travelling in the payload
would assume two instances agree on the hour, and skew would expire tickets early or late in a way
nobody would think to look for. The receiving instance applying its own lifetime removes the
assumption, and it is the instance bearing the cost of holding the row.

**Ten seconds is long enough.** The session is moved over a live AMP link and arrives immediately, so a
ticket is normally redeemed in the same breath as it is written. What the lifetime covers is the case
where nobody arrives — a player who drops mid-move — and the only cost of that is a row nobody sweeps
until the next one is stored.

**The sweep rides on traffic rather than a scheduler.** Cleanup happens after a write, so it is
proportional to what the instance is doing: a busy one sweeps constantly, a quiet one accumulates
nothing because nothing is arriving. The library owns no timer.

It sweeps *after* the write, not before. The new row is the one thing that must survive, and that order
means a sweep can never race it.

| ID | Case | Test function |
|---|---|---|
| TK-06 | `store_ticket` writes a row carrying every field of the ticket | test_tk_06_stores_every_field_of_the_ticket |
| TK-07 | The expiry is stamped from this instance's clock, not carried in the payload | test_tk_07_stamps_an_expiry_from_the_local_clock |
| TK-08 | Storing sweeps expired rows, so cleanup needs no scheduler | test_tk_08_storing_sweeps_expired_tickets |
| TK-09 | The sweep spares tickets that are still live, including the one just written | test_tk_09_the_sweep_spares_live_tickets |

#### Redeeming, on arrival

`redeem_ticket(token)` is the whole of the redemption side: one function rather than a lookup and a
delete, so no caller can forget to consume a ticket.

Not named `is_authorized` — it is not a question you may ask twice. Success deletes.

It returns the ticket's fields rather than a bool, because those are how the caller learns whose
account and character to rebuild.

**Consumed by character, not by token.** A character can only be in one place, so honouring one ticket
invalidates any sibling — otherwise a retried handoff leaves a second ticket able to pull that
character somewhere it has already left.

**The sweep runs before the lookup**, so what remains is live by construction and the query carries no
expiry predicate.

**Each refusal is logged with the check that failed.** From outside they are one `None`, and this is the
only place that knows which it was. An absent token is not a refusal and logs nothing — it is an
ordinary connection, and logging it would bury the real refusals.

| ID | Case | Test function |
|---|---|---|
| TK-10 | A live ticket addressed to this instance is redeemed, and returns its fields | test_tk_10_redeems_a_live_ticket_for_this_instance |
| TK-11 | An unknown token is refused | test_tk_11_refuses_an_unknown_token |
| TK-12 | A ticket addressed to another instance is refused, and left intact | test_tk_12_refuses_a_ticket_for_another_instance |
| TK-13 | An expired ticket is refused | test_tk_13_refuses_an_expired_ticket |
| TK-14 | Success consumes the ticket — a second redemption of the same token is refused | test_tk_14_a_redeemed_ticket_cannot_be_redeemed_again |
| TK-15 | Success also consumes any other ticket for the same character | test_tk_15_redeeming_consumes_siblings_for_the_same_character |
| TK-16 | Each refusal is logged with the check that failed | test_tk_16_a_refusal_is_logged_with_the_failed_check |
| TK-17 | No token returns `None` and logs nothing | test_tk_17_no_token_is_silent |
