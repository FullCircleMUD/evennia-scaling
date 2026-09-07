# SPDX-License-Identifier: BSD-3-Clause
"""Typeclass mixins a consumer adds to their own classes.

See docs/test-plan.md § SH.
"""

from evennia.typeclasses.attributes import AttributeProperty
from evennia_archive.mixins import (
    ArchivableAccountMixin,
    ArchivableCharacterMixin,
)

from .config import (
    get_default_home_shard,
    get_shards,
    get_start_location_shard,
)
from .log import scaling_log

#: The Attribute key holding the other half of where a character is: which
#: room, in the world of the shard `current_shard` names. It holds the room's
#: `scaling_room_uuid`, not a dbref — a dbref names a row in one database and
#: means nothing in the next, so it survives neither a transfer nor a world
#: rebuild.
CURRENT_ROOM_UUID_KEY = "current_room_uuid"

#: The same pair again, for where a character lives rather than where it is.
#: `character.home` is a dbref and does not survive the archive, so a home
#: that means anything across instances has to be stored this way.
HOME_SHARD_KEY = "home_shard"
HOME_ROOM_UUID_KEY = "home_room_uuid"

#: The Attribute key holding a room's own identity — the value the two keys
#: above point at. Assigned from the consumer's world source, never minted.
ROOM_UUID_KEY = "scaling_room_uuid"

#: The Attribute key naming where a character is in the game world.
#: `AttributeProperty` takes its key from the attribute name, so this and the
#: property below have to agree.
CURRENT_SHARD_KEY = "current_shard"


class _ShardProperty(AttributeProperty):
    """Refuses anything that is not a shard in this deployment.

    Declared twice — for where a character is and for where it lives.
    "Is this a shard in this deployment" is not specific to either, and one
    class means one refusal to read and one place to change it.
    """

    def at_set(self, value, obj):
        """Validate on the way in. What this returns is what is stored.

        One rule: the value is in ``SCALING_SHARDS``. That keeps the router
        out too, since boot refuses a `SCALING_ROUTER_ID` that appears in the
        roster — so there is no second check and no second place for the two
        to disagree.

        Not a guarantee that the shard is running. The roster is the
        deployment as intended, and a shard that is down is still a real part
        of the world.

        ``None`` is refused like anything else: there is no un-set path, and
        the first read after one would write the default straight back.

        Returned unchanged. Tidying ``"Shard0 "`` into ``"shard0"`` would
        hide the typo rather than report it.

        A ``ValueError`` rather than ``ImproperlyConfigured``: the settings
        are fine, and a caller passed something that is not a shard.

        ``.db`` bypasses this entirely — Evennia's own documentation says so —
        so this guards one door of two.
        """
        shards = get_shards()
        if value not in shards:
            # Named for the attribute being set: `AttributeProperty` records
            # its own key, so the message says which one was wrong rather
            # than the one this class was first written for.
            raise ValueError(
                f"{self._key} cannot be {value!r}. It names a shard, and the "
                f"shards are {tuple(shards)!r}."
            )
        return value


class _RoomUuidProperty(AttributeProperty):
    """Refuses anything that is not a uuid string.

    Declared twice, for the same reason `_ShardProperty` is: "is this a
    uuid" is not specific to where a character is or where it lives.
    """

    def at_set(self, value, obj):
        """Check the shape. What this returns is what is stored.

        The meaning cannot be checked: which uuids exist is the consumer's
        world, and the room named is on another instance. What can be
        checked is that it is a uuid at all — a dbref or a room name here
        would surface as a character arriving in the wrong place.

        ``None`` is accepted, unlike a shard. Unset is a real state for a
        room key: it is what a character has before anything stamps one,
        and what the location cascade's last step leaves behind.

        **Stored as given.** `evennia-world-builder` holds the matching
        identity on the room — an author-supplied ``entity_id`` — and keeps
        the string as written, absorbing the variation at lookup. A uuid
        canonicalised here would stop matching a room whose ``entity_id``
        was written in uppercase.

        **A `uuid.UUID` object is refused**, though `uuid.UUID` would take
        one back happily. A uuid travels as a string between these
        libraries, and letting an object in means half the stored values
        compare unequal to every string beside them.
        """
        import uuid

        if value is None:
            return None

        if not isinstance(value, str):
            raise ValueError(
                f"{self._key} cannot be {value!r}. It names a room by its "
                f"uuid, as a string."
            )

        try:
            uuid.UUID(value)
        except ValueError:
            raise ValueError(
                f"{self._key} cannot be {value!r}. It names a room by its "
                f"uuid, and that is not one."
            ) from None

        return value


