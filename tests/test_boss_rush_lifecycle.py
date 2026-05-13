"""
Boss Rush lifecycle flow tests.

Verifies Boss Rush round/session transitions follow the same broad shape as
Classic: end round returns to waiting/lobby, next round can start, and finished
sessions stop accepting player answers.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.boss_rush import BossRushBattleState, BossRushProblemAttempt, BossRushRoundConfig
from app.models.game import GameRound, GameSession, RoundPlayer
from app.models.player import Player
from app.models.problems import Problem, ProblemSet, Topic


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'boss-rush-lifecycle-secret'
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
            msg += f' ({detail})'
        print(msg)
        failed += 1


def _make_player(username, *, is_admin=False):
    player = Player(username=username, is_admin=is_admin)
    player.set_password('pass1234')
    db.session.add(player)
    db.session.flush()
    return player


def _login(client, username):
    client.get('/logout', follow_redirects=False)
    return client.post('/login', data={'username': username, 'password': 'pass1234'}, follow_redirects=True)


def _setup():
    with flask_app.app_context():
        db.create_all()
        admin = _make_player('__br_lifecycle_admin__', is_admin=True)
        player = _make_player('__br_lifecycle_player__')
        topic = Topic(name='__br_lifecycle_topic__')
        db.session.add(topic)
        db.session.flush()
        problem = Problem(
            topic_id=topic.id,
            title='Lifecycle Problem',
            prompt_text='1 + 1 = ?',
            answer_text='2',
            difficulty=1,
        )
        db.session.add(problem)
        db.session.flush()
        attack_set = ProblemSet(name='__br_lifecycle_attack__', usable_in_boss_rush=True)
        recovery_set = ProblemSet(name='__br_lifecycle_recovery__', usable_as_recovery=True)
        attack_set_2 = ProblemSet(name='__br_lifecycle_attack_next__', usable_in_boss_rush=True)
        recovery_set_2 = ProblemSet(name='__br_lifecycle_recovery_next__', usable_as_recovery=True)
        attack_set.problems.append(problem)
        recovery_set.problems.append(problem)
        attack_set_2.problems.append(problem)
        recovery_set_2.problems.append(problem)
        db.session.add_all([attack_set, recovery_set, attack_set_2, recovery_set_2])
        db.session.flush()
        session = GameSession(
            mode='boss_rush',
            status='waiting',
            problem_set_id=attack_set.id,
            label='Lifecycle Boss Rush',
        )
        db.session.add(session)
        db.session.flush()
        game_round = GameRound(session_id=session.id, problem_id=None, round_number=1)
        db.session.add(game_round)
        db.session.flush()
        config = BossRushRoundConfig(
            round_id=game_round.id,
            boss_type='fire_giant',
            boss_name='Fire Giant',
            boss_image_path='boss_rush/bosses/fire_giant.png',
            boss_max_hp=10,
            player_max_hp=3,
            attack_problem_set_id=attack_set.id,
            recovery_problem_set_id=recovery_set.id,
        )
        battle = BossRushBattleState(round_id=game_round.id, current_boss_hp=10, status='waiting')
        db.session.add_all([config, battle])
        db.session.commit()
        return {
            'session_id': session.id,
            'attack_set_2_id': attack_set_2.id,
            'recovery_set_2_id': recovery_set_2.id,
        }


def _next_round_form_data(attack_set_id, recovery_set_id, **overrides):
    data = {
        'attack_problem_set_id': attack_set_id,
        'recovery_problem_set_id': recovery_set_id,
        'group_id': 0,
        'label': 'Lifecycle Next Boss Rush',
        'boss_type': 'stone_golem',
        'boss_max_hp': 22,
        'player_max_hp': 4,
        'first_place_diamonds': 6,
        'second_place_diamonds': 5,
        'third_place_diamonds': 4,
        'other_participant_diamonds': 2,
        'highest_combo_diamonds': 7,
        'combo_bonus_threshold': 4,
        'combo_bonus_damage': 2,
        'ability_enabled': 'y',
        'ability_interval_seconds': 45,
        'fire_burn_damage': 1,
        'fire_shield_max_stacks': 1,
        'swamp_regen_amount': 2,
        'stone_guard_combo_required': 5,
        'time_drain_damage': 1,
    }
    data.update(overrides)
    return data


def run_tests():
    ids = _setup()
    session_id = ids['session_id']

    with flask_app.test_client() as client:
        _login(client, '__br_lifecycle_player__')
        r = client.post(f'/boss-rush/join/{session_id}', follow_redirects=False)
        check('BRLIFE-01: player joins waiting Boss Rush lobby', r.status_code == 302 and f'/boss-rush/lobby/{session_id}' in r.headers.get('Location', ''))

        _login(client, '__br_lifecycle_admin__')
        r = client.post(f'/admin/boss-rush/{session_id}/start', follow_redirects=False)
        check('BRLIFE-02: admin starts Boss Rush round', r.status_code == 302)
        r = client.post(f'/admin/boss-rush/{session_id}/ability/freeze', follow_redirects=False)
        check('BRLIFE-02b: admin can freeze ability during active round', r.status_code == 302)
        with flask_app.app_context():
            game_round = GameRound.query.filter_by(session_id=session_id).order_by(GameRound.round_number.desc()).first()
            check('BRLIFE-02c: freeze sets persisted ability_frozen and clears timer', game_round.boss_rush_battle_state.ability_frozen and game_round.boss_rush_battle_state.next_ability_at is None)
        r = client.post(f'/admin/boss-rush/{session_id}/ability/resume', follow_redirects=False)
        check('BRLIFE-02d: admin can resume ability during active round', r.status_code == 302)
        with flask_app.app_context():
            game_round = GameRound.query.filter_by(session_id=session_id).order_by(GameRound.round_number.desc()).first()
            check('BRLIFE-02e: resume clears frozen flag and restores timer', (not game_round.boss_rush_battle_state.ability_frozen) and game_round.boss_rush_battle_state.next_ability_at is not None)
        with flask_app.app_context():
            session = db.session.get(GameSession, session_id)
            game_round = GameRound.query.filter_by(session_id=session_id).order_by(GameRound.round_number.desc()).first()
            check('BRLIFE-03: started round marks session active', session.status == 'active' and game_round.started_at is not None)

        r = client.post(f'/admin/boss-rush/{session_id}/end', follow_redirects=False)
        check('BRLIFE-04: admin can end Boss Rush round', r.status_code == 302)
        with flask_app.app_context():
            session = db.session.get(GameSession, session_id)
            game_round = GameRound.query.filter_by(session_id=session_id).order_by(GameRound.round_number.desc()).first()
            battle = game_round.boss_rush_battle_state
            check('BRLIFE-05: ended round returns session to waiting', session.status == 'waiting' and game_round.ended_at is not None and battle.status == 'ended')

        _login(client, '__br_lifecycle_player__')
        r = client.get(f'/boss-rush/game/{session_id}', follow_redirects=False)
        check('BRLIFE-06: player game route redirects to lobby after round end', r.status_code == 302 and f'/boss-rush/lobby/{session_id}' in r.headers.get('Location', ''))
        r = client.post(f'/boss-rush/game/{session_id}/answer', data={'answer_text': '2'}, follow_redirects=False)
        check('BRLIFE-07: ended round rejects answer submissions', r.status_code == 302 and f'/boss-rush/lobby/{session_id}' in r.headers.get('Location', ''))
        with flask_app.app_context():
            check('BRLIFE-08: rejected ended-round answer writes no attempt', BossRushProblemAttempt.query.count() == 0)
            session = db.session.get(GameSession, session_id)
            game_round = GameRound.query.filter_by(session_id=session_id).order_by(GameRound.round_number.desc()).first()
            battle = game_round.boss_rush_battle_state
            session.status = 'active'
            battle.current_boss_hp = 7
            db.session.commit()

        r = client.post(f'/boss-rush/game/{session_id}/answer', data={'answer_text': '2'}, follow_redirects=False)
        check('BRLIFE-09: active session with ended round still rejects answer submissions', r.status_code == 302 and f'/boss-rush/lobby/{session_id}' in r.headers.get('Location', ''))
        with flask_app.app_context():
            session = db.session.get(GameSession, session_id)
            game_round = GameRound.query.filter_by(session_id=session_id).order_by(GameRound.round_number.desc()).first()
            battle = game_round.boss_rush_battle_state
            check('BRLIFE-10: ended active guard does not mutate battle or write attempt', battle.current_boss_hp == 7 and BossRushProblemAttempt.query.count() == 0)
            session.status = 'waiting'
            db.session.commit()

        _login(client, '__br_lifecycle_admin__')
        r = client.get(f'/admin/boss-rush/{session_id}/manage')
        html = r.get_data(as_text=True)
        check('BRLIFE-11: admin manage shows configure next-round control after round end', r.status_code == 200 and 'Configure Next Boss Rush Round' in html)
        r = client.get(f'/admin/boss-rush/{session_id}/next_round')
        html = r.get_data(as_text=True)
        check('BRLIFE-12: admin can reach full next-round configuration form', r.status_code == 200 and 'Configure Boss Rush Round 2' in html and 'Attack Problem Set' in html and 'Boss HP' in html)
        check('BRLIFE-13: boss-specific ability UI data is present', 'data-ability-setting' in html and 'Heat Wave' in html and 'Stone Guard' in html and 'data-boss-ability-summary' in html)
        r = client.post(
            f'/admin/boss-rush/{session_id}/next_round',
            data=_next_round_form_data(ids['attack_set_2_id'], ids['recovery_set_2_id']),
            follow_redirects=False,
        )
        check('BRLIFE-14: admin can start configured next Boss Rush round', r.status_code == 302)
        with flask_app.app_context():
            session = db.session.get(GameSession, session_id)
            latest = GameRound.query.filter_by(session_id=session_id).order_by(GameRound.round_number.desc()).first()
            config = latest.boss_rush_config
            check('BRLIFE-15: next round is active and increments round number', session.status == 'active' and latest.round_number == 2 and latest.started_at is not None)
            check('BRLIFE-16: next round can use a different boss', config.boss_type == 'stone_golem' and config.boss_name == 'Stone Golem')
            check('BRLIFE-17: next round can use different problem sets', config.attack_problem_set_id == ids['attack_set_2_id'] and config.recovery_problem_set_id == ids['recovery_set_2_id'])
            check('BRLIFE-18: next round can use different HP settings', config.boss_max_hp == 22 and config.player_max_hp == 4 and latest.boss_rush_battle_state.current_boss_hp == 22)

        r = client.post(f'/admin/boss-rush/{session_id}/end_session', follow_redirects=False)
        check('BRLIFE-19: admin can finish Boss Rush session', r.status_code == 302)
        with flask_app.app_context():
            session = db.session.get(GameSession, session_id)
            check('BRLIFE-20: finished Boss Rush session is marked finished', session.status == 'finished' and session.ended_at is not None)

        _login(client, '__br_lifecycle_player__')
        r = client.get(f'/boss-rush/game/{session_id}', follow_redirects=False)
        check('BRLIFE-21: player game route redirects to post-session lobby when finished', r.status_code == 302 and f'/boss-rush/lobby/{session_id}' in r.headers.get('Location', ''))
        r = client.get(f'/boss-rush/lobby/{session_id}')
        check('BRLIFE-22: post-session lobby shows ended state', r.status_code == 200 and 'session ended' in r.get_data(as_text=True).lower())


if __name__ == '__main__':
    print('Boss Rush Lifecycle - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    total = passed + failed
    print(f'Results: {passed} passed, {failed} failed out of {total} tests.')
    if failed:
        raise SystemExit(1)
    print('ALL BOSS RUSH LIFECYCLE TESTS PASSED.')
