"""
test_end_session_redirect.py
============================

Focused test for the end_session redirect fix.

Confirms:
  1. end_session() redirects to classic_admin.index (not back to manage page)
  2. When no live session exists, index redirects to new_session setup form
  3. When a live session exists, index redirects to its manage page

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_end_session_redirect.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game import GameSession, GameRound
from app.models.classic import ClassicRoundConfig

flask_app = create_app()
flask_app.config['WTF_CSRF_ENABLED'] = False
flask_app.config['TESTING'] = True

SET_NAME = '__test_esr__'
_ADMIN   = '__esr_admin__'

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


def _now():
    return datetime.now(timezone.utc)


def _clean():
    ps = ProblemSet.query.filter_by(name=SET_NAME).first()
    for gs in GameSession.query.filter_by(mode='classic').all():
        if gs.problem_set and gs.problem_set.name == SET_NAME:
            for gr in GameRound.query.filter_by(session_id=gs.id).all():
                ClassicRoundConfig.query.filter_by(round_id=gr.id).delete()
                db.session.delete(gr)
            db.session.delete(gs)
    db.session.flush()
    if ps:
        for prob in ps.problems.all():
            ps.problems.remove(prob)
        db.session.flush()
        for prob in Problem.query.filter(Problem.title.like('ESR P%')).all():
            db.session.execute(db.text('DELETE FROM player_problem_state WHERE problem_id = :pid'), {'pid': prob.id})
            db.session.execute(db.text('DELETE FROM problem_solver_count WHERE problem_id = :pid'), {'pid': prob.id})
            db.session.delete(prob)
        db.session.delete(ps)
    db.session.flush()
    p = Player.query.filter_by(username=_ADMIN).first()
    if p:
        db.session.delete(p)
    db.session.commit()


with flask_app.app_context():
    _clean()

    # Create admin user
    admin = Player(username=_ADMIN, is_admin=True)
    admin.set_password('x')
    db.session.add(admin)
    db.session.flush()

    # Create a problem set (needed for new_session form)
    topic = Topic.query.first()
    if not topic:
        topic = Topic(name='ESR_topic')
        db.session.add(topic)
        db.session.flush()
    ps = ProblemSet(name=SET_NAME)
    db.session.add(ps)
    db.session.flush()
    prob = Problem(title='ESR P1', prompt_text='1+1?', answer_text='2', topic_id=topic.id)
    db.session.add(prob)
    db.session.flush()
    ps.problems.append(prob)
    db.session.flush()

    # Create an active session
    gs = GameSession(mode='classic', status='active', problem_set_id=ps.id)
    db.session.add(gs)
    db.session.flush()
    sid = gs.id

    gr = GameRound(session_id=sid, round_number=1, started_at=_now())
    db.session.add(gr)
    db.session.flush()
    cfg = ClassicRoundConfig(round_id=gr.id)
    db.session.add(cfg)
    db.session.commit()

    # ── Test with Flask test client ──────────────────────────────────────

    with flask_app.test_client() as client:
        # Log in as admin
        client.post('/login', data={
            'username': _ADMIN, 'password': 'x',
        }, follow_redirects=True)

        print('\n-- End session redirect --------------------------------------------')

        # 1. end_session should redirect to new_session form (not index, to avoid
        #    landing on stale live sessions — see stale-session routing fix).
        resp = client.post(f'/admin/classic/{sid}/end_session', follow_redirects=False)
        check('ESR-01: end_session returns redirect (302)',
              resp.status_code == 302, f'status={resp.status_code}')
        location = resp.headers.get('Location', '')
        check('ESR-02: redirect target is new_session form (/admin/classic/new)',
              location.rstrip('/').endswith('/admin/classic/new'),
              f'location={location}')

        # Verify session is now finished
        db.session.refresh(gs)
        check('ESR-03: session status is finished', gs.status == 'finished')

        print('\n-- Index routing after session ended ------------------------------')

        # 2. No live session exists -> index should redirect to new_session
        #    Ensure no stale waiting/active classic sessions from other tests.
        for stale in GameSession.query.filter(
            GameSession.mode == 'classic',
            GameSession.status.in_(['waiting', 'active']),
        ).all():
            stale.status = 'finished'
        db.session.commit()

        resp2 = client.get('/admin/classic/', follow_redirects=False)
        check('ESR-04: index returns redirect (302)',
              resp2.status_code == 302, f'status={resp2.status_code}')
        loc2 = resp2.headers.get('Location', '')
        check('ESR-05: index redirects to new_session when no live session',
              '/new' in loc2, f'location={loc2}')

        print('\n-- Index routing with live session --------------------------------')

        # 3. Create a new waiting session -> index should go to manage
        gs2 = GameSession(mode='classic', status='waiting', problem_set_id=ps.id)
        db.session.add(gs2)
        db.session.commit()

        resp3 = client.get('/admin/classic/', follow_redirects=False)
        check('ESR-06: index returns redirect (302)',
              resp3.status_code == 302, f'status={resp3.status_code}')
        loc3 = resp3.headers.get('Location', '')
        check('ESR-07: index redirects to manage when live session exists',
              f'/{gs2.id}' in loc3, f'location={loc3}')

    # Cleanup
    _clean()

    print(f'\n{"=" * 60}')
    print(f'End-session redirect results: {passed} passed, {failed} failed')
    if failed:
        print('SOME TESTS FAILED.')
        sys.exit(1)
    else:
        print('ALL TESTS PASSED.')
        sys.exit(0)