class ScalingCharacterMixin(ArchivableCharacterMixin):
    """Records where a character is in the game world.

    Mix into the character typeclass named by ``BASE_CHARACTER_TYPECLASS``::

        class Character(ScalingCharacterMixin, DefaultCharacter):
            pass

    It carries `ArchivableCharacterMixin`, so that is one mixin rather than
    two. Adding the archive one as well is unnecessary, and listing it
    *before* this class cannot work — Python refuses a base class that
    precedes its own subclass.
    """

    #: Named for CURRENT_SHARD_KEY: `AttributeProperty` takes its key from
    #: the attribute name, so the two have to agree.
    current_shard = _ShardProperty(
        # The function, not a value: settings are not loaded when this module
        # imports, and Evennia calls it at the first read.
        default=get_start_location_shard,
        strattr=True,
    )

    #: The other half of the pair: which room, in the world of the shard
    #: above. No default — a room key means nothing without a shard beside
    #: it, so there is nothing useful to fall back to at read time.
    #:
    #: Its shape is checked and its meaning is not: the room it names is on
    #: another instance, so the only question answerable here is whether it
    #: is a uuid.
    current_room_uuid = _RoomUuidProperty(default=None, strattr=True)

    #: Where the character lives, as the same pair. The shard defaults to
    #: the game's home shard; the room does not default, and its absence is
    #: what sends the cascade on to the default home.
    home_shard = _ShardProperty(
        default=get_default_home_shard, strattr=True
    )
    home_room_uuid = _RoomUuidProperty(default=None, strattr=True)

    def ensure_location_for_transfer(self):
        """Complete where this character would be sent, and return the shard.

        Named for the transfer rather than for the character's location,
        because it is not the same thing. `character.location` is the room
        object this character is standing in *now*, on the instance running
        it. This pair is what survives the archive, and the two drift apart
        the moment a character walks anywhere — until something restamps
        the pair.

        A character carries two pairs, and there is a third behind them:
        where they are, where they live, and the one safe place in the
        game. Either half of a pair being unusable makes the whole pair
        unusable, because **the destination is one half of it**. There is
        nowhere to send them until both halves agree, which is why this
        runs before a transfer rather than on arrival — and why the arrival
        can assume both are present.

        **Their own home is the second step, and the default home the
        third.** A game with a beginner shard and an advanced shard does
        not want a character with a broken location resolving to whatever
        room sits at the default on the advanced shard — they would arrive
        somewhere that kills them.

        What it resolved is written back to the location pair, and never to
        the home pair. The location is now true; falling back to the
        default home is a recovery, not a decision that this is where the
        character lives from now on.

        **The third step names a shard and no room.** The one safe place is
        this instance's ``DEFAULT_HOME``, a dbref belonging to whichever
        instance is asked, so writing it into a field that holds uuids
        would leave the arrival unable to tell which kind of value it is
        holding. Leaving the room half unset is also the truer claim: this
        knows the shard and does not know the room, and the arrival places
        them at its own default home.

        Returns the shard, so a call site reads as the destination it is.
        """
        shards = get_shards()

        def usable(shard, room):
            return shard in shards and room

        if usable(self.current_shard, self.current_room_uuid):
            return self.current_shard

        if usable(self.home_shard, self.home_room_uuid):
            self.current_shard = self.home_shard
            self.current_room_uuid = self.home_room_uuid
            return self.current_shard

        self.current_shard = get_default_home_shard()
        self.current_room_uuid = None
        return self.current_shard

    def at_post_move(self, source_location, move_type="move", **kwargs):
        """Keep the location pair true as the character walks.

        Evennia calls this after a move completes, and again at creation
        with no source location — so a character built in a room is stamped
        without a special case.

        **The only seam that fits.** `at_object_receive` is the room's hook,
        and rooms have no business writing to characters; overriding the
        `location` property would catch a bare assignment too, but that
        descriptor is Evennia's and replacing it is fragile. What this
        misses is exactly that bare assignment, which is what the arrival
        does — and there the uuid is already known, because it is what the
        room was resolved from.

        **`super()` first.** `DefaultCharacter` overrides this to make the
        character look at the room it arrived in, and that is the one thing
        a player notices the moment it stops happening.

        **Nothing is stamped on a router.** A character is never *in* the
        router, and the router's id is by definition not in
        ``SCALING_SHARDS`` — so stamping there would raise on the shard
        half, at character creation, which is a router operation.

        **The room is asked, not tested for the mixin.** A room that
        exposes a uuid has one, and where it came from is the consumer's
        business.

        **The shard half is never cleared.** `_ShardProperty` refuses
        ``None``, and there is nothing to clear anyway: a character standing
        in an unrecorded room is still on this shard. An incomplete pair is
        what the cascade already reads as unusable, so the room half alone
        carries the meaning.
        """
        super().at_post_move(source_location, move_type=move_type, **kwargs)

        # multiplex's accessor rather than a setting of ours: `check_settings`
        # already requires SCALING_SHARDS to be spelled exactly as each
        # instance's MULTIPLEX_INSTANCE_ID, so a second setting for the same
        # fact would only give the two somewhere to disagree.
        from evennia_portal_multiplex.config import get_instance_id

        from .config import (
            ROLE_SHARD,
            get_keep_location_in_unmarked_room,
            get_role,
        )

        if get_role() != ROLE_SHARD:
            return

        room_uuid = getattr(self.location, ROOM_UUID_KEY, None)
        if room_uuid is None and get_keep_location_in_unmarked_room():
            return

        self.current_room_uuid = room_uuid
        self.current_shard = get_instance_id()


