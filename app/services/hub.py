# app/services/hub.py
# Read-model: determines a player's current hub/session state for the persistent Hub.
#
# Rules:
#   1. If the player already has a RoundPlayer row in any unfinished (waiting or active)
#      classic session → ENROLLED_UNFINISHED.  We check this FIRST so that a player who
#      has already joined never sees "Join Game" again.
#   2. Else if any live classic session exists that the player's group is eligible for
#      → ELIGIBLE.
#   3. Otherwise → NO_SESSION.
#
# No gameplay logic is changed here.  This is purely a read-model for the Hub UI.

from dataclasses import dataclass

from app.extensions import db
from app.models.game import GameSession, RoundPlayer
from app.models.groups import PlayerGroup

HUB_SUPPORTED_MODES = ('classic', 'boss_rush')

# ── Hub state constants ────────────────────────────────────────────────────────

HUB_STATE_NO_SESSION          = 'no_session'
"""No live classic session that this player's group is eligible for."""

HUB_STATE_ELIGIBLE            = 'eligible'
"""A live session exists, player is group-eligible, and has not joined yet."""

HUB_STATE_ENROLLED_UNFINISHED = 'enrolled_unfinished'
"""Player already has a RoundPlayer row in a waiting or active classic session."""


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class PlayerHubStatus:
    state: str                  # one of the HUB_STATE_* constants
    session: object = None      # the relevant GameSession instance, or None

    @property
    def mode(self) -> str | None:
        return self.session.mode if self.session else None


# ── Public API ─────────────────────────────────────────────────────────────────

def get_player_hub_status(player) -> PlayerHubStatus:
    """
    Return a PlayerHubStatus for *player* based on existing DB rows only.
    No writes; safe to call on every Hub page load.
    """
    # 1. Already enrolled in an unfinished session?
    enrolled_rp = (
        RoundPlayer.query
        .join(GameSession, RoundPlayer.session_id == GameSession.id)
        .filter(
            RoundPlayer.player_id == player.id,
            GameSession.mode.in_(HUB_SUPPORTED_MODES),
            GameSession.status != 'finished',
        )
        .first()
    )
    if enrolled_rp:
        session = db.session.get(GameSession, enrolled_rp.session_id)
        return PlayerHubStatus(state=HUB_STATE_ENROLLED_UNFINISHED, session=session)

    # 2. Any live classic session the player is eligible for?
    live_sessions = (
        GameSession.query
        .filter(
            GameSession.mode.in_(HUB_SUPPORTED_MODES),
            GameSession.status.in_(['waiting', 'active']),
        )
        .order_by(GameSession.id.desc())
        .all()
    )
    for session in live_sessions:
        if _player_eligible_for_session(player, session):
            return PlayerHubStatus(state=HUB_STATE_ELIGIBLE, session=session)

    return PlayerHubStatus(state=HUB_STATE_NO_SESSION)


# ── Private helpers ────────────────────────────────────────────────────────────

def _player_eligible_for_session(player, session) -> bool:
    """True if session is open (no group restriction) or player is a group member."""
    if session.group_id is None:
        return True
    group = db.session.get(PlayerGroup, session.group_id)
    if group is None:
        return True  # group deleted — treat as open
    return group.members.filter_by(id=player.id).first() is not None
