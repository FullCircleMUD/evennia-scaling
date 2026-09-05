# SPDX-License-Identifier: BSD-3-Clause
"""Typeclass mixins a consumer adds to their own classes.

See docs/test-plan.md § SH.
"""

from evennia.typeclasses.attributes import AttributeProperty
from evennia_archive.mixins import (
    ArchivableAccountMixin,
    ArchivableCharacterMixin,
)

from .config import get_shards, get_start_location_shard
from .log import scaling_log

#: The Attribute key holding the other half of where a character is: which
#: room, in the database of the shard `current_shard` names.
CURRENT_ROOM_REF_KEY = "current_room_ref"

#: The Attribute key naming where a character is in the game world.
#: `AttributeProperty` takes its key from the attribute name, so this and the
#: property below have to agree.
CURRENT_SHARD_KEY = "current_shard"


class _CurrentShardProperty(AttributeProperty):
    """Refuses anything that is not a shard in this deployment."""

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
            raise ValueError(
                f"{CURRENT_SHARD_KEY} cannot be {value!r}. It names the shard "
                f"a character is in, and the shards are {tuple(shards)!r}."
            )
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
    current_shard = _CurrentShardProperty(
        # The function, not a value: settings are not loaded when this module
        # imports, and Evennia calls it at the first read.
        default=get_start_location_shard,
        strattr=True,
    )

    #: The other half of the pair: which room, in the database of the shard
    #: above. No default — a room key means nothing without a shard beside
    #: it, so there is nothing useful to fall back to at read time.
    #:
    #: Nothing validates it. It names a row in a database this instance
    #: cannot see, so the only check available is that a value is present.
    current_room_ref = AttributeProperty(default=None)

    def ensure_location_for_transfer(self):
        """Complete where this character would be sent, and return the shard.

        Named for the transfer rather than for the character's location,
        because it is not the same thing. `character.location` is the room
        object this character is standing in *now*, on the instance running
        it. This pair is what survives the archive, and the two drift apart
        the moment a character walks anywhere — until something restamps
        the pair.

        `current_shard` and `current_room_ref` are one composite key —
        which instance, then which room in that instance's database. A
        shard alone does not say where a character stands.

        Returns the shard, so a call site reads as the destination it is.

        Either half being unusable means the character cannot be sent
        anywhere, because **the destination is one half of the pair**.
        There is nowhere to send them until both halves agree, which is why
        this runs before a transfer rather than on arrival — and why the
        arrival can assume both are present.

        Writes the home pair, both halves together. Keeping a start shard
        with no room key would leave a destination that still cannot say
        where on it the character stands.

        The shard half looks redundant, since `at_set` refuses anything
        outside the roster — but `.db` bypasses that, and a shard removed
        from the roster after a character was stamped goes stale the same
        way.
        """
        from django.conf import settings

        from .config import get_default_home_shard, get_shards

        if self.current_shard in get_shards() and self.current_room_ref:
            return self.current_shard

        self.current_shard = get_default_home_shard()
        self.current_room_ref = settings.DEFAULT_HOME
        return self.current_shard


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
            # it is what `restore_characters` searches by — so the delete
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
        """Rebuild this account from the archive, replacing what is local.

        The login door's wrapper around `rebuild_from_archive`, and the only
        place a username is all that is known — `authenticate` is handed a
        string a player typed, so finding the identity is the work. Every
        other way in already holds an ``archive_id`` and rebuilds directly.

        Returns the rebuilt account, or ``None`` when there is nothing to
        rebuild from. An identifier with nothing archived is the ordinary
        case on a first login, not a fault.

        **A superuser is never rebuilt.** Evennia expects ``#1`` to be
        there, and replacing it with an archived copy takes an operator's
        way in with it.

        The superuser lookup is ``filter(username=identifier)``, which is a
        second tie to the username and is *not* a seam. A consumer who
        overrides `find_in_archive` to identify accounts some other way must
        override this method too — otherwise the guard is handed something
        that is not a username, matches nothing, and stops protecting
        anything while still reading correctly.

        **Reaches the archive, so wrap the caller in `deferToThread`.**
        """
        existing = cls.objects.filter(username=identifier).first()
        if existing is not None and existing.is_superuser:
            return None

        archive_id = cls.find_in_archive(identifier)
        if archive_id is None:
            return None

        return cls.rebuild_from_archive(archive_id)

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
        """Release the character as Evennia does, and archive what was played.

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

        # Nothing about a superuser is archived: it does not travel, so an
        # archived copy could only ever overwrite the one the instance
        # depends on. Before the breach check below, and deliberately —
        # superusers do puppet on the router, so reporting them would bury
        # the real thing under routine noise.
        if self.is_superuser:
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

        # The account once, however many sessions arrived — this runs while
        # the server is trying to exit.
        archive(self)
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

        # A superuser stays where it is, so it puppets normally even on a
        # router. Transferring one would archive and delete an account the
        # instance needs.
        if self.is_superuser or get_role() != ROLE_ROUTER:
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
    def restore_characters(cls, account):
        """Rebuild every character this account owns. Router only.

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
            return

        for archive_id in find_by_attribute(
            OWNER_ACCOUNT_KEY, str(account.archive_id)
        ):
            account.characters.add(restore(archive_id))
