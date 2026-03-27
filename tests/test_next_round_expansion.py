"""
test_next_round_expansion.py
============================

Focused regression tests for the expanded next-round setup.

Confirms:
  1. Between-round form (manage page) exposes all editable round config fields
  2. Previous round config values appear as defaults in the form
  3. Changing settings produces a new round with the updated config
  4. Problem set change still works
  5. carry_over_gold and carry_over_gems still work
  6. Unchanged fields remain stable when admin keeps defaults
  7. Session/round lifecycle remains stable

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_next_round_expansion.py
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
from app.models.classic import ClassicRoundConfig, PlayerWallet
from app.models.history import RoundHistory, RoundPlayerResult

flask_app = create_app()
flask_app.config['WTF_CSRF_ENABLED'] = False
flask_app.config['TESTING'] = True

SET_NAME  = '__test_nre__'
SET_NAME2 = '__test_nre2__'
_ADMIN    = '__nre_admin__'
_PLAYER   = '__nre_player__'

# Config fields that map 1:1 between form and ClassicRoundConfig
CONFIG_FIELDS = (
    'mine_reward', 'treasure_search_reward', 'attempts_per_problem',
    'wrong_answer_penalty', 'bonus_timer_duration', 'bonus_timer_gold',
    'first_solver_count', 'first_solver_multiplier',
    'treasure_search_max_reward', 'gem_milestone_count', 'gem_streak_count',
    'gem_treasure_chance', 'steal_percent', 'steal_min_cap', 'steal_max_cap',
    'steal_fallback_gold', 'steal_chest_count', 'steal_winning_chest_count',
    'shield_duration', 'treasure_steal_token_chance',
)

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
    """Remove all test artefacts from the DB."""
    with db.session.no_autoflush:
        for sn in (SET_NAME, SET_NAME2):
            ps = ProblemSet.query.filter_by(name=sn).first()
            if not ps:
                continue
            for gs in GameSession.query.filter_by(problem_set_id=ps.id).all():
                # Delete history rows first (FK to game_round / game_session)
                for rh in RoundHistory.query.filter_by(session_id=gs.id).all():
                    RoundPlayerResult.query.filter_by(round_history_id=rh.id).delete()
                    db.session.delete(rh)
                for gr in GameRound.query.filter_by(session_id=gs.id).all():
                    ClassicRoundConfig.query.filter_by(round_id=gr.id).delete()
                    db.session.delete(gr)
                PlayerWallet.query.filter_by(session_id=gs.id).delete()
                db.session.delete(gs)
            db.session.flush()
            for prob in list(ps.problems):
                ps.problems.remove(prob)
            db.session.flush()
            for prob in Problem.query.filter(Problem.title.like('NRE P%')).all():
                db.session.execute(db.text('DELETE FROM player_problem_state WHERE problem_id = :pid'), {'pid': prob.id})
                db.session.execute(db.text('DELETE FROM problem_solver_count WHERE problem_id = :pid'), {'pid': prob.id})
                db.session.delete(prob)
            db.session.delete(ps)
        db.session.flush()
        for uname in (_ADMIN, _PLAYER):
            p = Player.query.filter_by(username=uname).first()
            if p:
                db.session.delete(p)
    db.session.commit()


def _login(client):
    """Log in as the test admin user."""
    client.post('/login', data={'username': _ADMIN, 'password': 'x'}, follow_redirects=True)


def _delete_session(gs_id):
    """Delete a test session and all its dependent rows (no_autoflush safe)."""
    with db.session.no_autoflush:
        for rh in RoundHistory.query.filter_by(session_id=gs_id).all():
            RoundPlayerResult.query.filter_by(round_history_id=rh.id).delete()
            db.session.delete(rh)
        for gr in GameRound.query.filter_by(session_id=gs_id).all():
            ClassicRoundConfig.query.filter_by(round_id=gr.id).delete()
            db.session.delete(gr)
        PlayerWallet.query.filter_by(session_id=gs_id).delete()
        gs = db.session.get(GameSession, gs_id)
        if gs:
            db.session.delete(gs)
    db.session.commit()


def _create_session_with_ended_round(ps, config_overrides=None):
    """Create a classic session with one ended round + config. Returns (session, round, config)."""
    gs = GameSession(mode='classic', status='waiting', problem_set_id=ps.id)
    db.session.add(gs)
    db.session.flush()

    gr = GameRound(session_id=gs.id, round_number=1, started_at=_now(), ended_at=_now())
    db.session.add(gr)
    db.session.flush()

    defaults = dict(
        round_id=gr.id,
        mine_reward=20,
        treasure_search_reward=5,
        attempts_per_problem=1,
        wrong_answer_penalty=0,
        bonus_timer_duration=120,
        bonus_timer_gold=5,
        first_solver_count=3,
        first_solver_multiplier=2,
        treasure_search_max_reward=5,
        gem_milestone_count=5,
        gem_streak_count=3,
        gem_treasure_chance=0.10,
        steal_percent=0.10,
        steal_min_cap=10,
        steal_max_cap=50,
        steal_fallback_gold=5,
        steal_chest_count=2,
        steal_winning_chest_count=1,
        shield_duration=60,
        treasure_steal_token_chance=0.0,
    )
    if config_overrides:
        defaults.update(config_overrides)
    cfg = ClassicRoundConfig(**defaults)
    db.session.add(cfg)
    db.session.commit()
    return gs, gr, cfg


def _build_next_round_data(old_cfg, overrides=None):
    """Build POST data for next_round, defaulting to old config values."""
    data = {
        'carry_over_gold': 'y',
        'carry_over_gems': 'y',
        'problem_set_id': str(old_cfg.round.session.problem_set_id),
    }
    for f in CONFIG_FIELDS:
        data[f] = str(getattr(old_cfg, f))
    if overrides:
        data.update(overrides)
    return data


with flask_app.app_context():
    _clean()

    # Create test users
    admin = Player(username=_ADMIN, is_admin=True)
    admin.set_password('x')
    db.session.add(admin)

    player = Player(username=_PLAYER, is_admin=False)
    player.set_password('x')
    db.session.add(player)
    db.session.flush()

    # Create problem sets
    topic = Topic.query.first()
    if not topic:
        topic = Topic(name='NRE_topic')
        db.session.add(topic)
        db.session.flush()

    ps1 = ProblemSet(name=SET_NAME)
    db.session.add(ps1)
    db.session.flush()
    prob1 = Problem(title='NRE P1', prompt_text='1+1?', answer_text='2', topic_id=topic.id)
    db.session.add(prob1)
    db.session.flush()
    ps1.problems.append(prob1)

    ps2 = ProblemSet(name=SET_NAME2)
    db.session.add(ps2)
    db.session.flush()
    prob2 = Problem(title='NRE P2', prompt_text='2+2?', answer_text='4', topic_id=topic.id)
    db.session.add(prob2)
    db.session.flush()
    ps2.problems.append(prob2)
    db.session.commit()

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 1: manage page exposes all config fields (pre-filled)
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Between-round form field exposure ──────────────────────')

    gs1, gr1, cfg1 = _create_session_with_ended_round(ps1, {
        'mine_reward': 42,
        'bonus_timer_gold': 99,
        'steal_percent': 0.25,
        'shield_duration': 180,
    })

    with flask_app.test_client() as client:
        _login(client)

        resp = client.get(f'/admin/classic/{gs1.id}/manage')
        html = resp.data.decode()

        # NRE-01: Page renders correctly (200)
        check('NRE-01: manage page returns 200', resp.status_code == 200)

        # NRE-02: Config fields present in the form HTML
        for f in CONFIG_FIELDS:
            check(f'NRE-02: field "{f}" in form HTML',
                  f'name="{f}"' in html,
                  f'missing name="{f}"')

        # NRE-03: Pre-filled values from previous config
        check('NRE-03a: mine_reward pre-filled with 42',
              'value="42"' in html, 'mine_reward value not found')
        check('NRE-03b: bonus_timer_gold pre-filled with 99',
              'value="99"' in html, 'bonus_timer_gold value not found')
        check('NRE-03c: shield_duration pre-filled with 180',
              'value="180"' in html, 'shield_duration value not found')
        check('NRE-03d: steal_percent pre-filled with 0.25',
              'value="0.25"' in html, 'steal_percent value not found')

        # NRE-04: Carry-over checkboxes present
        check('NRE-04a: carry_over_gold in form',
              'name="carry_over_gold"' in html)
        check('NRE-04b: carry_over_gems in form',
              'name="carry_over_gems"' in html)

        # NRE-05: Round Settings section present
        check('NRE-05: Round Settings section present',
              'Round Settings' in html)

    _delete_session(gs1.id)

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 2: Submitting changed settings produces correct new config
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Changed settings applied to new round ──────────────────')

    gs2, gr2, cfg2 = _create_session_with_ended_round(ps1, {
        'mine_reward': 20,
        'treasure_search_reward': 5,
        'bonus_timer_duration': 120,
        'steal_percent': 0.10,
        'shield_duration': 60,
    })

    with flask_app.test_client() as client:
        _login(client)

        # Submit with changed values
        post_data = _build_next_round_data(cfg2, {
            'mine_reward': '50',
            'bonus_timer_duration': '300',
            'steal_percent': '0.35',
            'shield_duration': '200',
            'first_solver_count': '5',
            'gem_treasure_chance': '0.5',
        })

        resp = client.post(f'/admin/classic/{gs2.id}/next_round',
                           data=post_data, follow_redirects=False)
        check('NRE-06: next_round returns 302', resp.status_code == 302)

        # Verify new round was created with updated config
        new_round = GameRound.query.filter_by(
            session_id=gs2.id
        ).order_by(GameRound.round_number.desc()).first()

        check('NRE-07: new round created (round_number=2)',
              new_round is not None and new_round.round_number == 2,
              f'round={new_round.round_number if new_round else None}')

        new_cfg = new_round.classic_config
        check('NRE-08: new config exists', new_cfg is not None)

        if new_cfg:
            check('NRE-09a: mine_reward changed to 50',
                  new_cfg.mine_reward == 50, f'got {new_cfg.mine_reward}')
            check('NRE-09b: bonus_timer_duration changed to 300',
                  new_cfg.bonus_timer_duration == 300, f'got {new_cfg.bonus_timer_duration}')
            check('NRE-09c: steal_percent changed to 0.35',
                  abs(new_cfg.steal_percent - 0.35) < 0.001, f'got {new_cfg.steal_percent}')
            check('NRE-09d: shield_duration changed to 200',
                  new_cfg.shield_duration == 200, f'got {new_cfg.shield_duration}')
            check('NRE-09e: first_solver_count changed to 5',
                  new_cfg.first_solver_count == 5, f'got {new_cfg.first_solver_count}')
            check('NRE-09f: gem_treasure_chance changed to 0.5',
                  abs(new_cfg.gem_treasure_chance - 0.5) < 0.001, f'got {new_cfg.gem_treasure_chance}')

        # Verify session is now active
        db.session.refresh(gs2)
        check('NRE-10: session is active after next_round',
              gs2.status == 'active', f'got {gs2.status}')

    _delete_session(gs2.id)

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 3: Unchanged defaults stay stable
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Unchanged defaults remain stable ───────────────────────')

    gs3, gr3, cfg3 = _create_session_with_ended_round(ps1, {
        'mine_reward': 77,
        'treasure_search_reward': 12,
        'treasure_search_max_reward': 12,
        'bonus_timer_gold': 33,
        'steal_min_cap': 15,
        'steal_max_cap': -1,
        'gem_streak_count': 7,
    })

    with flask_app.test_client() as client:
        _login(client)

        # Submit with ALL defaults unchanged (use exact old config values)
        post_data = _build_next_round_data(cfg3)

        resp = client.post(f'/admin/classic/{gs3.id}/next_round',
                           data=post_data, follow_redirects=False)
        check('NRE-11: next_round returns 302', resp.status_code == 302)

        new_round = GameRound.query.filter_by(
            session_id=gs3.id
        ).order_by(GameRound.round_number.desc()).first()
        new_cfg = new_round.classic_config if new_round else None

        if new_cfg:
            check('NRE-12a: mine_reward preserved (77)',
                  new_cfg.mine_reward == 77, f'got {new_cfg.mine_reward}')
            check('NRE-12b: treasure_search_reward preserved (12)',
                  new_cfg.treasure_search_reward == 12, f'got {new_cfg.treasure_search_reward}')
            check('NRE-12c: bonus_timer_gold preserved (33)',
                  new_cfg.bonus_timer_gold == 33, f'got {new_cfg.bonus_timer_gold}')
            check('NRE-12d: steal_min_cap preserved (15)',
                  new_cfg.steal_min_cap == 15, f'got {new_cfg.steal_min_cap}')
            check('NRE-12e: steal_max_cap preserved (-1)',
                  new_cfg.steal_max_cap == -1, f'got {new_cfg.steal_max_cap}')
            check('NRE-12f: gem_streak_count preserved (7)',
                  new_cfg.gem_streak_count == 7, f'got {new_cfg.gem_streak_count}')
            # Also check fields that had original defaults
            check('NRE-12g: wrong_answer_penalty preserved (0)',
                  new_cfg.wrong_answer_penalty == 0, f'got {new_cfg.wrong_answer_penalty}')
            check('NRE-12h: attempts_per_problem preserved (1)',
                  new_cfg.attempts_per_problem == 1, f'got {new_cfg.attempts_per_problem}')
        else:
            check('NRE-12: new config exists', False, 'no config')

    _delete_session(gs3.id)

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 4: Problem set change still works
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Problem set change ─────────────────────────────────────')

    gs4, gr4, cfg4 = _create_session_with_ended_round(ps1)

    with flask_app.test_client() as client:
        _login(client)

        post_data = _build_next_round_data(cfg4, {
            'problem_set_id': str(ps2.id),
        })

        resp = client.post(f'/admin/classic/{gs4.id}/next_round',
                           data=post_data, follow_redirects=False)
        check('NRE-13: next_round returns 302', resp.status_code == 302)

        db.session.refresh(gs4)
        check('NRE-14: problem_set_id updated to ps2',
              gs4.problem_set_id == ps2.id,
              f'got ps_id={gs4.problem_set_id}, expected {ps2.id}')

    _delete_session(gs4.id)

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 5: carry_over_gold and carry_over_gems
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Carry-over controls ────────────────────────────────────')

    gs5, gr5, cfg5 = _create_session_with_ended_round(ps1)

    # Give the player a wallet with gold and gems
    wallet = PlayerWallet(session_id=gs5.id, player_id=player.id, gold=100, gems=10)
    db.session.add(wallet)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client)

        # Test: carry_over_gold=False, carry_over_gems=True
        post_data = _build_next_round_data(cfg5)
        del post_data['carry_over_gold']  # uncheck = absent from form
        # carry_over_gems stays 'y'

        resp = client.post(f'/admin/classic/{gs5.id}/next_round',
                           data=post_data, follow_redirects=False)
        check('NRE-15: next_round returned 302', resp.status_code == 302)

        db.session.refresh(wallet)
        check('NRE-16: gold reset to 0 (carry_over_gold=False)',
              wallet.gold == 0, f'got gold={wallet.gold}')
        check('NRE-17: gems preserved (carry_over_gems=True)',
              wallet.gems == 10, f'got gems={wallet.gems}')

    # End round 2 to test gems reset
    r2 = GameRound.query.filter_by(
        session_id=gs5.id
    ).order_by(GameRound.round_number.desc()).first()
    r2.ended_at = _now()
    gs5.status = 'waiting'
    wallet.gold = 50  # give some gold back
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client)

        # Get old config for round 2
        cfg5b = r2.classic_config
        post_data = _build_next_round_data(cfg5b)
        del post_data['carry_over_gems']  # uncheck gems
        # carry_over_gold stays 'y'

        resp = client.post(f'/admin/classic/{gs5.id}/next_round',
                           data=post_data, follow_redirects=False)
        check('NRE-18: next_round returned 302', resp.status_code == 302)

        db.session.refresh(wallet)
        check('NRE-19: gold preserved (carry_over_gold=True)',
              wallet.gold == 50, f'got gold={wallet.gold}')
        check('NRE-20: gems reset to 0 (carry_over_gems=False)',
              wallet.gems == 0, f'got gems={wallet.gems}')

    _delete_session(gs5.id)

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 6: Validation — cross-field constraints
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Validation (cross-field) ────────────────────────────────')

    gs6, gr6, cfg6 = _create_session_with_ended_round(ps1)

    with flask_app.test_client() as client:
        _login(client)

        # treasure_search_max_reward < treasure_search_reward → should fail
        post_data = _build_next_round_data(cfg6, {
            'treasure_search_reward': '10',
            'treasure_search_max_reward': '3',
        })

        resp = client.post(f'/admin/classic/{gs6.id}/next_round',
                           data=post_data, follow_redirects=True)
        html = resp.data.decode()
        check('NRE-21: max < min validation rejects',
              'must be >=' in html.lower() or 'Max' in html,
              'expected validation error flash')

        # Verify no new round was created
        rounds = GameRound.query.filter_by(session_id=gs6.id).count()
        check('NRE-22: no new round created on validation failure',
              rounds == 1, f'got {rounds} rounds')

        # steal_winning_chest_count > steal_chest_count → should fail
        post_data = _build_next_round_data(cfg6, {
            'steal_chest_count': '2',
            'steal_winning_chest_count': '5',
        })

        resp2 = client.post(f'/admin/classic/{gs6.id}/next_round',
                            data=post_data, follow_redirects=True)
        html2 = resp2.data.decode()
        check('NRE-23: winning > total chests validation rejects',
              'must be <=' in html2.lower() or 'Winning' in html2,
              'expected validation error flash')

    _delete_session(gs6.id)

    # ══════════════════════════════════════════════════════════════════════
    # TEST GROUP 7: Session/round lifecycle stability
    # ══════════════════════════════════════════════════════════════════════
    print('\n── Lifecycle stability ────────────────────────────────────')

    gs7, gr7, cfg7 = _create_session_with_ended_round(ps1)

    with flask_app.test_client() as client:
        _login(client)

        # Start next round
        post_data = _build_next_round_data(cfg7, {'mine_reward': '99'})
        resp = client.post(f'/admin/classic/{gs7.id}/next_round',
                           data=post_data, follow_redirects=False)
        check('NRE-24: next_round returns 302', resp.status_code == 302)

        db.session.refresh(gs7)
        check('NRE-25: session active', gs7.status == 'active')

        r2 = GameRound.query.filter_by(
            session_id=gs7.id
        ).order_by(GameRound.round_number.desc()).first()
        check('NRE-26: round 2 has started_at', r2.started_at is not None)
        check('NRE-27: round 2 not ended yet', r2.ended_at is None)

        # End the round
        resp2 = client.post(f'/admin/classic/{gs7.id}/end',
                            follow_redirects=False)
        check('NRE-28: end_round returns 302', resp2.status_code == 302)

        db.session.refresh(gs7)
        check('NRE-29: session waiting after end_round',
              gs7.status == 'waiting', f'got {gs7.status}')
        db.session.refresh(r2)
        check('NRE-30: round 2 ended', r2.ended_at is not None)

        # Manage page should show next-round form again
        resp3 = client.get(f'/admin/classic/{gs7.id}/manage')
        html3 = resp3.data.decode()
        check('NRE-31: next-round form present after end_round',
              'Start Next Round' in html3)

        # Verify round 2 config shows the value we set
        cfg_r2 = r2.classic_config
        check('NRE-32: round 2 mine_reward is 99',
              cfg_r2.mine_reward == 99, f'got {cfg_r2.mine_reward}')

        # Round 2 config should be pre-filled in the form
        check('NRE-33: manage form pre-fills mine_reward=99 from round 2',
              'value="99"' in html3, 'mine_reward=99 not pre-filled')

    _delete_session(gs7.id)

    # ══════════════════════════════════════════════════════════════════════
    _clean()

    print(f'\n{"=" * 60}')
    print(f'Next-round expansion results: {passed} passed, {failed} failed')
    if failed:
        print('SOME TESTS FAILED.')
        sys.exit(1)
    else:
        print('ALL TESTS PASSED.')
        sys.exit(0)
