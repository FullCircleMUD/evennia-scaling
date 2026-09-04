# evennia-scaling

Move a character between independent [Evennia](https://www.evennia.com/) instances, each running its
own database.

## Why

Running one Evennia process means one database, one world, and one machine's worth of everything. The
usual answer is to shard over a shared database, so every instance sees every row.

This is the other answer: instances that share nothing. Each has its own Evennia database, its own
world, its own `#1`. A character moving between them is archived where it leaves and rebuilt where it
arrives, and the archive key is the only identity that crosses.

The player notices none of it. Their connection never moves — that is
[evennia-portal-multiplex](../evennia-portal-multiplex)'s job, and this library asks it to hand the
session over.

## Status

**Early.** What exists is the scaffold and the ticket half — minting one, storing it on the instance a
session is arriving at, and sweeping the stale ones. Not usable yet. See
[docs/progress.md](docs/progress.md).

## Is this for me?

Not yet, unless you are working on it.

When it is finished, it is for an Evennia game that wants more than one instance and does not want them
sharing a database — because they are on different machines, in different regions, or simply because a
fault in one should not be a fault in all of them.

It has no opinion about *why* a character should move. Rooms, zones, what a character carries, what
makes a transfer legal at this moment: all yours.

## Install

Not published. Its three sibling libraries are not on PyPI either, so they install editable first:

```bash
git clone https://github.com/FullCircleMUD/evennia-scaling.git
cd evennia-scaling
python -m venv venv
# Activate the venv (platform-specific)
pip install evennia
pip install -e ../evennia-portal-multiplex -e ../evennia-archive -e ../evennia-message-bus
pip install -e .
python runtests.py
```

Order matters: siblings before the library, or pip goes looking on PyPI for names that are not there.

## Learn more

- **[docs/test-plan.md](docs/test-plan.md)** — every behaviour the library commits to, and the test
  covering it. Start here; it is where the design is decided.
- **[docs/INDEX.md](docs/INDEX.md)** — index of design documents.
- **[docs/interoperability.md](docs/interoperability.md)** — how this library sits alongside its
  siblings.
- **[CLAUDE.md](CLAUDE.md)** — load-bearing principles, for working in the repository itself.

## Licence

BSD 3-Clause. See [LICENSE](LICENSE).
