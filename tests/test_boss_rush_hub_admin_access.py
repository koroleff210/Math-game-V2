"""
Focused Boss Rush access regressions.

Verifies:
  - /admin/boss-rush/ returns to the current waiting/active Boss Rush session.
  - Player Hub detects Boss Rush sessions and renders a working Join Game form.
  - Joined Boss Rush players return to the Boss Rush lobby/game from the Hub.
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.boss_rush import BossRushBattleState, BossRushRoundConfig
from app.models.game import GameRound, GameSession
from app.models.player import Player
from app.models.problems import Problem, ProblemSet, Topic


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'boss-rush-access-secret'
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
            msg += f'  ({detail})'
        print(msg)
        failed += 1


def _make_player(username, *, is_admin=False):
    player = Player(username=username, is_admin=is_admin)
    player.set_password('pass1234')
    db.session.add(player)
    db.session.flush()
    return player


def _login(client, username):
    return client.post(
        '/login',
        data={'username': username, 'password': 'pass1234'},
        follow_redirects=True,
    )


def _setup_db():
    with flask_app.app_context():
        db.create_all()
        admin = _make_player('__boss_access_admin__', is_admin=True)
        player = _make_player('__boss_access_player__')
        player.character_locked_at = datetime.now(timezone.utc)

        topic = Topic(name='__boss_access_topic__')
        db.session.add(topic)
        db.session.flush()
        problem = Problem(
            topic_id=topic.id,
            title='Boss Access Problem',
            prompt_text='1 + 1 = ?',
            answer_text='2',
            difficulty=1,
        )
        db.session.add(problem)
        db.session.flush()

        attack_set = ProblemSet(name='__boss_access_attack__', usable_in_boss_rush=True)
        recovery_set = ProblemSet(name='__boss_access_recovery__', usable_as_recovery=True)
        db.session.add_all([attack_set, recovery_set])
        db.session.flush()
        attack_set.problems.append(problem)
        recovery_set.problems.append(problem)
        db.session.flush()

        session = GameSession(
            mode='boss_rush',
            status='waiting',
            problem_set_id=attack_set.id,
            label='Access Test Boss',
        )
        db.session.add(session)
        db.session.flush()
        game_round = GameRound(session_id=session.id, round_number=1)
        db.session.add(game_round)
        db.session.flush()
        config = BossRushRoundConfig(
            round_id=game_round.id,
            boss_type='stone_golem',
            boss_name='Stone Golem',
            boss_max_hp=30,
            player_max_hp=3,
            attack_problem_set_id=attack_set.id,
            recovery_problem_set_id=recovery_set.id,
        )
        battle = BossRushBattleState(
            round_id=game_round.id,
            current_boss_hp=30,
            status='waiting',
        )
        db.session.add_all([config, battle])
        db.session.commit()

        _IDS.update({
            'admin_id': admin.id,
            'player_id': player.id,
            'session_id': session.id,
        })


def run_tests():
    _setup_db()

    with flask_app.test_client() as client:
        _login(client, '__boss_access_admin__')
        r = client.get('/admin/boss-rush/', follow_redirects=False)
        location = r.headers.get('Location', '')
        check(
            'BRACCESS-01: Boss Rush admin index redirects to live manage page',
            r.status_code == 302 and f'/admin/boss-rush/{_IDS["session_id"]}/manage' in location,
            f'status={r.status_code} location={location}',
        )

        client.get('/logout')
        _login(client, '__boss_access_player__')
        r = client.get('/player/dashboard')
        html = r.get_data(as_text=True)
        control_html = html[html.index('data-hub-session-control'):html.index('data-hub-session-control') + 900]
        check(
            'BRACCESS-02: Hub renders Boss Rush join form for eligible player',
            r.status_code == 200
            and 'action="/boss-rush/join"' in control_html
            and f'name="session_id" value="{_IDS["session_id"]}"' in control_html
            and 'Join Game' in control_html
            and 'disabled' not in control_html,
        )

        r = client.post('/boss-rush/join', data={'session_id': _IDS['session_id']}, follow_redirects=False)
        check(
            'BRACCESS-03: Hub-compatible Boss Rush join endpoint routes to lobby',
            r.status_code == 302 and f'/boss-rush/lobby/{_IDS["session_id"]}' in r.headers.get('Location', ''),
            f'status={r.status_code} location={r.headers.get("Location", "")}',
        )

        r = client.get('/player/dashboard', follow_redirects=False)
        check(
            'BRACCESS-04: joined player dashboard returns to Boss Rush lobby',
            r.status_code == 302 and f'/boss-rush/lobby/{_IDS["session_id"]}' in r.headers.get('Location', ''),
            f'status={r.status_code} location={r.headers.get("Location", "")}',
        )


if __name__ == '__main__':
    print('\nBoss Rush Hub/Admin Access - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL BOSS RUSH HUB/ADMIN ACCESS TESTS PASSED.')
    else:
        print('SOME BOSS RUSH HUB/ADMIN ACCESS TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
