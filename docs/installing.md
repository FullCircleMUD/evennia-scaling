# Installing

What a game has to configure to run several instances, each on its own database, with characters moving
between them.

Incomplete: the library is early, and this covers the settings that exist. It grows as it does.

## What a deployment looks like

One **router** and one or more **shards**. The router is where players log in and choose a character; a
shard is where a character is played. There is no third role.

Every instance runs its own Evennia database. Two things are shared: the **archive**, which holds a
character between instances, and the **message bus**, which carries the handoff. Both are databases
every instance can reach.

The player's connection never moves between instances —
[evennia-portal-multiplex](../../evennia-portal-multiplex) hands the session from one Server to another
behind a single Portal. That Portal belongs to the router.

## Naming instances

Three libraries need to know who an instance is, and they must agree.

**Required equalities**, whatever spelling you use:

- Every instance's `MULTIPLEX_INSTANCE_ID` and `MESSAGEBUS_INSTANCE_ID` are the same string — one
  instance, one name, whichever library is asking.
- Every instance's ids are distinct from every other's. Multiplex keys its registry by that name, so two
  instances sharing one means the second to attach replaces the first and takes its sessions.
- `MULTIPLEX_DEFAULT_INSTANCE` and `SCALING_ROUTER_ID` both name the router, and are the same on every
  instance.
- `SCALING_SHARDS` lists every shard's `MULTIPLEX_INSTANCE_ID`, spelled identically, and is the same on
  every instance.

Nothing checks those across instances — no instance can see another's settings. They fail as a session
arriving where nobody intended.

**The arrangement that guarantees them** uses two literals in the whole deployment. Shared settings,
imported by every instance:

```python
MULTIPLEX_DEFAULT_INSTANCE = "router"           # the only shared literal
SCALING_ROUTER_ID = MULTIPLEX_DEFAULT_INSTANCE

SCALING_SHARDS = ("shard0", "shard1")           # every shard, spelled exactly
```

The router's own settings:

```python
MULTIPLEX_INSTANCE_ID = MULTIPLEX_DEFAULT_INSTANCE   # it is the router
MESSAGEBUS_INSTANCE_ID = MULTIPLEX_INSTANCE_ID
```

Each shard's:

```python
MULTIPLEX_INSTANCE_ID = "shard0"                # the only per-instance literal
MESSAGEBUS_INSTANCE_ID = MULTIPLEX_INSTANCE_ID
```

Nothing is stated twice. The direction of those assignments is a settings-file convention and invisible
to the libraries — each reads only its own setting — so it buys no behaviour, only the absence of two
values that could drift apart.

**Why the router is named in shared settings and a shard is not.** A shard's name is private: only that
instance needs it. The router's is shared: every shard sends sessions back to it and none can work out
which peer it is, because instances see no database and no settings but their own. A fact common to the
deployment goes in the file every instance reads.

**`SCALING_SHARDS` is duplicated knowledge, and there is no way around it.** Every entry has to match
some instance's `MULTIPLEX_INSTANCE_ID` exactly, and nothing can check that for you — no instance can
read another's settings. A name here that no instance runs under, or an instance whose id is missing
here, passes every check at startup and surfaces later as a character assigned to a shard nothing
answers to. Comment it clearly and treat it as the list that has to be edited whenever a shard is
added or removed.

It cannot be assembled from the per-instance files instead. Each instance loads only its own, so there
is no point in the cascade where all of them have run.

**It is the deployment as intended, not as it is running.** A shard that is down is still a valid place
for a character to be played — it is a shard that needs bringing back up. Which instances are actually
attached right now is multiplex's registry, and is a different question this setting does not answer.

The router is not a shard and is not listed; it is named by `SCALING_ROUTER_ID`.

## Typeclasses

**The account and character typeclasses must carry this library's mixins**, or the instance refuses to
start:

```python
from evennia.accounts.accounts import DefaultAccount
from evennia.objects.objects import DefaultCharacter

from evennia_scaling.mixins import ScalingAccountMixin, ScalingCharacterMixin


class Account(ScalingAccountMixin, DefaultAccount):
    pass


class Character(ScalingCharacterMixin, DefaultCharacter):
    pass
```

Point `BASE_ACCOUNT_TYPECLASS` and `BASE_CHARACTER_TYPECLASS` at them as usual.

**These replace `evennia-archive`'s mixins — do not add both.** `ScalingAccountMixin` carries
`ArchivableAccountMixin` and `ScalingCharacterMixin` carries `ArchivableCharacterMixin`, so one mixin per
class gives you both. A game already using the archive's mixins swaps them for these rather than adding
to them.

Listing archive's mixin *first* cannot work at all — Python refuses a base class that precedes its own
subclass, and the module fails to import. The boot check translates that into a message saying which
line to change; unhandled, the interpreter's own MRO complaint says nothing about what to do.

**Why it is a refusal rather than a warning.** An archive identity is minted when an object is created
and never reissued, so a character made without the mixin can never be archived — and that cannot be
corrected afterwards. Left to run, it surfaces at transfer time, in front of a player, on a path that
has already archived them somewhere else.

The check reads the two configured typeclasses only. A game that creates characters of some other
typeclass gets no warning: it is a boot-time smoke test, not a guarantee. `BASE_GUEST_TYPECLASS` is
deliberately not checked — a guest account carries nothing worth moving between instances.

## Where the world's anchor rooms are

Evennia's `START_LOCATION` and `DEFAULT_HOME` name two rooms by primary key. Across several instances
a primary key names nothing: every instance has its own database, so room #5 exists on every shard and
is a different room on each. **These settings supply the missing half of the key.**

