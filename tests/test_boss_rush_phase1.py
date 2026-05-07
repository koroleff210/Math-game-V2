"""
Boss Rush Phase 1 foundation tests.

Verifies:
  - app/route registration does not break Classic
  - ProblemSet mode flags default safely
  - Boss Rush create form filters attack/recovery sets
  - missing recovery set is rejected
  - Boss Rush config/state rows can be created
  - player join shell creates participation/runtime state
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.boss_rush import BossRushBattleState, BossRushPlayerState, BossRushRoundConfig
from app.models.game import GameRound, GameSession, RoundPlayer
from app.models.player import Player
from app.models.problems import Problem, ProblemSet, Topic
from app.models.progression import SessionParticipantSnapshot


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'boss-rush-phase1-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED = False


flask_app = create_app(_TestConfig)

passed = 0
failed = 0


def check(label, condition, detail=''):
    global passed, failed
    if condition:
        print(f'  PASS  {label}')
        passed += 1
    else:
        msg = f'  FAIL  {label}'
        if detail:
            msg += f'  ({detail})'
        print(msg)
        failed += 1


def _make_player(username, *, is_admin=False, password='pass1234'):
    player = Player(username=username, is_admin=is_admin)
    player.set_password(password)
    db.session.add(player)
    db.session.flush()
    return player


def _login(client, username, password='pass1234'):
    return client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)


def _make_problem_set(name, problem, **flags):
    pset = ProblemSet(name=name, **flags)
    db.session.add(pset)
    db.session.flush()
    pset.problems.append(problem)
    db.session.flush()
    return pset


def _setup_base():
    with flask_app.app_context():
        db.create_all()
        admin = _make_player('__boss_rush_admin__', is_admin=True)
        player = _make_player('__boss_rush_player__')

        topic = Topic(name='__boss_rush_topic__')
        db.session.add(topic)
        db.session.flush()

        problem = Problem(
            topic_id=topic.id,
            title='Boss Rush Problem',
            prompt_text='2 + 3 = ?',
            answer_text='5',
            difficulty=1,
        )
        db.session.add(problem)
        db.session.flush()

        classic_only = _make_problem_set('__classic_only_set__', problem)
        attack_set = _make_problem_set(
            '__boss_attack_set__',
            problem,
            usable_in_boss_rush=True,
        )
        db.session.commit()

        return {
            'admin_id': admin.id,
            'player_id': player.id,
            'problem_id': problem.id,
            'classic_only_set_id': classic_only.id,
            'attack_set_id': attack_set.id,
        }


def _boss_rush_form_data(attack_set_id, recovery_set_id, **overrides):
    data = {
        'attack_problem_set_id': attack_set_id,
        'recovery_problem_set_id': recovery_set_id,
        'group_id': 0,
        'label': 'Phase 1 Test Boss',
        'boss_type': 'stone_golem',
        'boss_max_hp': 30,
        'player_max_hp': 3,
        'first_place_diamonds': 5,
        'second_place_diamonds': 4,
        'third_place_diamonds': 3,
        'other_participant_diamonds': 1,
        'highest_combo_diamonds': 5,
        'combo_bonus_threshold': 5,
        'combo_bonus_damage': 1,
    }
    data.update(overrides)
    return data


def run_tests():
    ids = _setup_base()

    with flask_app.app_context():
        classic_set = db.session.get(ProblemSet, ids['classic_only_set_id'])
        check('BR1-01: default problem sets stay Classic-usable', classic_set.usable_in_classic is True)
        check('BR1-02: default problem sets are not Boss Rush attack/recovery', not classic_set.usable_in_boss_rush and not classic_set.usable_as_recovery)

    with flask_app.test_client() as client:
        _login(client, '__boss_rush_admin__')

        r = client.get('/admin/classic/new')
        check('BR1-03: Classic create route still loads', r.status_code == 200 and 'New Classic Session' in r.get_data(as_text=True))

        r = client.get('/admin/boss-rush/new')
        html = r.get_data(as_text=True)
        check('BR1-04: Boss Rush create form loads', r.status_code == 200 and 'New Boss Rush' in html and 'Boss HP' in html)
        check('BR1-05: attack selector uses Boss Rush-eligible sets', '__boss_attack_set__' in html and '__classic_only_set__' not in html)
        check('BR1-05b: boss-specific ability UI data is rendered', 'data-ability-setting' in html and 'Heat Wave' in html and 'Stone Guard' in html)

        r = client.post(
            '/admin/boss-rush/new',
            data=_boss_rush_form_data(ids['attack_set_id'], 999),
            follow_redirects=True,
        )
        with flask_app.app_context():
            count = GameSession.query.filter_by(mode='boss_rush').count()
        check('BR1-06: invalid missing recovery set is rejected', count == 0 and r.status_code == 200)

        with flask_app.app_context():
            problem = db.session.get(Problem, ids['problem_id'])
            recovery_set = _make_problem_set(
                '__boss_recovery_set__',
                problem,
                usable_as_recovery=True,
            )
            db.session.commit()
            ids['recovery_set_id'] = recovery_set.id

        r = client.post(
            '/admin/boss-rush/new',
            data=_boss_rush_form_data(ids['attack_set_id'], ids['recovery_set_id']),
            follow_redirects=False,
        )
        check('BR1-07: valid Boss Rush create redirects to manage', r.status_code == 302 and '/admin/boss-rush/' in r.headers.get('Location', ''))

        with flask_app.app_context():
            session = GameSession.query.filter_by(mode='boss_rush').first()
            game_round = GameRound.query.filter_by(session_id=session.id).first()
            config = BossRushRoundConfig.query.filter_by(round_id=game_round.id).first()
            battle_state = BossRushBattleState.query.filter_by(round_id=game_round.id).first()
            ids['session_id'] = session.id
            check('BR1-08: Boss Rush session/config/state rows exist', bool(session and game_round and config and battle_state))
            check('BR1-09: Boss Rush defaults are stored', config.boss_max_hp == 30 and config.player_max_hp == 3 and config.highest_combo_diamonds == 5)
            check('BR1-10: battle state starts at max HP', battle_state.current_boss_hp == config.boss_max_hp and battle_state.status == 'waiting')

        r = client.get(f'/admin/boss-rush/{ids["session_id"]}/manage')
        check('BR1-11: Boss Rush manage shell loads', r.status_code == 200 and 'Battle Progress' in r.get_data(as_text=True))

        client.get('/logout')
        _login(client, '__boss_rush_player__')
        r = client.post(f'/boss-rush/join/{ids["session_id"]}', follow_redirects=False)
        check('BR1-12: player can join Boss Rush shell lobby', r.status_code == 302 and '/boss-rush/lobby/' in r.headers.get('Location', ''))

        with flask_app.app_context():
            session = db.session.get(GameSession, ids['session_id'])
            game_round = GameRound.query.filter_by(session_id=session.id).first()
            round_player = RoundPlayer.query.filter_by(session_id=session.id, player_id=ids['player_id']).first()
            player_state = BossRushPlayerState.query.filter_by(round_id=game_round.id, player_id=ids['player_id']).first()
            snapshot = SessionParticipantSnapshot.query.filter_by(session_id=session.id, player_id=ids['player_id']).first()
            check('BR1-13: join creates participant, Boss Rush state, and frozen snapshot', bool(round_player and player_state and snapshot))
            check('BR1-14: joined player starts with configured HP', player_state.hp == 3)


if __name__ == '__main__':
    print('\nBoss Rush Phase 1 - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL BOSS RUSH PHASE 1 TESTS PASSED.')
    else:
        print('SOME BOSS RUSH PHASE 1 TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
