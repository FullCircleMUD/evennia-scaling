"""
Room

Rooms are simple containers that has no location of their own.

"""

from evennia.objects.objects import DefaultRoom
from evennia_scaling.mixins import ScalingRoomMixin

from .objects import ObjectParent


class Room(ScalingRoomMixin, ObjectParent, DefaultRoom):
    """
    Rooms are like any Object, except their location is None
    (which is default). They also use basetype_setup() to
    add locks so they cannot be puppeted or picked up.
    (to change that, use at_object_creation instead)

    `ScalingRoomMixin` adds `scaling_room_uuid`, which is how a character
    arriving from another instance finds its way back to this room. It is
    assigned, never minted, so every room here starts with none — including
    Limbo, which is left without one on purpose so there is somewhere to
    stand that the deployment cannot reproduce.

    `world/demo_rooms.py` builds a few rooms that do carry one.
    """

    pass
