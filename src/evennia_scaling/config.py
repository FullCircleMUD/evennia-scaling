# SPDX-License-Identifier: BSD-3-Clause
"""Settings this library reads, each behind an accessor.

Settings are read here and nowhere else, so a default lives in one place and
a consumer overriding one changes every reader at once.
"""

SETTING_TICKET_LIFETIME = "SCALING_TICKET_LIFETIME_SECONDS"

#: How long a stored ticket stays redeemable, in seconds. The session is moved
#: over a live AMP link and arrives immediately, so a ticket is normally
#: redeemed in the same breath as it is written. What this covers is the case
#: where nobody arrives — a player who drops mid-move — and the only cost of
#: that is a row nobody sweeps until the next one is stored.
DEFAULT_TICKET_LIFETIME = 10


def get_ticket_lifetime() -> int:
    """Return ``SCALING_TICKET_LIFETIME_SECONDS``, defaulting to 10."""
    from django.conf import settings

    return int(
        getattr(settings, SETTING_TICKET_LIFETIME, DEFAULT_TICKET_LIFETIME)
    )


SETTING_ROUTER_ID = "SCALING_ROUTER_ID"

def get_router_id():
    """Which instance manages the out-of-character game. Checked at boot.

    Where a player logs in, chooses a character and goes in character from —
    and the instance that runs the Portal. A shard sends a session back here
    whenever it cannot admit it, and cannot work out which of its peers that
    is: instances share no database and no settings, so nothing a shard can
    read names one.

    Not the same thing as multiplex's ``MULTIPLEX_DEFAULT_INSTANCE``, which
    is where an unbound session lands. That library knows nothing about
    roles; naming an instance there says where traffic goes, not which
    instance manages the out-of-character game.
    """
    from django.conf import settings

    return getattr(settings, SETTING_ROUTER_ID)


SETTING_SHARDS = "SCALING_SHARDS"


def get_shards():
    """Return every shard in the deployment. Checked at boot.

    **The roster is the deployment as intended, not as it is running.** A
    shard that is down is still a valid place for a character to be played.
    Which instances are attached right now is multiplex's registry, and is a
    different question.
    """
    from django.conf import settings

    return getattr(settings, SETTING_SHARDS)


SETTING_START_LOCATION_SHARD = "SCALING_START_LOCATION_SHARD"
SETTING_START_LOCATION_UUID = "SCALING_START_LOCATION_UUID"
SETTING_DEFAULT_HOME_SHARD = "SCALING_DEFAULT_HOME_SHARD"
SETTING_DEFAULT_HOME_UUID = "SCALING_DEFAULT_HOME_UUID"

#: The two world anchors, each a shard and a room. The first is where a new
#: character begins; the second is where any character can always be sent.
#: A game is free to point both at one room, or at two.
WORLD_ANCHORS = (
    (
        SETTING_START_LOCATION_SHARD,
        SETTING_START_LOCATION_UUID,
        "where a new character begins",
    ),
    (
        SETTING_DEFAULT_HOME_SHARD,
        SETTING_DEFAULT_HOME_UUID,
        "the one room a character can always be sent to",
    ),
)


def get_start_location_shard():
    """Return the shard a new character begins on. Checked at boot.

    Read whenever a character is created — it is what ``current_shard``
    defaults to, and `AttributeProperty` takes the function rather than a
    value so the read happens then rather than when `mixins` imports.
    """
    from django.conf import settings

    return getattr(settings, SETTING_START_LOCATION_SHARD)


def get_start_location_uuid():
    """Return the start location room's uuid. Checked at boot.

    The room half of the pair `get_start_location_shard` opens, and what a
    character's `current_room_uuid` defaults to.
    """
    from django.conf import settings

    return getattr(settings, SETTING_START_LOCATION_UUID)


def get_default_home_shard():
    """Return the shard the default home room is on. Checked at boot."""
    from django.conf import settings

    return getattr(settings, SETTING_DEFAULT_HOME_SHARD)


def get_default_home_uuid():
    """Return the default home room's uuid. Checked at boot.

    The room half of the pair `get_default_home_shard` opens, and the last
    resort in the placement cascade.
    """
    from django.conf import settings

    return getattr(settings, SETTING_DEFAULT_HOME_UUID)


SETTING_KEEP_LOCATION_IN_UNMARKED_ROOM = (
    "SCALING_KEEP_LOCATION_IN_UNMARKED_ROOM"
)

