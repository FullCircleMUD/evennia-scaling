# Interoperability

This library against every `evennia-*` sibling library in `libraries/`. The `fcm-*` libraries are
deliberately absent: they are coupled to FullCircleMUD's game concepts and are not offered for outside
consumption, so a reader deciding what to co-install with this library cannot install them anyway.

Each section names the relationship — **hard dependency**, **optional integration**, or **no
coupling** — followed either by the constraints that apply or by an explicit clearance stating *why* it
is clear in terms of what this library does. "No known issues" is not a clearance.

## evennia-ai-memory

**No coupling.** What an NPC remembers is an NPC's business, and an NPC is not a thing this library
moves — only a player's character and its account travel between instances. An NPC stays in the world
its instance holds.

## evennia-archive

**Hard dependency.** A character does not travel between instances; it is archived where it leaves and
rebuilt where it arrives, and the archive is what holds it in between. The account is archived too,
because the arriving session has to authenticate as something.

An account is found in the archive by `find_by_column("accountdb", "username", ...)`. The username is
the only thing a player supplies at a login screen, and the column carries the schema's uniqueness — so
nothing has to be duplicated into an Attribute to make it findable.

The archive must be **shared storage**, reachable by every instance — a database all of them can see.
This is the one thing instances do share, and the whole approach rests on it: without it the archive
key minted on one instance names nothing on another.

## evennia-equipment

**No coupling, and one constraint that decides how a game recovers a character.**

**A transfer carries the character and nothing it is holding.** The archive stores the character's own
row, its Attributes and its tags. Carried objects are separate rows that point at the character through
`db_location`, which is one of the references the archive drops — so a character is rebuilt on the
destination with empty hands.

From the character's side those objects are gone. Evennia's own `delete()` calls `clear_contents()`
first, so the rows are not orphaned — they are moved to their home or the default home before the
character's row goes. But that is a room on the instance being left, which the character cannot reach
from where they are going.

**So a game needs a record of what a character owns that is not an Evennia object.** Objects are
per-instance; ownership has to outlive them. Something says what the character owns, and something puts
what is owned back into the slots it belongs in — two jobs, neither of them this library's. It moves a
character; a game weaves the rest.

**What does travel is this library's own state.** Wear slots and carrying capacity are
`AttributeProperty`, so they come through the round trip. A slot recording *which object* is worn holds
a reference to a row that does not exist on the destination, so what survives is the shape of the
character's equipment and not its contents — which is the same statement as above from the other side.

## evennia-llm-service

**No coupling.** It calls a model on behalf of whatever asks. This library moves characters and accounts
between instances and holds nothing a request would carry.

## evennia-message-bus

**Hard dependency.** Carries the handoff message between instances that share no game database, so the
receiving instance learns about a transfer independently of the session that is about to arrive.

**An instance is named once.** This library declares no id for the instance it is running on — it reads
the bus's. What it does declare is which *other* instances exist: `SCALING_ROUTER_ID` and
`SCALING_SHARDS`. Those have to match the ids the bus routes by, and nothing can check that across
instances, so the failure is a message addressed to a name nobody answers to.

**The session beats the bus, and it does not matter.** Multiplex delivers a session over a live AMP link
in milliseconds; a bus message goes through a database and a polling interval. So an arriving session
routinely gets there before the poll that would have told the destination to expect it.

The arrival path drains the inbox itself — `process_inbox()` before the ticket is checked — so the
message is read at the moment it is needed rather than at the next poll. The row is certain to be there
by then: the sender writes it synchronously and only then asks for the move, so it is committed before
the session leaves.

## evennia-mob-spawner

**No coupling.** Mobs belong to the world an instance holds and never travel; this library moves only a
player's character and its account. A spawner on each instance populates that instance, and neither
knows about the other.

## evennia-portal-multiplex

**Hard dependency.** Moves the player's session from one instance to another without the socket moving,
whatever protocol they are on. This library asks for the move and is told the outcome; it never touches
a socket, a protocol or a connection.

`handoff.py` is the only module here that touches it, through two calls: `transfer_to_instance` for a
move that carries a character, and `move_session` for one that carries nothing. Both report the outcome
the same way.

The ticket travels in multiplex's payload — a dict carried to the destination and stamped into the
session's `server_data`. Multiplex does not read it and has no opinion about what it means.

**A moved session arrives unauthenticated.** Multiplex clears `uid`, `logged_in` and `puid` on the way,
deliberately, because those are primary keys belonging to the instance being left. Everything this
library does on arrival follows from that.

## evennia-scaling

This library.

## evennia-shards

**Not co-installed.** Shards partitions one shared Postgres by `shard_id`, so every instance sees every
row and a character moves by changing a column. This library's instances share no game database at all.
The two are alternative answers to the same question, and installing both would mean two mechanisms
disagreeing about where a character is.

**The current direction is that this library replaces it.** Once scaling works, shards has no job — its
reason for existing is running one world across several processes, and this answers that without a
shared database. The intent is to withdraw shards from PyPI and make this the preferred approach.

That is the direction while this library keeps proving out, not a commitment.

## evennia-survival

**No coupling.** Hunger and thirst are `AttributeProperty` on the character, so they come through the
archive and a character arrives as hungry as it left. Nothing this library does touches them.

**The clocks are per-instance, and a character only ages where it is.** The two tickers are services on
the instance running them, so a character on `shard1` is aged by `shard1`'s clock. A character with no
instance holding it — sitting in the archive between a departure and an arrival, or on the router while
its player is out of character — is not ticked by anybody.

Whether that matters is the game's call, not this library's. A game that wants hunger to advance while a
player is logged out has that question already, because Evennia only ticks what is loaded; instances
change the answer's shape and not the question.

## evennia-targeting

**No coupling.** Resolving what a command means by "the guard" is a question about one room on one
instance, answered and finished within a single command. Nothing it works out is state a character
carries anywhere.

## evennia-world-builder

**No coupling, and the most useful thing to co-install.** This library needs every room a character can
be sent to carry a `scaling_room_uuid`, assigned by the game and reproduced whenever the world is
rebuilt — because that is the only thing about a room that survives both a rebuild and the crossing to
another instance's database.

World-builder already holds exactly that: an author-supplied `entity_id`, declared in YAML, stable
across redeploys by design. A game building its world with it has the values already and needs only to
put them where this library reads them.

**It is not a dependency, and the uuid is not its to supply.** Any world source can assign them — a
fixture script, a migration, a builder command. What this library requires is that the value is the same
after a rebuild as before it, and that is a property of how a game builds its world rather than of which
tool it uses.

## evennia-yaml-reader

**No coupling.** It reads YAML. Nothing this library does involves a file, and nothing it moves came
from one.
