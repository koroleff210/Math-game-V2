"""Root-run staging checks against the dedicated disposable game QA database."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def main():
    values = dict(dotenv_values('/etc/korephysics-game/app.env'))
    url = make_url(values['DATABASE_URL']).set(database='korephysics_game_qa')
    if url.database != 'korephysics_game_qa':
        raise RuntimeError('Only the dedicated QA database may be modified.')
    engine = create_engine(url)
    def reset():
        with engine.begin() as conn:
            conn.execute(text('DROP SCHEMA public CASCADE'))
            conn.execute(text('CREATE SCHEMA public'))
    with TemporaryDirectory(prefix='learning-qa-') as temp:
        environment = os.environ | values | {
            'DATABASE_URL': url.render_as_string(hide_password=False), 'GAME_ENV': 'development',
            'GAME_IDENTITY_URL': '', 'GAME_MEDIA_ROOT': str(Path(temp)/'media'),
            'GAME_INSTANCE_PATH': str(Path(temp)/'instance'), 'PYTHONIOENCODING': 'utf-8',
        }
        def run(args):
            result = subprocess.run([sys.executable, *args], env=environment, capture_output=True, text=True)
            print(result.stdout, flush=True)
            if args[:1] == ['-c']:
                print(result.stderr, flush=True)
            if result.returncode:
                print(result.stderr, flush=True)
                raise SystemExit('QA failed: ' + str(args[:4]))
        reset()
        run(['-m', 'flask', '--app', 'run', 'db', 'upgrade', 'd9e0f1a2b3c4'])
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO player (id,username,password_hash,is_admin,credential_version,avatar_body_variant,avatar_gender_selected,selected_face_key,created_at) VALUES (90001,'migration-sentinel','unused',false,0,'m',true,'001',CURRENT_TIMESTAMP)"))
        run(['-m', 'flask', '--app', 'run', 'db', 'upgrade'])
        with engine.connect() as conn:
            assert conn.scalar(text('SELECT count(*) FROM player WHERE id=90001')) == 1
            assert 'content_snapshot_json' in {c['name'] for c in inspect(conn).get_columns('analytics_round_problem')}
            assert inspect(conn).has_table('analytics_session_settings')
        print('PASS PostgreSQL migration preserves existing records', flush=True)
        files = ['test_learning_reports.py', 'test_analytics_h1.py', 'test_analytics_h2.py',
                     'test_analytics_h3.py', 'test_analytics_h4.py', 'test_analytics_h5.py',
                     'test_analytics_h6.py', 'test_analytics_h7.py',
                     'test_classic_admin_live_supervision.py', 'test_boss_rush_lifecycle.py', 'test_regression_multi_round.py']
        if len(sys.argv) > 1:
            files = files[files.index(sys.argv[1]):]
        for name in files:
            reset()
            path = str(Path('tests')/name)
            code = "import os,sys,types\nfrom pathlib import Path\np=Path(%r)\ns=p.read_text(encoding='utf-8').replace(\"'sqlite:///:memory:'\",\"os.environ['DATABASE_URL']\")\nm=types.ModuleType('__main__')\nm.__file__=str(p.resolve())\nsys.modules['__main__']=m\nexec(compile(s,str(p),'exec'),m.__dict__)" % path
            run(['-c', code])
            print('POSTGRES PASS:', name, flush=True)
        reset()


if __name__ == '__main__':
    main()
