"""Read-only online content export for the isolated Windows play instance.

Run via SSH with the production virtualenv. The zip goes to stdout; no accounts,
credentials, game history or production configuration are included.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

from dotenv import dotenv_values
from sqlalchemy import create_engine, select, text

CONTENT_TABLES = {
    'subject', 'topic', 'problem', 'problem_set', 'problem_set_problems',
    'problem_block', 'problem_accepted_answer', 'problem_choice_option',
    'problem_source_metadata', 'gear_item_definition', 'uploaded_asset',
}


def main():
    os.environ.update({k: v for k, v in dotenv_values('/etc/korephysics-game/app.env').items() if v is not None})
    from app import create_app
    from app.extensions import db
    app = create_app()
    root = Path('/opt/korephysics-game/app')
    with app.app_context(), tempfile.TemporaryDirectory() as tmp:
        target = create_engine('sqlite:///' + str(Path(tmp) / 'content.sqlite'))
        db.metadata.create_all(target)
        counts = {}
        with db.engine.connect().execution_options(isolation_level='REPEATABLE READ') as source:
            with source.begin(), target.begin() as dest:
                source.execute(text('SET TRANSACTION READ ONLY'))
                for table in db.metadata.sorted_tables:
                    if table.name not in CONTENT_TABLES:
                        continue
                    rows = [dict(r) for r in source.execute(select(table)).mappings()]
                    if rows:
                        dest.execute(table.insert(), rows)
                    counts[table.name] = len(rows)
                version = source.scalar(text('SELECT version_num FROM alembic_version'))
        target.dispose()
        manifest = {}
        for folder in ('app', 'migrations'):
            for file in (root / folder).rglob('*'):
                if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc':
                    manifest[file.relative_to(root).as_posix()] = hashlib.sha256(file.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        for name in ('config.py', 'run.py'):
            manifest[name] = hashlib.sha256((root / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(Path(tmp) / 'content.sqlite', 'content.sqlite')
            archive.writestr('manifest.json', json.dumps(dict(tables=counts, schema=version, files=manifest)))
            media = Path(app.config['MEDIA_ROOT'])
            for file in media.rglob('*'):
                if file.is_file() and not file.is_symlink():
                    archive.write(file, 'media/' + file.relative_to(media).as_posix())
            layout = Path(app.instance_path) / 'overlay_layouts.json'
            if layout.exists():
                archive.write(layout, 'overlay_layouts.json')
        sys.stdout.buffer.write(output.getvalue())


if __name__ == '__main__':
    main()
