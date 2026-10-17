"""Root-only PostgreSQL + uploaded media + configuration snapshot."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import os
import subprocess
import tempfile
from urllib.parse import urlsplit
import zipfile


def main():
    config = Path('/etc/korephysics-game')
    values = dict(line.split('=', 1) for line in (config / 'app.env').read_text().splitlines() if '=' in line)
    uri = urlsplit(values['DATABASE_URL'].replace('postgresql+psycopg:', 'postgresql:'))
    output = Path('/var/backups/korephysics-game')
    output.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    destination = output / ('game-' + stamp + '.zip')
    with tempfile.TemporaryDirectory() as tmp:
        dump = Path(tmp) / 'game.dump'
        subprocess.run(['pg_dump', '-h', uri.hostname, '-U', uri.username, '-d', uri.path.lstrip('/'),
                        '-Fc', '-f', str(dump)], env=os.environ | {'PGPASSWORD': uri.password}, check=True)
        with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(dump, 'game.dump')
            layout = Path('/var/lib/korephysics-game/overlay_layouts.json')
            if layout.exists():
                archive.write(layout, 'instance/overlay_layouts.json')
            for name in ('app.env', 'identity.env', 'admin-access.txt'):
                if (config / name).exists():
                    archive.write(config / name, 'config/' + name)
            media = Path('/var/lib/korephysics-game/media')
            for file in media.rglob('*'):
                if file.is_file():
                    archive.write(file, 'media/' + str(file.relative_to(media)))
    os.chmod(destination, 0o600)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    checksum = destination.with_suffix('.zip.sha256')
    checksum.write_text(digest + '  ' + destination.name + '\n')
    os.chmod(checksum, 0o600)
    snapshots = sorted(output.glob('game-*.zip'), reverse=True)
    total = 0
    for i, file in enumerate(snapshots):
        total += file.stat().st_size
        if i >= 2 and (i >= 60 or total > 5 * 1024**3):
            file.unlink()
            file.with_suffix('.zip.sha256').unlink(missing_ok=True)
    print('Backup saved:', destination.name)


if __name__ == '__main__':
    main()
