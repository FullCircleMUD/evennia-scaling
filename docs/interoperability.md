# Interoperability

This library against every `evennia-*` sibling library in `libraries/`. The `fcm-*` libraries are
deliberately absent: they are coupled to FullCircleMUD's game concepts and are not offered for outside
consumption, so a reader deciding what to co-install with this library cannot install them anyway.

Each section names the relationship — **hard dependency**, **optional integration**, or **no
coupling** — followed either by the constraints that apply or by an explicit clearance stating *why* it
is clear in terms of what this library does. "No known issues" is not a clearance.

## evennia-ai-memory

`[TBD — needs discussion: not yet assessed.]`

## evennia-archive

**Hard dependency.** A character does not travel between instances; it is archived where it leaves and
rebuilt where it arrives, and the archive is what holds it in between. The account is archived too,
because the arriving session has to authenticate as something.

The archive must be **shared storage**, reachable by every instance — a database all of them can see.
This is the one thing instances do share, and the whole approach rests on it: without it the archive
key minted on one instance names nothing on another.

## evennia-llm-service

`[TBD — needs discussion: not yet assessed.]`

## evennia-message-bus

**Hard dependency.** Carries the handoff message between instances that share no game database, so the
receiving instance learns about a transfer independently of the session that is about to arrive.

**An instance is named once, by the bus.** This library declares no instance id of its own. A handoff
addresses a destination, and that name has to be one the bus can route to — two settings would
eventually disagree, and the failure is silent.

`[TBD — needs discussion: whether the bus message must arrive before the moved session does. Multiplex
delivers the session over a live AMP link in milliseconds, while a bus message goes through a database
and a polling interval, so the session can arrive at a destination that has not yet been told to expect
it.]`

## evennia-mob-spawner

`[TBD — needs discussion: not yet assessed.]`

## evennia-portal-multiplex

**Hard dependency.** Moves the player's session from one instance to another without the socket moving,
whatever protocol they are on. This library asks for the move and is told the outcome; it never touches
a socket, a protocol or a connection.

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

`[TBD — needs discussion: what this means for evennia-shards' future. This is described as an alternate
approach to try, not as a replacement, and no decision has been made.]`

## evennia-targeting

`[TBD — needs discussion: not yet assessed.]`

## evennia-world-builder

`[TBD — needs discussion: not yet assessed.]`

## evennia-yaml-reader

`[TBD — needs discussion: not yet assessed.]`
