# Installing

What a game has to configure to run several instances, each on its own database, with characters moving
between them.

The nine steps are the whole install path, and `examples/` is a working deployment of them. The
library is early, so the settings themselves will grow.

## What a deployment looks like

One **router** and one or more **shards**. The router is where players log in and choose a character; a
shard is where a character is played. There is no third role.

Every instance runs its own Evennia database. Two things are shared: the **archive**, which holds a
character between instances, and the **message bus**, which carries the handoff. Both are databases
every instance can reach.

The player's connection never moves between instances —
[evennia-portal-multiplex](../../evennia-portal-multiplex) hands the session from one Server to another
behind a single Portal. That Portal belongs to the router.

## 1. Install the libraries

None are on PyPI. Install the siblings editable first, then this library, or pip goes looking for names
that are not there:

```bash
pip install evennia
pip install -e ../evennia-logging-extension -e ../evennia-database-cascade
pip install -e ../evennia-portal-multiplex -e ../evennia-archive -e ../evennia-message-bus
pip install -e .
```

Deepest first. `evennia-logging-extension` and `evennia-database-cascade` are not named in this
library's `pyproject.toml` — nothing in `src/` imports either — but the archive and the bus depend on
them, so they have to be in the environment. Once these are published, pip resolves that chain itself.

## 2. Add the apps

Every instance's `INSTALLED_APPS`, `evennia_database_cascade` included — its `cascade_migrate` command
is only found through the app registry:

```python
INSTALLED_APPS = list(INSTALLED_APPS) + [
    "evennia_archive",
    "evennia_database_cascade",
    "evennia_message_bus",
    "evennia_portal_multiplex",
    "evennia_scaling",
]
```

**`evennia_portal_multiplex` must come before `evennia_scaling`, and the order is load-bearing.**
Django runs each app's `AppConfig.ready()` in the order this list gives, and multiplex refuses to start
an instance that has not declared `MULTIPLEX_INSTANCE_ID`. This library reads that name — at startup
for its own first log line, and on every transfer afterwards — without checking it, because by then
multiplex has. Listed the other way round, that read happens first and the instance refuses with
multiplex's message raised from this library, which says nothing about where to look.

Nothing detects the wrong order. Alphabetical ordering gives the right one, which is why it is easy to
get right and easy to break by hand.

## 3. Name the instances

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

## 4. Mix in the typeclasses

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

### Rooms

**The room typeclass is not checked at boot, and a room without the mixin costs a player their
location.** A character's location travels between instances as the room's uuid, so a room with no uuid
cannot be returned to — the character arrives at whichever room the destination instance has as its
`DEFAULT_HOME`.

That is silent. Nothing is logged, no transfer fails, and every character simply appears in the same
place: a symptom nobody traces back to a missing mixin. So it is the one thing here worth checking
yourself.

```python
from evennia.objects.objects import DefaultRoom

from evennia_scaling.mixins import ScalingRoomMixin

class Room(ScalingRoomMixin, DefaultRoom):
    pass
```

Point `BASE_ROOM_TYPECLASS` at it as usual.

**The uuid is assigned, never minted.** The mixin adds `scaling_room_uuid` and leaves it `None`; your
world source fills it in. A room that mints its own would mint a fresh one on every world rebuild, which
is the moment the identity has to hold still.

A game built with `evennia-world-builder` already has the value — each entity carries an author-supplied
`entity_id`, reproduced on every deploy. Any other world source supplies one however it likes; this
library only reads it.

Rooms a character can never be sent to do not need one. `None` is a valid state, and the boot is not
refused over it — unlike the account and character typeclasses, where a missing mixin means a transfer
cannot happen at all.

**Why it is a refusal rather than a warning.** An archive identity is minted when an object is created
and never reissued, so a character made without the mixin can never be archived — and that cannot be
corrected afterwards. Left to run, it surfaces at transfer time, in front of a player, on a path that
has already archived them somewhere else.

The check reads the two configured typeclasses only. A game that creates characters of some other
typeclass gets no warning: it is a boot-time smoke test, not a guarantee. `BASE_GUEST_TYPECLASS` is
deliberately not checked — a guest account carries nothing worth moving between instances.

## 5. Declare the world anchor rooms

Evennia's `START_LOCATION` and `DEFAULT_HOME` name two rooms by primary key. Across several instances
a primary key names nothing: every instance has its own database, so room #5 exists on every shard and
is a different room on each. **These settings supply the missing half of the key.**

```python
SCALING_START_LOCATION_SHARD = "shard0"
SCALING_START_LOCATION_UUID = "4d8f1a02-6b35-4e97-a0c4-8e2d7f5b3a16"
SCALING_DEFAULT_HOME_SHARD = "shard0"
SCALING_DEFAULT_HOME_UUID = "9c2f8b6d-4a71-4e35-b0c8-7d1e2a5f3049"
```

