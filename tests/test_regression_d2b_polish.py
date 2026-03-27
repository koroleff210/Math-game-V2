"""
test_regression_d2b_polish.py
==============================

Regression tests for Step D2b — small UI polish fixes.

1. Steal shield player-facing description is correct and distinct from Second Chance
2. Second Chance description remains unchanged
3. Push Store button is on the Manage Store page (store.html)
4. Push Store functionality route still registered
5. Icons for steal_shield and Second Chance render correctly in JS bonusLabels
6. Unrelated store behavior stable

Tests operate via template file inspection and route checks inside a Flask
app context. No HTTP/WebSocket required.

Run (from project root):
    .venv\\Scripts\\python.exe tests\\test_regression_d2b_polish.py

Expected: all tests pass, final line "ALL D2b TESTS PASSED."
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app

flask_app = create_app()

# ─────────────────────────────────────────────────────────────────────────────
# Lightweight test runner
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
# Read template files once
# ─────────────────────────────────────────────────────────────────────────────

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(BASE, 'app', 'templates', 'player', 'classic', 'game.html'),
          'r', encoding='utf-8') as f:
    game_html = f.read()

with open(os.path.join(BASE, 'app', 'templates', 'admin', 'classic', 'store.html'),
          'r', encoding='utf-8') as f:
    store_html = f.read()

with open(os.path.join(BASE, 'app', 'templates', 'admin', 'classic', 'manage.html'),
          'r', encoding='utf-8') as f:
    manage_html = f.read()

# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

print('\n── D2b-1: Steal shield description is distinct from Second Chance ──')

# In bonusLabels, the steal_shield entry must NOT contain "Second Chance"
# and must contain its own identity ("Steal Shield")
check('D2b-1a: bonusLabels steal_shield contains "Steal Shield"',
      'Steal Shield' in game_html and 'steal_shield' in game_html)

# The steal_shield label must NOT say "try again" or "Second Chance"
# Extract the steal_shield line from bonusLabels
import re
ss_match = re.search(r"'steal_shield':\s*'([^']*)'", game_html)
check('D2b-1b: steal_shield bonusLabel found', ss_match is not None)
if ss_match:
    ss_label = ss_match.group(1)
    check('D2b-1c: steal_shield label does NOT contain "Second Chance"',
          'Second Chance' not in ss_label, f'label={ss_label}')
    check('D2b-1d: steal_shield label does NOT contain "try again"',
          'try again' not in ss_label, f'label={ss_label}')
    check('D2b-1e: steal_shield label contains "Steal Shield"',
          'Steal Shield' in ss_label, f'label={ss_label}')


print('\n── D2b-2: Second Chance description is correct ─────────────────────')

sc_match = re.search(r"'shield':\s*'([^']*)'", game_html)
check('D2b-2a: shield bonusLabel found', sc_match is not None)
if sc_match:
    sc_label = sc_match.group(1)
    check('D2b-2b: shield label contains "Second Chance"',
          'Second Chance' in sc_label, f'label={sc_label}')
    check('D2b-2c: shield label contains "try again"',
          'try again' in sc_label, f'label={sc_label}')
    check('D2b-2d: shield label does NOT contain "Steal Shield"',
          'Steal Shield' not in sc_label, f'label={sc_label}')


print('\n── D2b-3: Push Store button location ───────────────────────────────')

check('D2b-3a: Push Store button on store.html',
      'Push Store to Players' in store_html)
check('D2b-3b: push_store URL in store.html',
      'push_store' in store_html)
check('D2b-3c: Push Store button NOT on manage.html',
      'Push Store to Players' not in manage_html)


print('\n── D2b-4: Push Store route still registered ────────────────────────')

with flask_app.app_context():
    endpoints = [rule.endpoint for rule in flask_app.url_map.iter_rules()]
    check('D2b-4a: push_store route registered',
          'classic_admin.push_store' in endpoints)


print('\n── D2b-5: Icons for steal_shield and Second Chance ─────────────────')

# Second Chance in bonusLabels should have an emoji (either direct or \uD83D\uDD04)
if sc_match:
    sc_raw = sc_match.group(1)
    has_icon = '\\uD83D\\uDD04' in sc_raw or '\U0001f504' in sc_raw or '\ud83d\udd04' in sc_raw
    check('D2b-5a: Second Chance bonusLabel has icon', has_icon, f'raw={repr(sc_raw[:20])}')

# steal_shield in bonusLabels should have an emoji
if ss_match:
    ss_raw = ss_match.group(1)
    has_icon = '\\uD83D\\uDEE1' in ss_raw or '\U0001f6e1' in ss_raw or '\ud83d\udee1' in ss_raw or '\U0001F6E1' in ss_raw
    check('D2b-5b: steal_shield bonusLabel has icon', has_icon, f'raw={repr(ss_raw[:20])}')

# renderBonuses Second Chance line should have icon
rb_match = re.search(r"bonuses\.shield\).*?parts\.push\('([^']*)'", game_html)
check('D2b-5c: renderBonuses shield line found', rb_match is not None)
if rb_match:
    rb_label = rb_match.group(1)
    has_icon = '\\uD83D\\uDD04' in rb_label or '\U0001f504' in rb_label or '\ud83d\udd04' in rb_label
    check('D2b-5d: renderBonuses Second Chance has icon', has_icon, f'raw={repr(rb_label[:20])}')

# Wrong-answer feedback line should still have icon
check('D2b-5e: wrong-answer feedback has Second Chance icon',
      'Second Chance used' in game_html)


print('\n── D2b-6: Unrelated store behavior stable ──────────────────────────')

# x2_mine still present in bonusLabels
check('D2b-6a: x2_mine bonusLabel present', "'x2_mine'" in game_html)
# steal_token still present
check('D2b-6b: steal_token bonusLabel present', "'steal_token'" in game_html)
# Store page still has Add Item form
check('D2b-6c: store.html has Add Item form', 'Add Item' in store_html)
# Manage Store link still on manage page
check('D2b-6d: Manage Store link on manage.html', 'Manage Store' in manage_html)


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────

print(f'\n{"=" * 60}')
print(f'D2b results: {passed} passed, {failed} failed')
if failed:
    print('SOME D2b TESTS FAILED.')
    sys.exit(1)
else:
    print('ALL D2b TESTS PASSED.')
    sys.exit(0)