#: What a character's recorded location becomes when they walk into a room
#: carrying no uuid. Keeping the last recorded room is the default: a room
#: with no uuid is one the deployment cannot reproduce — deliberately
#: unmarked, or procedurally generated and gone — so there is nothing to
#: record, and sending someone home for losing their connection there
#: punishes them for it.
#:
#: It is also the default a consumer can most easily reverse. Clearing after
#: `super().at_post_move()` is a line; restoring a value already cleared
#: means reading it first.
DEFAULT_KEEP_LOCATION_IN_UNMARKED_ROOM = True


def get_keep_location_in_unmarked_room() -> bool:
    """Return ``SCALING_KEEP_LOCATION_IN_UNMARKED_ROOM``, defaulting to True."""
    from django.conf import settings

    return bool(
        getattr(
            settings,
            SETTING_KEEP_LOCATION_IN_UNMARKED_ROOM,
            DEFAULT_KEEP_LOCATION_IN_UNMARKED_ROOM,
        )
    )


SETTING_ROLE = "SCALING_ROLE"

#: A router is where players log in and choose a character; a shard is where a
#: character is played. There is no third role. `evennia-shards` carries a
#: dormant `monolith` mode so a game can be built on it and grow into a split
#: deployment later; the equivalent is out of scope here, because installing
#: this library means at least a router and one shard.
ROLE_ROUTER = "router"
ROLE_SHARD = "shard"
ROLES = (ROLE_ROUTER, ROLE_SHARD)


def get_role():
    """Return this instance's role. Checked at boot."""
    from django.conf import settings

    return getattr(settings, SETTING_ROLE)


SETTING_ACCOUNT_TYPECLASS = "BASE_ACCOUNT_TYPECLASS"
SETTING_CHARACTER_TYPECLASS = "BASE_CHARACTER_TYPECLASS"


def _check_typeclass(setting, ours, theirs, problems):
    """Refuse a typeclass that cannot carry an archive identity.

    Called once per configured typeclass, so the account's messages and the
    character's cannot drift apart.

    Identity is minted at creation and never reissued, so an object made
    without the mixin can never be archived — and that cannot be corrected
    afterwards. Left alone it surfaces at transfer time, in front of a
    player, on a path that has already archived them somewhere else.

    Tests for the mixin, not for an ``archive_id`` attribute. The archive
    takes identity minted any way; this library needs a uuid4 unique across
    instances, and a hand-rolled value satisfies the attribute while
    guaranteeing neither.

    Checks the configured defaults only. A game creating objects of some
    other typeclass gets no warning — a boot-time smoke test, not a
    guarantee. ``BASE_GUEST_TYPECLASS`` is deliberately absent: a guest
    account carries nothing worth moving between instances.
    """
    from django.conf import settings
    from evennia.utils.utils import class_from_module

    path = getattr(settings, setting, None)
    if not path:
        return

    try:
        typeclass = class_from_module(path)
    except TypeError as err:
        # Listing both mixins with archive's first cannot work — Python
        # refuses a base that precedes its own subclass — and the
        # interpreter's complaint says nothing about what to do. We can
        # translate it because this is what imports the module.
        #
        # Whitespace-normalised: CPython line-wraps the message, so the
        # phrase arrives as "method resolution\norder (MRO)".
        text = " ".join(str(err).split())
        if "method resolution order" in text and ours.__name__ in text:
            problems.append(
                f"{setting} is {path!r}, which lists {theirs.__name__} "
                f"before {ours.__name__}. Ours already carries archive's, "
                f"so list ours alone."
            )
        # Anything else is the consumer's own bug, and is let go rather than
        # re-raised: a traceback reaching this library should mean this
        # library is the problem. A module that failed to import is not left
        # in sys.modules, so their next import raises again at their own
        # call site with their own traceback.
        return

    if issubclass(typeclass, ours):
        return

    if issubclass(typeclass, theirs):
        # They followed evennia-archive's install guide and stopped. Telling
        # them to add a mixin when they have added one says nothing.
        problems.append(
            f"{setting} is {path!r}, which carries {theirs.__name__} but "
            f"not {ours.__name__}. Ours carries archive's, so replace it "
            f"rather than adding to it."
        )
        return

    problems.append(
        f"{setting} is {path!r}, which does not carry {ours.__name__}. An "
        f"object created without it has no archive identity, and identity "
        f"is minted at creation — so it cannot be given one later."
    )


