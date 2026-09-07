# Where state changes

An account changes only on the router. A character changes only on the shard it is being played on.
Everything else in this library follows from those two sentences, so they are worth stating on their
own.

## Why it has to be true

There is no shared database. A character travels by being archived where it leaves and rebuilt where it
arrives, and an account travels with it — the destination needs something to log the session in as.

That means two instances can hold a copy of the same account at once. One of them has to be the real
one, or a write on either side can be lost or can overwrite the other. So:

- The **router** holds the authoritative account. It never leaves, and it is never deleted or rebuilt
  there.
- A **shard** holds a working copy, discarded when the character leaves. Anything written to it goes
  with it.

The same argument runs the other way for characters. A character is only played on a shard, so a shard
holds the real one and the router holds a copy that only has to be good enough to show in a menu.

## What follows

**Leaving an instance archives what could have changed there.** Router to shard stores the account;
shard to router and shard to shard store the character. Storing the other one would write a copy that
cannot have changed over one that is authoritative.

**Arriving rebuilds only what is not already right.** A shard rebuilds the account, because its copy is
stale by definition. The router does not, because its copy is the real one — and rebuilding moves its
primary key, which anything outside the game holding that key is then naming a row that is gone.

**Logging in restores only what is absent.** An account that is here is returned untouched. Characters
missing from the roster are restored, because a character that never came home from a shard is only in
the archive.

**Where a character is travels as a uuid, not a dbref.** A primary key names a row in one database and
nothing in the next, and does not survive a world rebuild either. So a room carries a
`scaling_room_uuid` assigned by the game's world source, a character records the one it is standing in,
and the arriving instance resolves that back to a room of its own. The character's shard is stamped
beside it, because a room uuid means nothing without knowing which world it is in.

**Account-changing commands are out of character only.** Nine of Evennia's defaults change account
state. Seven are locked; `channel` and `nick` keep working in character with the parts that write to
the account held back. See [commands.md](commands.md).

**This instance's `#1` never moves.** Evennia requires one on every instance and makes it at first
boot, so it belongs where it was made — never transferred, never archived, never restored, never
deleted.

It is identified by both halves: `#1` **and** a superuser. `is_superuser` alone would catch a second
privileged account, which is exactly the one a game wants to be able to move between instances; `pk ==
1` alone would catch whatever is first in a database where initial setup never ran.

## The exception

**Creating a character happens out of character, on the router.** `charcreate` is account-side work by
nature, and the character it makes has never been played, so there is nothing on any shard to conflict
with it.

That leaves one thing this rule depends on: a new character has to reach the archive before it can be
sent anywhere, because leaving the router does not archive it. `evennia-archive` stores an account and
a character at the hook that mints their identity, so it is there from the moment it exists.

## What it does not cover

A character missing from the router looks the same whether it was stranded by an ungraceful exit or is
being played on a shard right now. The router cannot tell them apart on its own
[TBD — needs discussion: this needs the shard to say so].
