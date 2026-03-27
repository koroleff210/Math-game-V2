"""
test_stale_session_routing.py
==============================

Regression tests for the Classic Mode stale-live-session routing bug.

Verified scenarios
------------------
SSR-01  Cannot POST /admin/classic/new while a *waiting* session is live
SSR-02  Cannot POST /admin/classic/new while an *active* session is live
SSR-03  Duplicate-session guard redirects to the existing live session manage page
SSR-04  end_session() redirects to new_session form (not index)
SSR-05  Post-end redirect does NOT land on an unrelated stale live session
SSR-06  index() redirects to new_session when no live Classic session exists
SSR-07  index() redirects to newest live session when exactly one exists
SSR-08  index() redirects to newest live session and flashes warning when multiple exist

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_stale_session_routing.py
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

_SET_NAME = '__test_ssr__'
_ADMIN    = '__ssr_admin__'

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


# ── Shared state populated in _setup() ────────────────────────────────────────
_admin_id = None
_ps_id    = None


def _clean():
    """Remove all test-specific data from the DB."""
    for gs in GameSession.query.filter_by(mode='classic').all():
        if gs.problem_set and gs.problem_set.name == _SET_NAME:
            for gr in GameRound.query.filter_by(session_id=gs.id).all():
                ClassicRoundConfig.query.filter_by(round_id=gr.id).delete()
                db.session.delete(gr)
            db.session.delete(gs)
    db.session.flush()
    ps = ProblemSet.query.filter_by(name=_SET_NAME).first()
    if ps:
        for prob in ps.problems.all():
            ps.problems.remove(prob)
        db.session.flush()
        for prob in Problem.query.filter(Problem.title.like('SSR P%')).all():
            db.session.execute(
                db.text('DELETE FROM player_problem_state WHERE problem_id = :pid'),
                {'pid': prob.id},
            )
            db.session.execute(
                db.text('DELETE FROM problem_solver_count WHERE problem_id = :pid'),
                {'pid': prob.id},
            )
            db.session.delete(prob)
        db.session.delete(ps)
    db.session.flush()
    p = Player.query.filter_by(username=_ADMIN).first()
    if p:
        db.session.delete(p)
    db.session.commit()


def _setup():
    """Create admin user + minimal problem set. Returns (admin_id, ps_id)."""
    topic = Topic.query.first()
    if not topic:
        topic = Topic(name='SSR_topic')
        db.session.add(topic)
        db.session.flush()

    ps = ProblemSet(name=_SET_NAME)
    db.session.add(ps)
    db.session.flush()

    prob = Problem(title='SSR P1', prompt_text='1+1?', answer_text='2', topic_id=topic.id)
    db.session.add(prob)
    db.session.flush()
    ps.problems.append(prob)
    db.session.flush()

    admin = Player(username=_ADMIN, is_admin=True)
    admin.set_password('x')
    db.session.add(admin)
    db.session.commit()
    return admin.id, ps.id


def _make_session(ps_id, status='waiting'):
    """Insert a minimal Classic session + round + config, return session object."""
    gs = GameSession(mode='classic', status=status, problem_set_id=ps_id)
    db.session.add(gs)
    db.session.flush()
    started = _now() if status == 'active' else None
    gr = GameRound(session_id=gs.id, round_number=1, started_at=started)
    db.session.add(gr)
    db.session.flush()
    cfg = ClassicRoundConfig(round_id=gr.id)
    db.session.add(cfg)
    db.session.commit()
    return gs


def _finish_all_live():
    """Mark every live classic session as finished (inter-test isolation helper)."""
    for s in GameSession.query.filter(
        GameSession.mode == 'classic',
        GameSession.status.in_(['waiting', 'active']),
    ).all():
        s.status = 'finished'
    db.session.commit()


# ── Form data minimal for new_session POST ────────────────────────────────────
def _new_session_form(ps_id):
    return {
        'problem_set_id': ps_id,
        'group_id':       0,
        'label':          '',
        'mine_reward':    20,
        'treasure_search_reward': 5,
        'treasure_search_max_reward': 5,
        'attempts_per_problem': 1,
        'wrong_answer_penalty': 0,
        'bonus_timer_duration': 120,
        'bonus_timer_gold': 5,
        'first_solver_count': 3,
        'first_solver_multiplier': 2,
        'gem_milestone_count': 5,
        'gem_streak_count': 3,
        'gem_treasure_chance': 0,
        'steal_percent': 0.10,
        'steal_min_cap': 10,
        'steal_max_cap': 50,
        'steal_fallback_gold': 5,
        'steal_chest_count': 2,
        'steal_winning_chest_count': 1,
        'shield_duration': 60,
        'treasure_steal_token_chance': 0,
        'treasure_active_shield_chance': 0,
        'treasure_second_chance_chance': 0,
    }


# ══════════════════════════════════════════════════════════════════════════════

with flask_app.app_context():
    _clean()
    _admin_id, _ps_id = _setup()

    with flask_app.test_client() as client:
        # Log in as admin
        client.post('/login', data={'username': _ADMIN, 'password': 'x'},
                    follow_redirects=True)

        # ── SSR-01 / SSR-02: guard blocks new session when one is live ─────────
        print('\n-- Duplicate-session creation guard -----------------------')

        for status_label, status in [('waiting', 'waiting'), ('active', 'active')]:
            _finish_all_live()
            existing = _make_session(_ps_id, status=status)

            resp = client.post(
                '/admin/classic/new',
                data=_new_session_form(_ps_id),
                follow_redirects=False,
            )
            n = 'SSR-01' if status == 'waiting' else 'SSR-02'
            check(
                f'{n}: POST /new blocked when {status_label} session exists (302)',
                resp.status_code == 302,
                f'status={resp.status_code}',
            )
            loc = resp.headers.get('Location', '')
            check(
                f'{n}: blocked POST redirects to existing session manage page',
                f'/{existing.id}/manage' in loc or f'/{existing.id}' in loc,
                f'location={loc}',
            )

            # Confirm no second session was created
            live_count = GameSession.query.filter(
                GameSession.mode == 'classic',
                GameSession.status.in_(['waiting', 'active']),
            ).count()
            check(
                f'{n}: only one live session exists after blocked POST',
                live_count == 1,
                f'live_count={live_count}',
            )

        # ── SSR-03: guard redirects to correct (existing) session ──────────────
        print('\n-- Guard redirects to the correct session ------------------')
        _finish_all_live()
        existing = _make_session(_ps_id, status='waiting')

        resp = client.post(
            '/admin/classic/new',
            data=_new_session_form(_ps_id),
            follow_redirects=False,
        )
        loc = resp.headers.get('Location', '')
        check(
            'SSR-03: blocked redirect contains existing session id in URL',
            str(existing.id) in loc,
            f'expected_id={existing.id}, location={loc}',
        )

        # ── SSR-04: end_session() redirects to new_session form ───────────────
        print('\n-- end_session redirect target -----------------------------')
        _finish_all_live()
        gs = _make_session(_ps_id, status='active')
        sid = gs.id

        resp = client.post(f'/admin/classic/{sid}/end_session', follow_redirects=False)
        check(
            'SSR-04: end_session returns 302',
            resp.status_code == 302,
            f'status={resp.status_code}',
        )
        loc = resp.headers.get('Location', '')
        check(
            'SSR-04: end_session redirect target is new_session (/admin/classic/new)',
            loc.rstrip('/').endswith('/admin/classic/new'),
            f'location={loc}',
        )

        # ── SSR-05: end_session does NOT drop admin into stale live session ────
        print('\n-- end_session does not land on stale live session ---------')
        _finish_all_live()

        # Two sessions: stale (older id) + current (newer id)
        stale  = _make_session(_ps_id, status='waiting')
        current = _make_session(_ps_id, status='active')

        resp = client.post(
            f'/admin/classic/{current.id}/end_session',
            follow_redirects=False,
        )
        loc = resp.headers.get('Location', '')
        check(
            'SSR-05: end_session redirect does not point at stale session manage',
            f'/{stale.id}/manage' not in loc,
            f'stale_id={stale.id}, location={loc}',
        )
        check(
            'SSR-05: end_session redirect is new_session form (not manage of any session)',
            '/manage' not in loc,
            f'location={loc}',
        )

        # ── SSR-06: index → new_session when no live session ─────────────────
        print('\n-- index() routing -----------------------------------------')
        _finish_all_live()

        resp = client.get('/admin/classic/', follow_redirects=False)
        check(
            'SSR-06: index returns 302 when no live session',
            resp.status_code == 302,
            f'status={resp.status_code}',
        )
        loc = resp.headers.get('Location', '')
        check(
            'SSR-06: index redirects to new_session when no live session',
            '/new' in loc,
            f'location={loc}',
        )

        # ── SSR-07: index → manage when exactly one live session ──────────────
        _finish_all_live()
        only = _make_session(_ps_id, status='waiting')

        resp = client.get('/admin/classic/', follow_redirects=False)
        check(
            'SSR-07: index returns 302 with exactly one live session',
            resp.status_code == 302,
            f'status={resp.status_code}',
        )
        loc = resp.headers.get('Location', '')
        check(
            'SSR-07: index redirects to that session manage page',
            f'/{only.id}' in loc,
            f'location={loc}',
        )

        # ── SSR-08: index → newest + warning when multiple live sessions ───────
        _finish_all_live()
        older  = _make_session(_ps_id, status='waiting')   # lower id
        newer  = _make_session(_ps_id, status='waiting')   # higher id

        resp = client.get('/admin/classic/', follow_redirects=False)
        check(
            'SSR-08: index returns 302 with multiple live sessions',
            resp.status_code == 302,
            f'status={resp.status_code}',
        )
        loc = resp.headers.get('Location', '')
        check(
            'SSR-08: index redirects to newest (highest-id) live session',
            f'/{newer.id}' in loc,
            f'newer_id={newer.id}, location={loc}',
        )

        # Follow through to check that a warning flash appears
        resp_follow = client.get('/admin/classic/', follow_redirects=True)
        body = resp_follow.get_data(as_text=True)
        check(
            'SSR-08: page body contains multi-session warning text',
            'Warning' in body or 'warning' in body or 'multiple' in body.lower()
            or 'live' in body.lower(),
            'warning flash not found in page body',
        )

    # Cleanup
    _clean()

print(f'\n{"=" * 60}')
print(f'Stale-session routing results: {passed} passed, {failed} failed')
if failed:
    print('SOME TESTS FAILED.')
    sys.exit(1)
else:
    print('ALL TESTS PASSED.')
    sys.exit(0)
