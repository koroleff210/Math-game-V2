from datetime import datetime, timezone

from app.extensions import db
from app.models.classic import PlayerClassicState, PlayerInventory, PlayerProblemState, PlayerWallet
from app.models.game import GameRound, GameSession, PlayerAnswer, RoundPlayer
from app.models.gear import PlayerGearLoadout, PlayerGearOwnership
from app.models.player import Player
from app.models.progression import (
    DiamondTransaction,
    PlayerProgression,
    PlayerUpgrade,
    SessionParticipantSnapshot,
)


STARTING_DIAMONDS = 3
WELCOME_GIFT_REASON = 'welcome gift'


def reset_player_to_starting_state(
    player: Player,
    *,
    admin_player_id: int | None = None,
) -> dict:
    """Reset one non-admin player to the first-login persistent state.

    This intentionally avoids deleting session/round history. It only resets
    Hub-facing character, gear, upgrades, and persistent diamond state.
    Caller owns commit/rollback.
    """
    if player is None:
        raise ValueError('Player not found.')
    if player.is_admin:
        raise ValueError('Admin accounts cannot be reset as players.')

    now = datetime.now(timezone.utc)

    player.avatar_body_variant = 'm'
    player.avatar_gender_selected = False
    player.selected_face_key = '001'
    player.character_locked_at = None

    removed_gear = (
        PlayerGearOwnership.query
        .filter_by(player_id=player.id)
        .delete(synchronize_session=False)
    )
    removed_upgrades = (
        PlayerUpgrade.query
        .filter_by(player_id=player.id)
        .delete(synchronize_session=False)
    )
    removed_transactions = (
        DiamondTransaction.query
        .filter_by(player_id=player.id)
        .delete(synchronize_session=False)
    )
    unfinished_session_ids = [
        row.session_id
        for row in (
            db.session.query(RoundPlayer.session_id)
            .join(GameSession, RoundPlayer.session_id == GameSession.id)
            .filter(
                RoundPlayer.player_id == player.id,
                GameSession.status != 'finished',
            )
            .all()
        )
    ]
    unfinished_round_ids = []
    if unfinished_session_ids:
        unfinished_round_ids = [
            row.id
            for row in (
                db.session.query(GameRound.id)
                .filter(GameRound.session_id.in_(unfinished_session_ids))
                .all()
            )
        ]

        if unfinished_round_ids:
            PlayerAnswer.query.filter(
                PlayerAnswer.player_id == player.id,
                PlayerAnswer.round_id.in_(unfinished_round_ids),
            ).delete(synchronize_session=False)
            PlayerProblemState.query.filter(
                PlayerProblemState.player_id == player.id,
                PlayerProblemState.round_id.in_(unfinished_round_ids),
            ).delete(synchronize_session=False)

        PlayerInventory.query.filter(
            PlayerInventory.player_id == player.id,
            PlayerInventory.session_id.in_(unfinished_session_ids),
        ).delete(synchronize_session=False)
        PlayerWallet.query.filter(
            PlayerWallet.player_id == player.id,
            PlayerWallet.session_id.in_(unfinished_session_ids),
        ).delete(synchronize_session=False)
        PlayerClassicState.query.filter(
            PlayerClassicState.player_id == player.id,
            PlayerClassicState.session_id.in_(unfinished_session_ids),
        ).delete(synchronize_session=False)
        SessionParticipantSnapshot.query.filter(
            SessionParticipantSnapshot.player_id == player.id,
            SessionParticipantSnapshot.session_id.in_(unfinished_session_ids),
        ).delete(synchronize_session=False)
        RoundPlayer.query.filter(
            RoundPlayer.player_id == player.id,
            RoundPlayer.session_id.in_(unfinished_session_ids),
        ).delete(synchronize_session=False)

    loadout = PlayerGearLoadout.query.filter_by(player_id=player.id).first()
    if loadout is not None:
        loadout.main_hand_item_id = None
        loadout.off_hand_item_id = None
        loadout.chest_item_id = None
        loadout.head_item_id = None
        loadout.boots_item_id = None
        loadout.pocket1_item_id = None
        loadout.pocket2_item_id = None
        loadout.updated_at = now

    progression = PlayerProgression.query.filter_by(player_id=player.id).first()
    if progression is None:
        progression = PlayerProgression(
            player_id=player.id,
            diamonds_balance=STARTING_DIAMONDS,
            created_at=now,
            updated_at=now,
        )
        db.session.add(progression)
        db.session.flush()
    else:
        progression.diamonds_balance = STARTING_DIAMONDS
        progression.updated_at = now

    tx = DiamondTransaction(
        player_id=player.id,
        amount_delta=STARTING_DIAMONDS,
        balance_after=STARTING_DIAMONDS,
        reason=WELCOME_GIFT_REASON,
        admin_player_id=admin_player_id,
        session_id=None,
        created_at=now,
    )
    db.session.add(tx)
    db.session.flush()

    return {
        'removed_gear': removed_gear,
        'removed_upgrades': removed_upgrades,
        'removed_transactions': removed_transactions,
        'cleared_unfinished_sessions': len(unfinished_session_ids),
        'cleared_unfinished_rounds': len(unfinished_round_ids),
        'diamonds_balance': STARTING_DIAMONDS,
    }
