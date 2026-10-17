"""One-time administrator creation for a fresh, migrated database."""

import os

import click
from flask.cli import with_appcontext

from app.extensions import db
from app.models.player import Player


@click.command('create-admin')
@click.option('--username', help='Administrator username; defaults to INITIAL_ADMIN_USERNAME.')
@with_appcontext
def create_admin_command(username):
    if Player.query.filter_by(is_admin=True).first():
        click.echo('Administrator already exists; no account or password changed.')
        return
    username = (username or os.environ.get('INITIAL_ADMIN_USERNAME') or '').strip()
    password = os.environ.get('INITIAL_ADMIN_PASSWORD') or ''
    if not username:
        raise click.ClickException('Set INITIAL_ADMIN_USERNAME or pass --username.')
    if not password:
        raise click.ClickException('Set INITIAL_ADMIN_PASSWORD in the environment.')
    if len(password) < 12:
        raise click.ClickException('INITIAL_ADMIN_PASSWORD must be at least 12 characters.')

    existing = Player.query.filter_by(username=username).first()
    if existing:
        if not existing.is_admin:
            raise click.ClickException('That username already belongs to a player.')
        click.echo(f'Administrator {username} already exists; password was not changed.')
        return
    player = Player(username=username, is_admin=True, avatar_gender_selected=True)
    player.set_password(password)
    db.session.add(player)
    db.session.commit()
    click.echo(f'Administrator {username} created.')
