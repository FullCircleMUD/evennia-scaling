# Test plan

Every test case the library commits to covering, and the test function that covers it. The library is
built test-first: cases are agreed here, tests are written against them, then the implementation is
written to pass. The **Test function** column is the auditable trail — it is filled in as each test is
written, so an empty cell means the case is agreed but not yet covered.

Case IDs are stable and referenceable. Do not renumber; retire an ID rather than reuse it. Every test
function carries its case ID as its docstring, so the trail reads in both directions.

All test functions live in `src/evennia_scaling/tests.py`.

Behaviour is agreed here first, before any test or code — see
[test-first-process.md](../../../design/test-first-process.md).

| Prefix | Covers |
|---|---|
| `CF` | Settings, each behind an accessor |
| `MS` | Messages between instances |
| `SC` | The scaffold — the library is installed and the runner reaches it |
| `TK` | Tickets — what lets an arriving session be recognised |

## Fixtures

The fake objects the suite needs, named and purposed.

| Fixture | Purpose |
|---|---|
| — | None yet |

## Cases

One section per function or surface, each with its own prefix and its own table.

### SC — the scaffold

Not behaviour of the library, but a check that there is a library to test. These fail when the editable
install is missing, when the test settings do not name the app, or when the runner cannot find the test
module — each of which otherwise looks like "no tests ran".

| ID | Case | Test function |
|---|---|---|
| SC-01 | The package is importable and carries its version | test_sc_01_the_package_is_importable_and_versioned |
| SC-02 | A log call outside an Evennia engine is a silent no-op rather than an error | test_sc_02_the_log_shim_is_a_no_op_outside_evennia |

### CF — settings

Settings are read through an accessor in `config.py` and nowhere else, so a default lives in one place
and a consumer overriding one changes every reader at once.

**The defaults are commitments.** A consumer who sets nothing gets them, so a case pins each one — the
value can change, but not by accident and not without the plan saying so.

**A setting with no safe default is checked at boot.** `SCALING_ROLE` has none: an instance that does
not know whether it is a router or a shard cannot behave correctly in any direction, so refusing is the
honest answer and guessing hides the mistake until it costs more. `evennia-shards` can default to a
dormant `monolith` mode and do nothing; installing this library means at least a router and one shard,
so there is no equivalent to fall back on.

The accessor raising is not enough on its own. It raises when something first calls it, and on a router
that may be the first player to connect — so a misconfigured instance boots cleanly and fails somewhere
that says nothing about the setting. `AppConfig.ready()` calls the accessor so the failure happens at
startup, naming what to add.

**Two roles, and no third.** A router is where players log in and choose a character; a shard is where
a character is played.

`[TBD — needs review once the library does something with a role: nothing reads `get_role` today except
the boot check that demands it. If the transfer ends up not branching on role at all, the setting, its
constants and the check that refuses without it all go — a required setting nothing consults is a
consumer obligation for nothing.]`

| ID | Case | Test function |
|---|---|---|
| CF-01 | The ticket lifetime defaults to ten seconds when the setting is absent | test_cf_01_the_ticket_lifetime_defaults_to_ten_seconds |
| CF-02 | An undeclared `SCALING_ROLE` is refused, naming the setting | test_cf_02_an_undeclared_role_is_refused |
| CF-03 | A value that is neither role is refused, listing the two that are | test_cf_03_an_unknown_role_lists_the_valid_ones |
| CF-04 | `ready()` checks the required settings, so a misconfigured instance does not start | test_cf_04_ready_checks_the_required_settings |

### MS — messages between instances

`SessionAuthorized` carries a ticket to the instance a session is about to arrive at, so the receiver
learns about a transfer independently of the session that then shows up. Past tense in the name because
it is true the moment the ticket is minted and stays true through every retry — a name claiming arrival
would be wrong on every attempt but the last.

**One type, one handler.** A router and a shard do the same thing with the message: store the ticket so
an arriving session can be checked against it. When the two roles need to diverge, the branch goes in
then — a branch whose arms are identical is a claim about the future rather than a behaviour.

**`payload_keys` is exactly what `create_ticket` returns.** Message-bus checks those keys before a send,
so a malformed ticket is refused where it was minted rather than arriving somewhere as a payload the far
end cannot use.

**The class registers itself on import.** Both ends need it — the sender to call `send`, the receiver to
find a handler for an arriving message — so the registration is an import side effect and the module has
to be imported somewhere that runs on every instance.

