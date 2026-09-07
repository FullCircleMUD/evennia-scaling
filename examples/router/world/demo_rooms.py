# SPDX-License-Identifier: BSD-3-Clause
"""A handful of rooms carrying uuids, for exercising placement by hand.

Run it in game, as a superuser, on the instance you want rooms on::

    py from world.demo_rooms import build; build()

Safe to run more than once — a room whose uuid is already here is left
alone, so it is also how you repair the set after a rebuild.

There is no world source in this demo, so this stands in for one: the uuids
below are the fixed values a real deployment would keep in YAML, and the
point of them is that they are the same after every rebuild while the
dbrefs are not.

**Limbo deliberately gets none.** It is the room to walk into when you want
to see what happens somewhere the deployment cannot reproduce — which is
what `SCALING_KEEP_LOCATION_IN_UNMARKED_ROOM` decides.
"""

#: Fixed uuids, per instance. `a…` on shard0, `b…` on shard1, so a glance at
#: a character's `current_room_uuid` says which shard it names.
#:
#: The first on shard0 is what `SCALING_DEFAULT_HOME_UUID` points at, so
#: changing it here means changing it in `settings_common.py` too.
ROOMS = {
    "shard0": [
        ("a1000000-0000-4000-8000-000000000001", "The Inn"),
        ("a1000000-0000-4000-8000-000000000002", "Forest Path"),
        ("a1000000-0000-4000-8000-000000000003", "Riverbank"),
    ],
    "shard1": [
        ("b1000000-0000-4000-8000-000000000001", "Mountain Pass"),
        ("b1000000-0000-4000-8000-000000000002", "Snowfield"),
    ],
}

#: Where the rooms are hung off, so they are reachable on foot from a
#: standing start. Exits both ways between each room and the next.
ROOM_TYPECLASS = "typeclasses.rooms.Room"
EXIT_TYPECLASS = "typeclasses.exits.Exit"


def build():
    """Create this instance's rooms, and return a summary to read.

    Walking between them is the point as much as arriving in them: moving
    is what restamps a character's location pair, so the exits are what
    let you watch it change.
    """
    from evennia.utils.create import create_object
    from evennia_portal_multiplex.config import get_instance_id
    from evennia_scaling.mixins import find_room_by_uuid

    here = get_instance_id()
    wanted = ROOMS.get(here)
    if not wanted:
        return (
            f"{here} has no rooms in demo_rooms.ROOMS. Add some, or run "
            f"this on one of {tuple(ROOMS)}."
        )

    built, kept = [], []
    rooms = []
    for room_uuid, key in wanted:
        existing = find_room_by_uuid(room_uuid)
        if existing:
            rooms.append(existing)
            kept.append(f"{existing.key} {existing.dbref}")
            continue

        room = create_object(ROOM_TYPECLASS, key=key)
        room.scaling_room_uuid = room_uuid
        rooms.append(room)
        built.append(f"{room.key} {room.dbref} {room_uuid}")

    links = _link(rooms)

    lines = [f"{here}:"]
    lines += [f"  built  {line}" for line in built]
    lines += [f"  kept   {line}" for line in kept]
    lines += [f"  exits  {links}"]
    lines += [
        "  Limbo has no uuid, on purpose — walk in to test",
        "  SCALING_KEEP_LOCATION_IN_UNMARKED_ROOM.",
    ]
    return "\n".join(lines)


def _link(rooms):
    """Two-way exits along the chain, skipping any that already exist."""
    from evennia.utils.create import create_object

    made = 0
    for first, second in zip(rooms, rooms[1:]):
        for source, target, name in (
            (first, second, second.key.lower()),
            (second, first, first.key.lower()),
        ):
            if any(exit.key == name for exit in source.exits):
                continue
            create_object(
                EXIT_TYPECLASS,
                key=name,
                location=source,
                destination=target,
            )
            made += 1
    return f"{made} made"
