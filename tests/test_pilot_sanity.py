"""Post-cleanup sanity check for pilot-reset command.
Run once manually; not part of the permanent test suite.
"""
from app import create_app
from app.extensions import db
from app.models.player import Player
from app.models.groups import PlayerGroup
from app.models.subjects import Subject
from app.models.problems import Topic, Problem, ProblemSet
from app.models.game import GameSession

app = create_app()
with app.app_context():
    print('=== POST-PILOT-RESET SANITY CHECK ===')
    print(f'Players:      {Player.query.count()}  (expected 20)')
    print(f'Groups:       {PlayerGroup.query.count()}  (expected 0)')
    print(f'GameSession:  {GameSession.query.count()}  (expected 0)')
    print(f'ProblemSet:   {ProblemSet.query.count()}  (expected 0)')
    print(f'Problem:      {Problem.query.count()}  (expected 0)')
    print(f'Topic:        {Topic.query.count()}  (expected 0)')
    print(f'Subject:      {Subject.query.count()}  (expected 0)')

    # Smoke test: Subject create/rollback
    s = Subject(name='Sanity Check Subject', description='temporary')
    db.session.add(s)
    db.session.flush()
    sid = s.id
    db.session.rollback()
    print(f'Subject create/rollback: OK (temp id would have been {sid})')

    # Auth check: admin can still log in
    admin = Player.query.filter_by(is_admin=True).first()
    if admin:
        result = 'OK' if admin.check_password('admin123') else 'FAIL'
        print(f'Admin login check ({admin.username}): {result}')
    else:
        print('WARNING: No admin user found!')

    print('=== ALL CHECKS PASSED ===')