| ID | Case | Test function |
|---|---|---|
| MS-01 | The kind is `session_authorized` | test_ms_01_kind_is_session_authorized |
| MS-02 | `payload_keys` names exactly what `create_ticket` returns, so a malformed ticket is refused before it is sent | test_ms_02_payload_keys_match_a_ticket |
| MS-03 | Handling a message stores the ticket | test_ms_03_handling_stores_the_ticket |
| MS-04 | A handled message is consumed rather than left to be retried | test_ms_04_a_handled_message_is_consumed |
| MS-05 | The class registers itself on import, so a peer's message finds a handler | test_ms_05_registers_itself_on_import |

### TK — tickets

A ticket is what lets a session arriving at an instance be recognised as the one a handoff announced.
The instances share no game database, so minting and storing happen in different places and the ticket
travels between them.

**It is what authenticates the arrival.** A session moved by `evennia-portal-multiplex` arrives with
`uid`, `logged_in` and `puid` cleared — deliberately, since those are primary keys belonging to the
instance it left. So the destination has a session and no idea who it is. Without a ticket the player
types their password again on every hop, which is the thing this library exists to avoid.

**A ticket names two identities, not one.** They do different jobs on arrival: the account is what the
session authenticates *as*, and the character is what it then puppets. A ticket naming only the
character leaves the receiving instance with nothing to log the session in as.

**Both are `archive_id` values, never primary keys.** The field names say so deliberately. Instances
have separate databases, so an `account.id` from the sending instance identifies an unrelated row on
the receiving one, and a name like `account_id` would invite exactly that mistake.

**Nothing is written when a ticket is minted.** The only stored copy lives on the receiving instance.
TK-04 pins that: if it ever starts failing, the library has grown a second source of truth for where a
transfer stands.

**A ticket is not pinned to an address.** Pinning one would make a stolen token useless elsewhere, but
the token never touches the client: it travels from one Server to the Portal and on to another Server,
over their AMP links. There is nothing to intercept. The address the Portal reports is also the same
for every instance, so the check would either always pass or refuse on something incidental.

**The table lives in the consumer's game database.** A library's tables go on an alias of its own when
its data has to outlive the game database or be read by more than one instance. A ticket is neither: it
is written and read by one instance seconds apart, and after a wipe there is no in-flight handoff whose
ticket still matters. An alias would cost a database, a router and a migration step a consumer has to
configure, to protect rows that are garbage almost immediately. TK-05 pins that, so it is not later
"fixed" into an alias by someone applying the alias rule without reading the reason.

It has to be in *a* database rather than in memory: the two ends of a handoff run in different
processes, and a database is what crosses that boundary.

| ID | Case | Test function |
|---|---|---|
| TK-01 | `create_ticket` returns a mapping carrying the token, both archive ids and the destination instance | test_tk_01_returns_the_ticket_as_data |
| TK-02 | Each call mints a different token | test_tk_02_each_call_mints_a_different_token |
| TK-03 | The token is a canonical lowercase hex string, so comparison is plain string equality | test_tk_03_token_is_canonical_lowercase_hex |
| TK-04 | The sending instance stores nothing — `create_ticket` writes no row to any database | test_tk_04_writes_no_row_on_the_sending_instance |
| TK-05 | The ticket table is in the game database, not on an alias of the library's own | test_tk_05_the_table_is_in_the_game_database |

#### Storing, on the receiving instance

`store_ticket` writes the row when the handoff message is handled. The ticket crosses in the shared bus
database and lives here in the local one — the bus is transport, not storage, and it deletes the
message as soon as the handler says it is done.

**The receiver stamps the expiry, from its own clock.** An absolute time travelling in the payload
would assume two instances agree on the hour, and skew would expire tickets early or late in a way
nobody would think to look for. The receiving instance applying its own lifetime removes the
assumption, and it is the instance bearing the cost of holding the row.

**Ten seconds is long enough.** The session is moved over a live AMP link and arrives immediately, so a
ticket is normally redeemed in the same breath as it is written. What the lifetime covers is the case
where nobody arrives — a player who drops mid-move — and the only cost of that is a row nobody sweeps
until the next one is stored.

**The sweep rides on traffic rather than a scheduler.** Cleanup happens after a write, so it is
proportional to what the instance is doing: a busy one sweeps constantly, a quiet one accumulates
nothing because nothing is arriving. The library owns no timer.

It sweeps *after* the write, not before. The new row is the one thing that must survive, and that order
means a sweep can never race it.

| ID | Case | Test function |
|---|---|---|
| TK-06 | `store_ticket` writes a row carrying every field of the ticket | test_tk_06_stores_every_field_of_the_ticket |
| TK-07 | The expiry is stamped from this instance's clock, not carried in the payload | test_tk_07_stamps_an_expiry_from_the_local_clock |
| TK-08 | Storing sweeps expired rows, so cleanup needs no scheduler | test_tk_08_storing_sweeps_expired_tickets |
| TK-09 | The sweep spares tickets that are still live, including the one just written | test_tk_09_the_sweep_spares_live_tickets |
