"""
Focused fresh-start seeding test.

Verifies that maintenance seeding now creates structured problem content by
default while preserving legacy compatibility mirrors through sync.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.cli.maintenance import _do_seed
from app.extensions import db
from app.models.problems import Problem


class _TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SECRET_KEY = 'maintenance-structured-seed-secret'
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


def run_tests():
    with flask_app.app_context():
        db.create_all()
        summary = _do_seed()

        seeded_problems = Problem.query.order_by(Problem.id.asc()).all()
        first_problem = seeded_problems[0] if seeded_problems else None

        check(
            'MSS-01: fresh-start seed still creates the expected problem count',
            summary['problems'] == 8 and len(seeded_problems) == 8,
            f'summary={summary.get("problems")} actual={len(seeded_problems)}',
        )
        check(
            'MSS-02: seeded problems now include at least one structured body block',
            bool(first_problem and first_problem.blocks and first_problem.blocks[0].text_content.strip()),
        )
        check(
            'MSS-03: text-input seeded problems now include accepted-answer rows',
            bool(first_problem and first_problem.accepted_answers and first_problem.accepted_answers[0].answer_text.strip()),
        )
        check(
            'MSS-04: compatibility mirrors remain populated after structured seeding',
            bool(
                first_problem
                and (first_problem.prompt_text or '').strip()
                and (first_problem.answer_text or '').strip()
            ),
        )

    print(f'\nMaintenance structured-seed checks: {passed} passed, {failed} failed')
    raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    run_tests()