A room is addressed as a pair — the shard, then the room on it:

| Room | Which shard | Which room |
|---|---|---|
| Where a new character starts | `SCALING_START_LOCATION_SHARD` | `SCALING_START_LOCATION_UUID` |
| Where a character falls back to | `SCALING_DEFAULT_HOME_SHARD` | `SCALING_DEFAULT_HOME_UUID` |

The shard cannot be worked out at runtime. Asking over the bus which instance holds room #5 would get
several answers, all of them correct.

**Both rooms are named by uuid, not by Evennia's `START_LOCATION` and `DEFAULT_HOME`.** A dbref names
nothing after a world rebuild, and both of those exist on every instance — so resolving one locally puts
a character in whichever shard's Limbo they happened to be standing on. Out of the box that is `#2`, a
technical room for the contents of destroyed objects rather than anywhere a game wants a player to wake
up. Give each setting the `scaling_room_uuid` of a real room in your world; this library reads neither
Evennia setting, and Evennia goes on using them for its own purposes.

**The two rooms do different jobs.** The start location places a character once, at creation. From then
on it is their own home room that matters, and a character whose location goes away falls back to the
default home. Point both pairs at one room if you want them the same; point them at two if you want a
starting village and a temple to wake up in.

None of the four has a default. Each shard must be in `SCALING_SHARDS`, and each uuid must parse as one
— a guess would send every new character to a real instance that simply is not the one intended, and
nothing about that failure looks like a misconfiguration.

**The start pair is what a character's location defaults to.** `current_shard` reads
`SCALING_START_LOCATION_SHARD` and `current_room_uuid` reads `SCALING_START_LOCATION_UUID`, so a
character created any way at all is somewhere real without the game having to hook chargen. A game that
offers a choice of starting towns assigns the pair during chargen instead.

## 6. Wire the archive and message-bus databases

Neither alias is declared by hand. Both libraries ship a `db_spec`, and
[evennia-database-cascade](../../evennia-database-cascade) derives the `DATABASES` entry, the router
and the migration list from it:

```python
from evennia_database_cascade import configure

DATABASES, DATABASE_ROUTERS = configure(DATABASES, INSTALLED_APPS, GAME_DIR, os.environ)
```

With no `DATABASE_URL_ARCHIVE` or `DATABASE_URL_MESSAGEBUS` set, each lands on
`<GAME_DIR>/server/<alias>.db3`. Both must be **shared storage** every instance can reach — that is
what makes an archive key minted on one instance mean something on another. The demo does it with
symlinks; a real deployment points every instance's `DATABASE_URL_*` at one server.

Migrate with `evennia cascade_migrate`, which covers the game database and both aliases. A bare
`evennia migrate` covers only the game's.

### Where the configure() call goes

**In each instance's own settings file, after its import of any shared settings module — never inside
the shared module itself.** A settings cascade makes this load-bearing rather than stylistic.

`configure()` resolves each entry in `INSTALLED_APPS` to a package, and Evennia's own apps include
`evennia.utils.idmapper`. Resolving it imports `evennia.utils`, which imports Evennia's logger, whose
class body reads a setting the moment it is imported. That read re-enters Django's settings loading,
and Django answers by rebuilding the settings from the **top-level** module — the one named by
`DJANGO_SETTINGS_MODULE`.

If `configure()` runs from a shared module, that top-level module is still mid-import and its namespace
is empty, so the rebuild produces almost nothing and the boot dies on an `AttributeError` naming a
setting that is, in fact, set. Called from the top-level file after its imports have returned, the
namespace is fully populated and the same read succeeds.

Nothing is duplicated by this beyond the call itself: every input it takes is already per-instance.
`GAME_DIR` differs on each instance — and with it each alias's resolved path — so the same three lines
are correct everywhere. `examples/` does exactly this in `settings_router.py`, `settings_shard0.py` and
`settings_shard1.py`.

## 7. Give the router the Portal, and point the shards at it

One Portal, on the router. Every shard runs a Server that dials it, so the port is named once and used
by all of them:

```python
MULTIPLEX_AMP_PORT = 4006       # shared settings, so a mismatch is impossible
```

The router's own settings, which is the instance that listens:

```python
AMP_PORT = MULTIPLEX_AMP_PORT
TELNET_PORTS = [4000]
```

Each shard's, dialling that port rather than opening one:

```python
AMP_PORT = MULTIPLEX_AMP_PORT   # the router's Portal, not one of ours
TELNET_PORTS = [4020]           # never listened on — see below
```

**Give every shard distinct telnet and web ports even though it never listens on them.** Starting one
fully by accident then fails on something obvious rather than several instances quietly fighting over
port 4000.

