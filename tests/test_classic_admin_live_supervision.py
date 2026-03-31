import atexit
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db, socketio
from app.models.player import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game import GameSession, GameRound, RoundPlayer
from app.models.classic import (
    ClassicRoundConfig,
    PlayerWallet,
    PlayerClassicState,
    PlayerProblemState,
    StoreItem,
)


_DB_FILE = tempfile.NamedTemporaryFile(
    prefix='classic_admin_live_supervision_',
    suffix='.sqlite3',
    delete=False,
)
_DB_FILE.close()


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{_DB_FILE.name.replace(os.sep, '/')}"
    SECRET_KEY = 'classic-admin-live-supervision-secret'
    WTF_CSRF_ENABLED = False
    SOCKETIO_ASYNC_MODE = 'threading'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOGIN_DISABLED = False


flask_app = create_app(_TestConfig)


@atexit.register
def _cleanup_db_file():
    try:
        os.remove(_DB_FILE.name)
    except OSError:
        pass

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

        admin = _make_player('__classic_admin_live_admin__', is_admin=True)
        player = _make_player('__classic_admin_live_player__')

        topic = Topic(name='__classic_admin_live_topic__')
        db.session.add(topic)
        db.session.flush()

        problem = Problem(
            topic_id=topic.id,
            title='Live Summary Problem',
            prompt_text='2 + 2 = ?',
            answer_text='4',
            difficulty=1,
        )
        db.session.add(problem)
        db.session.flush()

        problem_set = ProblemSet(name='__classic_admin_live_set__')
        db.session.add(problem_set)
        db.session.flush()
        problem_set.problems.append(problem)

        waiting_session = GameSession(
            mode='classic',
            status='waiting',
            problem_set_id=problem_set.id,
            label='Waiting Supervision Session',
        )
        db.session.add(waiting_session)
        db.session.flush()

        waiting_round = GameRound(
            session_id=waiting_session.id,
            round_number=1,
            started_at=None,
        )
        db.session.add(waiting_round)
        db.session.flush()
        db.session.add(ClassicRoundConfig(round_id=waiting_round.id))

        active_session = GameSession(
            mode='classic',
            status='active',
            problem_set_id=problem_set.id,
            label='Active Supervision Session',
            started_at=datetime.now(timezone.utc),
        )
        db.session.add(active_session)
        db.session.flush()

        active_round = GameRound(
            session_id=active_session.id,
            round_number=1,
            started_at=datetime.now(timezone.utc),
        )
        db.session.add(active_round)
        db.session.flush()
        db.session.add(
            ClassicRoundConfig(
                round_id=active_round.id,
                attempts_per_problem=2,
                steal_fallback_gold=7,
                steal_chest_count=0,
            )
        )

        db.session.add(RoundPlayer(session_id=active_session.id, player_id=admin.id))
        db.session.add(RoundPlayer(session_id=active_session.id, player_id=player.id))
        db.session.add(PlayerWallet(player_id=admin.id, session_id=active_session.id, gold=10, gems=0, steal_tokens=1))
        db.session.add(PlayerWallet(player_id=player.id, session_id=active_session.id, gold=20, gems=0, steal_tokens=0))
        db.session.add(PlayerClassicState(player_id=admin.id, session_id=active_session.id))
        db.session.add(PlayerClassicState(player_id=player.id, session_id=active_session.id))
        db.session.add(
            PlayerProblemState(
                player_id=admin.id,
                round_id=active_round.id,
                problem_id=problem.id,
                attempts_used=0,
                is_solved=False,
                is_closed=False,
            )
        )
        db.session.add(
            StoreItem(
                session_id=active_session.id,
                name='Live Summary Pickaxe',
                description='Store purchase leaderboard refresh test',
                cost=5,
                currency='gold',
                bonus_type='x2_mine',
                session_stock=-1,
                per_player_limit=-1,
                is_system=False,
            )
        )
        db.session.commit()

        _IDS.update(
            admin_id=admin.id,
            player_id=player.id,
            problem_id=problem.id,
            waiting_session_id=waiting_session.id,
            waiting_round_id=waiting_round.id,
            active_session_id=active_session.id,
            active_round_id=active_round.id,
        )


