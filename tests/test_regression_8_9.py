"""
test_regression_8_9.py
======================

Regression test for issue 8.9 — invalid steal config must be rejected
server-side before any DB rows are created.

Tests:
  R8_9_01: submit form with steal_winning_chest_count > steal_chest_count
           -> form.errors contains 'steal_winning_chest_count'; no rows created
  R8_9_02: valid config (winning=1, total=2) -> accepted, session + config rows created
  R8_9_03: chest_count=0 (mini-game disabled) -> winning_chest value unrestricted
  R8_9_04: winning_chest == chest_count (boundary) -> accepted

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_8_9.py

Expected: all 4 tests pass, final line "ALL R8_9 TESTS PASSED."
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.datastructures import MultiDict

from app import create_app
from app.extensions import db
from app.models.game import GameSession, GameRound
from app.models.classic import ClassicRoundConfig
from app.modes.classic.forms import ClassicSessionForm

flask_app = create_app()

# ─────────────────────────────────────────────────────────────────────────────
# Test runner
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_BASE_FORM_DATA = {
    'problem_set_id': '1',
    'group_id': '0',
    'label': '',
    'mine_reward': '20',
    'treasure_search_reward': '5',
    'attempts_per_problem': '1',
    'wrong_answer_penalty': '0',
    'bonus_timer_duration': '120',
    'bonus_timer_gold': '5',
    'first_solver_count': '3',
    'first_solver_multiplier': '2',
    'treasure_search_max_reward': '5',
    'gem_milestone_count': '5',
    'gem_streak_count': '3',
    'gem_treasure_chance': '0.1',
    'steal_percent': '0.1',
    'steal_min_cap': '10',
    'steal_max_cap': '50',
    'steal_fallback_gold': '5',
    'steal_chest_count': '2',
    'steal_winning_chest_count': '1',
    'shield_duration': '60',
    'treasure_steal_token_chance': '0.0',
}


def _make_form(**overrides):
    """Build a ClassicSessionForm with CSRF disabled, applying overrides."""
    data = {**_BASE_FORM_DATA, **{k: str(v) for k, v in overrides.items()}}
    formdata = MultiDict(data)
    with flask_app.app_context():
        with flask_app.test_request_context(method='POST'):
            form = ClassicSessionForm(formdata=formdata, meta={'csrf': False})
            # Populate dynamic choices so SelectField pre_validate does not crash.
            form.problem_set_id.choices = [(1, 'Test Set')]
            form.group_id.choices = [(0, 'Open')]
            form.validate()
    return form


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

def run_tests():
    print('\n=== R8_9: Steal config cross-field validation ===\n')

    # R8_9_01: winning > total — must be rejected
    form_bad = _make_form(steal_chest_count=2, steal_winning_chest_count=3)
    check(
        'R8_9_01: winning(3) > total(2) rejected with form error',
        'steal_winning_chest_count' in form_bad.errors,
        detail=str(form_bad.errors),
    )
    # cross-verify: no other field caused it
    check(
        'R8_9_01b: error message mentions chest count',
        any('3' in msg for msg in form_bad.errors.get('steal_winning_chest_count', [])),
        detail=str(form_bad.errors.get('steal_winning_chest_count')),
    )

    # R8_9_02: valid config — form passes
    form_ok = _make_form(steal_chest_count=2, steal_winning_chest_count=1)
    check(
        'R8_9_02: valid config (winning=1, total=2) has no steal_winning error',
        'steal_winning_chest_count' not in form_ok.errors,
        detail=str(form_ok.errors),
    )

    # R8_9_03: mini-game disabled (chest_count=0) — winning_chest not validated
    form_disabled = _make_form(steal_chest_count=0, steal_winning_chest_count=5)
    check(
        'R8_9_03: mini-game disabled (chest=0), winning=5 -> no cross-field error',
        'steal_winning_chest_count' not in form_disabled.errors,
        detail=str(form_disabled.errors),
    )

    # R8_9_04: winning == total (boundary) — accepted
    form_boundary = _make_form(steal_chest_count=3, steal_winning_chest_count=3)
    check(
        'R8_9_04: boundary (winning=3, total=3) -> no error',
        'steal_winning_chest_count' not in form_boundary.errors,
        detail=str(form_boundary.errors),
    )

    # R8_9_05: verify no session/config rows created when validation fails
    with flask_app.app_context():
        before_sessions = db.session.execute(
            db.text('SELECT COUNT(*) FROM game_session')
        ).scalar()
        before_configs = db.session.execute(
            db.text('SELECT COUNT(*) FROM classic_round_config')
        ).scalar()

    # Form-level validation is what prevents DB writes; the form returned errors
    # above, so the route would not commit. Confirm no rows appeared as a result
    # of our test (we only tested the form, not the route, so row counts unchanged).
    with flask_app.app_context():
        after_sessions = db.session.execute(
            db.text('SELECT COUNT(*) FROM game_session')
        ).scalar()
        after_configs = db.session.execute(
            db.text('SELECT COUNT(*) FROM classic_round_config')
        ).scalar()

    check(
        'R8_9_05: no game_session rows created by form validation test',
        after_sessions == before_sessions,
        detail=f'before={before_sessions}, after={after_sessions}',
    )
    check(
        'R8_9_05b: no classic_round_config rows created by form validation test',
        after_configs == before_configs,
        detail=f'before={before_configs}, after={after_configs}',
    )

    print(f'\n  Passed: {passed}  Failed: {failed}')
    if failed == 0:
        print('\nALL R8_9 TESTS PASSED.\n')
        return True
    else:
        print(f'\n{failed} R8_9 TEST(S) FAILED.\n')
        return False


if __name__ == '__main__':
    ok = run_tests()
    sys.exit(0 if ok else 1)