class ScalingRoomMixin:
    """Gives a room an identity that survives a world rebuild.

    Mix into a room typeclass::

        class Room(ScalingRoomMixin, DefaultRoom):
            pass

    A character's location travels as a room uuid, and this is the other
    end of it. Only rooms a character can be sent to need one.

    **The uuid is assigned, never minted.** A room minting its own would
    mint a fresh one every time the world was rebuilt, which is exactly
    when the identity has to hold still — the dbrefs change on a rebuild
    and this is what survives them. The consumer's world source supplies
    the value; a game using `evennia-world-builder` already has it as the
    room's ``entity_id``.

    No archive mixin, unlike the character and account ones. Rooms are
    built from the consumer's world source and never archived.
    """

    #: Checked by the same property the character's two location halves
    #: use, so there is one answer to "is this a uuid" in the library.
    scaling_room_uuid = _RoomUuidProperty(default=None, strattr=True)


class DuplicateRoomUuid(Exception):
    """Raised when two rooms claim the same uuid.

    A mistake in the consumer's world source rather than a state this
    library can be in. Nothing here can choose between them, and choosing
    silently would stand a character in a room that is not where the game
    believes they are.
    """


def find_room_by_uuid(room_uuid):
    """Return the live room carrying this uuid, or ``None``.

    The other direction from `ScalingRoomMixin`: a uuid in, a room out.
    Module-level rather than a method, because the caller has a uuid and no
    room.

    **``None`` is a normal answer.** The world may have been redeployed
    without that room, or the uuid may name a room on another instance. A
    falsy uuid returns ``None`` without a query, so a caller holding an
    unstamped character does not have to guard.

    **Matching ignores case.** Neither copy is canonicalised — the room's
    value is the consumer's string as written and the character's is
    whatever was stamped from it — so the two can differ in case while
    naming one uuid.

    Raises `DuplicateRoomUuid` when more than one room carries it, naming
    both, because fixing it means finding the two colliding entries in the
    world source.
    """
    if not room_uuid:
        return None

    from evennia.objects.models import ObjectDB

    found = list(
        ObjectDB.objects.filter(
            db_attributes__db_key=ROOM_UUID_KEY,
            db_attributes__db_strvalue__iexact=str(room_uuid),
        ).values_list("id", flat=True)
    )

    if not found:
        return None

    if len(found) > 1:
        dbrefs = ", ".join(f"#{pk}" for pk in found)
        raise DuplicateRoomUuid(
            f"{room_uuid!r} is carried by more than one object ({dbrefs}). "
            f"A room uuid names one room, and nothing here can choose "
            f"between them."
        )

    # Fetched by primary key so the handle is the live typeclass instance,
    # with its attributes and handlers, rather than a bare row.
    return ObjectDB.objects.get(pk=found[0])


def is_instance_root(account):
    """Whether this is the account Evennia requires the instance to have.

    The one its initial setup creates at first boot and expects to find
    thereafter. Restoring a copy anywhere would displace the local one, so
    it never travels, is never archived, and is never rebuilt.

    **Both halves, because neither names it alone.** ``is_superuser`` on
    its own catches a second privileged account, which is exactly the one
    a game wants to be able to move between instances. ``pk == 1`` on its
    own catches whatever happens to be first in a database where initial
    setup never ran — a test database, for one.
    """
    return account.pk == 1 and account.is_superuser