def test_manage_page_regions_and_live_updates():
    with flask_app.test_client() as admin_client:
        _login(admin_client, '__classic_admin_live_admin__')
        manage_resp = admin_client.get(f'/admin/classic/{_IDS["active_session_id"]}/manage')
        html = manage_resp.get_data(as_text=True)
        check(
            'CLS-01: manage page renders live supervision summary regions',
            manage_resp.status_code == 200
            and 'id="solve-counts-region"' in html
            and 'id="steal-history-region"' in html,
        )

        admin_socket = socketio.test_client(flask_app, flask_test_client=admin_client)
        check('CLS-02: admin socket connects', admin_socket.is_connected())
        admin_socket.emit('classic_admin_watch', {'session_id': _IDS['active_session_id']})
        admin_socket.get_received()

        admin_socket.emit('classic_submit_answer', {
            'session_id': _IDS['active_session_id'],
            'problem_id': _IDS['problem_id'],
            'answer_text': '4',
        })

        admin_events = admin_socket.get_received()
        summary_event = next((e for e in admin_events if e['name'] == 'admin_summary_update'), None)
        check(
            'CLS-03: solve counts summary updates live after a correct solve',
            summary_event is not None
            and str(_IDS['problem_id']) in summary_event['args'][0]['solve_counts_html']
            and '>1<' in summary_event['args'][0]['solve_counts_html'],
        )

        with flask_app.app_context():
            player_wallet = PlayerWallet.query.filter_by(
                player_id=_IDS['player_id'],
                session_id=_IDS['active_session_id'],
            ).first()
            if player_wallet:
                player_wallet.gold = 0
                db.session.commit()

        admin_socket.emit('classic_choose_action', {
            'session_id': _IDS['active_session_id'],
            'problem_id': _IDS['problem_id'],
            'action': 'steal',
        })

        admin_events = admin_socket.get_received()
        summary_event = next((e for e in admin_events if e['name'] == 'admin_summary_update'), None)
        check(
            'CLS-04: steal history summary updates live after steal resolution',
            summary_event is not None
            and 'no targets' in summary_event['args'][0]['steal_history_html'].lower()
            and '>7<' in summary_event['args'][0]['steal_history_html'],
        )


def test_round_start_pushes_empty_summary_reset():
    with flask_app.test_client() as admin_client:
        _login(admin_client, '__classic_admin_live_admin__')
        admin_socket = socketio.test_client(flask_app, flask_test_client=admin_client)
        check('CLS-05: admin socket connects for waiting session', admin_socket.is_connected())
        admin_socket.emit('classic_admin_watch', {'session_id': _IDS['waiting_session_id']})
        admin_socket.get_received()

        start_resp = admin_client.post(
            f'/admin/classic/{_IDS["waiting_session_id"]}/start',
            data={},
            follow_redirects=False,
        )
        check('CLS-06: start round still works', start_resp.status_code in (302, 303))

        admin_events = admin_socket.get_received()
        summary_event = next((e for e in admin_events if e['name'] == 'admin_summary_update'), None)
        check(
            'CLS-07: round start pushes fresh empty summary regions',
            summary_event is not None
            and 'No problems solved yet.' in summary_event['args'][0]['solve_counts_html']
            and 'No steal attempts yet.' in summary_event['args'][0]['steal_history_html'],
        )


def test_store_purchase_pushes_leaderboard_and_summary_refresh():
    with flask_app.test_client() as admin_client:
        _login(admin_client, '__classic_admin_live_admin__')

        with flask_app.app_context():
            buyer_wallet = PlayerWallet.query.filter_by(
                player_id=_IDS['admin_id'],
                session_id=_IDS['active_session_id'],
            ).first()
            if buyer_wallet:
                buyer_wallet.gold = 10
                db.session.commit()
            store_item = StoreItem.query.filter_by(
                session_id=_IDS['active_session_id'],
                name='Live Summary Pickaxe',
            ).first()
            item_id = store_item.id if store_item else 0

        admin_socket = socketio.test_client(flask_app, flask_test_client=admin_client)
        check('CLS-08: admin socket connects for store refresh watch', admin_socket.is_connected())
        admin_socket.emit('classic_admin_watch', {'session_id': _IDS['active_session_id']})
        admin_socket.get_received()
        check('CLS-09: watcher socket is ready for store purchase', admin_socket.is_connected())

        admin_socket.emit('classic_buy_item', {
            'session_id': _IDS['active_session_id'],
            'item_id': item_id,
        })

        events = admin_socket.get_received()
        buy_result = next((e for e in events if e['name'] == 'buy_result'), None)
        leaderboard_event = next((e for e in events if e['name'] == 'leaderboard_update'), None)
        summary_event = next((e for e in events if e['name'] == 'admin_summary_update'), None)

        check(
            'CLS-10: store purchase succeeds and buyer wallet updates immediately',
            buy_result is not None
            and buy_result['args'][0]['ok'] is True
            and buy_result['args'][0]['new_balance'] == 5,
        )
        check(
            'CLS-11: store purchase pushes immediate leaderboard refresh',
            leaderboard_event is not None
            and any(
                row['username'] == '__classic_admin_live_admin__' and row['gold'] == 5
                for row in leaderboard_event['args'][0].get('leaderboard', [])
            ),
        )
        check(
            'CLS-12: store purchase pushes admin summary refresh event',
            summary_event is not None,
        )


if __name__ == '__main__':
    print('\nClassic Admin Live Supervision - Tests')
    print('-' * 60)
    _setup_db()
    test_manage_page_regions_and_live_updates()
    test_round_start_pushes_empty_summary_reset()
    test_store_purchase_pushes_leaderboard_and_summary_refresh()
    print('-' * 60)
    print(f'Results: {passed} passed, {failed} failed out of {passed + failed} tests.')
    if failed == 0:
        print('ALL CLASSIC ADMIN LIVE SUPERVISION TESTS PASSED.')
    else:
        print('SOME CLASSIC ADMIN LIVE SUPERVISION TESTS FAILED.')
    sys.exit(0 if failed == 0 else 1)
