"""
Boss Rush player UI layout smoke tests.

Verifies the redesigned gameplay page keeps the battle mechanics reachable
while removing the visible Hub navigation button/link.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.boss_rush import BossRushBattleState, BossRushRoundConfig
from app.models.game import GameRound, GameSession, RoundPlayer
from app.models.player import Player
from app.models.problems import (
    PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE,
    Problem,
    ProblemChoiceOption,
    ProblemSet,
    Topic,
)
from app.modes.boss_rush.engine import initialize_player_state
from app.modes.boss_rush.engine import boss_catalog_entry


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'boss-rush-player-ui-secret'
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


def _make_player(username):
    player = Player(username=username)
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


def _make_session(*, answer_type='text', boss_type='air_elemental'):
    player = _make_player(f'__boss_ui_player_{answer_type}_{boss_type}__')
    topic = Topic(name=f'__boss_ui_topic_{answer_type}_{boss_type}__')
    db.session.add(topic)
    db.session.flush()

    attack = Problem(
        topic_id=topic.id,
        title=f'Boss UI {answer_type} {boss_type} Attack',
        prompt_text='Choose the correct answer.',
        answer_text='7' if answer_type == 'text' else '',
        difficulty=1,
        answer_type=PROBLEM_ANSWER_TYPE_MULTIPLE_CHOICE if answer_type == 'mc' else 'text_input',
    )
    recovery = Problem(
        topic_id=topic.id,
        title=f'Boss UI {answer_type} {boss_type} Recovery',
        prompt_text='Recovery answer is yes.',
        answer_text='yes',
        difficulty=1,
    )
    db.session.add_all([attack, recovery])
    db.session.flush()
    correct_option_id = None
    if answer_type == 'mc':
        wrong = ProblemChoiceOption(problem_id=attack.id, position=1, option_text='Wrong', is_correct=False)
        correct = ProblemChoiceOption(problem_id=attack.id, position=2, option_text='Correct', is_correct=True)
        db.session.add_all([wrong, correct])
        db.session.flush()
        correct_option_id = correct.id

    attack_set = ProblemSet(name=f'Boss UI Attack {answer_type} {boss_type}', usable_in_boss_rush=True)
    recovery_set = ProblemSet(name=f'Boss UI Recovery {answer_type} {boss_type}', usable_as_recovery=True)
    db.session.add_all([attack_set, recovery_set])
    db.session.flush()
    attack_set.problems.append(attack)
    recovery_set.problems.append(recovery)
    db.session.flush()

    session = GameSession(mode='boss_rush', status='active', problem_set_id=attack_set.id)
    db.session.add(session)
    db.session.flush()
    game_round = GameRound(session_id=session.id, round_number=1)
    db.session.add(game_round)
    db.session.flush()
    config = BossRushRoundConfig(
        round_id=game_round.id,
        boss_type=boss_type,
        boss_name=boss_type.replace('_', ' ').title(),
        boss_image_path='boss_rush/bosses/air_boss.png',
        boss_max_hp=30,
        player_max_hp=3,
        attack_problem_set_id=attack_set.id,
        recovery_problem_set_id=recovery_set.id,
    )
    battle = BossRushBattleState(round_id=game_round.id, current_boss_hp=30, status='active')
    db.session.add_all([config, battle, RoundPlayer(session_id=session.id, player_id=player.id)])
    db.session.flush()
    state = initialize_player_state(game_round, player.id, config)
    db.session.commit()
    return {
        'username': player.username,
        'session_id': session.id,
        'battle': battle,
        'state': state,
        'correct_option_id': correct_option_id,
    }


def run_tests():
    with flask_app.app_context():
        db.create_all()
        text_ctx = _make_session(answer_type='text')
        mc_ctx = _make_session(answer_type='mc')
        theme_contexts = {'air_elemental': text_ctx}
        theme_contexts.update({
            boss_type: _make_session(answer_type='text', boss_type=boss_type)
            for boss_type in (
                'fire_giant',
                'mirror_phantom',
                'swamp_monster',
                'stone_golem',
                'time_wraith',
            )
        })

    with flask_app.test_client() as client:
        _login(client, text_ctx['username'])
        r = client.get(f'/boss-rush/game/{text_ctx["session_id"]}')
        html = r.get_data(as_text=True)
        check(
            'BRUI-01: player page renders 3-column Boss Rush shell without Hub return link',
            r.status_code == 200
            and 'boss-battle-shell' in html
            and 'boss-left-rail' in html
            and 'problem-arena' in html
            and 'boss-right-rail' in html
            and 'Back to Hub' not in html
            and 'Return to Hub' not in html,
        )
        check(
            'BRUI-01b: Boss Rush page includes boss theme variables and air class',
            'boss-theme-air-elemental' in html
            and 'background_air_elemental.png' in html
            and '--br-bg-image' in html
            and '--br-hp-fill' in html
            and '--br-ability-fill' in html,
        )
        check(
            'BRUI-02: live update targets remain on redesigned page',
            'data-boss-hp' in html
            and 'data-player-hearts' in html
            and 'data-player-combo' in html
            and 'data-active-bonuses' in html
            and 'data-ability-timer' in html
            and 'data-ability-timer-fill' in html
            and 'data-ability-toast' in html
            and 'data-boss-rush-leaderboard' in html,
        )
        check(
            'BRUI-03: boss info modal and compact rail controls render',
            'data-boss-info-modal' in html
            and 'boss-info-drawer' in html
            and 'data-boss-info-open' in html
            and 'data-ability-full-rule' in html
            and 'combo-primary' in html
            and 'ability-time' in html
            and 'data-ability-summary' in html,
        )
        r = client.post(
            f'/boss-rush/game/{text_ctx["session_id"]}/answer',
            data={'answer_text': '7'},
            follow_redirects=True,
        )
        check(
            'BRUI-04: text answer still submits through redesigned page',
            r.status_code == 200 and 'Correct. You dealt 1 damage.' in r.get_data(as_text=True),
        )

        client.get('/logout')
        _login(client, mc_ctx['username'])
        r = client.get(f'/boss-rush/game/{mc_ctx["session_id"]}')
        html = r.get_data(as_text=True)
        check(
            'BRUI-05: multiple-choice controls render without problem selector chips',
            r.status_code == 200
            and 'name="selected_option_id"' in html
            and 'problem chip' not in html.lower()
            and 'prob-btn-' not in html,
        )
        r = client.post(
            f'/boss-rush/game/{mc_ctx["session_id"]}/answer',
            data={'selected_option_id': mc_ctx['correct_option_id']},
            follow_redirects=True,
        )
        check(
            'BRUI-06: multiple-choice answer still submits through redesigned page',
            r.status_code == 200 and 'Correct. You dealt 1 damage.' in r.get_data(as_text=True),
        )

        expected_theme_classes = {
            'fire_giant': 'boss-theme-fire-giant',
            'air_elemental': 'boss-theme-air-elemental',
            'mirror_phantom': 'boss-theme-mirror-phantom',
            'swamp_monster': 'boss-theme-swamp-monster',
            'stone_golem': 'boss-theme-stone-golem',
            'time_wraith': 'boss-theme-time-wraith',
        }
        expected_backgrounds = {
            'fire_giant': 'background_fire_giant.png',
            'air_elemental': 'background_air_elemental.png',
            'mirror_phantom': 'background_mirror_cave.png',
            'swamp_monster': 'background_mud_monster.png',
            'stone_golem': 'background_stone_golem.png',
            'time_wraith': 'background_time_keeper.png',
        }
        all_themes_render = True
        for boss_type, ctx in theme_contexts.items():
            client.get('/logout')
            _login(client, ctx['username'])
            r = client.get(f'/boss-rush/game/{ctx["session_id"]}')
            html = r.get_data(as_text=True)
            all_themes_render = all_themes_render and (
                r.status_code == 200
                and expected_theme_classes[boss_type] in html
                and expected_backgrounds[boss_type] in html
                and 'boss-battle-shell' in html
                and 'data-ability-timer-fill' in html
            )
        check('BRUI-07: all six non-Hydra boss themes render in the shared layout', all_themes_render)
        check(
            'BRUI-08: Mirror and Time bosses use their dedicated images',
            boss_catalog_entry('mirror_phantom')['image_path'] == 'boss_rush/bosses/mirror_boss.png'
            and boss_catalog_entry('time_wraith')['image_path'] == 'boss_rush/bosses/time_boss.png',
        )


if __name__ == '__main__':
    print('\nBoss Rush Player UI Layout - Tests')
    print('-' * 60)
    run_tests()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL BOSS RUSH PLAYER UI LAYOUT TESTS PASSED.')
    else:
        print('SOME BOSS RUSH PLAYER UI LAYOUT TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
