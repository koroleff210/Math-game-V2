"""Copy a migrated SQLite snapshot to an EMPTY PostgreSQL database; verify all rows.

Run with the game's production environment and --source /private/migrated.sqlite.
No source writes, deletes, resets or overwrites of nonempty destination tables.
"""
import argparse
import json
from decimal import Decimal
from datetime import date, datetime
from sqlalchemy import create_engine, select, func, text
from app import create_app
from app.extensions import db


def normal(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat().rstrip('Z').replace('+00:00', '')
    if isinstance(value, Decimal):
        return float(value)
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    source = create_engine('sqlite:///' + args.source)
    app = create_app()
    report = {}
    with app.app_context(), source.connect() as src, db.engine.begin() as dst:
        if db.engine.dialect.name != 'postgresql':
            raise RuntimeError('Destination must be PostgreSQL.')
        for table in db.metadata.sorted_tables:
            if dst.scalar(select(func.count()).select_from(table)):
                raise RuntimeError('Destination is not empty: ' + table.name)
        for table in db.metadata.sorted_tables:
            rows = [dict(row) for row in src.execute(select(table)).mappings()]
            if rows:
                dst.execute(table.insert(), rows)
            report[table.name] = len(rows)
            # Verify values as well as counts, in deterministic primary key order.
            order = list(table.primary_key.columns)
            original = [dict(row) for row in src.execute(select(table).order_by(*order)).mappings()]
            copied = [dict(row) for row in dst.execute(select(table).order_by(*order)).mappings()]
            canonical = lambda data: json.dumps(data, default=normal, sort_keys=True, ensure_ascii=False)
            if canonical(original) != canonical(copied):
                raise RuntimeError('Copied values differ: ' + table.name)
            for column in table.primary_key:
                if column.type.python_type is int:
                    sequence = dst.scalar(text('SELECT pg_get_serial_sequence(:table, :column)'),
                                          dict(table=table.name, column=column.name))
                    if sequence:
                        maximum = dst.scalar(select(func.max(column)))
                        dst.execute(text('SELECT setval(CAST(:sequence AS regclass), :value, :used)'),
                                    dict(sequence=sequence, value=maximum or 1, used=maximum is not None))
    from pathlib import Path
    Path(args.report).write_text(json.dumps(report, indent=2))
    print('Verified', len(report), 'tables;', sum(report.values()), 'rows copied.')


if __name__ == '__main__':
    main()