Each instance needs its own directory: Evennia derives its database and logs from `GAME_DIR`, which is
the directory it was started from.

## 8. Declare the Server-only launcher verb, and start in order

`evennia start` brings up a Portal too, which collides on the AMP port, and `evennia istart` tells the
Portal to stop the Server it already has — which on a shared Portal is somebody else's instance.
Multiplex supplies a verb that starts a Server and speaks to no Portal at all. Declare it on every
instance:

```python
EXTRA_LAUNCHER_COMMANDS = {
    "server_start": "evennia_portal_multiplex.launcher.server_start",
}
```

Without the setting the verb does not resolve, and it fails silently — it falls through to Django and
is reported as an unknown command.

The router first, because `server_start` needs a live Portal at the address it dials:

```bash
evennia start --settings settings_router          # from the router's directory
evennia server_start --settings settings_shard0   # from each shard's
```

**`AMP_PORT` is the launcher's control channel as well as the Server's dial target**, so `stop`,
`reload` and `istart` run from a shard's directory all reach the *router's* Portal. `server_start` is
the only launcher verb safe to use from a shard.

Multiplex's own [installing.md](../../evennia-portal-multiplex/docs/installing.md) carries the full
detail of its half; the above is what a router-and-shards deployment needs from it.

## 9. Set auto-puppet per role

Evennia's `AUTO_PUPPET_ON_LOGIN` puppets a character as soon as an account logs in. The two roles need
opposite answers, and neither is Evennia's default behaviour for this deployment:

```python
# the router
AUTO_PUPPET_ON_LOGIN = False

# every shard
AUTO_PUPPET_ON_LOGIN = True
```

**Off on the router**, because going in character there is a *transfer*. Left on, an account with one
character is auto-puppeted the instant it logs in, which fires `puppet_object`, which sends the session
straight to a shard — so a player can never reach the character-select menu, and a player coming back
out of character bounces immediately back in.

**On for a shard**, because a session arrives already knowing which character it is playing. The
arrival sets the character as `_last_puppet` and logs the session in; auto-puppet is what turns that
into actually playing.

The library does not set either. They are Evennia's settings and a consumer's to own, and a game may
have its own reason for a different arrangement — but this is the one that matches how the transfer
works.

## Quick start — every setting in one place

**A summary of steps 1–9, not a source.** Where this and a step above disagree, the step is right: each
setting belongs to the library that reads it, and those libraries document their own — the links are in
the steps. This block exists so a deployment can be stood up in one pass rather than assembled from
nine sections.

**It is not actively maintained against the siblings.** A sibling that renames or adds a setting will
not update this block, and nothing checks it. If something here does not work, the steps above and the
owning library's `installing.md` are the current answer, and `examples/router/server/conf/` is the
executable one — the demo boots, so it cannot be quietly wrong the way prose can.

Three files, because that is the shape the settings take: what every instance shares, what the router
adds, and what each shard adds.

**Shared, imported by every instance:**

```python
INSTALLED_APPS = list(INSTALLED_APPS) + [          # multiplex before scaling
    "evennia_archive",
    "evennia_database_cascade",
    "evennia_message_bus",
    "evennia_portal_multiplex",
    "evennia_scaling",
]

MULTIPLEX_DEFAULT_INSTANCE = "router"              # the only shared literal
SCALING_ROUTER_ID = MULTIPLEX_DEFAULT_INSTANCE
SCALING_SHARDS = ("shard0", "shard1")              # every shard, spelled exactly

SCALING_START_LOCATION_SHARD = "shard0"            # where a new character begins
SCALING_START_LOCATION_UUID = "<uuid of that room>"
SCALING_DEFAULT_HOME_SHARD = "shard0"              # the always-available fallback
SCALING_DEFAULT_HOME_UUID = "<uuid of that room>"

MULTIPLEX_AMP_PORT = 4006                          # the router's Portal; shards dial it

EXTRA_LAUNCHER_COMMANDS = {                        # or `evennia server_start` fails silently
    "server_start": "evennia_portal_multiplex.launcher.server_start",
}

LOCK_FUNC_MODULES = list(LOCK_FUNC_MODULES) + [    # archive's owns_character()
    "evennia_archive.lockfuncs",
]

BASE_ACCOUNT_TYPECLASS = "typeclasses.accounts.Account"      # carrying ScalingAccountMixin
BASE_CHARACTER_TYPECLASS = "typeclasses.characters.Character"  # ScalingCharacterMixin
BASE_ROOM_TYPECLASS = "typeclasses.rooms.Room"               # ScalingRoomMixin — unchecked
```

**The router adds:**