def _check_typeclasses(problems):
    """Check both configured typeclasses against their mixins."""
    from evennia_archive.mixins import (
        ArchivableAccountMixin,
        ArchivableCharacterMixin,
    )

    # Imported here rather than at module scope: `mixins` reads this module,
    # so importing it at the top is a cycle.
    from .mixins import ScalingAccountMixin, ScalingCharacterMixin

    _check_typeclass(
        SETTING_ACCOUNT_TYPECLASS,
        ScalingAccountMixin,
        ArchivableAccountMixin,
        problems,
    )
    _check_typeclass(
        SETTING_CHARACTER_TYPECLASS,
        ScalingCharacterMixin,
        ArchivableCharacterMixin,
        problems,
    )


def check_settings():
    """Refuse to start unless every required setting is set and usable.

    Called once, from `AppConfig.ready()`. The settings below have no safe
    default — there is no value the library could pick that is correct — so
    an instance missing one does not start.

    Validating at first use instead would fire whenever that is: on a router
    it may be the first player to connect, so a misconfigured instance boots
    cleanly and fails somewhere that says nothing about the setting.

    Everything is checked before anything raises, so a deployment missing
    three settings hears about three rather than one per restart.

    See design/library-standards.md § Reading settings.
    """
    import uuid

    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    problems = []

    role = getattr(settings, SETTING_ROLE, None)
    if role not in ROLES:
        problems.append(
            f"{SETTING_ROLE} is {role!r}. Every instance running "
            f"evennia-scaling is either {ROLE_ROUTER!r} or {ROLE_SHARD!r}, "
            f"and there is no default — an instance that does not know which "
            f"it is cannot route a session or hold a character correctly."
        )

    # A string passes every other test — it is iterable, it has a length,
    # and membership against it silently succeeds one letter at a time.
    shards = getattr(settings, SETTING_SHARDS, None)
    if not shards or isinstance(shards, str):
        problems.append(
            f"{SETTING_SHARDS} is {shards!r}. It lists every shard in the "
            f"deployment, spelled exactly as each one's "
            f"MULTIPLEX_INSTANCE_ID, and a bare string is read one letter at "
            f"a time and matches nothing. Write a list or a tuple."
        )
        shards = ()

    # Guessing "router" is right only for a deployment that happens to use
    # that word, and wrong it is silent: sessions go to an instance nobody
    # runs and bus rows expire unread.
    router = getattr(settings, SETTING_ROUTER_ID, None)
    if not router:
        problems.append(
            f"{SETTING_ROUTER_ID} is not set. It names the instance that "
            f"manages the out-of-character game, and a shard cannot work one "
            f"out — instances see no database and no settings but their own."
        )
    elif router in shards:
        problems.append(
            f"{SETTING_ROUTER_ID} is {router!r}, which is also in "
            f"{SETTING_SHARDS}. The router manages the out-of-character "
            f"game; a character is played on a shard, so it is not one."
        )

    # Evennia's START_LOCATION and DEFAULT_HOME name two rooms; across
    # several instances each is on one shard, and these say which. Two
    # settings, because a game may put the two rooms on different shards.
    for setting in (SETTING_START_LOCATION_SHARD, SETTING_DEFAULT_HOME_SHARD):
        anchor = getattr(settings, setting, None)
        if not anchor:
            problems.append(
                f"{setting} is not set. It names the shard that room is on, "
                f"and has no default — this library cannot guess which of "
                f"your instances holds it."
            )
        elif anchor not in shards:
            problems.append(
                f"{setting} is {anchor!r}, which is not in {SETTING_SHARDS} "
                f"({tuple(shards)!r}). A room on an instance no deployment "
                f"runs is a room no character can reach."
            )

    # The room half of each anchor. Checked for shape rather than for
    # existence: the room is on one shard and every other instance boots
    # without it, so "does it name a room" can only be asked where the
    # answer means something. A mangled uuid otherwise satisfies every test
    # here and simply matches nothing.
    for _, setting, what in WORLD_ANCHORS:
        room_uuid = getattr(settings, setting, None)
        if not room_uuid:
            problems.append(
                f"{setting} is not set. It names {what}, and no uuid this "
                f"library invented would name anything."
            )
            continue
        try:
            uuid.UUID(str(room_uuid))
        except ValueError:
            problems.append(
                f"{setting} is {room_uuid!r}, which is not a uuid. It is "
                f"carried as a string and compared as one, so a value that "
                f"is not one matches no room at all."
            )

    # Not a setting of ours, but the same question: is this instance
    # configured to work at all? Collected with the rest so a deployment
    # missing a setting and a mixin is told both at once.
    _check_typeclasses(problems)

    if problems:
        raise ImproperlyConfigured(" ".join(problems))
