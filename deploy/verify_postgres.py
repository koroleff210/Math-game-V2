"""Run isolated gameplay regressions on a dedicated, disposable PostgreSQL DB.

Requires a pre-created korephysics_game_qa database owned by the game role.
Never connects to the production database for schema/data changes.
"""
from pathlib import Path
import os
import subprocess
import sys

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def main():
    values = dict(dotenv_values('/etc/korephysics-game/app.env'))
    url = make_url(values['DATABASE_URL']).set(database='korephysics_game_qa')
    assert url.database == 'korephysics_game_qa'
    uri = url.render_as_string(hide_password=False)
    engine = create_engine(url)
    environment = os.environ | values | {'DATABASE_URL': uri, 'GAME_ENV': 'development', 'PYTHONIOENCODING': 'utf-8'}
    files = ['test_classic_admin_live_supervision.py', 'test_boss_rush_lifecycle.py',
             'test_regression_multi_round.py', 'test_problem_set_builder.py', 'test_gear_step6d.py']
    for name in files:
        with engine.begin() as connection:
            connection.execute(text('DROP SCHEMA public CASCADE'))
            connection.execute(text('CREATE SCHEMA public'))
        path = str(Path('tests') / name)
        code = '''import os
from pathlib import Path
p = Path(%r)
s = p.read_text(encoding='utf-8').replace("'sqlite:///:memory:'", "os.environ['DATABASE_URL']")
exec(compile(s,str(p),'exec'),dict(__name__='__main__',__file__=str(p.resolve())))
''' % path
        result = subprocess.run([sys.executable, '-c', code], env=environment, capture_output=True, text=True)
        print(result.stdout)
        if result.returncode:
            print(result.stderr)
            raise SystemExit('PostgreSQL regression failed: ' + name)
        print('POSTGRES PASS:', name)


if __name__ == '__main__':
    main()
