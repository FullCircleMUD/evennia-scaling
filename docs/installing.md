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

Nothing checks those across instances — no instance can see another's settings. They fail as a session
arriving where nobody intended.

**The arrangement that guarantees them** uses two literals in the whole deployment. Shared settings,
imported by every instance:

```python
MULTIPLEX_DEFAULT_INSTANCE = "router"           # the only shared literal
SCALING_ROUTER_ID = MULTIPLEX_DEFAULT_INSTANCE
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

## Settings this library reads

| Setting | Required | What it names |
|---|---|---|
| `SCALING_ROLE` | Yes, no default | `"router"` or `"shard"`. An instance that does not know which cannot behave correctly, so it refuses to start |
| `SCALING_ROUTER_ID` | Defaults to `"router"` | Which instance is the router |
| `SCALING_TICKET_LIFETIME_SECONDS` | Defaults to `10` | How long a stored ticket stays redeemable |

`SCALING_ROLE` is checked in `AppConfig.ready()`, so a missing one fails at boot naming the setting
rather than at whatever moment first needs it.

`[TBD — needs discussion: whether `SCALING_ROUTER_ID` should keep its default. Under the arrangement
above it is the root of the naming chain, and a default quietly supplies that root — a deployment that
forgot it gets `"router"` everywhere and looks like it works.]`

## Installing the libraries

None are on PyPI. Install the siblings editable first, then this library, or pip goes looking for names
that are not there:

```bash
pip install evennia
pip install -e ../evennia-portal-multiplex -e ../evennia-archive -e ../evennia-message-bus
pip install -e .
```

Then add them to every instance's `INSTALLED_APPS`.

`[TBD — needs writing: the archive and message-bus database aliases and routers, the multiplex Portal
and Server settings, and which launcher verb starts a shard. See
`evennia-portal-multiplex/docs/installing.md` for its half.]`
