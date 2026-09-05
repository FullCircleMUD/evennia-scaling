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
| `SS` | The Server session override — where an arriving session is admitted |
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

### SS — the Server session override

`load_sync_data` is where a session's synced data arrives on the Server, and it is where an arriving
session gets admitted or sent away. Installed by reading whatever `SERVER_SESSION_CLASS` the consumer
configured, subclassing it and repointing the setting — ours is the leaf, so our method runs and
`super()` runs theirs underneath.

**The ticket rides in multiplex's payload.** A moved session carries whatever the mover put in
`session.server_data[PAYLOAD_KEY]`, as JSON. This library puts the token there under
`SCALING_TICKET_KEY` and reads it back here. Multiplex neither reads it nor has an opinion about it.

**Only the token travels.** The ticket itself is already in this instance's table, put there by the bus
message. Sending the fields as well would be a second copy able to disagree with the first.

**A malformed payload is not an error.** `json.loads` raises on a corrupt string, and this runs on
every session that arrives carrying one — so a payload that cannot be read yields no token, exactly as
an absent one does, and the session is treated as untickered.

**The bus is drained before redeeming.** The sender commits the handoff row and only then asks for the
move, so the row is there — but the bus polls on an interval and the session arrives over a live AMP
link in milliseconds. Draining here reads a row already sitting there rather than waiting for a poll
the session is faster than. Only when a token arrived: an ordinary connection should not pay for a
database round trip.

**A session already authenticated is left alone.** It did not arrive by transfer, and admitting it
again would fire the login hooks twice.

**A shard that cannot admit a session sends it to the router.** A shard holds no accounts of its own,
so there is nowhere else for it to go. On the router there is nothing to do: Evennia shows the login
screen.

| ID | Case | Test function |
|---|---|---|
| SS-01 | The generated class subclasses whatever session class the consumer had configured | test_ss_01_subclasses_the_consumers_session_class |
| SS-02 | `ready()` stashes the consumer's class and repoints `SERVER_SESSION_CLASS` at ours | test_ss_02_ready_stashes_and_repoints_the_setting |
| SS-03 | `load_sync_data` calls the base, so Evennia's own sync and a consumer's override still run | test_ss_03_load_sync_data_calls_the_base |
| SS-04 | A session already carrying `logged_in` and `uid` is left alone | test_ss_04_an_authenticated_session_is_left_alone |
| SS-05 | The token is read from multiplex's payload | test_ss_05_reads_the_token_from_the_payload |
| SS-06 | A payload that is absent, unparseable, or carries no token yields none | test_ss_06_an_unreadable_payload_yields_no_token |
| SS-07 | A session carrying a token drains the bus before redeeming | test_ss_07_a_ticketed_session_drains_the_bus_first |
| SS-08 | A session carrying no token does not drain the bus | test_ss_08_an_unticketed_session_does_not_drain_the_bus |
| SS-09 | A shard sends a session it cannot admit to the router | test_ss_09_a_shard_sends_an_unadmitted_session_to_the_router |
| SS-10 | A router leaves a session it cannot admit alone | test_ss_10_a_router_leaves_an_unadmitted_session_alone |

`[TBD — needs building: what happens on a redeemed ticket. The session is admitted and the account and
character rebuilt from the archive, which is `handoff.py`, which does not exist yet.]`

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

#### Redeeming, on arrival

`redeem_ticket(token)` is the whole of the redemption side: one function rather than a lookup and a
delete, so no caller can forget to consume a ticket.

Not named `is_authorized` — it is not a question you may ask twice. Success deletes.

It returns the ticket's fields rather than a bool, because those are how the caller learns whose
account and character to rebuild.

**Consumed by character, not by token.** A character can only be in one place, so honouring one ticket
invalidates any sibling — otherwise a retried handoff leaves a second ticket able to pull that
character somewhere it has already left.

**The sweep runs before the lookup**, so what remains is live by construction and the query carries no
expiry predicate.

**Each refusal is logged with the check that failed.** From outside they are one `None`, and this is the
only place that knows which it was. An absent token is not a refusal and logs nothing — it is an
ordinary connection, and logging it would bury the real refusals.

| ID | Case | Test function |
|---|---|---|
| TK-10 | A live ticket addressed to this instance is redeemed, and returns its fields | test_tk_10_redeems_a_live_ticket_for_this_instance |
| TK-11 | An unknown token is refused | test_tk_11_refuses_an_unknown_token |
| TK-12 | A ticket addressed to another instance is refused, and left intact | test_tk_12_refuses_a_ticket_for_another_instance |
| TK-13 | An expired ticket is refused | test_tk_13_refuses_an_expired_ticket |
| TK-14 | Success consumes the ticket — a second redemption of the same token is refused | test_tk_14_a_redeemed_ticket_cannot_be_redeemed_again |
| TK-15 | Success also consumes any other ticket for the same character | test_tk_15_redeeming_consumes_siblings_for_the_same_character |
| TK-16 | Each refusal is logged with the check that failed | test_tk_16_a_refusal_is_logged_with_the_failed_check |
| TK-17 | No token returns `None` and logs nothing | test_tk_17_no_token_is_silent |
