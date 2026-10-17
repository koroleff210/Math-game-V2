"""One-time guarded import of the existing local game snapshot on the VPS."""
from pathlib import Path
import json
import os
import secrets
import shutil
import subprocess
import sys

from dotenv import dotenv_values


def main():
    root = Path('/opt/korephysics-game/app')
    backup = Path('/var/backups/korephysics-game/migration-20261017')
    backup.mkdir(mode=0o700)
    original = backup / 'original.sqlite'
    clean = backup / 'migration.sqlite'
    shutil.copy2('/home/ubuntu/game-migration.sqlite', original)
    shutil.copy2('/home/ubuntu/game-assets-manifest.json', backup / 'assets-manifest.json')
    environment = os.environ | dict(dotenv_values('/etc/korephysics-game/app.env'))
    def run(*args, env=environment):
        subprocess.run([sys.executable, *args], cwd=root, env=env, check=True)
    run('-m', 'deploy.prepare_snapshot', str(original), str(clean), str(backup / 'legacy-orphans.json'))
    run('-m', 'flask', '--app', 'run:app', 'db', 'upgrade', env=environment | {
        'GAME_ENV': 'development', 'DATABASE_URL': 'sqlite:///' + str(clean)})
    run('-m', 'deploy.copy_database', '--source', str(clean), '--report', str(backup / 'copy-report.json'))
    os.environ.update(environment)
    from app import create_app
    from app.models.player import Player
    from app.extensions import db
    app = create_app()
    with app.app_context():
        admins = Player.query.filter_by(is_admin=True).all()
        if len(admins) != 1:
            raise RuntimeError('Review admin roster before public launch.')
        admin = admins[0]
        if admin.check_password('admin123'):
            password = secrets.token_urlsafe(24)
            admin.set_password(password)
            db.session.commit()
            access = f'https://game.korephysics.com/login\nUsername: {admin.username}\nPassword: {password}\n'
        else:
            access = f'https://game.korephysics.com/login\nUsername: {admin.username}\nUse the existing game admin password.\n'
        path = Path('/etc/korephysics-game/admin-access.txt')
        path.write_text(access)
        os.chmod(path, 0o600)
    import hashlib
    manifest = json.loads((backup / 'assets-manifest.json').read_text())
    for name, digest in manifest.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Asset differs: ' + name)
    print('Verified', len(manifest), 'asset checksums. Existing records copied; demo admin password secured.')


if __name__ == '__main__':
    main()
