"""Preserve pre-existing dangling rows privately and clean only a migration COPY.

The original snapshot is never modified. No live/source database writes occur.
"""
import argparse
import json
from pathlib import Path
import sqlite3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('destination')
    parser.add_argument('archive')
    args = parser.parse_args()
    if Path(args.destination).exists() or Path(args.archive).exists():
        raise SystemExit('Destination/archive already exists; refusing to overwrite it.')
    with sqlite3.connect('file:' + Path(args.source).as_posix() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(args.destination) as destination:
            source.backup(destination)
    preserved = []
    with sqlite3.connect(args.destination) as connection:
        connection.row_factory = sqlite3.Row
        while True:
            errors = connection.execute('PRAGMA foreign_key_check').fetchall()
            if not errors:
                break
            rows = {}
            for table, rowid, parent, key in errors:
                rows.setdefault((table, rowid), []).append(dict(parent=parent, foreign_key=key))
            for (table, rowid), reasons in rows.items():
                # Table names come solely from SQLite's own schema inspection.
                quoted = '"' + table.replace('"', '""') + '"'
                row = connection.execute(f'SELECT * FROM {quoted} WHERE rowid=?', (rowid,)).fetchone()
                preserved.append(dict(table=table, rowid=rowid, record=dict(row), reasons=reasons))
                connection.execute(f'DELETE FROM {quoted} WHERE rowid=?', (rowid,))
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    Path(args.archive).write_text(json.dumps(preserved, indent=2, ensure_ascii=False), encoding='utf-8')
    from collections import Counter
    print('Archived dangling rows:', json.dumps(Counter(row['table'] for row in preserved)))


if __name__ == '__main__':
    main()
