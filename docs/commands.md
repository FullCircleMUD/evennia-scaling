# Commands this library changes

The library replaces nine of Evennia's default commands. Seven can no longer be used while playing a
character, and two — `channel` and `nick` — keep working in character with the parts that write to the
account held back. This is what a consumer's players will notice, and the rule a consumer's own
commands should follow.

## The principle

**In character, only the character changes. Out of character, only the account changes.**

That separation is what lets a router and its shards run independently. The account is authoritative on
the router; a shard holds a working copy for as long as the character is there. A change made to an
account on a shard would be lost when the character leaves, so it must not be possible to make one.

## Restricted to out of character

Evennia's commands, unchanged except that they can no longer be used while playing a character:

- `password`
- `option`
- `style`
- `quell`
- `charcreate`
- `chardelete`
- `ic`

## `channel`

Four switches are restricted: `channel/sub`, `channel/unsub`, `channel/alias` and `channel/unalias`.
Used in character they say so and do nothing.

Those four mutate the account object — the subscription and the channel aliases are both stored there —
and account changes have to be made on the router. The rest of the command touches nothing on the
account.

So the rest is unchanged. Talking on a channel, reading one, listing them, muting one — all of it works
in character exactly as it always did.

## `nick`

Altered so nicks do not cross between the two. Used in character it affects the character's nicks only;
used out of character it affects the account's nicks only.

## Commands a consumer writes

Apply the same rule. A command that changes account state should not be usable in character, and one
that changes character or world state should not be usable out of character.

Creating and deleting characters is the exception — that is account-side work by nature.

Anything else that crosses the line is the consumer's to keep in sync between instances. This library
will not do it for them.
