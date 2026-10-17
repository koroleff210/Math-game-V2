"""Restore the latest private game backup to a separate disposable database."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import tempfile
import zipfile

from dotenv import dotenv_values
from sqlalchemy import create_engine, MetaData, select, func
from sqlalchemy.engine import make_url


def main():
    backup = sorted(Path('/var/backups/korephysics-game').glob('game-*.zip'))[-1]
    expected = backup.with_suffix('.zip.sha256').read_text().split()[0]
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == expected
    values = dict(dotenv_values('/etc/korephysics-game/app.env'))
    source_url = make_url(values['DATABASE_URL'])
    target_url = source_url.set(database='korephysics_game_restorecheck')
    assert target_url.database != source_url.database
    subprocess.run(['runuser', '-u', 'postgres', '--', 'createdb', '-O', source_url.username,
                    target_url.database], check=True)
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(backup) as archive:
        assert archive.testzip() is None
        dump = Path(tmp) / 'game.dump'
        dump.write_bytes(archive.read('game.dump'))
        subprocess.run(['pg_restore', '-h', source_url.host, '-U', source_url.username, '-d', target_url.database,
                        '--no-owner', '--exit-on-error', str(dump)],
                       env=os.environ | {'PGPASSWORD': source_url.password}, check=True)
        layout = Path('/var/lib/korephysics-game/overlay_layouts.json')
        assert archive.read('instance/overlay_layouts.json') == layout.read_bytes()
    source, target = create_engine(source_url), create_engine(target_url)
    metadata = MetaData()
    metadata.reflect(bind=source)
    counts = {}
    with source.connect() as live, target.connect() as restored:
        for table in metadata.sorted_tables:
            # Full row equality, excluding sequence state which pg_restore restores separately.
            order = list(table.primary_key.columns)
            before = list(live.execute(select(table).order_by(*order)).mappings())
            after = list(restored.execute(select(table).order_by(*order)).mappings())
            assert before == after, table.name
            counts[table.name] = len(after)
    source.dispose()
    target.dispose()
    subprocess.run(['runuser', '-u', 'postgres', '--', 'dropdb', 'korephysics_game_restorecheck'], check=True)
    report = dict(backup=backup.name, tables=len(counts), rows=sum(counts.values()),
                  layout_restored=True, checksum_verified=True, full_row_equality=True)
    Path('/var/backups/korephysics-game/restore-verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
