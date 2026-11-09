"""Download online content into instance/local-play, retaining local progress.

Stop the local play server first. Online access is read-only. Existing local
database and layouts are backed up before each refresh. Online-owned content IDs
are reserved: author new question sets online, then run this tool again.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import socket
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy.export_local_content import CONTENT_TABLES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='Use an already downloaded export (offline).')
    args = parser.parse_args()
    home = ROOT / 'instance' / 'local-play'
    home.mkdir(parents=True, exist_ok=True)
    marker = home / 'server.json'
    if marker.exists():
        server = json.loads(marker.read_text())
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex(('127.0.0.1', server['port'])) == 0:
                raise SystemExit('Use Stop Local Game.bat before refreshing content.')
    # Only this dedicated instance may be updated. Never inherit a production URL.
    os.environ.update(GAME_ENV='development', GAME_INSTANCE_PATH=str(home),
                      DATABASE_URL='sqlite:///' + (home / 'math_game.db').as_posix(),
                      GAME_MEDIA_ROOT=str(home / 'media'), GAME_IDENTITY_URL='', GAME_IDENTITY_TOKEN='')
    from app import create_app
    from config import Config as AppConfig
    from app.extensions import db
    from app.models.player import Player
    from flask_migrate import upgrade
    from sqlalchemy import create_engine, select, and_, text
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    backup = home / 'backups' / stamp
    backup.mkdir(parents=True)
    archive_path = args.archive
    if archive_path is None:
        payload = base64.b64encode((ROOT / 'deploy/export_local_content.py').read_bytes()).decode('ascii')
        command = "cd /opt/korephysics-game/app && sudo /opt/korephysics-game/venv/bin/python -c \"import base64; exec(base64.b64decode('" + payload + "'))\""
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                                 '-o', 'ConnectTimeout=15', '-i', str(Path.home() / '.ssh/korephysics_ovh_ed25519'),
                                 'ubuntu@158.69.213.70', command], capture_output=True, check=True, timeout=180)
        archive_path = backup / 'online-content.zip'
        archive_path.write_bytes(result.stdout)
    with zipfile.ZipFile(archive_path) as archive, tempfile.TemporaryDirectory() as tmp:
        assert archive.testzip() is None, 'Corrupt content export'
        for entry in archive.infolist():
            path = Path(entry.filename)
            if path.is_absolute() or '..' in path.parts or ':' in entry.filename or '\\' in entry.filename:
                raise RuntimeError('Unsafe export path')
        manifest = json.loads(archive.read('manifest.json'))
        cfg = Config()
        cfg.set_main_option('script_location', str(ROOT / 'migrations'))
        assert manifest['schema'] == ScriptDirectory.from_config(cfg).get_current_head(), 'Online and local schema differ'
        different = [name for name, digest in manifest['files'].items()
                     if not (ROOT / name).is_file() or hashlib.sha256((ROOT / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() != digest]
        if different:
            raise RuntimeError('Local code differs from online; review before sync: ' + ', '.join(different[:20]))
        snapshot = Path(tmp) / 'content.sqlite'
        snapshot.write_bytes(archive.read('content.sqlite'))
        database = home / 'math_game.db'
        if database.exists():
            with sqlite3.connect(database) as src, sqlite3.connect(backup / 'math_game.db') as dst:
                src.backup(dst)
        layout = home / 'overlay_layouts.json'
        if layout.exists():
            shutil.copy2(layout, backup / layout.name)
        class LocalConfig(AppConfig):
            GAME_ENV = 'development'
            INSTANCE_PATH = str(home)
            SQLALCHEMY_DATABASE_URI = 'sqlite:///' + (home / 'math_game.db').as_posix()
            MEDIA_ROOT = str(home / 'media')
            SHARED_IDENTITY_URL = ''
            SHARED_IDENTITY_TOKEN = ''
        app = create_app(LocalConfig)
        with app.app_context():
            upgrade(directory=str(ROOT / 'migrations'))
            active = db.session.scalar(text("SELECT count(*) FROM game_session WHERE status <> 'finished'"))
            if active:
                raise RuntimeError('Finish local sessions before refreshing content.')
            db.session.remove()
            source = create_engine('sqlite:///' + snapshot.as_posix())
            with source.connect() as src, db.engine.begin() as dst:
                # Replace child content for current online questions/sets. History
                # references root problem IDs and immutable analytics snapshots.
                for name, parent in [('problem_set_problems', 'problem_set_id'), ('problem_block', 'problem_id'),
                                     ('problem_accepted_answer', 'problem_id'), ('problem_choice_option', 'problem_id'),
                                     ('problem_source_metadata', 'problem_id')]:
                    table = db.metadata.tables[name]
                    root_name = 'problem_set' if parent == 'problem_set_id' else 'problem'
                    ids = list(src.execute(select(db.metadata.tables[root_name].c.id)).scalars())
                    dst.execute(table.delete().where(table.c[parent].in_(ids)))
                for table in db.metadata.sorted_tables:
                    if table.name not in CONTENT_TABLES:
                        continue
                    for row in src.execute(select(table)).mappings():
                        values = dict(row)
                        key = and_(*(column == values[column.name] for column in table.primary_key))
                        if dst.execute(select(table).where(key)).first() is None:
                            dst.execute(table.insert().values(**values))
                        else:
                            dst.execute(table.update().where(key).values(**values))
                if dst.execute(text('PRAGMA foreign_key_check')).fetchall():
                    raise RuntimeError('Content refresh violates local references; changes rolled back.')
            source.dispose()
            if not Player.query.filter_by(is_admin=True).first():
                admin = Player(username='local-admin', is_admin=True, avatar_gender_selected=True)
                admin.set_password('local-admin123')
                player = Player(username='local-test', is_admin=False, avatar_gender_selected=True)
                player.set_password('local-test123')
                db.session.add_all([admin, player])
                db.session.commit()
            db.session.remove()
            with db.engine.connect() as conn:
                assert not conn.execute(text('PRAGMA foreign_key_check')).fetchall()
        # Retain prior media too: older local reports may still reference it.
        for entry in archive.infolist():
            path = Path(entry.filename)
            if entry.filename.startswith('media/') and not entry.is_dir():
                target = home / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(entry))
        if 'overlay_layouts.json' in archive.namelist():
            layout.write_bytes(archive.read('overlay_layouts.json'))
        report = dict(synced_utc=stamp, content=manifest['tables'], code_files_verified=len(manifest['files']),
                      progress='local only; retained on refresh', backup=str(backup))
        (home / 'sync-report.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
