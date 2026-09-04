# Progress

Running log of milestones with links to evidence. Reverse chronological — newest first.

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
