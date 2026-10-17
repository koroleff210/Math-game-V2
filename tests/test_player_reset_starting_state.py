"""
Focused regression tests for admin player reset and new-player starting state.

Run:
    .venv\\Scripts\\python.exe tests\\test_player_reset_starting_state.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.classic import PlayerClassicState, PlayerProblemState, PlayerWallet
from app.models.game import GameRound, GameSession, PlayerAnswer, RoundPlayer
from app.models.gear import GearItemDefinition, PlayerGearLoadout, PlayerGearOwnership
from app.models.player import Player
from app.models.progression import DiamondTransaction, PlayerProgression, PlayerUpgrade, SessionParticipantSnapshot
from app.services.player_reset import STARTING_DIAMONDS, WELCOME_GIFT_REASON


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'player-reset-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED = False


flask_app = create_app(_TestConfig)

passed = 0
failed = 0
_IDS = {}


def check(label, condition, detail=''):
    global passed, failed
    if condition:
        print(f'  PASS  {label}')
        passed += 1
    else:
        msg = f'  FAIL  {label}'
        if detail:
            msg += f' ({detail})'
        print(msg)
        failed += 1


def _make_player(username, *, is_admin=False, password='pass1234'):
    player = Player(username=username, is_admin=is_admin)
    player.set_password(password)
    db.session.add(player)
    db.session.flush()
    return player


def _login(client, username, password='pass1234'):
    return client.post(
        '/login',
        data={'username': username, 'password': password},
        follow_redirects=True,
    )


def _setup_db():
    with flask_app.app_context():
        db.create_all()
        admin = _make_player('__reset_admin__', is_admin=True)
        player = _make_player('__reset_player__')
        gear = GearItemDefinition(
            id='reset_pick',
            slot_type='main_hand',
            name='Reset Pick',
            description='Temporary reset test gear.',
            diamond_cost=1,
            is_active=True,
            is_blacksmith_visible=True,
        )
        db.session.add(gear)
        db.session.flush()

        player.avatar_body_variant = 'f'
        player.avatar_gender_selected = True
        player.selected_face_key = '003'
        player.character_locked_at = datetime.now(timezone.utc)
        db.session.add(PlayerGearOwnership(player_id=player.id, item_id=gear.id))
        db.session.add(PlayerGearLoadout(player_id=player.id, main_hand_item_id=gear.id))
        db.session.add(PlayerUpgrade(player_id=player.id, upgrade_type='mine_bonus', level=1))
        db.session.add(PlayerProgression(player_id=player.id, diamonds_balance=42))
        db.session.add(DiamondTransaction(
            player_id=player.id,
            amount_delta=42,
            balance_after=42,
            reason='old_state',
        ))
        session = GameSession(mode='classic', status='active')
        db.session.add(session)
        db.session.flush()
        game_round = GameRound(session_id=session.id, round_number=1)
        db.session.add(game_round)
        db.session.flush()
        db.session.add(RoundPlayer(session_id=session.id, player_id=player.id))
        db.session.add(PlayerWallet(session_id=session.id, player_id=player.id, gold=99, gems=9))
        db.session.add(PlayerClassicState(session_id=session.id, player_id=player.id))
        db.session.add(SessionParticipantSnapshot(session_id=session.id, player_id=player.id))
        db.session.add(PlayerProblemState(
            round_id=game_round.id,
            player_id=player.id,
            problem_id=1,
        ))
        db.session.add(PlayerAnswer(
            round_id=game_round.id,
            player_id=player.id,
            answer_text='old',
        ))
        db.session.commit()

        _IDS['admin_id'] = admin.id
        _IDS['player_id'] = player.id
        _IDS['session_id'] = session.id
        _IDS['round_id'] = game_round.id


def test_admin_reset_player_starting_state():
    with flask_app.test_client() as client:
        _login(client, '__reset_admin__')
        resp = client.post(
            f'/admin/players/{_IDS["player_id"]}/reset',
            follow_redirects=True,
        )
        html = resp.get_data(as_text=True)
        check(
            'PRS-01 reset route succeeds',
            resp.status_code == 200 and '__reset_player__' in html,
            f'status={resp.status_code}',
        )

    with flask_app.app_context():
        player = db.session.get(Player, _IDS['player_id'])
        progression = PlayerProgression.query.filter_by(player_id=player.id).first()
        txs = DiamondTransaction.query.filter_by(player_id=player.id).all()
        loadout = PlayerGearLoadout.query.filter_by(player_id=player.id).first()

        check(
            'PRS-02 avatar is unlocked and gender is unselected',
            player.character_locked_at is None and player.avatar_gender_selected is False,
        )
        check(
            'PRS-03 face/body return to first-login defaults',
            player.avatar_body_variant == 'm' and player.selected_face_key == '001',
        )
        check(
            'PRS-04 persistent gear inventory is cleared',
            PlayerGearOwnership.query.filter_by(player_id=player.id).count() == 0,
        )
        check(
            'PRS-05 persistent loadout is empty',
            loadout is not None and loadout.main_hand_item_id is None,
        )
        check(
            'PRS-06 upgrades are cleared',
            PlayerUpgrade.query.filter_by(player_id=player.id).count() == 0,
        )
        check(
            'PRS-07 starting balance is the welcome gift amount',
            progression is not None and progression.diamonds_balance == STARTING_DIAMONDS,
        )
        check(
            'PRS-08 diamond history is replaced with welcome gift',
            len(txs) == 1
            and txs[0].amount_delta == STARTING_DIAMONDS
            and txs[0].balance_after == STARTING_DIAMONDS
            and txs[0].reason == WELCOME_GIFT_REASON,
        )
        check(
            'PRS-09 unfinished session enrollment is cleared',
            RoundPlayer.query.filter_by(player_id=player.id, session_id=_IDS['session_id']).count() == 0,
        )
        check(
            'PRS-10 unfinished session runtime state is cleared',
            PlayerWallet.query.filter_by(player_id=player.id, session_id=_IDS['session_id']).count() == 0
            and PlayerClassicState.query.filter_by(player_id=player.id, session_id=_IDS['session_id']).count() == 0
            and SessionParticipantSnapshot.query.filter_by(player_id=player.id, session_id=_IDS['session_id']).count() == 0
            and PlayerProblemState.query.filter_by(player_id=player.id, round_id=_IDS['round_id']).count() == 0
            and PlayerAnswer.query.filter_by(player_id=player.id, round_id=_IDS['round_id']).count() == 0,
        )


def test_new_player_gets_starting_welcome_gift():
    with flask_app.test_client() as client:
        _login(client, '__reset_admin__')
        resp = client.post(
            '/admin/players/new',
            data={
                'username': '__fresh_start_player__',
                'password': 'pass1234',
                'yeargroup': '',
            },
            follow_redirects=True,
        )
        check(
            'PRS-11 admin can create a player with starting state',
            resp.status_code == 200,
            f'status={resp.status_code}',
        )

    with flask_app.app_context():
        player = Player.query.filter_by(username='__fresh_start_player__').first()
        progression = PlayerProgression.query.filter_by(player_id=player.id).first()
        tx = DiamondTransaction.query.filter_by(player_id=player.id).first()
        check(
            'PRS-12 new player must choose character on first login',
            player is not None and player.avatar_gender_selected is False and player.character_locked_at is None,
        )
        check(
            'PRS-13 new player receives welcome gift transaction',
            progression is not None
            and progression.diamonds_balance == STARTING_DIAMONDS
            and tx is not None
            and tx.reason == WELCOME_GIFT_REASON,
        )


def run_all():
    _setup_db()
    test_admin_reset_player_starting_state()
    test_new_player_gets_starting_welcome_gift()
    if failed:
        print(f'\nPLAYER RESET TESTS FAILED: {failed} failed, {passed} passed.')
        raise SystemExit(1)
    print(f'\nALL PLAYER RESET TESTS PASSED. ({passed} checks)')


if __name__ == '__main__':
    run_all()
