"""Run UI persistence regressions only in the fixed disposable PostgreSQL QA DB."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def main():
    values=dict(dotenv_values('/etc/korephysics-game/app.env'))
    url=make_url(values['DATABASE_URL']).set(database='korephysics_game_qa')
    if url.database != 'korephysics_game_qa':
        raise RuntimeError('Only the dedicated QA database may be modified.')
    engine=create_engine(url)
    with TemporaryDirectory(prefix='player-ui-qa-') as temp:
        env=os.environ|values|{'DATABASE_URL':url.render_as_string(hide_password=False),'GAME_ENV':'development',
            'GAME_IDENTITY_URL':'','GAME_INSTANCE_PATH':str(Path(temp)/'instance'),'GAME_MEDIA_ROOT':str(Path(temp)/'media'),'PYTHONIOENCODING':'utf-8'}
        for name in ['test_player_ui_loading.py','test_avatar_preview_step1.py','test_character_lock_flow.py','test_hub_polish_pass.py','test_gear_step6d.py']:
            with engine.begin() as connection:
                connection.execute(text('DROP SCHEMA public CASCADE'))
                connection.execute(text('CREATE SCHEMA public'))
            path=str(Path('tests')/name)
            code="import os,sys,types\nfrom pathlib import Path\np=Path(%r)\ns=p.read_text(encoding='utf-8').replace(\"'sqlite:///:memory:'\",\"os.environ['DATABASE_URL']\")\nm=types.ModuleType('__main__')\nm.__file__=str(p.resolve())\nsys.modules['__main__']=m\nexec(compile(s,str(p),'exec'),m.__dict__)" % path
            result=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True)
            print(result.stdout,flush=True)
            print(result.stderr,flush=True)
            if result.returncode:raise SystemExit('QA failed: '+name)
            print('POSTGRES PASS:',name,flush=True)
        with engine.begin() as connection:
            connection.execute(text('DROP SCHEMA public CASCADE'))
            connection.execute(text('CREATE SCHEMA public'))


if __name__=='__main__':
    main()
