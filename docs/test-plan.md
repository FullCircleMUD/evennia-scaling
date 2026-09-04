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

| ID | Case | Test function |
|---|---|---|
| TK-01 | `create_ticket` returns a mapping carrying the token, both archive ids and the destination instance | test_tk_01_returns_the_ticket_as_data |
| TK-02 | Each call mints a different token | test_tk_02_each_call_mints_a_different_token |
| TK-03 | The token is a canonical lowercase hex string, so comparison is plain string equality | test_tk_03_token_is_canonical_lowercase_hex |
| TK-04 | The sending instance stores nothing — `create_ticket` writes no row to any database | test_tk_04_writes_no_row_on_the_sending_instance |