```python
SCALING_ROLE = "router"
MULTIPLEX_INSTANCE_ID = MULTIPLEX_DEFAULT_INSTANCE
MESSAGEBUS_INSTANCE_ID = MULTIPLEX_INSTANCE_ID

AUTO_PUPPET_ON_LOGIN = False        # going in character here is a transfer
AMP_PORT = MULTIPLEX_AMP_PORT       # this instance listens
TELNET_PORTS = [4000]
```

**Each shard adds**, with its own name and its own ports:

```python
SCALING_ROLE = "shard"
MULTIPLEX_INSTANCE_ID = "shard0"    # the only per-instance literal
MESSAGEBUS_INSTANCE_ID = MULTIPLEX_INSTANCE_ID

AUTO_PUPPET_ON_LOGIN = True         # a session arrives already told who it is
AMP_PORT = MULTIPLEX_AMP_PORT       # dials the router, does not listen
TELNET_PORTS = [4020]               # never listened on; distinct so a mistake is obvious
```

**Then, last in each instance's own settings file**, after its import of the shared one:

```python
from evennia_database_cascade import configure

DATABASES, DATABASE_ROUTERS = configure(DATABASES, INSTALLED_APPS, GAME_DIR, os.environ)
```

Migrate with `evennia cascade_migrate`, then start the router before the shards:

```bash
evennia start --settings settings_router          # from the router's directory
evennia server_start --settings settings_shard0   # from each shard's
```

## What is not checked for you

`check_settings()` runs at boot and refuses an instance that cannot work — an unset role, a shard
roster that is empty or a bare string, a world anchor naming a shard that is not in the roster, a
typeclass missing its mixin. Everything below is outside what it can see.

- **`INSTALLED_APPS`.** A missing `evennia_scaling` means the AppConfig never loads, so nothing
  installs and nothing reports it — Evennia has no way to know the app was meant to be there. A missing
  `evennia_database_cascade` leaves `cascade_migrate` undefined. Nor is the **order** checked:
  `evennia_portal_multiplex` listed after this library makes a missing `MULTIPLEX_INSTANCE_ID` refuse
  the boot from here, with multiplex's message — see step 2.
- **Anything on another instance.** Instances share no settings and no game database, so nothing here
  can verify that `SCALING_SHARDS` names instances that exist, that their ids are spelled the same way,
  or that `SCALING_ROUTER_ID` names the instance actually running the Portal. A mismatch surfaces as a
  session arriving where nobody intended.
- **The room typeclass.** `BASE_ROOM_TYPECLASS` is not checked. A room without `ScalingRoomMixin`
  carries no uuid, and a character who leaves from one cannot be returned to it — silently, with every
  character appearing at `DEFAULT_HOME` instead. See step 4.
- **Whether a world anchor names a room that exists.** Each anchor room lives on one shard, and every
  other instance boots without it, so the question can only be asked where the answer means something.
- **That the shared databases are shared.** The archive and the bus must be reachable by every
  instance. An instance pointed at its own private copy starts cleanly and fails as a character who
  arrives nowhere.

## Settings this library reads

| Setting | Required | What it names |
|---|---|---|
| `SCALING_ROLE` | Yes, no default | `"router"` or `"shard"`. An instance that does not know which cannot behave correctly, so it refuses to start |
| `SCALING_ROUTER_ID` | Yes, no default | The instance that runs the portal and acts as the OOC area for the game. Must not be in `SCALING_SHARDS` |
| `SCALING_SHARDS` | Yes, no default | Every shard in the deployment, as a list or tuple of instance ids. A character's `current_shard` is validated against it |
| `SCALING_START_LOCATION_SHARD` | Yes, no default | Which shard a new character begins on. Also what `current_shard` defaults to |
| `SCALING_START_LOCATION_UUID` | Yes, no default | That room's `scaling_room_uuid`. Also what `current_room_uuid` defaults to. Checked at boot for being set and for parsing as a uuid |
| `SCALING_DEFAULT_HOME_SHARD` | Yes, no default | Which shard holds the default home room |
| `SCALING_DEFAULT_HOME_UUID` | Yes, no default | That room's `scaling_room_uuid`. Checked at boot for being set and for parsing as a uuid |
| `SCALING_TICKET_LIFETIME_SECONDS` | Defaults to `10` | How long a stored ticket stays redeemable |
| `SCALING_KEEP_LOCATION_IN_UNMARKED_ROOM` | Defaults to `True` | Whether walking into a room with no uuid keeps the last recorded room or clears it |

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
| `refresh_from_archive(identifier)` | The local lookup that guards this instance's `#1`, which is `filter(username=identifier)` |

**Both, or neither.** Override only the first and that guard stops protecting anything: it looks the
local account up by username, is handed something that is not one, matches nothing, and lets the
restore proceed. This instance's `#1` rebuilt from the archive takes an operator's way in with it, and
nothing about the failure looks like a failure.
