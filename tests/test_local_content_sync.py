"""Content refresh adds sets without resetting local identity or progression."""
import json
from pathlib import Path
import shutil
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select, text
from app import create_app
from app.extensions import db
from app.models.problems import Problem, ProblemSet, Topic
from tools import sync_local_content


def test_refresh_retains_progress_and_adds_sets(tmp_path, monkeypatch):
    real_root = Path(__file__).resolve().parents[1]
    root = tmp_path / 'project'
    root.mkdir()
    shutil.copytree(real_root / 'migrations', root / 'migrations')
    snapshot = tmp_path / 'source.sqlite'

    class TestConfig:
        TESTING = True
        SECRET_KEY = 'sync-test'
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + snapshot.as_posix()
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SOCKETIO_ASYNC_MODE = 'threading'

    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        topic = Topic(name='Physics')
        problem = Problem(topic=topic, title='First', prompt_text='One?', answer_text='1')
        problem_set = ProblemSet(name='First set')
        problem_set.problems.append(problem)
        db.session.add_all([topic, problem, problem_set])
        db.session.commit()
        db.session.remove()
        db.engine.dispose()
    cfg = Config()
    cfg.set_main_option('script_location', str(root / 'migrations'))
    archive_path = tmp_path / 'export.zip'

    def package():
        with zipfile.ZipFile(archive_path, 'w') as archive:
            archive.write(snapshot, 'content.sqlite')
            archive.writestr('manifest.json', json.dumps(dict(
                schema=ScriptDirectory.from_config(cfg).get_current_head(), files={}, tables={})))

    monkeypatch.setattr(sync_local_content, 'ROOT', root)
    monkeypatch.setattr(sys, 'argv', ['sync', '--archive', str(archive_path)])
    # main() intentionally changes these settings for its dedicated instance.
    for name in ('GAME_ENV', 'GAME_INSTANCE_PATH', 'DATABASE_URL', 'GAME_MEDIA_ROOT',
                 'GAME_IDENTITY_URL', 'GAME_IDENTITY_TOKEN'):
        monkeypatch.setenv(name, '')
    package()
    sync_local_content.main()
    local = create_engine('sqlite:///' + (root / 'instance/local-play/math_game.db').as_posix())
    from app.models.player import Player
    from app.models.progression import PlayerProgression
    with local.begin() as conn:
        player_id = conn.scalar(select(Player.id).where(Player.username == 'local-test'))
        conn.execute(PlayerProgression.__table__.insert().values(player_id=player_id, diamonds_balance=37))
        original_player = dict(conn.execute(select(Player.__table__).where(Player.id == player_id)).mappings().one())
    source = create_engine('sqlite:///' + snapshot.as_posix())
    with source.begin() as conn:
        conn.execute(ProblemSet.__table__.insert().values(name='Second set'))
    source.dispose()
    package()
    sync_local_content.main()
    sync_local_content.main()  # Repeat refresh must be idempotent.
    with local.connect() as conn:
        assert conn.scalar(select(PlayerProgression.diamonds_balance)) == 37
        assert dict(conn.execute(select(Player.__table__).where(Player.id == player_id)).mappings().one()) == original_player
        assert list(conn.execute(select(ProblemSet.name).order_by(ProblemSet.id)).scalars()) == ['First set', 'Second set']
        assert not conn.execute(text('PRAGMA foreign_key_check')).fetchall()
    local.dispose()
    assert len(list((root / 'instance/local-play/backups').glob('*/math_game.db'))) == 2
