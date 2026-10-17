"""First install on the existing KorePhysics Ubuntu VPS. Run as root after upload.

Refuses to overwrite existing game environment/data. Does not alter exam services.
"""
from pathlib import Path
import os
import secrets
import subprocess


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def main():
    root = Path('/opt/korephysics-game')
    config = Path('/etc/korephysics-game')
    if (config / 'app.env').exists():
        raise SystemExit('Game already configured. Use the documented update procedure.')
    run('useradd', '--system', '--home', '/var/lib/korephysics-game', '--shell', '/usr/sbin/nologin', 'korephysics-game')
    config.mkdir(mode=0o750)
    run('chown', 'root:korephysics-game', str(config))
    run('install', '-d', '-o', 'korephysics-game', '-g', 'korephysics-game', '-m', '750', '/var/lib/korephysics-game/media')
    run('python3', '-m', 'venv', str(root / 'venv'))
    run(str(root / 'venv/bin/pip'), 'install', '-r', str(root / 'app/requirements-prod.txt'))
    password, key, token = secrets.token_hex(32), secrets.token_hex(32), secrets.token_hex(32)
    # Input, rather than argv/logs, carries database credentials.
    sql = f"CREATE ROLE korephysics_game LOGIN PASSWORD '{password}';\nCREATE DATABASE korephysics_game OWNER korephysics_game;\n"
    run('runuser', '-u', 'postgres', '--', 'psql', '-v', 'ON_ERROR_STOP=1', input=sql, text=True)
    env = dict(GAME_ENV='production', SECRET_KEY=key,
               DATABASE_URL=f'postgresql+psycopg://korephysics_game:{password}@127.0.0.1:5432/korephysics_game',
               GAME_PUBLIC_ORIGINS='https://game.korephysics.com',
               GAME_MEDIA_ROOT='/var/lib/korephysics-game/media',
               GAME_INSTANCE_PATH='/var/lib/korephysics-game',
               GAME_IDENTITY_URL='http://127.0.0.1:5061', GAME_IDENTITY_TOKEN=token)
    path = config / 'app.env'
    path.write_text(''.join(f'{k}={v}\n' for k, v in env.items()))
    os.chmod(path, 0o640)
    run('chown', 'root:korephysics-game', str(path))
    path = config / 'identity.env'
    path.write_text('DATABASE_URL=sqlite:////var/lib/korephysics/instance/classroom.sqlite\nGAME_IDENTITY_TOKEN=' + token + '\n')
    os.chmod(path, 0o640)
    run('chown', 'root:korephysics', str(path))
    # Directory traversal only for the adapter's service user; secrets remain private.
    os.chmod(config, 0o751)
    for name in ('korephysics-game.service', 'korephysics-identity.service'):
        run('install', '-m', '644', str(root / 'app/deploy' / name), '/etc/systemd/system/' + name)
    run('systemctl', 'daemon-reload')
    environment = os.environ | env
    run(str(root / 'venv/bin/python'), '-m', 'flask', '--app', 'run:app', 'db', 'upgrade',
        cwd=root / 'app', env=environment)
    print('Game runtime, private configuration and empty PostgreSQL schema prepared.')


if __name__ == '__main__':
    main()
