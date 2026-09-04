# Progress

Running log of milestones with links to evidence. Reverse chronological — newest first.

## 2026-09-04 — scaffold and ticket minting

Six tests, both linters clean. Nothing is usable yet.

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