class ScalingAccountMixin(ArchivableAccountMixin):
    """Finds an account in the archive.

    Mix into the account typeclass named by ``BASE_ACCOUNT_TYPECLASS``::

        class Account(ScalingAccountMixin, DefaultAccount):
            pass

    It carries `ArchivableAccountMixin`, so that is one mixin rather than
    two. Listing archive's *before* this class cannot work — Python refuses
    a base class that precedes its own subclass.
    """

    @classmethod
    def find_in_archive(cls, identifier):
        """The archive id of the account this identifier names, or ``None``.

        The seam a consumer overrides to identify an account by something
        other than its username — a wallet address, say. One argument, named
        for what it is rather than for what we do with it, and the library
        calls it positionally, so renaming it in an override is safe.

        Not ``find_in_archive(column, value)``: that generic form is
        `evennia_archive.find_by_column`, and a passthrough would add
        nothing. The point of this method is to be the one place that
        decides which key identifies an account.

        The username is what a player supplies at a login screen, and it is
        unique — Django enforces that on the column, and the archive runs
        the same schema.

        **Reaches `find_by_column`, so wrap the caller in `deferToThread`.**
        The archive may not be local and the column is not indexed.
        """
        from evennia_archive.api import find_by_column

        found = find_by_column("accountdb", "username", identifier)
        return found[0] if found else None

    @classmethod
    def rebuild_from_archive(cls, archive_id):
        """Delete whatever is live under this identity, then restore it.

        `restore` is idempotent — given an identity that is already live it
        hands back the existing object rather than rebuilding it — so
        restoring over a stale copy does nothing at all. The delete is the
        mechanism, not tidiness.

        That is what makes correctness a property of arriving rather than of
        leaving. Whatever this instance still holds from a previous visit is
        thrown away and rebuilt before anyone gets in, which is why none of
        the ways of leaving an instance is handled.

        **The account's local characters go with it.** Evennia's `delete`
        nulls ``db_account`` rather than cascading, and clears the account's
        attributes with the roster among them — so they would survive as
        orphans nothing references, and a later `restore` would hand one
        back unchanged.

        Safe because the archive is authoritative for a character: the
        library archives at the end of chargen and again whenever a
        character leaves a shard, and nothing on the router changes a
        character's state in between.

        Raises `NotArchived` for an identity the archive does not hold. The
        caller asked for something that is not there, which is information
        rather than an empty result.

        **Reaches `find_by_attribute` and `restore`, so wrap the caller in
        `deferToThread`.**
        """
        from evennia.objects.models import ObjectDB
        from evennia_archive.api import restore
        from evennia_archive.mixins import ARCHIVE_ID_KEY, OWNER_ACCOUNT_KEY

        existing = cls.objects.filter(
            db_attributes__db_key=ARCHIVE_ID_KEY,
            db_attributes__db_strvalue=str(archive_id),
        ).first()

        if existing is not None:
            # By the owner stamp rather than `db_account` or the roster.
            # The stamp is the link that survives an archive round trip, and
            # it is what `restore_missing_characters` searches by — so the delete
            # and the restore agree by construction.
            #
            # No cache flush needed: Evennia's `delete` calls
            # `flush_from_cache` itself, and a `pre_delete` signal evicts
            # the instance as well.
            for character in ObjectDB.objects.filter(
                db_attributes__db_key=OWNER_ACCOUNT_KEY,
                db_attributes__db_strvalue=str(archive_id),
            ):
                character.delete()
            existing.delete()

        return restore(archive_id)

    @classmethod
    def refresh_from_archive(cls, identifier):
        """Make sure this account and its characters are here.

        The login door, and the only place a username is all that is known
        — `authenticate` is handed a string a player typed, so finding the
        identity is the work. Every other way in already holds an
        ``archive_id``.

        **An account that is already here is returned untouched.** This
        instance is the only place it can have changed, so there is nothing
        better to replace it with — and replacing it moves its primary key,
        which anything outside the game holding that key is then naming a
        row that is gone. A Django website session resolves it on every
        request.

        Only an absent account is restored, which is an instance whose
        database was rebuilt. Nothing is deleted, because there is nothing
        there to delete.

        Returns the account, or ``None`` when there is nothing to restore
        and nothing local. An identifier with nothing archived is the
        ordinary case on a first login, not a fault.

        **The roster is restored either way.** For a restored account that
        is the obvious half — its characters are absent too. For an account
        that was already here it is the stranded-character case: a player
        who left ungracefully while in character never came back through
        the ticket door, so their character is still only in the archive.
        This is where that is noticed.

        **Account ``#1`` is never restored.** Evennia expects one on every
        instance, and replacing it with an archived copy takes an
        operator's way in with it.

        The ``#1`` lookup is ``filter(username=identifier)``, which is a
        second tie to the username and is *not* a seam. A consumer who
        overrides `find_in_archive` to identify accounts some other way must
        override this method too — otherwise the guard is handed something
        that is not a username, matches nothing, and stops protecting
        anything while still reading correctly.

        **Reaches the archive, so wrap the caller in `deferToThread`.**
        """
        from evennia_archive.api import restore

        account = cls.objects.filter(username=identifier).first()

        if account is not None and is_instance_root(account):
            return None

        if account is None:
            archive_id = cls.find_in_archive(identifier)
            if archive_id is None:
                return None
            account = restore(archive_id)

        # Both paths. A restored account arrives without its characters,
        # and one that was already here may be missing a character that
        # never came home from a shard. Safe over characters that are
        # already present, and role-gated inside itself so it does nothing
        # on a shard.
        cls.restore_missing_characters(account)
        return account

    @classmethod
    def authenticate(cls, username, password, ip="", **kwargs):
        """Refresh from the archive, then let Evennia check the credentials.

        There is no seam inside Evennia's login flow — it looks the account
        up and checks the password in one call — but this is a classmethod
        on the typeclass, so overriding it *is* the seam.

        **Refreshing before `super()` is the point.** Credentials are then
        checked against the archived copy rather than whatever this instance
        was still holding, so a player who changed their password elsewhere
        is not refused their own password.

        The refresh's result is ignored: an account with nothing archived is
        a first-time player, and the login proceeds exactly as Evennia would.

        No role gate. A shard is never reached through this door — an
        unticketed session is sent to the router before a login screen
        renders.

        **Blocks on the archive.** Evennia calls this synchronously and uses
        what it returns, so there is nowhere above it to put a
        `deferToThread`.
        """
        cls.refresh_from_archive(username)
        return super().authenticate(username, password, ip=ip, **kwargs)

    def unpuppet_object(self, session):
        """Release the character as Evennia does, and archive it.

        **The character alone.** It is only ever played on a shard, so a
        release is the moment its newest state is worth storing. The
        account is not touched: on a shard it is a working copy, and on a
        router nothing is puppeted for this to be reached from.

        Archiving and nothing else. This is not only reached from `ooc` —
        `at_disconnect` calls it on every dropped connection and
        `unpuppet_all()` calls it at shutdown. Archiving is safe and useful
        on all three; deleting the character is not. A five-second dropout
        would cost a player their position, and closing the browser
        mid-fight would become the way out of it.

        The delete and the transfer hang off the command that knows the
        player asked for it.

        Unpuppeting itself destroys nothing: it removes the session from
        the object, clears the account link, fires the hooks and drops the
        `puppeted` tag. The character stands where it was, which is what
        makes linkdead work.
        """
        from evennia.utils.utils import make_iter
        from evennia_archive.api import archive

        from .config import ROLE_ROUTER, get_role

        # `session` is one session or a list of them. Evennia's own body
        # opens with make_iter for the same reason: unpuppet_all() — called
        # before every reset and shutdown — passes self.sessions.all().
        # Reading .puppet off the parameter directly works for every
        # runtime path and raises on every shutdown.
        #
        # Collected before super(), which clears session.puppet.
        # Deduplicated because two sessions can puppet one character in
        # multisession modes 2 and 3.
        characters = []
        for one in make_iter(session):
            puppet = getattr(one, "puppet", None)
            if puppet is not None and puppet not in characters:
                characters.append(puppet)

        super().unpuppet_object(session)

        if not characters:
            return

        # Nothing about #1 is archived: it does not travel, so an
        # archived copy could only ever overwrite the one the instance
        # depends on. Before the breach check below, and deliberately —
        # #1 does puppet on the router, so reporting it would bury the real
        # thing under routine noise. Any other account puppeting there is a
        # breach, a second superuser included: one travels like anybody.
        if is_instance_root(self):
            return

        if get_role() == ROLE_ROUTER:
            named = ", ".join(
                f"{character} ({character.archive_id})"
                for character in characters
            )
            scaling_log(
                f"INVARIANT BREACH: {named} was puppeted on the router by "
                f"{self} ({self.archive_id}). puppet_object never puppets "
                f"here, so something bypassed it — a bug, or a way in this "
                f"library does not cover. Archiving anyway; nothing else "
                f"has been done.",
                level="ERROR",
            )

        for character in characters:
            archive(character)

    def puppet_object(self, session, obj):
        """On a router, go to the character's shard instead of puppeting it.

        `CmdIC` resolves the character and then calls this, so Evennia's
        resolution stays Evennia's. `evennia-shards` overrides the command
        instead and reimplements that resolution, which it has to: it needs
        ``_last_puppet`` written before the redirect, since that is how its
        destination learns which character to puppet. Our ticket carries the
        character's ``archive_id``, so nothing needs writing first.

        Returning without puppeting is a shape this method already uses —
        Evennia does the same for no permission, for a character puppeted
        elsewhere, and for too many puppets.

        Of the checks Evennia runs first, most concern state a router never
        has: an existing puppet on the session, a character already
        puppeted, a simultaneous-puppet limit. Two are kept. A missing
        object or session still raises, and the puppet lock still applies —
        without it a builder could send someone else's character to a shard.

        Nothing here handles the outcome of the move. `transfer_to_instance`
        owns that, so this path, the out-of-character path and a consumer's
        own shard-to-shard move all report the same way.
        """
        from .config import ROLE_ROUTER, get_role
        from .handoff import transfer_to_instance

        # #1 stays where it is, so it puppets normally even on a router.
        # Transferring it would archive and delete an account the instance
        # needs.
        if is_instance_root(self) or get_role() != ROLE_ROUTER:
            return super().puppet_object(session, obj)

        if not obj:
            raise RuntimeError("Object not found")
        if not session:
            raise RuntimeError("Session not found")

        if not obj.access(self, "puppet"):
            self.msg(f"You don't have permission to puppet '{obj.key}'.")
            return

        # The destination is one half of the character's location pair, so
        # the pair has to be complete before there is anywhere to send them.
        transfer_to_instance(
            self, session, obj, obj.ensure_location_for_transfer()
        )

    @classmethod
    def restore_missing_characters(cls, account):
        """Bring back any character this account owns that is not here.

        Returns the list of characters it restored, which is empty when
        the roster was already complete. A caller wanting to say something
        about a character that had been left behind reads that.

        The character-select menu reads live objects, so an account
        restored without its characters logs in to an empty menu — which
        looks like it worked.

        They are found by the owner stamp `evennia-archive` writes at
        character creation. ``db_account`` is a primary key and does not
        survive the archive, so the stamp is the only link back to an owner
        that does.

        **Gated on the role here rather than at the call site**, so a caller
        never branches and a login straight to a shard cannot reach it
        either. A shard receives exactly one character, the one its ticket
        names; restoring a whole roster there would put every character on
        an instance it is not being played on.

        `add` rather than writing the roster attribute, since that also
        fires ``at_post_add_character``.

        **Reaches `find_by_attribute` and `restore`, so wrap the caller in
        `deferToThread`.**
        """
        from evennia_archive.api import find_by_attribute, restore
        from evennia_archive.mixins import OWNER_ACCOUNT_KEY

        from .config import ROLE_ROUTER, get_role

        if get_role() != ROLE_ROUTER:
            return []

        # Safe to run over characters that are already here: `restore`
        # returns a live one unchanged, and Evennia's `add` skips one
        # already on the roster. What is reported as restored is what was
        # genuinely absent, so the emptiness of the list means something.
        restored = []
        for archive_id in find_by_attribute(
            OWNER_ACCOUNT_KEY, str(account.archive_id)
        ):
            was_here = cls._live_character(archive_id)
            character = restore(archive_id)
            account.characters.add(character)
            if not was_here:
                restored.append(character)
        return restored

    @staticmethod
    def _live_character(archive_id):
        """Whether a character carrying this archive id is already here."""
        from evennia.objects.models import ObjectDB
        from evennia_archive.mixins import ARCHIVE_ID_KEY

        return ObjectDB.objects.filter(
            db_attributes__db_key=ARCHIVE_ID_KEY,
            db_attributes__db_strvalue=str(archive_id),
        ).exists()