```python
SCALING_START_LOCATION_SHARD = "shard0"
SCALING_DEFAULT_HOME_SHARD = "shard0"
```

A room is addressed as a pair — the shard, then the room on it:

| Room | Which shard | Which room |
|---|---|---|
| Where a new character starts | `SCALING_START_LOCATION_SHARD` | `START_LOCATION` |
| Where a character falls back to | `SCALING_DEFAULT_HOME_SHARD` | `DEFAULT_HOME` |

The shard cannot be worked out at runtime. Asking over the bus which instance holds room #5 would get
several answers, all of them correct.

**The two rooms do different jobs.** `START_LOCATION` places a character once, at creation. From then
on it is the home room that matters, so a character whose location goes away falls back to
`DEFAULT_HOME`. That is why they are two settings and not one — and why a game is free to put them on
different shards.

Neither has a default and both must name a shard in `SCALING_SHARDS`. A guess would send every new
character to a real instance that simply is not the one intended, and nothing about that failure looks
like a misconfiguration.

`SCALING_START_LOCATION_SHARD` is also what a character's `current_shard` defaults to, so a character
created any way at all is somewhere without the game having to hook chargen. A game that offers a
choice of starting towns assigns `current_shard` during chargen instead.

## Settings this library reads

| Setting | Required | What it names |
|---|---|---|
| `SCALING_ROLE` | Yes, no default | `"router"` or `"shard"`. An instance that does not know which cannot behave correctly, so it refuses to start |
| `SCALING_ROUTER_ID` | Yes, no default | The instance that runs the portal and acts as the OOC area for the game. Must not be in `SCALING_SHARDS` |
| `SCALING_SHARDS` | Yes, no default | Every shard in the deployment, as a list or tuple of instance ids. A character's `current_shard` is validated against it |
| `SCALING_START_LOCATION_SHARD` | Yes, no default | Which shard holds `START_LOCATION`. Also what `current_shard` defaults to |
| `SCALING_DEFAULT_HOME_SHARD` | Yes, no default | Which shard holds `DEFAULT_HOME` |
| `SCALING_TICKET_LIFETIME_SECONDS` | Defaults to `10` | How long a stored ticket stays redeemable |

## Settings the sibling libraries need

`evennia-portal-multiplex`, `evennia-archive` and `evennia-message-bus` are hard dependencies, and each
reads its own settings. The library never reads them — it reads its own — but the values have to line
up, because they name the same instances.

| Setting | Library | Set it to |
|---|---|---|
| `MULTIPLEX_INSTANCE_ID` | multiplex | This instance's name. On a shard it must be one of `SCALING_SHARDS`; on the router it must be `SCALING_ROUTER_ID` |
| `MESSAGEBUS_INSTANCE_ID` | message-bus | The same string as `MULTIPLEX_INSTANCE_ID` — one instance, one name |
| `MULTIPLEX_DEFAULT_INSTANCE` | multiplex | Where an unbound session lands. Normally the router, so a player arriving fresh lands out of character |

**The recommended arrangement**, which is what the demo does. Shared settings, imported by every
instance:

```python
MULTIPLEX_DEFAULT_INSTANCE = "router"           # the only shared literal
SCALING_ROUTER_ID = MULTIPLEX_DEFAULT_INSTANCE
```

The router's own settings:

```python
MULTIPLEX_INSTANCE_ID = MULTIPLEX_DEFAULT_INSTANCE
MESSAGEBUS_INSTANCE_ID = MULTIPLEX_DEFAULT_INSTANCE
```

Each shard's:

```python
MULTIPLEX_INSTANCE_ID = "shard0"                # the only per-instance literal
MESSAGEBUS_INSTANCE_ID = MULTIPLEX_INSTANCE_ID
```

Each name is written once and everything else points at it. The direction of the assignments buys no
behaviour — each library reads only its own setting — just the absence of two values that can drift.

**`MULTIPLEX_DEFAULT_INSTANCE` is not `SCALING_ROUTER_ID` under another name.** Multiplex knows nothing
about roles; it says where traffic goes when nothing has said otherwise. Pointing one at the other is
the sensible arrangement, not a rule — a deployment could default to a shard, and the shard would send
the session back to the router.

## Identifying an account by something other than its username

By default an account is found in the archive by its username. It is the only thing a player supplies at
a login screen, and it is unique — Django enforces that on the column and the archive runs the same
schema.

A game that identifies accounts some other way — a wallet address, an external id — overrides **two**
classmethods on its account typeclass:

| Method | What to change |
|---|---|
| `find_in_archive(identifier)` | Which column or attribute finds the archived account |
| `refresh_from_archive(identifier)` | The local lookup for the superuser guard, which is `filter(username=identifier)` |

**Both, or neither.** Override only the first and the superuser guard stops protecting anything: it
looks the local account up by username, is handed something that is not one, matches nothing, and lets
the rebuild proceed. A superuser rebuilt from the archive takes an operator's way in with it, and
nothing about the failure looks like a failure.

## Installing the libraries

None are on PyPI. Install the siblings editable first, then this library, or pip goes looking for names
that are not there:

```bash
pip install evennia
pip install -e ../evennia-portal-multiplex -e ../evennia-archive -e ../evennia-message-bus
pip install -e .
```

Then add them to every instance's `INSTALLED_APPS`.

**Not written yet:** the archive and message-bus database aliases and routers, the multiplex Portal and
Server settings, and which launcher verb starts a shard. All of it works in `examples/` — read the
settings cascade there in the meantime, and see
[evennia-portal-multiplex](../../evennia-portal-multiplex/docs/installing.md) for its half. It is
written up here once the library's shape stops moving.
