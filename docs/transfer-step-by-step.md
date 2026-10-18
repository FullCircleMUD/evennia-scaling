# Transfer, step by step

Every step of moving a player between instances, and who owns each one. Three processes: leaving in
character, leaving out of character, and arriving — which both departures end in, so it is written
once.

Tags name the party: **[scaling]** this library, **[archive]** `evennia-archive`, **[bus]**
`evennia-message-bus`, **[multiplex]** `evennia-portal-multiplex`, **[Evennia]** Evennia itself.

Which of the two is archived on the way out follows from the state rule — an account changes only on
the router, a character only on the shard it is played on. See
[where-state-changes.md](where-state-changes.md).

## Going in character, router to shard

No gaps: this path is complete.

- **[Evennia]** the player types `ic <character>`; `CmdIC` resolves the character and calls
  `account.puppet_object(session, character)`
- **[scaling]** on a router, `puppet_object` does not puppet. It checks the object, the session and
  the puppet lock, then hands over
- **[scaling]** the character's location pair is completed, and the shard half of it is the destination
- **[scaling]** `transfer_to_instance` refuses account `#1` outright and stops here
- **[scaling]** the character's `current_shard` is stamped with the destination
- **[archive]** the account is archived — the router is where an account can have changed
- **[scaling]** a ticket is minted naming both archive ids and the destination; nothing is stored here
- **[bus]** `SessionAuthorized` carries the ticket to the destination, which stores it with an expiry
  stamped from its own clock
- **[scaling]** the local character is deleted, queued for the next reactor turn so Evennia has
  finished with the object first
- **[multiplex]** the session is handed to the destination Server behind the one Portal, carrying the
  token in its payload
- **[scaling]** the outcome comes back, and anything but a move is logged; the player is told where a
  message can still reach them

**Puppeting is where the redirect goes, not the command.** `CmdIC` resolves which character is meant
and then calls `puppet_object`, so overriding the method keeps Evennia's resolution and inherits
whatever a consumer's own `ic` does.

**The destination is half the character's location pair**, so the pair has to be complete before there
is anywhere to send them — which is why it is completed on the way out rather than on arrival.

**Deleting after the ticket is sent is deliberate.** A failure at the handoff leaves the character out
of this database but present in the archive with a live ticket waiting, so a client that reaches the
destination still gets in. The account is not deleted at all: that waits for the session to close,
because deleting an account out from under a live session disconnects it.

## Going out of character, shard to router

No gaps: this path is complete.

- **[Evennia]** the player types `ooc`; the cmdset resolves `CmdOOC`, which `ready()` has pointed at
  this library's override
- **[scaling]** on a shard, and for any account but `#1`, the override reads the character off the
  session before anything clears it — Evennia's own `func()` is never reached, because it ends by
  rendering a character menu a shard has no roster for
- **[scaling]** `unpuppet_object` collects what the session is puppeting, then calls up
- **[Evennia]** the parent releases the character: the session is detached, the account link cleared,
  the hooks fired and the `puppeted` tag dropped
- **[archive]** the character is archived, because a release is the moment its newest state is worth
  storing
- **[scaling]** `transfer_to_instance` is called with the router as the destination
- **[scaling]** `current_shard` is left as it is — the router is not a shard, and the character waits
  on the one it names
- **[archive]** the character is archived, because leaving a shard archives the character
- **[scaling]** a ticket is minted, and from here the steps are the departure's: bus, delete, handover,
  outcome

**Releasing and leaving are separate.** `unpuppet_object` archives and nothing else, because it is
reached from every dropped connection and from shutdown as well as from `ooc`. A five-second dropout
must not cost a player their position, so the delete and the transfer hang off the command that knows
the player asked for it.

**A shard with nothing puppeted is a breach**, not a case: no path allows going out of character there
without a character. It is logged as one and the session is sent to the router with no ticket, so the
player logs in again.

## Arriving, either way

No gaps: this path is complete.

- **[multiplex]** the session lands on the destination Server and its payload is synced onto it
- **[Evennia]** `load_sync_data` is called with everything `SESSION_SYNC_ATTRS` carries
- **[scaling]** the session override calls up first, so Evennia's sync and any consumer's override have
  both run before anything here reads the session
- **[scaling]** a session that is already authenticated returns immediately — it did not arrive by
  transfer, and admitting it again would fire the login hooks twice
- **[scaling]** the token is read out of multiplex's payload; absent, unreadable and carrying no token
  are one answer
- **[bus]** the inbox is drained on the spot, so the row written before the move is read now rather
  than at the next poll
- **[scaling]** the ticket is redeemed: expired rows are swept, the token looked up, the addressee
  checked, and every ticket naming that character deleted
- **[archive]** the account is rebuilt — a shard deletes its stale copy first, while the router
  restores, which hands back its live account untouched
- **[archive]** the character is restored and added back to the account's roster
- **[scaling]** on a shard, the character is placed: the room it recorded, then its home, then the
  deployment's default home. A superuser goes to Limbo instead
- **[scaling]** `_last_puppet` is set to the character, putting back the reference the archive dropped
- **[Evennia]** `portal_connect` sees `uid` and `logged_in` and logs the session in, and
  `AUTO_PUPPET_ON_LOGIN` turns `_last_puppet` into actually playing
- **[scaling]** a session nothing admits is sent to the router when this is a shard; on the router it
  is left to meet Evennia's login screen

**The session beats the bus, and it does not matter.** A session crosses a live AMP link in
milliseconds while a bus message goes through a database and a polling interval, so the arrival
routinely outruns the poll. Draining the inbox at this point reads a row that is already there — the
sender commits it before asking for the move. See
[interoperability.md](interoperability.md) for the bus relationship.

**The ticket is what authenticates the arrival.** Multiplex clears `uid`, `logged_in` and `puid` on the
way, deliberately, because those are primary keys belonging to the instance being left. Without a
ticket the player would retype their password on every hop.

**Two arrivals do not end here.** A character whose room resolves to another shard raises out to the
session override, which transfers it on — the placement cascade advances one row per hop, so it
terminates. A room uuid naming two rooms is a content bug the player is told about, because it is the
one failure here anybody can act on.

## Between shards

A consumer moving a character from one shard to another calls `transfer_to_instance` itself; there is
no separate primitive. The steps are the in-character list from `transfer_to_instance` onward, with the
character archived rather than the account, and the arrival is the same one.
