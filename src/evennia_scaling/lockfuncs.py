# SPDX-License-Identifier: BSD-3-Clause
"""Lock functions this library adds.

Add to a consumer's settings::

    LOCK_FUNC_MODULES = list(LOCK_FUNC_MODULES) + ["evennia_scaling.lockfuncs"]

See docs/test-plan.md § LK.
"""


def is_ooc(accessing_obj, accessed_obj, *args, session=None, **kwargs):
    """True when nothing is being puppeted on this session.

    Usage::

        cmd:pperm(Player) and is_ooc()

    Evennia passes the session into a ``cmd`` access check — see
    `cmdparser.py`, where matches are filtered with
    ``match.access(caller, "cmd", session=session)`` — so a lockfunc can
    ask what a lockstring otherwise cannot: what state the *connection* is
    in, rather than what the caller is.

    No session means no puppet. A lock checked outside a command is not a
    character standing somewhere, and refusing there would fail closed for
    a caller that never had a session to begin with.
    """
    return not (session and session.puppet)
